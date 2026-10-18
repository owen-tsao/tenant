"""Q&A selected by the genuine agent during an authenticated app turn.

No effects on import. Native commands use a private one-use file handoff; only
dispatch after the existing NativeDevices authority check may issue a command.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

OPERATIONS = frozenset({'question-answer', 'question-answer-stop'})
ROOT = Path(__file__).resolve().parents[3] / 'tenant-fast-demo'


def response(ok, code, message, **extra):
    return {'ok': ok, 'code': code, 'message': message, **extra}


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) is not None


class NativeQARunner:
    """No launch/retry: the host prepares the native controller before the demo."""
    def __init__(self, root=ROOT, *, clock=time.time, timeout=45, poll=.1):
        self.root = Path(root)
        self.folder = self.root / 'state/qa-commands'
        self.clock, self.timeout, self.poll = clock, timeout, poll

    def _write(self, path, value, *, exclusive=False):
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.folder / (uuid.uuid4().hex + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'w') as stream: json.dump(value, stream)
            if exclusive:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def cancel(self, request_id):
        if identifier(request_id):
            try:
                (self.folder / (request_id + '.permit.json')).unlink(missing_ok=True)
            except OSError:
                pass  # Stop renewal regardless; the native permit expires in 1s.

    async def __call__(self, request_id, *, authorized):
        if not identifier(request_id) or not authorized():
            return response(False, 'PERMISSION', 'No current app request. Nothing was sent.')
        try:
            health = json.loads((self.root / 'state/answers-runtime.json').read_text())
            if (health.get('native_protocol') != 3 or health.get('backend_ready') is not True
                    or not 0 <= self.clock() - health['updated_at'] <= 8
                    or not isinstance(health.get('controller_instance'), str)):
                raise ValueError('unready')
            if health.get('thinking') or health.get('speaking') or health.get('finishing') or health.get('backend_busy'):
                return response(False, 'BUSY', 'An answer is already running. Nothing was queued.')
        except (OSError, ValueError, KeyError, TypeError):
            return response(False, 'UNAVAILABLE', 'The answer controller is not ready. Nothing was sent.')
        nonce = uuid.uuid4().hex
        command = {'protocol': 1, 'action': 'answer', 'request_id': request_id, 'nonce': nonce,
                   'controller_instance': health['controller_instance'], 'expires_at': self.clock() + 2}
        issued = self.folder / (request_id + '.issued.json')
        try:
            self._write(issued, {'nonce': nonce}, exclusive=True)
        except FileExistsError:
            return response(False, 'DUPLICATE', 'This native request was already issued. It was not replayed.', duplicate=True)
        sent = False
        try:
            if not authorized():
                return response(False, 'PERMISSION', 'App request ended before dispatch. Nothing was sent.')
            permit = {**command, 'expires_at': self.clock() + 1}
            self._write(self.folder / (request_id + '.permit.json'), permit)
            self._write(self.folder / (request_id + '.command.json'), command, exclusive=True)
            sent = True
            deadline = asyncio.get_running_loop().time() + self.timeout
            while True:
                if not authorized():
                    return response(False, 'CANCELLED', 'App authority ended. Pending answer/captions were fenced.')
                target = self.folder / (request_id + '.result.json')
                if target.exists():
                    result = json.loads(target.read_text())
                    if (result.get('request_id') != request_id or result.get('nonce') != nonce
                            or result.get('controller_instance') != command['controller_instance']):
                        return response(False, 'UNKNOWN', 'Native result identity did not match. Nothing was retried.')
                    return {key: value for key, value in result.items()
                            if key in {'ok', 'code', 'speech_started', 'speech_completed', 'caption_completed', 'word_callbacks', 'phrase_switches'}}
                if asyncio.get_running_loop().time() >= deadline:
                    return response(False, 'UNKNOWN', 'Native outcome is unknown. Nothing was retried.')
                self._write(self.folder / (request_id + '.permit.json'), {**command, 'expires_at': self.clock() + 1})
                await asyncio.sleep(self.poll)
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, TypeError):
            return response(False, 'UNKNOWN' if sent else 'FAILED', 'Answer handoff failed. Nothing was retried.')
        finally:
            self.cancel(request_id)


@dataclass
class Pending:
    grant: object
    request_id: str
    logical_request_id: str
    cancelled: bool = False


class PreparedQA:
    """Interface frozen: tools owns live grants; caller supplies authorized()."""
    def __init__(self, tools, *, runner=None):
        self.tools = tools
        self.runner = runner or NativeQARunner()
        self.messages = {}
        self.active: Pending | None = None
        self.calls = {}

    def observe_turn(self, grant, text):
        self.messages[grant.token] = text if isinstance(text, str) and text.strip() else None
        # A new guest message interrupts this spoken answer, irrespective of
        # wording. The agent can then interpret Stop or another request normally.
        if self.active and self._same_owner(grant, self.active.grant):
            self._cancel()

    @staticmethod
    def _same_owner(left, right):
        return (left.lease is right.lease and left.generation == right.generation
                and left.room_id == right.room_id and left.epoch == right.epoch)

    def _cancel(self):
        if self.active:
            self.active.cancelled = True
            self.runner.cancel(self.active.request_id)

    def inventory(self, grant):
        current = {}
        try:
            health = json.loads((ROOT / 'state/answers-runtime.json').read_text())
            if 0 <= time.time() - health['updated_at'] <= 8:
                current = {key: health[key] for key in
                           ('displays', 'selected_caption_display', 'caption_display_selection', 'captions_enabled')
                           if key in health}
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return {'operations': sorted(OPERATIONS), **current,
                'interpretation': 'Use the genuine agent to interpret an actual guest request; no fixed wording.',
                'transcript': 'read-only question context, never an action trigger'}

    def context(self, grant):
        if self.messages.get(grant.token) is None:
            return ''
        return ('\nQ&A: interpret actual guest requests/followups naturally. question-answer(request_id) '
                'composes an answer to the latest separately heard judge question using the transcript and '
                'verified facts, then speaks with captions on an available screen (Mac if no external). '
                'No prepared-answer whitelist. Use only when the guest requests that spoken/presented '
                'interaction. Ordinary typed questions get text; never substitute an unrelated transcript '
                'question. No action for negated/quoted/hypothetical/unrelated input or transcript updates '
                'alone. If no question is identifiable, ask without inventing it; distinguish inference '
                'failure. question-answer-stop(request_id) stops it. New guest input interrupts answers, '
                'not music. No duplicate narration or UNKNOWN retries.')

    def finish(self, grant):
        self.messages.pop(grant.token, None)
        if self.active and self.active.grant is grant:
            self._cancel()

    def invalidate(self):
        self.messages.clear(); self._cancel()

    async def dispatch(self, grant, operation, payload, *, authorized):
        if operation not in OPERATIONS or not isinstance(payload, dict) or set(payload) != {'request_id'} or not identifier(payload['request_id']):
            return response(False, 'INVALID', 'Expected only a unique request_id. Nothing was sent.')
        expected = 'answer' if operation == 'question-answer' else 'stop'
        if not authorized():
            return response(False, 'PERMISSION', 'This app turn has no current Q&A authority. Nothing was sent.')
        key = (grant.token, payload['request_id'])
        previous = self.calls.get(key)
        if previous:
            op, future = previous
            if op != operation:
                return response(False, 'INVALID', 'Request ID belongs to another action.')
            return {**await asyncio.shield(future), 'duplicate': True}
        if self.messages.get(grant.token) is None:
            return response(False, 'PERMISSION', 'No authenticated guest input is bound to this turn. Nothing was sent.')
        future = asyncio.get_running_loop().create_future()
        self.calls[key] = (operation, future)
        # No language classifier here: the genuine agent chose this operation.
        # Lifecycle, request identity and source checks stay deterministic.
        if expected == 'stop':
            if self.active and not self._same_owner(grant, self.active.grant):
                result = response(False, 'PERMISSION', 'Another owner controls the pending answer.')
            else:
                self._cancel()
                result = response(True, 'CANCELLED', 'Answer/captions fenced; native cleanup is pending.', cleanup='pending')
            future.set_result(result)
            return result
        if self.active is not None:
            result = response(False, 'BUSY', 'An answer is already pending. Nothing was queued.')
            future.set_result(result); return result
        # Model-chosen logical IDs are only turn-local. Keep the native receipt
        # namespace distinct across grants without exposing the private token.
        native_id = 'qa_' + hashlib.sha256((grant.token + '\0' + payload['request_id']).encode()).hexdigest()
        pending = Pending(grant, native_id, payload['request_id']); self.active = pending
        def allowed():
            return self.active is pending and not pending.cancelled and authorized()
        try:
            result = await self.runner(pending.request_id, authorized=allowed)
            if not isinstance(result, dict) or type(result.get('ok')) is not bool:
                result = response(False, 'UNKNOWN', 'Native answer outcome was unreadable. Nothing was retried.')
            if not allowed():
                result = response(False, 'CANCELLED', 'Answer authority ended; late results were discarded.')
            future.set_result(result)
            return result
        except asyncio.CancelledError:
            pending.cancelled = True; self.runner.cancel(pending.request_id)
            future.set_result(response(False, 'UNKNOWN', 'Answer was interrupted. Nothing was retried.'))
            raise
        except Exception:
            result = response(False, 'UNKNOWN', 'Answer outcome is unknown. Nothing was retried.')
            future.set_result(result); return result
        finally:
            if self.active is pending: self.active = None
