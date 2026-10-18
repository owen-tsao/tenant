"""Leased, two-turn access to the already accepted local photo implementation.

Only ConversationAgent supplies guest text. Microphone/transcript observations,
helper payload declarations and a remembered photo id cannot authorize capture.
The broad native computer tools remain outside this helper's authority boundary.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import re
import signal
import sys


QUESTION = 'Are you ready?'
OPERATIONS = {'demo-photo-prepare', 'demo-photo-capture', 'demo-photo-cancel', 'demo-photo-status'}


def normalized(text):
    return re.sub(r'\s+', ' ', text.strip().casefold().replace('’', "'")) if isinstance(text, str) else ''


def photo_request(text):
    # A small admission check, not a second general intent model. The genuine
    # agent decides whether to call prepare on the actual current app request.
    return bool(re.fullmatch(
        r"(?:hey[, ]+(?:tenant[, ]+)?)?(?:(?:can|could|would|will) you |can we )?"
        r"(?:please )?(?:take|snap|capture|shoot|get)\b[^.!?\n]{0,100}\b(?:photo|picture|selfie)s?\b[^.!?\n]{0,80}[.!?]?",
        normalized(text)))


def explicit_ready(text):
    return bool(re.fullmatch(
        r"(?:i(?:'m| am)|we(?:'re| are)) (?:all |now )?ready(?: now)?[.!]?|ready(?: now)?[.!]?|"
        r"(?:yes[, ]+)?(?:i(?:'m| am)|we(?:'re| are)) ready[.!]?",
        normalized(text)))


def explicit_photo_ready(text):
    return bool(re.fullmatch(r"(?:i(?:'m| am)|we(?:'re| are)) ready for (?:the |a )?(?:photo|picture)[.!]?",
                             normalized(text)))


def not_yet(text):
    return bool(re.fullmatch(r"(?:no[, ]+)?(?:not yet|wait|not ready|i(?:'m| am) not ready)(?: please)?[.!]?",
                             normalized(text)))


def cancellation(text):
    return normalized(text).rstrip('.!') in {'cancel', 'cancel the photo', 'cancel photo', 'stop', 'never mind', 'nevermind'}


def bare_yes(text):
    return normalized(text).rstrip('.!') in {'yes', 'yep', 'yeah', 'yes please'}


def denied(code, message):
    return {'ok': False, 'code': code, 'status': 'unknown' if code == 'UNKNOWN' else 'unsent', 'message': message}


class PhotoRunner:
    """Invoke the existing photo CLI once, never start/restart its service."""
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parents[3] / 'tenant-fast-demo/photo.py')

    async def __call__(self, action, photo_id=None, *, authorized):
        if not authorized():
            return denied('PERMISSION', 'Room access ended before the photo action.')
        args = [sys.executable, str(self.path), action]
        if photo_id is not None:
            args += ['--id', photo_id]
        if action == 'capture':
            args += ['--confirmed']
        process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
        task = asyncio.create_task(process.communicate())
        try:
            async with asyncio.timeout(24):
                while not task.done():
                    await asyncio.wait((task,), timeout=.05)
                    if not authorized():
                        raise PermissionError('Room access ended during the photo action')
                output, _ = await task
            if len(output) > 65536:
                raise ValueError('Oversized photo receipt')
            result = json.loads(output)
            if not isinstance(result, dict):
                raise ValueError('Invalid photo receipt')
            return result
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(asyncio.shield(task), 1)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@dataclass
class PendingPhoto:
    photo_id: str
    grant: object = field(repr=False)
    expires: float
    phase: str = 'waiting_for_reply'
    prompt_seen: bool = False
    first_reply: bool = True
    photo_conversation: bool = True


class DemoPhotos:
    def __init__(self, tools, *, runner=None):
        self.tools = tools
        self.runner = runner or PhotoRunner()
        self.pending = None
        self.messages = {}
        self.ready = {}
        self.unconfirmed_preparations = set()
        self.lock = asyncio.Lock()

    def invalidate(self):
        self.pending = None
        self.messages.clear()
        self.ready.clear()
        self.unconfirmed_preparations.clear()

    def _matches(self, grant):
        pending = self.pending
        if pending is None:
            return False
        previous = pending.grant
        return (previous.guest_id == grant.guest_id and previous.lease is grant.lease
                and previous.generation == grant.generation and previous.room_id == grant.room_id
                and previous.epoch == grant.epoch
                and self.tools.registry.room.id == grant.room_id
                and self.tools.leases.current(grant.guest_id) is grant.lease
                and self.tools.registry.room.epoch == grant.epoch
                and self.tools.leases.clock() < pending.expires)

    def requires_new_turn(self, guest_id, text):
        """Sync: do not steer this real follow-up into the preparation grant."""
        pending = self.pending
        return bool(pending and pending.phase == 'waiting_for_reply'
                    and pending.grant.guest_id == guest_id and self._matches(pending.grant)
                    and (explicit_ready(text) or explicit_photo_ready(text) or bare_yes(text)
                         or not_yet(text) or cancellation(text)))

    def _published_prompt(self, pending):
        grant = pending.grant
        session = self.tools.leases.sessions.get(grant.guest_id)
        if session is None:
            return False
        publication = (grant.generation, grant.thread_id, grant.turn_id)
        last_room = next((row['text'] for row in reversed(session.transcript) if row['role'] == 'room'), '')
        return (publication in session.published_turns
                and bool(re.search(r'\bare you ready\b[^?]*\?', normalized(last_room))))

    async def wait_for_prompt(self, guest_id, text, *, timeout=1.5):
        """Await ONLY after the controller lock admits the follow-up as a new turn.

        Publication happens outside agent.turn's lock, after WebSocket send.
        This bounded, read-only recheck closes that scheduling race. False means
        the caller must return feedback rather than steer/drop/capture the reply.
        """
        if not self.requires_new_turn(guest_id, text):
            return True
        pending = self.pending
        deadline = asyncio.get_running_loop().time() + timeout
        while self.pending is pending and self._matches(pending.grant):
            if pending.grant.closed and (pending.prompt_seen or self._published_prompt(pending)):
                return True
            if asyncio.get_running_loop().time() >= deadline:
                return False
            await asyncio.sleep(.01)
        return False

    def observe_turn(self, grant, text):
        """Called only by the ordinary room agent, before its actual native turn."""
        self.messages[grant.token] = text if grant.lease.channel == 'webchat' else None
        if not self._matches(grant):
            return
        pending = self.pending
        if (pending.phase != 'waiting_for_reply' or not pending.grant.closed
                or self.messages[grant.token] is None):
            return
        session = self.tools.leases.sessions[grant.guest_id]
        publication = (grant.generation, grant.thread_id, pending.grant.turn_id)
        # The public projection is written by the actual app delivery path, not
        # by a tool's question_asked/confirmed flag or by a transcript watcher.
        prior = session.transcript[:-1] if session.transcript and session.transcript[-1]['role'] == 'guest' else session.transcript
        last_room = next((row['text'] for row in reversed(prior) if row['role'] == 'room'), '')
        prompt_now = (publication in session.published_turns
                      and bool(re.search(r'\bare you ready\b[^?]*\?', normalized(last_room))))
        pending.prompt_seen = pending.prompt_seen or prompt_now
        direct = pending.first_reply and prompt_now
        pending.first_reply = False
        if pending.prompt_seen and (explicit_photo_ready(text)
                or (pending.photo_conversation and explicit_ready(text)) or (direct and bare_yes(text))):
            self.ready[grant.token] = pending.photo_id
        elif not not_yet(text):
            pending.photo_conversation = False

    def finish(self, grant):
        self.messages.pop(grant.token, None)
        self.ready.pop(grant.token, None)
        self.unconfirmed_preparations.discard(grant.token)

    def final_reply(self, grant, text):
        if grant.token in self.unconfirmed_preparations:
            return "I couldn't prepare the camera. No countdown was started; readiness is not confirmed."
        return text

    def context(self, grant):
        pending = self.pending if self._matches(grant) else None
        state = ({'photo_id': pending.photo_id, 'phase': pending.phase,
                  'capture_allowed_this_turn': self.ready.get(grant.token) == pending.photo_id}
                 if pending else None)
        return ('\nMac photo workflow: use ONLY this turn\'s helper demo-photo-prepare '
                '(request_id), demo-photo-capture (request_id,photo_id), demo-photo-status '
                '(request_id), demo-photo-cancel (request_id,photo_id). On a photo request '
                'prepare. ONLY after ok:true and phase:waiting_for_reply, reply exactly '
                '"Are you ready?" and END the turn. On failure report preparation failed; '
                'do not claim readiness or retry. WAIT for '
                'a later Tenant message. Never capture in the preparation turn or use '
                'the raw photo.py --confirmed shortcut. Readiness comes only from actual '
                'current guest input, never continuous transcript speech. If not yet, '
                'wait. Capture only when the helper says capture_allowed_this_turn; '
                'use that exact photo_id. Cancel is supported only while waiting, '
                'before countdown. After capture is requested, cancellation cannot '
                'stop it; report its pending or unknown outcome truthfully. '
                'No retry of unknown effects. Current photo: '
                + json.dumps(state, separators=(',', ':')))

    def status(self, grant):
        pending = self.pending if self._matches(grant) else None
        return {'ok': True, 'pending': ({'photo_id': pending.photo_id, 'phase': pending.phase,
                'capture_allowed_this_turn': self.ready.get(grant.token) == pending.photo_id}
                if pending else None)}

    async def dispatch(self, grant, operation, payload, *, authorized):
        # Capture holds the effect lock. A validated late cancel must report
        # that boundary promptly, without waiting or sending a native action.
        if (operation == 'demo-photo-cancel' and authorized()
                and cancellation(self.messages.get(grant.token))
                and self._matches(grant) and payload.get('photo_id') == self.pending.photo_id
                and self.pending.phase == 'capture_requested_or_unknown'):
            return {**denied('UNKNOWN', 'Capture was already requested; its result may still be pending or unconfirmed. '
                            'Cancellation is supported only before countdown. Do not repeat the capture.'),
                    'phase': self.pending.phase, 'photo_id': self.pending.photo_id}
        async with self.lock:
            if operation not in OPERATIONS:
                return denied('INVALID', 'Unknown photo operation. Nothing was sent.')
            if not authorized() or self.messages.get(grant.token) is None:
                return denied('PERMISSION', 'A current message in Tenant is required for this photo action.')
            if operation == 'demo-photo-status':
                return self.status(grant)
            if operation == 'demo-photo-prepare':
                if not photo_request(self.messages[grant.token]):
                    return denied('PERMISSION', 'This Tenant message did not request a photo.')
                if grant.token in self.unconfirmed_preparations:
                    return denied('UNKNOWN', 'Preparation was already attempted this turn. Nothing was retried.')
                if self._matches(grant):
                    if self.pending.phase == 'waiting_for_reply':
                        self.pending.grant = grant
                        self.pending.prompt_seen = False
                        self.pending.first_reply = True
                        self.pending.photo_conversation = True
                    return {**self.status(grant), 'phase': self.pending.phase, 'message': QUESTION}
                self.unconfirmed_preparations.add(grant.token)
                result = await self.runner('prepare', authorized=authorized)
                if (not authorized() or result.get('ok') is not True
                        or result.get('phase') != 'waiting_for_yes'
                        or not isinstance(result.get('id'), str)
                        or not re.fullmatch(r'[a-f0-9]{32}', result['id'])
                        or type(result.get('expires')) not in (float, int)
                        or not math.isfinite(result['expires'])
                        or result['expires'] <= self.tools.leases.clock()):
                    return denied('UNKNOWN', 'Photo preparation was not confirmed. Nothing was retried.')
                self.pending = PendingPhoto(result['id'], grant,
                    min(result['expires'], self.tools.leases.clock() + 90, grant.lease.expires_at))
                self.unconfirmed_preparations.discard(grant.token)
                return {'ok': True, 'phase': 'waiting_for_reply', 'photo_id': result['id'],
                        'message': QUESTION, 'end_turn_and_wait': True, 'capture_allowed_this_turn': False}
            if not self._matches(grant) or payload.get('photo_id') != self.pending.photo_id:
                return denied('STALE', 'This guest has no matching unexpired pending photo. Request a new photo.')
            pending = self.pending
            if operation == 'demo-photo-cancel':
                if not cancellation(self.messages[grant.token]):
                    return denied('PERMISSION', 'This Tenant message did not cancel the photo.')
                if pending.phase != 'waiting_for_reply':
                    if pending.phase == 'displayed':
                        return {'ok': False, 'code': 'COMPLETED', 'status': 'displayed',
                                'phase': pending.phase, 'photo_id': pending.photo_id,
                                'message': 'The photo is already displayed. Cancellation is supported only before countdown.'}
                    return denied('UNKNOWN', 'This photo is no longer waiting before countdown. '
                                  'Cancellation was not confirmed. Do not repeat the capture.')
                pending.phase = 'cancelled'
                return await self.runner('cancel', pending.photo_id, authorized=authorized)
            if (pending.phase != 'waiting_for_reply' or not pending.grant.closed
                    or self.ready.get(grant.token) != pending.photo_id):
                return denied('READINESS', 'Wait for this guest to reply in Tenant that they are ready. No countdown was started.')
            pending.phase = 'capture_requested_or_unknown'
            result = await self.runner('capture', pending.photo_id, authorized=authorized)
            if (not authorized() or result.get('ok') is not True or result.get('id') != pending.photo_id
                    or result.get('phase') != 'displayed' or result.get('capture_verified') is not True):
                return denied('UNKNOWN', 'The photo result is unconfirmed. Do not repeat the countdown or capture.')
            pending.phase = 'displayed'
            return {'ok': True, 'phase': 'displayed', 'photo_id': pending.photo_id,
                    'capture_verified': True, 'message': 'Your photo is displayed on the TV.'}
