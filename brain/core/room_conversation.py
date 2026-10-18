"""One genuine native Codex conversation, with a single leased room controller.

Admission happens on the first valid message. A new lease ends the old controller
and mechanically resets native history before its first submission. Broad native
computer tools do not pass through Tenant's device Bus: interruption is best
 effort and cannot undo already-started computer, file, or physical effects.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Callable
from agent.room_session import RoomSession, RoomSessionError
from brain.core.conversation_speech import CompletedReply, ReplyFrames


@dataclass(frozen=True)
class ConversationSettings:
    thread_id: str
    anchor_turn_ids: tuple[str, ...]
    socket_path: str | None = None
    turn_timeout: float = 120
    cleanup_timeout: float = 15
    poll_interval: float = .1
    session_factory: Callable | None = field(default=None, repr=False)

    def __post_init__(self):
        if not self.thread_id or not self.anchor_turn_ids or any(not isinstance(t, str) or not t for t in self.anchor_turn_ids):
            raise ValueError('Conversation mode requires a fixed thread and explicit clean setup anchor')


class ConversationAgent:
    agent_mode = 'conversation'

    def __init__(self, leases, log, settings: ConversationSettings, *, private_values=(), registry=None, bus=None):
        self.leases, self.log, self.settings = leases, log, settings
        self.registry = registry
        self.private_values = tuple(v for v in private_values if isinstance(v, str) and v)
        self.pending = {}  # Existing Core compatibility; no interpreter fallback.
        self.locks = {}
        self._lock = asyncio.Lock()
        self._session = None
        self._controller = None
        self._generation = 0
        self._clean_generation = None
        self._stop = asyncio.Event()
        self._cleanup_tasks = set()
        self._failed = False
        self._first_guest_turn = None
        self.device_tools = None
        if registry is not None and bus is not None:
            from brain.core.native_devices import NativeDevices
            self.device_tools = NativeDevices(registry, bus, leases, log, self._device_turn_allowed,
                                               turn_timeout=settings.turn_timeout)

    def _device_turn_allowed(self, grant):
        return (self._allowed(grant.guest_id, grant.generation)
                and self._session is not None and self._session.active_turn_id == grant.turn_id)

    def label_is_ambiguous(self, device):
        if self.registry is None:
            return False
        def normalized(label):
            return re.sub(r'[^\w ]', '', label.casefold()).strip()
        return sum(normalized(other.label) == normalized(device.label)
                   for other in self.registry.devices.values()
                   if other.room_id == self.registry.room.id) > 1

    @staticmethod
    def reply(text):
        return [{'type': 'assistant', 'text': text}]

    def _denied(self, guest_id):
        return self.reply(self.leases.denial(guest_id))

    def _allowed(self, guest_id, generation):
        lease = self.leases.current(guest_id)
        return (not self._failed and self._controller == guest_id and self._generation == generation
                and lease is not None and ('*' in lease.scopes or 'computer' in lease.scopes)
                and not self._stop.is_set())

    def allows_reply(self, receipt):
        """Authorize this completed turn's optional output without renewing access."""
        return (isinstance(receipt, CompletedReply)
                and receipt.thread_id == self.settings.thread_id
                and self.leases.current(receipt.guest_id) is receipt.lease
                and self._allowed(receipt.guest_id, receipt.generation))

    def _admit(self, guest_id):
        if self._controller != guest_id:
            if self.device_tools is not None:
                self.device_tools.revoke_all()
            previous = self._controller
            self._stop.set()
            self._stop = asyncio.Event()
            self._generation += 1
            self._clean_generation = None
            self._controller = guest_id
            if previous:
                self.leases.revoke(previous)
        return self._generation

    def access_ended(self, guest_id):
        """Synchronous authority transition; asynchronously interrupt/drain native work."""
        if self._controller != guest_id:
            return
        if self.device_tools is not None:
            self.device_tools.revoke_all()
        self._stop.set()
        self._controller = None
        self._generation += 1
        self._clean_generation = None
        generation = self._generation
        try:
            task = asyncio.create_task(self._settle_ended(generation))
        except RuntimeError:
            return
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    def check_access(self):
        if self._controller and self.leases.current(self._controller) is None:
            self.access_ended(self._controller)

    async def _settle_ended(self, generation):
        async with self._lock:
            if generation != self._generation:
                return  # The incoming controller performs the same cleanup before submission.
            try:
                if self._session is not None:
                    await self._reset_native()
            except Exception:
                self._failed = True
                self.log.append('err', 'Tenant could not confirm that the previous conversation stopped.')

    async def _connect(self):
        if self._session is None:
            factory = self.settings.session_factory or RoomSession
            session = factory(self.settings.thread_id, socket_path=self.settings.socket_path)
            await session.connect()
            self._session = session
        return self._session

    async def _drain_active(self):
        session = self._session
        if session is None:
            return
        if getattr(self, '_cleanup_failure', False):
            raise RoomSessionError('Native cleanup remains unconfirmed; it was not retried', outcome_unknown=True)
        # Completing an interrupted turn can automatically promote native queued
        # input. Remove that input first, under the SAME deadline as interruption,
        # completion observation and background-job verification.
        deadline = asyncio.get_running_loop().time() + self.settings.cleanup_timeout
        try:
            async with asyncio.timeout_at(deadline):
                await session.drain_queue()
                turn_id = session.active_turn_id
                if turn_id is not None:
                    await session.interrupt()
                    while True:
                        event = await session.next_event()
                        # No approval or guest output is forwarded during cleanup.
                        params = event.get('params', {})
                        if (event.get('method') == 'turn/started'
                                and params.get('turn', {}).get('id') != turn_id):
                            raise RoomSessionError('Unexpected native work started during cleanup')
                        if (event.get('method') == 'turn/completed'
                                and params.get('turn', {}).get('id') == turn_id):
                            break
                if session.active_turn_id is not None:
                    raise RoomSessionError('Native work remains active after interruption')
                generation = getattr(session, '_activity_generation', None)
                await session.assert_queue_empty()
                for job in await session.background_terminals():
                    result = await session.terminate_background_terminal(job.get('processId'))
                    if result.get('terminated') is not True:
                        raise RoomSessionError('Native background work did not stop')
                if await session.background_terminals():
                    raise RoomSessionError('Native background work remains')
                await session.assert_queue_empty()
                if (session.active_turn_id is not None
                        or getattr(session, '_activity_generation', None) != generation):
                    raise RoomSessionError('Native activity changed during cleanup verification')
        except BaseException as error:
            # A failed or cancelled cleanup must release the controller lock,
            # never silently reopen authority or retry the same uncertain work.
            self._cleanup_failure = True
            self._failed = True
            if hasattr(session, 'require_reset'):
                session.require_reset()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RoomSessionError('Native cleanup outcome is unknown; control remains blocked and nothing was retried',
                                   outcome_unknown=True) from None

    async def _cancel_cleanup(self, guest_id, generation):
        # Include same-lease history verification in the one cleanup budget.
        # Await directly: a second cancellation must close authority rather than
        # leave a shielded cleanup task running after the controller lock exits.
        try:
            async with asyncio.timeout(self.settings.cleanup_timeout):
                await self._drain_active()
                if self._clean_generation == generation and self._allowed(guest_id, generation):
                    ids = [turn.get('id') for turn in await self._session.list_turns()]
                    await self._session.confirm_clean(ids)
        except BaseException as error:
            self._cleanup_failure = True
            self._failed = True
            if self._session is not None and hasattr(self._session, 'require_reset'):
                self._session.require_reset()
            if isinstance(error, asyncio.CancelledError):
                raise
            raise RoomSessionError('Native cleanup outcome is unknown; control remains blocked and nothing was retried',
                                   outcome_unknown=True) from None

    async def _reset_native(self):
        if self.device_tools is not None:
            self.device_tools.revoke_all()
        async with asyncio.timeout(self.settings.cleanup_timeout):
            session = await self._connect()
            await self._drain_active()
            history = await session.list_turns()
            anchors = list(self.settings.anchor_turn_ids)
            ids = [turn.get('id') for turn in history]
            if ids[:len(anchors)] != anchors:
                raise RoomSessionError('The configured clean setup anchor is unavailable')
            if len(ids) > len(anchors):
                await session.revert(ids[len(anchors)], expected_retained_turn_ids=anchors)
            else:
                # Even an already-clean thread must pass the native pending-work gate.
                await session.confirm_clean(anchors)
            if [turn.get('id') for turn in await session.list_turns()] != anchors:
                raise RoomSessionError('Native conversation cleanup was not confirmed')
            self._first_guest_turn = None

    async def reset_context(self):
        controller = self._controller
        if controller:
            self.access_ended(controller)
        async with self._lock:
            try:
                await self._reset_native()
                self._failed = False
                return True
            except Exception:
                self._failed = True
                return False

    def _redact(self, text):
        for value in self.private_values:
            text = text.replace(value, '[private value]')
        return self.device_tools.redact(text) if self.device_tools is not None else text

    async def _answer_request(self, event, guest_id, generation, turn_id):
        session = self._session
        params = event.get('params', {})
        if params.get('threadId') != self.settings.thread_id or params.get('turnId') != turn_id:
            raise RoomSessionError('Native request did not match the active guest turn')
        if not self._allowed(guest_id, generation):
            raise RoomSessionError('Guest access ended before a native approval')
        method = event.get('method')
        # Jay explicitly grants every admitted QR guest broad computer control.
        # Grant a single native action, never a persisted permission/rule amendment.
        if method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            await session.answer(event['id'], {'decision': 'accept'})
            return
        if method == 'item/permissions/requestApproval':
            await session.answer(event['id'], {'permissions': params.get('permissions', {}), 'scope': 'turn'})
            return
        # Unknown dynamic tools/authentication forms need an integration, not a fabricated success.
        raise RoomSessionError('Native interaction requires an unsupported response')

    async def _native_turn(self, text, guest_id, generation):
        grant = None
        application_context = None
        if self.device_tools is not None:
            grant = await self.device_tools.prepare(guest_id, generation, self.leases.current(guest_id),
                                                     self.settings.thread_id)
            application_context = self.device_tools.context(grant)
        try:
            return await self._run_native_turn(text, guest_id, generation, grant=grant,
                                               application_context=application_context)
        finally:
            if self.device_tools is not None:
                self.device_tools.finish(grant)

    async def _run_native_turn(self, text, guest_id, generation, *, grant=None, application_context=None):
        session = self._session
        options = {'authorize': lambda: self._allowed(guest_id, generation)}
        if application_context is not None:
            options['application_context'] = application_context
        turn_id = await session.start_turn(text, **options)
        if grant is not None:
            self.device_tools.activate(grant, turn_id)
        self._first_guest_turn = self._first_guest_turn or turn_id
        self.log.append('cmd', 'A guest is speaking with Tenant.', guest_id=guest_id,
                        thread_id=self.settings.thread_id, turn_id=turn_id, generation=generation)
        final = []
        try:
            async with asyncio.timeout(self.settings.turn_timeout):
                while True:
                    if not self._allowed(guest_id, generation):
                        await self._drain_active()
                        return self._denied(guest_id)
                    try:
                        event = await asyncio.wait_for(session.next_event(), self.settings.poll_interval)
                    except TimeoutError:
                        continue
                    params = event.get('params', {})
                    if params.get('threadId') != self.settings.thread_id:
                        continue
                    event_turn = params.get('turnId') or params.get('turn', {}).get('id')
                    if event_turn != turn_id:
                        if 'id' in event:
                            raise RoomSessionError('A stale native approval arrived')
                        continue
                    if 'id' in event:
                        await self._answer_request(event, guest_id, generation, turn_id)
                    if event.get('method') == 'item/completed':
                        item = params.get('item', {})
                        if item.get('type') == 'agentMessage' and item.get('phase') != 'commentary' and isinstance(item.get('text'), str):
                            final.append(item['text'])
                    if event.get('method') == 'turn/completed':
                        if params['turn'].get('status') != 'completed':
                            raise RoomSessionError('Native turn was not completed', outcome_unknown=True)
                        if not self._allowed(guest_id, generation):
                            return self._denied(guest_id)
                        if not final:
                            return self.reply('Tenant finished without a text reply. The request was not repeated.')
                        self.log.append('ok', 'Tenant replied to the guest.', guest_id=guest_id,
                                        thread_id=self.settings.thread_id, turn_id=turn_id, generation=generation)
                        return ReplyFrames(CompletedReply(
                            guest_id, generation, self.settings.thread_id, turn_id,
                            self._redact(final[-1]), self.leases.current(guest_id)))
        except BaseException:
            # The outer controller keeps the lock through one bounded cleanup.
            # Starting another shielded drain here could orphan native work if
            # the browser disconnects while that cleanup is already running.
            raise

    async def turn(self, guest_id, text):
        lease = self.leases.current(guest_id)
        if lease is None:
            return self._denied(guest_id)
        if '*' not in lease.scopes and 'computer' not in lease.scopes:
            return self.reply('Your room access does not include computer control.')
        if not isinstance(text, str) or not text.strip() or len(text) > 8000:
            return self.reply('Please send a message of 1–8000 characters.')
        if self._failed:
            return self.reply('Tenant could not verify a clean conversation. Ask the host to check the connection; nothing was retried.')
        if text.strip().casefold() in ('leave', 'goodbye', 'done'):
            self.leases.revoke(guest_id)
            self.access_ended(guest_id)
            return self.reply('Your room access has ended. Already-started effects may remain.')
        self.leases.current(guest_id, activate=True)
        generation = self._admit(guest_id)
        async with self._lock:
            if self._failed:
                return self.reply('Tenant could not verify a clean conversation. Ask the host to check the connection; nothing was retried.')
            if not self._allowed(guest_id, generation):
                return self._denied(guest_id)
            try:
                await self._connect()
                if self._clean_generation != generation:
                    await self._reset_native()
                    if self._allowed(guest_id, generation):
                        self._clean_generation = generation
                if not self._allowed(guest_id, generation):
                    return self._denied(guest_id)
                return await self._native_turn(text, guest_id, generation)
            except asyncio.CancelledError:
                # A browser reconnect is not a new guest. Stop this turn without
                # resending it; retain the same valid lease and its transcript.
                try:
                    await self._cancel_cleanup(guest_id, generation)
                except Exception:
                    self._failed = True
                raise
            except Exception:
                self._failed = True
                try:
                    if self._session is not None:
                        await self._drain_active()
                except Exception:
                    pass
                self.log.append('err', 'Tenant could not confirm the conversation result. Nothing was retried.',
                                guest_id=guest_id, generation=generation)
                return self.reply('Tenant could not confirm the result. Already-started actions may have happened; nothing was retried.')

    async def close(self):
        controller = self._controller
        if controller:
            self.leases.revoke(controller)
            self.access_ended(controller)
        for task in tuple(self._cleanup_tasks):
            task.cancel()
        if self._cleanup_tasks:
            await asyncio.gather(*self._cleanup_tasks, return_exceptions=True)
        if self._session is not None:
            try:
                await self._drain_active()
            finally:
                try:
                    await self._session.close()
                finally:
                    if self.device_tools is not None:
                        await self.device_tools.close()
