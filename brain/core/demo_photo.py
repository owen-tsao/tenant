"""Leased, two-turn access to the already accepted local photo implementation.

Only ConversationAgent supplies guest text. Microphone/transcript observations,
a remembered photo id and observations cannot supply a later authenticated app turn.
The genuine agent interprets requests and readiness; this adapter validates provenance and lifecycle.
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
OPERATIONS = {'demo-photo-prepare', 'demo-photo-capture', 'demo-photo-cancel', 'demo-photo-status', 'demo-display-list'}


def denied(code, message):
    return {'ok': False, 'code': code, 'status': 'unknown' if code == 'UNKNOWN' else 'unsent', 'message': message}


class PhotoRunner:
    """Invoke the existing photo CLI once, never start/restart its service."""
    def __init__(self, path=None):
        self.path = Path(path or Path(__file__).resolve().parents[3] / 'tenant-fast-demo/photo.py')

    async def __call__(self, action, photo_id=None, *, authorized, display_id=None):
        if not authorized():
            return denied('PERMISSION', 'Room access ended before the photo action.')
        args = [sys.executable, str(self.path), action]
        if photo_id is not None:
            args += ['--id', photo_id]
        if display_id is not None:
            args += ['--display-id', str(display_id)]
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
            if action == 'screens' and isinstance(result, list):
                return {'ok': True, 'displays': result}
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
    display_id: int | None = None


class DemoPhotos:
    def __init__(self, tools, *, runner=None):
        self.tools = tools
        self.runner = runner or PhotoRunner()
        self.pending = None
        self.messages = {}
        self.eligible = {}
        self.unconfirmed_preparations = set()
        self.preparation_failures = {}
        self.lock = asyncio.Lock()

    def invalidate(self):
        self.pending = None
        self.messages.clear()
        self.eligible.clear()
        self.unconfirmed_preparations.clear()
        self.preparation_failures.clear()

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
        """All actual replies get a fresh turn while photo readiness is pending.

        The model, not a phrase list, decides whether that reply means ready,
        wait, cancel, a topic change, or something else.
        """
        pending = self.pending
        return bool(pending and pending.phase == 'waiting_for_reply'
                    and pending.grant.guest_id == guest_id and self._matches(pending.grant))

    def _published_prompt(self, pending):
        grant = pending.grant
        session = self.tools.leases.sessions.get(grant.guest_id)
        return bool(session and (grant.generation, grant.thread_id, grant.turn_id)
                    in session.published_turns)

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
        """Provenance hook for actual ordinary guest input, never ASR/OCR events."""
        self.messages[grant.token] = text if isinstance(text, str) and text.strip() else None
        if not self._matches(grant):
            return
        pending = self.pending
        if (pending.phase == 'waiting_for_reply' and pending.grant.closed
                and grant is not pending.grant and self.messages[grant.token] is not None
                and self._published_prompt(pending)):
            pending.prompt_seen = True
            self.eligible[grant.token] = pending.photo_id

    def finish(self, grant):
        self.messages.pop(grant.token, None)
        self.eligible.pop(grant.token, None)
        self.unconfirmed_preparations.discard(grant.token)
        self.preparation_failures.pop(grant.token, None)

    def final_reply(self, grant, text):
        if grant.token in self.unconfirmed_preparations:
            return self.preparation_failures.get(grant.token,
                "I couldn't prepare the camera. No countdown was started; readiness is not confirmed.")
        return text

    def inventory(self, grant):
        return {'operations': sorted(OPERATIONS), 'pending': self.status(grant)['pending'],
                'interpretation': 'The room agent interprets natural requests and readiness; no keyword matching.',
                'display_discovery': 'demo-display-list',
                'default_presentation': 'Prefer an available unambiguous external display; otherwise the Mac. Ask only on ambiguity.'}

    def context(self, grant):
        return ('\nPhoto/display tools: interpret the actual guest conversation naturally; no fixed wording. '
                'demo-display-list(request_id) discovers displays; prefer an unambiguous external TV/projector, '
                'otherwise Mac. demo-photo-prepare(request_id,optional display_id) stages a photo. '
                'On success ask readiness naturally, END and WAIT. Interpret a later actual app reply: '
                'ready means demo-photo-capture(request_id,photo_id); '
                'negative, ambiguous or unrelated means wait/clarify. capture_eligible_this_turn is ONLY '
                'a lifecycle check, not consent. demo-photo-status(request_id) reads pending state; '
                'demo-photo-cancel(request_id,photo_id) cancels before countdown when asked. '
                'No ASR triggers, raw shortcuts or UNKNOWN retries. Report failed preparation. '
                'Current photo: ' + json.dumps(self.status(grant)['pending'], separators=(',', ':')))

    def status(self, grant):
        pending = self.pending if self._matches(grant) else None
        return {'ok': True, 'pending': ({'photo_id': pending.photo_id, 'phase': pending.phase,
                'display_id': pending.display_id,
                'capture_eligible_this_turn': self.eligible.get(grant.token) == pending.photo_id,
                'readiness_interpretation': 'agent_must_interpret_current_guest_reply'}
                if pending else None)}

    async def dispatch(self, grant, operation, payload, *, authorized):
        fields = set(payload) - {'request_id'} if isinstance(payload, dict) else None
        valid = (operation in ('demo-photo-status', 'demo-display-list') and fields == set()
                 or operation == 'demo-photo-prepare' and fields in (set(), {'display_id'})
                 and ('display_id' not in payload or type(payload['display_id']) is int and 0 < payload['display_id'] < 2**32)
                 or operation in ('demo-photo-capture', 'demo-photo-cancel') and fields == {'photo_id'}
                 and isinstance(payload.get('photo_id'), str))
        if not valid:
            return denied('INVALID', 'Invalid photo/display payload. Nothing was sent.')
        # Capture holds the effect lock. A validated late cancel must report
        # that boundary promptly, without waiting or sending a native action.
        if (operation == 'demo-photo-cancel' and authorized()
                and self.messages.get(grant.token) is not None
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
            if operation == 'demo-display-list':
                return await self.runner('displays', authorized=authorized)
            if operation == 'demo-photo-prepare':
                if grant.token in self.unconfirmed_preparations:
                    return denied('UNKNOWN', 'Preparation was already attempted this turn. Nothing was retried.')
                if self._matches(grant):
                    if self.pending.phase == 'waiting_for_reply':
                        if ('display_id' in payload and payload['display_id'] != self.pending.display_id):
                            return denied('DISPLAY_PINNED', 'Cancel the waiting photo before preparing it on another display.')
                        self.pending.grant = grant
                        self.pending.prompt_seen = False
                        return {**self.status(grant), 'phase': self.pending.phase, 'message': QUESTION}
                    if self.pending.phase == 'capture_requested_or_unknown':
                        return denied('UNKNOWN', 'The previous capture is unconfirmed. Nothing was retried.')
                self.unconfirmed_preparations.add(grant.token)
                options = {'display_id': payload['display_id']} if 'display_id' in payload else {}
                result = await self.runner('prepare', authorized=authorized, **options)
                if (authorized() and result.get('ok') is False
                        and result.get('code') == 'PHOTO_PREPARE_FAILED'
                        and result.get('status') == 'unsent'
                        and result.get('countdown_started') is False
                        and result.get('shutter_requested') is False):
                    # Only an explicit pre-shutter failure can be reported as
                    # unsent; timeouts and incomplete receipts stay UNKNOWN.
                    stage = result.get('stage')
                    message = ('Photo Booth could not be fitted to the selected display. '
                               if stage in ('placement', 'geometry', 'fit') else
                               'The camera could not be prepared. '
                               if stage in ('warmup', 'camera') else
                               'Photo setup failed. ')
                    message += 'No countdown was started and no photo was taken.'
                    self.preparation_failures[grant.token] = message
                    return denied('PHOTO_PREPARE_FAILED', message)
                if (not authorized() or result.get('ok') is not True
                        or result.get('phase') != 'waiting_for_yes'
                        or not isinstance(result.get('id'), str)
                        or not re.fullmatch(r'[a-f0-9]{32}', result['id'])
                        or type(result.get('expires')) not in (float, int)
                        or not math.isfinite(result['expires'])
                        or type(result.get('display_id')) is not int or not 0 < result['display_id'] < 2**32
                        or ('display_id' in payload and result['display_id'] != payload['display_id'])
                        or result['expires'] <= self.tools.leases.clock()):
                    return denied('UNKNOWN', 'Photo preparation was not confirmed. Nothing was retried.')
                self.pending = PendingPhoto(result['id'], grant,
                    min(result['expires'], self.tools.leases.clock() + 90, grant.lease.expires_at),
                    display_id=result.get('display_id'))
                self.unconfirmed_preparations.discard(grant.token)
                return {'ok': True, 'phase': 'waiting_for_reply', 'photo_id': result['id'],
                        'message': QUESTION, 'end_turn_and_wait': True, 'capture_eligible_this_turn': False}
            if not self._matches(grant) or payload.get('photo_id') != self.pending.photo_id:
                return denied('STALE', 'This guest has no matching unexpired pending photo. Request a new photo.')
            pending = self.pending
            if operation == 'demo-photo-cancel':
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
                    or self.eligible.get(grant.token) != pending.photo_id):
                return denied('READINESS', 'Wait for this guest to reply in Tenant that they are ready. No countdown was started.')
            pending.phase = 'capture_requested_or_unknown'
            options = {'display_id': pending.display_id} if pending.display_id is not None else {}
            result = await self.runner('capture', pending.photo_id, authorized=authorized, **options)
            if (not authorized() or result.get('ok') is not True or result.get('id') != pending.photo_id
                    or result.get('phase') != 'displayed' or result.get('capture_verified') is not True):
                return denied('UNKNOWN', 'The photo result is unconfirmed. Do not repeat the countdown or capture.')
            pending.phase = 'displayed'
            return {'ok': True, 'phase': 'displayed', 'photo_id': pending.photo_id,
                    'capture_verified': True, 'message': 'Your photo is displayed on the selected screen.'}
