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


class RoomSessionError(RuntimeError):
    def __init__(self, message, *, code=None, outcome_unknown=False):
        super().__init__(message)
        self.code = code
        self.outcome_unknown = outcome_unknown


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
                                       outcome_unknown=method == 'turn/start') from None
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
                if message['method'] in ('turn/started', 'turn/completed', 'thread/queue/changed') or 'id' in message:
                    self._activity_generation += 1
                turn = params.get('turn', {})
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

    async def start_turn(self, text, *, authorize=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            raise ValueError('A room message of 1–8000 characters is required')
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
                result = await self._request('turn/start', {
                    'threadId': self.thread_id, 'input': [{'type': 'text', 'text': text}]})
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
            if not isinstance(turn.get('id'), str):
                self._busy_unknown = True
                raise RoomSessionError('Room turn may have started; no turn ID was returned', outcome_unknown=True)
            if turn.get('status') == 'inProgress' and turn['id'] not in self._completed_turns:
                self._active_turn = turn['id']
            else:
                self._busy_unknown = False
            return turn['id']

    async def read_thread(self, *, include_turns=False):
        return await self._request('thread/read', {'threadId': self.thread_id, 'includeTurns': include_turns})

    async def list_turns(self):
        """Return ordered private history, using the supported paginated contract."""
        turns, cursor = [], None
        while True:
            params = {'threadId': self.thread_id, 'sortDirection': 'asc', 'limit': 100, 'itemsView': 'summary'}
            if cursor is not None:
                params['cursor'] = cursor
            page = await self._request('thread/turns/list', params)
            if not isinstance(page.get('data'), list):
                raise RoomSessionError('Invalid room history response')
            turns.extend(page['data'])
            next_cursor = page.get('nextCursor')
            if next_cursor is None:
                return turns
            if next_cursor == cursor or len(turns) > 1000:
                raise RoomSessionError('Room history could not be safely verified')
            cursor = next_cursor

    async def _list_control_items(self, method):
        items, cursor = [], None
        while True:
            params = {'threadId': self.thread_id, 'limit': 100}
            if cursor is not None:
                params['cursor'] = cursor
            page = await self._request(method, params)
            if not isinstance(page.get('data'), list):
                raise RoomSessionError('Invalid room pending-work response')
            items.extend(page['data'])
            next_cursor = page.get('nextCursor')
            if next_cursor is None:
                return items
            if next_cursor == cursor or len(items) > 1000:
                raise RoomSessionError('Room pending work could not be safely verified')
            cursor = next_cursor

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
