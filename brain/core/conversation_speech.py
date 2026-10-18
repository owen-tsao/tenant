"""Optional, once-only audio for an already-delivered native conversation reply.

Text delivery owns the conversation. Speech never interprets a guest request,
retries an uncertain action, or changes the Mac's output device or volume.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re


FALLBACK = 'I put the details in the chat.'
MAX_WORDS = 12
MAX_CHARACTERS = 100


@dataclass(frozen=True)
class CompletedReply:
    guest_id: str
    generation: int
    thread_id: str
    turn_id: str
    text: str
    lease: object = field(repr=False, compare=False)


class ReplyFrames(list):
    """Normal wire frames with an internal receipt that JSON does not serialize."""

    def __init__(self, receipt: CompletedReply):
        super().__init__([{'type': 'assistant', 'text': receipt.text}])
        self.completed_reply = receipt


def spoken_sentence(text):
    """Read a brief plain reply or first sentence, otherwise point to the chat.

    This is a conservative presentation filter, not a classifier or a promise
    that arbitrary generated prose cannot contain private information. Known
    private values must already be redacted by the conversation owner.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    first_line = text.strip().split('\n', 1)[0]
    candidate = first_line
    if len(candidate) > MAX_CHARACTERS or len(candidate.split()) > MAX_WORDS:
        candidate = re.split(r'(?<=[.!?])\s+', first_line, maxsplit=1)[0].strip()
    unsafe = (
        len(candidate) > MAX_CHARACTERS
        or len(candidate.split()) > MAX_WORDS
        or not re.search(r'\w', candidate)
        or re.search(r'[\x00-\x1f\x7f`<>\[\]{}()*_#|\\=]', candidate)
        or re.match(r'(?:[-+•]\s|\d+\.\s)', candidate)
        or re.search(r'(?:[A-Za-z]+://|www\.|\S@\S|(?:^|\s)(?:/|~/)|\b[A-Za-z0-9_-]{28,}\b|\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}\b)', candidate)
        or re.search(r'\b(?:password|token|secret|credential|api[ -]?key|bearer)\b|\b(?:sk-|gh[pousr]_)', candidate, re.I)
        or candidate.endswith((':', ';', ',', '-', '—'))
    )
    return FALLBACK if unsafe else candidate


class ConversationSpeech:
    def __init__(self, registry, bus, leases, log, authorize_reply, *, speaker_device_id=None, timeout=4.0):
        self.registry, self.bus, self.leases, self.log = registry, bus, leases, log
        self.authorize_reply = authorize_reply
        self.speaker_device_id = speaker_device_id
        self.timeout = timeout
        self._seen = set()

    def _speaker(self):
        candidates = [dev for dev in self.registry.devices.values()
                      if dev.online and dev.room_id == self.registry.room.id and 'say' in dev.caps]
        if self.speaker_device_id is not None:
            return next((dev for dev in candidates if dev.id == self.speaker_device_id), None)
        return candidates[0] if len(candidates) == 1 else None

    def _record(self, receipt, status, *, device=None, req=None):
        # Neither the spoken phrase nor arbitrary bridge error messages enter the log.
        self.log.append('speech', 'Room reply audio status was recorded.',
                        guest_id=receipt.guest_id, thread_id=receipt.thread_id,
                        turn_id=receipt.turn_id, generation=receipt.generation,
                        audio_status=status, device_id=getattr(device, 'id', None), req=req)

    async def speak_reply(self, frames):
        """Call only after sending these final frames successfully to the guest."""
        if not isinstance(frames, ReplyFrames):
            return  # History, errors, access notices and interpreter replies are never read aloud.
        receipt = frames.completed_reply
        key = (receipt.thread_id, receipt.turn_id)
        if key in self._seen:
            return
        # Consume before any await: cancellation, reconnect and UNKNOWN never replay this turn.
        self._seen.add(key)
        lease = self.leases.current(receipt.guest_id)
        if lease is not receipt.lease or not self.authorize_reply(receipt):
            self._record(receipt, 'PERMISSION')
            return
        phrase = spoken_sentence(receipt.text)
        if phrase is None:
            self._record(receipt, 'EMPTY')
            return
        speaker = self._speaker()
        if speaker is None:
            self._record(receipt, 'NO_UNIQUE_SPEAKER')
            return

        def permitted(device, cap, args):
            return (device is speaker and self._speaker() is speaker
                    and self.leases.current(receipt.guest_id) is lease
                    and self.authorize_reply(receipt)
                    and self.leases.allows(lease, device, cap))

        try:
            result = await self.bus.call(speaker.id, 'say', {'text': phrase}, timeout=self.timeout,
                                         authorize=permitted)
        except asyncio.CancelledError:
            uncertain = any(owner is speaker for owner in self.bus.uncertain.values())
            self._record(receipt, 'UNKNOWN' if uncertain else 'CANCELLED_BEFORE_SEND', device=speaker)
            raise
        except Exception:
            self._record(receipt, 'UNCONFIRMED', device=speaker)
            return
        confirmed = result.ok and isinstance(result.result, dict) and result.result.get('spoken') is True
        self._record(receipt, 'ACKNOWLEDGED' if confirmed else
                     ('UNCONFIRMED' if result.ok else result.code or 'UNCONFIRMED'),
                     device=speaker, req=result.req)
