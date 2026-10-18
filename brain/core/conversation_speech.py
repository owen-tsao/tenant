"""Optional, once-only audio for an already-delivered native conversation reply.

Text delivery owns the conversation. Speech never interprets a guest request,
retries an uncertain action, or changes the Mac's output device or volume.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import uuid


FALLBACK = 'I put the details in the chat.'
# Match the enrolled Mac driver's supported input, rather than a word limit.
MAX_CHARACTERS = 160


@dataclass(frozen=True)
class CompletedReply:
    guest_id: str
    generation: int
    thread_id: str
    turn_id: str
    text: str
    lease: object = field(repr=False, compare=False)
    explicit_speech_attempted: bool = False
    voice_revision: int | None = None


@dataclass
class VoicePreference:
    lease: object
    revision: int = 0
    enabled: bool = False
    speaker: object = None
    connection: object = None
    speaker_ref: str | None = None
    offered: set = field(default_factory=set)


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
    if len(candidate) > MAX_CHARACTERS:
        candidate = re.split(r'(?<=[.!?])\s+', first_line, maxsplit=1)[0].strip()
    unsafe = (
        len(candidate) > MAX_CHARACTERS
        or not re.search(r'\w', candidate)
        or re.search(r'[\x00-\x1f\x7f`<>\[\]{}()*_#|\\=]', candidate)
        or re.match(r'(?:[-+•]\s|\d+\.\s)', candidate)
        or re.search(r'(?:[A-Za-z]+://|www\.|\S@\S|(?:^|\s)(?:/|~/)|\b[A-Za-z0-9_-]{28,}\b|\b(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,24}\b)', candidate)
        or re.search(r'\b(?:password|token|secret|credential|api[ -]?key|bearer)\b|\b(?:sk-|gh[pousr]_)', candidate, re.I)
        or candidate.endswith((':', ';', ',', '-', '—'))
    )
    return FALLBACK if unsafe else candidate


class ConversationSpeech:
    def __init__(self, registry, bus, leases, log, authorize_reply, *, speaker_device_id=None, timeout=15.0):
        self.registry, self.bus, self.leases, self.log = registry, bus, leases, log
        self.authorize_reply = authorize_reply
        self.speaker_device_id = speaker_device_id
        self.timeout = timeout
        self._seen = set()
        self._preferences = {}
        self._speaker_refs = {}
        self._tasks = {}
        self._scheduled = set()
        self._closed = False

    def _receipt(self, owner):
        return CompletedReply(owner.guest_id, owner.generation, owner.thread_id,
                              getattr(owner, 'turn_id', None) or 'voice-policy', '', owner.lease)

    def _preference(self, owner):
        receipt = self._receipt(owner)
        if (self._closed or self.leases.current(owner.guest_id) is not owner.lease
                or not self.authorize_reply(receipt)):
            return None
        key = (owner.guest_id, owner.generation, owner.thread_id)
        state = self._preferences.get(key)
        if state is None or state.lease is not owner.lease:
            state = self._preferences[key] = VoicePreference(owner.lease)
        if state.enabled and not self._bound(state):
            state.enabled = False
            state.revision += 1
        return state

    def _bound(self, state):
        dev = state.speaker
        return (dev is not None and self.registry.devices.get(dev.id) is dev and dev.online
                and dev.ws is state.connection and dev.room_id == self.registry.room.id
                and 'say' in dev.caps and self.leases.allows(state.lease, dev, 'say'))

    def _choices(self, owner):
        choices = []
        for dev in self.registry.devices.values():
            if (not dev.online or dev.room_id != self.registry.room.id or 'say' not in dev.caps
                    or not self.leases.allows(owner.lease, dev, 'say')
                    or self.speaker_device_id is not None and dev.id != self.speaker_device_id):
                continue
            prior = self._speaker_refs.get(dev.id)
            if prior is None or prior[0] is not dev or prior[1] is not dev.ws:
                prior = self._speaker_refs[dev.id] = (dev, dev.ws, 'speaker_' + uuid.uuid4().hex)
            ref = prior[2]
            choices.append({'device_id': dev.id, 'label': dev.label, 'speaker_ref': ref})
        return choices

    def inventory(self, owner):
        state = self._preference(owner)
        if state is None:
            return {'enabled': False, 'mode': 'text', 'speakers': []}
        return {'enabled': state.enabled, 'mode': 'brief_voice' if state.enabled else 'text',
                'selected_device_id': state.speaker.id if state.enabled else None,
                'speakers': self._choices(owner), 'already_started_speech_may_finish': True}

    def context(self, owner):
        state = self._preference(owner)
        if state is None:
            return {'enabled': False, 'offer_speaker_choice': False}
        choices = self._choices(owner)
        unseen = {choice['speaker_ref'] for choice in choices} - state.offered
        state.offered.update(unseen)
        return {'enabled': state.enabled, 'selected_device_id': state.speaker.id if state.enabled else None,
                'offer_speaker_choice': bool(unseen)}

    def revision_for(self, owner):
        state = self._preference(owner)
        return state.revision if state is not None else None

    def set_voice(self, grant, payload, *, authorized=lambda: True):
        deadline = getattr(grant, 'deadline', None)
        if (getattr(grant, 'closed', True) or not getattr(grant, 'turn_id', None)
                or deadline is None or asyncio.get_running_loop().time() >= deadline or not authorized()):
            return {'ok': False, 'code': 'PERMISSION', 'message': 'This turn cannot change reply voice.'}
        state = self._preference(grant)
        if state is None:
            return {'ok': False, 'code': 'PERMISSION', 'message': 'This turn cannot change reply voice.'}
        enabled = payload.get('enabled') if isinstance(payload, dict) else None
        expected = {'request_id', 'enabled', 'device_id', 'speaker_ref'} if enabled is True else {'request_id', 'enabled'}
        if type(enabled) is not bool or set(payload) != expected:
            return {'ok': False, 'code': 'INVALID', 'message': 'Use an explicit reply voice choice.'}
        if enabled:
            choice = next((choice for choice in self._choices(grant)
                           if choice['device_id'] == payload['device_id'] and choice['speaker_ref'] == payload['speaker_ref']), None)
            if choice is None:
                return {'ok': False, 'code': 'OFFLINE', 'message': 'That speaker choice changed. Ask the guest to choose again; no substitute was used.'}
            state.speaker = self.registry.devices[choice['device_id']]
            state.connection, state.speaker_ref = state.speaker.ws, choice['speaker_ref']
        state.enabled = enabled
        state.revision += 1
        self._cancel_unsent(grant.guest_id)
        return {'ok': True, 'result': self.inventory(grant),
                'message': 'Brief future replies use the chosen speaker for this guest.' if enabled else
                           'Future replies are text only. Speech already started may finish.'}

    def _cancel_unsent(self, guest_id):
        for task, job in tuple(self._tasks.items()):
            if job['guest_id'] == guest_id and not job['dispatched']:
                self._seen.add(job['key'])
                task.cancel()

    def end_guest(self, guest_id):
        self._cancel_unsent(guest_id)
        for key in tuple(self._preferences):
            if key[0] == guest_id:
                self._preferences.pop(key)

    def schedule_reply(self, frames):
        if self._closed or not isinstance(frames, ReplyFrames):
            return None
        key = (frames.completed_reply.thread_id, frames.completed_reply.turn_id)
        if key in self._scheduled or key in self._seen:
            return None
        self._scheduled.add(key)
        task = asyncio.create_task(self.speak_reply(frames))
        self._tasks[task] = {'guest_id': frames.completed_reply.guest_id, 'dispatched': False, 'key': key}
        def finished(done):
            self._seen.add(key)
            self._tasks.pop(done, None)
            if not done.cancelled() and done.exception() is not None:
                self._record(frames.completed_reply, 'UNCONFIRMED')
        task.add_done_callback(finished)
        return task

    async def drain(self, guest_id=None):
        tasks = [task for task, job in self._tasks.items() if guest_id is None or job['guest_id'] == guest_id]
        if tasks:
            try:
                async with asyncio.timeout(self.timeout + 1):
                    await asyncio.gather(*tasks, return_exceptions=True)
            except TimeoutError:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        self._closed = True
        for key in tuple(self._preferences):
            self.end_guest(key[0])
        await self.drain()

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
        if receipt.explicit_speech_attempted:
            # The native turn already sent speech, including a possible UNKNOWN
            # outcome. Narrating its final text would repeat or obscure that
            # physical effect. Never infer this from the prose itself.
            self._record(receipt, 'EXPLICIT_SPEECH_ATTEMPTED')
            return
        lease = self.leases.current(receipt.guest_id)
        if lease is not receipt.lease or not self.authorize_reply(receipt):
            self._record(receipt, 'PERMISSION')
            return
        state = self._preference(receipt)
        if state is None or not state.enabled:
            self._record(receipt, 'TEXT_DEFAULT')
            return
        revision = state.revision
        if receipt.voice_revision is not None and receipt.voice_revision != revision:
            self._record(receipt, 'POLICY_CHANGED')
            return
        timeout = min(self.timeout, lease.expires_at - self.leases.clock())
        if timeout <= 0:
            self._record(receipt, 'PERMISSION')
            return
        phrase = spoken_sentence(receipt.text)
        if phrase is None:
            self._record(receipt, 'EMPTY')
            return
        speaker, connection = state.speaker, state.connection

        def permitted(device, cap, args):
            return (device is speaker and device.ws is connection and self._bound(state)
                    and self._preference(receipt) is state and state.enabled and state.revision == revision
                    and self.leases.current(receipt.guest_id) is lease
                    and self.authorize_reply(receipt)
                    and self.leases.allows(lease, device, cap))

        try:
            def dispatched(_req, _device):
                job = self._tasks.get(asyncio.current_task())
                if job is not None:
                    job['dispatched'] = True
            result = await self.bus.call(speaker.id, 'say', {'text': phrase}, timeout=timeout,
                                         authorize=permitted, on_dispatch=dispatched)
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
