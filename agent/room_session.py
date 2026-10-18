"""Client for one already-created, visible Codex room conversation.

Uses the existing local desktop daemon; never creates threads, changes global
configuration, copies authentication, retries turns, or auto-approves tools.
Closing this connection does not imply that physical effects were undone.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

# Full device/result guidance plus the local demo index exceed 6k on this Mac.
# Keep a finite pre-submission bound without truncating execution/cleanup rules.
MAX_APPLICATION_CONTEXT = 8000
# The desktop renderer shortens each application-context fragment. Keep every
# fragment below that limit rather than silently losing middle tool guidance.
APPLICATION_CONTEXT_FRAGMENT = 2000


def application_fragments(context):
    parts = []
    while context:
        boundary = min(len(context), APPLICATION_CONTEXT_FRAGMENT)
        if boundary < len(context):
            split = context.rfind(' ', 0, boundary)
            if split > boundary // 2:
                boundary = split + 1
        parts.append(context[:boundary])
        context = context[boundary:]
    return {('tenant_devices' if index == 0 else f'tenant_devices_{index + 1:02d}'):
            {'kind': 'application', 'value': part}
            for index, part in enumerate(parts)}


class RoomSessionError(RuntimeError):
    def __init__(self, message, *, code=None, outcome_unknown=False):
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown


class NativeTurnError(RoomSessionError):
    """A scoped native failure; it does not prove that earlier effects stopped."""

    def __init__(self, status, *, turn_id):
        super().__init__('Native turn did not complete', code='NATIVE_TERMINAL', outcome_unknown=True)
        self.status = status
        self.turn_id = turn_id


class RoomSession:
    def __init__(self, thread_id, *, socket_path=None, connector=None,
                 request_timeout=10, event_limit=512):
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError('A configured room thread ID is required')
        self.thread_id = thread_id
        codex_home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
        self.socket_path = str(socket_path or codex_home / 'app-server-control' / 'app-server-control.sock')
        self.connector = connector
        self.request_timeout = request_timeout
        self._events = asyncio.Queue(maxsize=event_limit)
        self._pending = {}
        self._server_requests = {}
        self._ws = None
        self._reader = None
        self._closed = False
        self._failure = None
        self._active_turn = None
        self._busy_unknown = False
        self._reset_required = False
        self._completed_turns = set()
        self._activity_generation = 0
        self._start_lock = asyncio.Lock()
        self._steer_blocked_turn = None
        self.resume_info = None

    @property
    def active_turn_id(self):
        return self._active_turn

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def connect(self):
        if self._ws is not None:
            return self.resume_info
        if self._closed:
            raise RoomSessionError('Room connection is closed')
        connector = self.connector
        if connector is None:
            from websockets.asyncio.client import unix_connect
            connector = unix_connect
        try:
            self._ws = await connector(self.socket_path, uri='ws://localhost', open_timeout=5,
                                       close_timeout=1, max_size=8_000_000)
            self._reader = asyncio.create_task(self._read())
            await self._request('initialize', {
                'clientInfo': {'name': 'tenant_room', 'title': 'Tenant room', 'version': '0.1'},
                'capabilities': {'experimentalApi': True}})
            await self._send({'method': 'initialized', 'params': {}})
            self.resume_info = await self._request('thread/resume', {'threadId': self.thread_id, 'excludeTurns': True})
            thread = self.resume_info.get('thread', {})
            if thread.get('id') != self.thread_id:
                raise RoomSessionError('Daemon returned a different room conversation')
            self._busy_unknown = thread.get('status', {}).get('type') == 'active' and self._active_turn is None
            return self.resume_info
        except BaseException:
            await self.close()
            raise

    async def _send(self, message):
        if self._closed or self._ws is None or self._failure:
            raise RoomSessionError('Room connection is unavailable')
        await self._ws.send(json.dumps(message))

    async def _request(self, method, params):
        request_id = 'tenant_' + uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({'id': request_id, 'method': method, 'params': params})
            try:
                async with asyncio.timeout(self.request_timeout):
                    return await future
            except TimeoutError:
                raise RoomSessionError('Room request timed out; it was not retried',
                                       outcome_unknown=method in ('turn/start', 'turn/steer')) from None
        finally:
            self._pending.pop(request_id, None)

    async def _read(self):
        try:
            async for raw in self._ws:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise RoomSessionError('Invalid room protocol message')
                if 'method' not in message:
                    future = self._pending.get(message.get('id'))
                    if future is None or future.done():
                        continue
                    if 'error' in message:
                        future.set_exception(RoomSessionError('Room daemon rejected the request',
                                                              code=message['error'].get('code')))
                    elif isinstance(message.get('result'), dict):
                        future.set_result(message['result'])
                    else:
                        future.set_exception(RoomSessionError('Invalid room response'))
                    continue
                params = message.get('params', {})
                if not isinstance(params, dict):
                    raise RoomSessionError('Invalid room event')
                event_thread = params.get('threadId') or params.get('thread', {}).get('id')
                # Only the configured room's events can reach the room frontend.
                if event_thread != self.thread_id:
                    if 'id' in message:
                        raise RoomSessionError('Tool request belongs to another conversation')
                    continue
                turn = params.get('turn', {})
                if message['method'] in ('turn/started', 'turn/completed') and turn.get('id') in self._completed_turns:
                    # A terminal start response and its notification may race.
                    # Neither a duplicate completion nor a late start reopens it.
                    continue
                if (message['method'] in ('turn/started', 'turn/completed', 'thread/queue/changed')
                        or (message['method'] == 'error' and params.get('willRetry') is False) or 'id' in message):
                    self._activity_generation += 1
                if message['method'] == 'turn/started':
                    self._active_turn = turn.get('id')
                    self._busy_unknown = False
                elif message['method'] == 'turn/completed':
                    self._completed_turns.add(turn.get('id'))
                    if self._active_turn is None or turn.get('id') == self._active_turn:
                        self._active_turn = None
                        self._busy_unknown = False
                if 'id' in message:
                    self._server_requests[message['id']] = params
                # Losing progress or an approval would be unsafe; fail instead of dropping it.
                self._events.put_nowait(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(RoomSessionError('Room connection ended; ongoing effects may already have started',
                                        outcome_unknown=self._active_turn is not None or self._busy_unknown))
        else:
            if not self._closed:
                self._fail(RoomSessionError('Room connection ended; it was not automatically restarted',
                                            outcome_unknown=self._active_turn is not None or self._busy_unknown))

    def _fail(self, error):
        self._failure = error
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(error)
        # Wake event consumers even if the bounded queue was full.
        if self._events.full():
            self._events.get_nowait()
        self._events.put_nowait(error)

    async def start_turn(self, text, *, authorize=None, application_context=None,
                         image_paths=None, output_schema=None, model=None, effort=None,
                         turn_trigger=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ValueError('A room message of 1–8000 characters is required')
        if application_context is not None and (not isinstance(application_context, str)
                                                or not 0 < len(application_context) <= MAX_APPLICATION_CONTEXT):
            raise ValueError(f'Application context must contain 1–{MAX_APPLICATION_CONTEXT} characters')
        images = self._local_images(image_paths)
        if output_schema is not None and (not isinstance(output_schema, dict)
                or len(json.dumps(output_schema)) > 8000):
            raise ValueError('A bounded JSON output schema is required')
        if model is not None and (not isinstance(model, str) or not model or len(model) > 128):
            raise ValueError('An explicit supported model is required')
        if effort is not None and effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'):
            raise ValueError('Invalid reasoning effort')
        if turn_trigger is not None and turn_trigger != 'celsius_observation':
            raise ValueError('Unsupported observation source')
        async with self._start_lock:
            if self._reset_required:
                raise RoomSessionError('Room context must be reset before another user can continue')
            if self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('Room conversation already has an active turn')
            await self.assert_queue_empty()
            if authorize is not None and not authorize():
                raise RoomSessionError('Room access ended before submission')
            self._busy_unknown = True
            try:
                params = {'threadId': self.thread_id, 'input': [{'type': 'text', 'text': text}] + images}
                for key, value in (('outputSchema', output_schema), ('model', model),
                                   ('effort', effort), ('turnTrigger', turn_trigger)):
                    if value is not None:
                        params[key] = value
                if application_context is not None:
                    # Installed experimental TurnStartParams defines this as
                    # application context, separate from exact guest input.
                    params['additionalContext'] = application_fragments(application_context)
                result = await self._request('turn/start', params)
            except asyncio.CancelledError:
                # Cancellation of this client cannot undo shell, UI or physical effects.
                self.require_reset()
                try:
                    await asyncio.shield(self.interrupt())
                finally:
                    raise
            except RoomSessionError as error:
                self.require_reset()
                if error.outcome_unknown:
                    self._busy_unknown = self._active_turn is None
                raise
            turn = result.get('turn', {})
            if not isinstance(turn.get('id'), str) or not turn['id']:
                self._busy_unknown = True
                raise RoomSessionError('Room turn may have started; no turn ID was returned', outcome_unknown=True)
            status = turn.get('status')
            if status in ('completed', 'interrupted', 'failed', 'cancelled'):
                if turn['id'] not in self._completed_turns:
                    self._completed_turns.add(turn['id'])
                    if self._active_turn in (None, turn['id']):
                        self._active_turn = None
                    self._busy_unknown = False
                    self._activity_generation += 1
                    try:
                        # A terminal RPC response need not have another notification.
                        # Only final assistant text is eligible for guest publication.
                        if status == 'completed':
                            for item in turn.get('items', []):
                                if item.get('type') == 'agentMessage':
                                    self._events.put_nowait({'method': 'item/completed', 'params': {
                                        'threadId': self.thread_id, 'turnId': turn['id'], 'item': item}})
                        self._events.put_nowait({'method': 'turn/completed', 'params': {
                            'threadId': self.thread_id, 'turn': turn}})
                    except asyncio.QueueFull:
                        self._fail(RoomSessionError('Room terminal events exceeded their bound', outcome_unknown=True))
            elif status == 'inProgress':
                if turn['id'] not in self._completed_turns:
                    self._active_turn = turn['id']
                else:
                    self._busy_unknown = False
            else:
                self.require_reset()
                raise RoomSessionError('Invalid native turn status; it was not retried', outcome_unknown=True)
            return turn['id']

    @staticmethod
    def _local_images(image_paths):
        if image_paths is None:
            return []
        if not isinstance(image_paths, (tuple, list)) or not 0 < len(image_paths) <= 2:
            raise ValueError('One or two real local observation images are required')
        result = []
        for value in image_paths:
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError('Observation image paths must be absolute')
            path = Path(value).resolve(strict=True)
            if not path.is_file() or path.stat().st_size > 10_000_000:
                raise ValueError('Invalid observation image')
            with path.open('rb') as stream:
                if stream.read(8) != b'\x89PNG\r\n\x1a\n':
                    raise ValueError('A real PNG observation is required')
            result.append({'type': 'localImage', 'path': str(path)})
        return result

    async def scene_baseline(self, model, effort='low'):
        """Read explicit restorable defaults and verify this account's catalog.

        No model/setting is changed here. Unknown/null baseline effort cannot be
        restored reliably through optional-field updates, so fail before a turn.
        """
        if self.active_turn_id is not None or self._busy_unknown or self._reset_required:
            raise RoomSessionError('The room is not idle for scene admission')
        thread = (await self.read_thread()).get('thread', {})
        baseline = {'model': thread.get('model'), 'effort': thread.get('reasoningEffort')}
        if (thread.get('id') != self.thread_id or not isinstance(baseline['model'], str)
                or not baseline['model'] or baseline['effort'] not in
                ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')):
            raise RoomSessionError('Explicit restorable room model settings are unavailable')
        catalog = await self._request('model/list', {'limit': 100, 'includeHidden': False})
        supported = any(item.get('model') == model and 'image' in item.get('inputModalities', [])
                        and any(option.get('reasoningEffort') == effort
                                for option in item.get('supportedReasoningEfforts', []))
                        for item in catalog.get('data', []) if isinstance(item, dict))
        if not supported:
            raise RoomSessionError('The scene model/effort/image combination is not supported here')
        return baseline

    async def restore_scene_baseline(self, baseline):
        """Restore and reread exact thread defaults before guest work resumes."""
        try:
            await self._request('thread/settings/update', {'threadId': self.thread_id, **baseline})
            thread = (await self.read_thread()).get('thread', {})
            if (thread.get('id') != self.thread_id or thread.get('model') != baseline['model']
                    or thread.get('reasoningEffort') != baseline['effort']):
                raise RoomSessionError('Room model restoration could not be verified', outcome_unknown=True)
        except BaseException:
            self.require_reset()
            raise

    async def steer_turn(self, text, *, expected_turn_id, authorize=None, image_paths=None):
        """Append to exactly one active turn; never consume events or fall back.

        The original turn's caller remains its only event consumer. An uncertain,
        rejected or cancelled steer cannot be replayed into a later turn.
        """
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ValueError('A room message of 1–8000 characters is required')
        if not isinstance(expected_turn_id, str) or not expected_turn_id:
            raise ValueError('An exact active native turn ID is required')
        images = self._local_images(image_paths)
        async with self._start_lock:
            if self._reset_required or self._steer_blocked_turn == expected_turn_id:
                raise RoomSessionError('Steering this room turn is blocked; nothing was retried', code='STEER_BLOCKED')
            if self._active_turn != expected_turn_id or expected_turn_id in self._completed_turns:
                raise RoomSessionError('The expected room turn is no longer active', code='STEER_INACTIVE')
            if authorize is not None and not authorize():
                raise RoomSessionError('Room access ended before steering', code='STEER_ACCESS_ENDED')
            try:
                result = await self._request('turn/steer', {'threadId': self.thread_id,
                    'input': [{'type': 'text', 'text': text}] + images, 'expectedTurnId': expected_turn_id})
            except asyncio.CancelledError:
                self._steer_blocked_turn = expected_turn_id
                raise
            except RoomSessionError:
                self._steer_blocked_turn = expected_turn_id
                raise
            except Exception:
                self._steer_blocked_turn = expected_turn_id
                raise RoomSessionError('Room steering outcome is unknown; it was not retried',
                                       outcome_unknown=True) from None
            if result.get('turnId') != expected_turn_id:
                self._steer_blocked_turn = expected_turn_id
                raise RoomSessionError('Room steering returned an unexpected turn; it was not retried',
                                       outcome_unknown=True)
            if authorize is not None and not authorize():
                self._steer_blocked_turn = expected_turn_id
                raise RoomSessionError('Room access ended before steering confirmation',
                                       code='STEER_ACCESS_ENDED', outcome_unknown=True)
            return expected_turn_id

    async def read_thread(self, *, include_turns=False):
        return await self._request('thread/read', {'threadId': self.thread_id, 'includeTurns': include_turns})

    async def list_turns(self):
        """Return ordered private history, using the supported paginated contract."""
        return await self._list_pages('thread/turns/list', {'sortDirection': 'asc', 'itemsView': 'summary'})

    async def _list_control_items(self, method):
        return await self._list_pages(method)

    async def _list_pages(self, method, extra_params=None):
        items, cursor, seen_cursors = [], None, {None}
        # Page count also bounds empty pages with endlessly changing cursors;
        # item count alone cannot do that. Every seen cursor detects multi-page
        # cycles, rather than only an immediately repeated cursor.
        try:
            for _ in range(16):
                params = {'threadId': self.thread_id, 'limit': 100, **(extra_params or {})}
                if cursor is not None:
                    params['cursor'] = cursor
                page = await self._request(method, params)
                data = page.get('data')
                if not isinstance(data, list) or len(data) > 100:
                    raise RoomSessionError('Invalid room pagination response')
                items.extend(data)
                if len(items) > 1000:
                    raise RoomSessionError('Room pagination exceeds its item limit')
                next_cursor = page.get('nextCursor')
                if next_cursor is None:
                    return items
                if (not isinstance(next_cursor, str) or not next_cursor
                        or next_cursor in seen_cursors):
                    raise RoomSessionError('Room pagination cursor is invalid or repeated')
                seen_cursors.add(next_cursor)
                cursor = next_cursor
            raise RoomSessionError('Room pagination exceeds its page limit')
        except BaseException:
            self.require_reset()
            raise

    async def list_queue(self):
        return await self._list_control_items('thread/queue/list')

    async def assert_queue_empty(self):
        if await self.list_queue():
            self.require_reset()
            raise RoomSessionError('Queued room messages must be removed before continuing')

    async def drain_queue(self):
        self.require_reset()
        deleted = 0
        for item in await self.list_queue():
            if not isinstance(item.get('id'), str):
                raise RoomSessionError('Invalid queued room message')
            result = await self._request('thread/queue/delete', {
                'threadId': self.thread_id, 'queuedSubmissionId': item['id']})
            if result.get('deleted') is not True:
                raise RoomSessionError('A queued room message could not be removed')
            deleted += 1
        await self.assert_queue_empty()
        return deleted

    async def background_terminals(self):
        return await self._list_control_items('thread/backgroundTerminals/list')

    async def terminate_background_terminal(self, process_id):
        self.require_reset()
        if not isinstance(process_id, str) or not process_id:
            raise ValueError('A room-owned background process ID is required')
        return await self._request('thread/backgroundTerminals/terminate', {
            'threadId': self.thread_id, 'processId': process_id})

    def require_reset(self):
        self._reset_required = True

    async def confirm_clean(self, expected_retained_turn_ids):
        """Open the handoff gate only after an already-clean setup is verified."""
        self.require_reset()
        async with self._start_lock:
            generation = self._activity_generation
            if self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('Room turn is still active')
            await self.assert_queue_empty()
            if await self.background_terminals():
                raise RoomSessionError('Room background work remains')
            history = await self.list_turns()
            if [turn.get('id') for turn in history] != list(expected_retained_turn_ids):
                raise RoomSessionError('Room history did not match its clean setup')
            await self.assert_queue_empty()
            if await self.background_terminals():
                raise RoomSessionError('Room background work remains after verification')
            if generation != self._activity_generation or self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('Room activity changed during context verification')
            self._server_requests.clear()
            while not self._events.empty():
                self._events.get_nowait()
            self._reset_required = False

    async def revert(self, before_turn_id, *, expected_retained_turn_ids):
        """Mechanically remove the old guest's history, retaining the known setup.

        The caller must interrupt/drain active work and stop background jobs first.
        This changes stored conversation history; it cannot undo files or effects.
        A rejected, timed-out or unverifiable revert keeps the next-user gate shut.
        """
        self.require_reset()
        async with self._start_lock:
            if self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('Wait for the active room turn to finish before resetting context')
            if not isinstance(before_turn_id, str) or not before_turn_id:
                raise ValueError('The first old-guest turn ID is required')
            if not isinstance(expected_retained_turn_ids, (list, tuple)) or not all(isinstance(t, str) for t in expected_retained_turn_ids):
                raise ValueError('The retained setup turn IDs are required')
            await self.drain_queue()
            if await self.background_terminals():
                raise RoomSessionError('Stop room background jobs before resetting context')
            if self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('A room turn became active during reset')
            generation = self._activity_generation
            result = await self._request('thread/revert', {'threadId': self.thread_id, 'beforeTurnId': before_turn_id})
            if result.get('thread', {}).get('id') != self.thread_id:
                raise RoomSessionError('Context reset returned a different conversation')
            # thread/revert always returns an empty turns array, even with retained
            # history; only pagination verifies what the model will see next.
            history = await self.list_turns()
            if [turn.get('id') for turn in history] != list(expected_retained_turn_ids):
                raise RoomSessionError('Room history did not match its clean setup')
            await self.assert_queue_empty()
            if await self.background_terminals():
                raise RoomSessionError('Room background jobs remain after reset')
            if generation != self._activity_generation or self._active_turn is not None or self._busy_unknown:
                raise RoomSessionError('Room activity changed during context reset')
            self._server_requests.clear()
            while not self._events.empty():
                self._events.get_nowait()
            self._completed_turns.clear()
            self._reset_required = False
            return result

    async def interrupt(self):
        """Request best-effort cancellation. Wait for turn/completed to confirm it.

        A successful response is not evidence that an OS or physical effect was undone.
        """
        if self._active_turn is None:
            return False
        await self._request('turn/interrupt', {'threadId': self.thread_id, 'turnId': self._active_turn})
        return True

    async def next_event(self):
        if self._failure and self._events.empty():
            raise self._failure
        event = await self._events.get()
        if isinstance(event, Exception):
            raise event
        return event

    async def answer(self, request_id, result):
        """Explicit caller response to this room's pending approval/dynamic-tool request.

        The backend must recheck the originating guest lease before granting an
        approval or dispatching a room tool. This transport never grants automatically.
        """
        params = self._server_requests.get(request_id)
        if params is None or params.get('threadId') != self.thread_id:
            raise RoomSessionError('No matching room tool request')
        if not isinstance(params.get('turnId'), str) or not params['turnId'] or params['turnId'] != self._active_turn:
            raise RoomSessionError('Room tool request is no longer active')
        await self._send({'id': request_id, 'result': result})
        self._server_requests.pop(request_id, None)

    async def close(self):
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
        for future in tuple(self._pending.values()):
            if not future.done():
                future.set_exception(RoomSessionError('Room connection closed'))
        self._pending.clear()
