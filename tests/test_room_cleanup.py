"""Failure-injection for native handoff cleanup; never calls a daemon or model."""
import asyncio
from contextlib import suppress
from dataclasses import replace
import unittest
from agent.room_session import RoomSession, RoomSessionError
from brain.core.room_conversation import ConversationAgent
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.state import Room
from test_room_conversation import NativeSession, settings_for, THREAD


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def make(self, timeout=.03):
        native = NativeSession()
        leases = Leases(Room('TEST', 'Test'))
        agent = ConversationAgent(leases, EventLog(), replace(settings_for(native), cleanup_timeout=timeout))
        agent._session = native
        self.addAsyncCleanup(self.close, agent)
        return agent, native

    async def close(self, agent):
        with suppress(RoomSessionError):
            await agent.close()

    async def test_delete_native_queue_before_interrupt_prevents_old_work_promotion(self):
        agent, native = self.make()
        native.active_turn_id = 'old-active'
        native.queue = [{'id': 'queued-old-guest'}]
        promoted = []
        original_interrupt = native.interrupt
        async def promote_on_completion():
            if native.queue:
                promoted.extend(native.queue)
            return await original_interrupt()
        native.interrupt = promote_on_completion
        await agent._drain_active()
        self.assertEqual(promoted, [])
        self.assertEqual([call[0] for call in native.calls[:2]], ['drain', 'interrupt'])
        self.assertIsNone(native.active_turn_id)
        self.assertEqual(native.queue, [])

    async def test_each_native_cleanup_wait_is_inside_the_same_deadline(self):
        for stage in ('drain_queue', 'interrupt', 'next_event', 'assert_queue_empty',
                      'background_terminals', 'terminate_background_terminal'):
            with self.subTest(stage=stage):
                agent, native = self.make(timeout=.02)
                if stage in ('interrupt', 'next_event'):
                    native.active_turn_id = 'old-active'
                if stage == 'next_event':
                    async def acknowledge_without_completion():
                        native.active_turn_id = None
                        return True
                    native.interrupt = acknowledge_without_completion
                if stage == 'terminate_background_terminal':
                    native.jobs = [{'processId': 'job1'}]
                async def never_returns(*_args, **_kwargs):
                    await asyncio.Event().wait()
                setattr(native, stage, never_returns)
                started = asyncio.get_running_loop().time()
                async with asyncio.timeout(.2):
                    with self.assertRaises(RoomSessionError) as caught:
                        await agent._drain_active()
                self.assertTrue(caught.exception.outcome_unknown)
                self.assertTrue(agent._failed)
                self.assertLess(asyncio.get_running_loop().time() - started, .15)
                # Repeated exception handlers cannot restart the same uncertain cleanup.
                with self.assertRaises(RoomSessionError):
                    await agent._drain_active()

    async def test_queue_and_interrupt_share_one_budget_instead_of_each_getting_a_fresh_timeout(self):
        agent, native = self.make(timeout=.03)
        native.active_turn_id = 'old-active'
        original_drain, original_interrupt = native.drain_queue, native.interrupt
        async def delayed_drain():
            await asyncio.sleep(.02)
            await original_drain()
        async def delayed_interrupt():
            await asyncio.sleep(.02)
            return await original_interrupt()
        native.drain_queue, native.interrupt = delayed_drain, delayed_interrupt
        with self.assertRaises(RoomSessionError) as caught:
            await agent._drain_active()
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertTrue(agent._failed)

    async def test_native_queue_reappearing_after_interrupt_does_not_open_authority(self):
        agent, native = self.make()
        native.active_turn_id = 'old-active'
        original = native.interrupt
        async def requeue_after_completion():
            result = await original()
            native.queue = [{'id': 'racing-old-work'}]
            return result
        native.interrupt = requeue_after_completion
        with self.assertRaises(RoomSessionError) as caught:
            await agent._drain_active()
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertTrue(agent._failed)
        self.assertEqual(native.counter, 0)

    async def test_new_activity_during_final_background_check_is_not_ignored(self):
        agent, native = self.make()
        native._activity_generation = 0
        calls = 0
        async def changed_after_verification():
            nonlocal calls
            calls += 1
            if calls == 2:
                native._activity_generation += 1
            return []
        native.background_terminals = changed_after_verification
        with self.assertRaises(RoomSessionError):
            await agent._drain_active()
        self.assertTrue(agent._failed)

    async def test_cancelled_turn_history_and_confirmation_cannot_hold_controller_lock(self):
        for stage in ('list_turns', 'confirm_clean'):
            with self.subTest(stage=stage):
                agent, native = self.make(timeout=.02)
                lease = agent.leases.create()
                native.auto_finish = False
                running = asyncio.create_task(agent.turn(lease.guest_id, 'request before disconnect'))
                await native.started.wait()
                entered = asyncio.Event()
                async def never_returns(*_args, **_kwargs):
                    entered.set()
                    await asyncio.Event().wait()
                setattr(native, stage, never_returns)
                started = asyncio.get_running_loop().time()
                running.cancel()
                async with asyncio.timeout(.2):
                    with self.assertRaises(asyncio.CancelledError):
                        await running
                self.assertTrue(entered.is_set())
                self.assertTrue(agent._failed)
                self.assertTrue(agent._cleanup_failure)
                self.assertFalse(agent._lock.locked())
                self.assertLess(asyncio.get_running_loop().time() - started, .15)
                previous_starts = native.counter
                other = agent.leases.create()
                reply = await agent.turn(other.guest_id, 'a new controller must not start')
                self.assertIn('nothing was retried', reply[-1]['text'])
                self.assertEqual(native.counter, previous_starts)

    async def test_cancellation_drain_and_history_check_share_one_cleanup_budget(self):
        agent, native = self.make(timeout=.03)
        lease = agent.leases.create()
        native.auto_finish = False
        running = asyncio.create_task(agent.turn(lease.guest_id, 'request before disconnect'))
        await native.started.wait()
        original_drain, original_list = native.drain_queue, native.list_turns
        async def slow_drain():
            await asyncio.sleep(.02)
            await original_drain()
        async def slow_list():
            await asyncio.sleep(.02)
            return await original_list()
        native.drain_queue, native.list_turns = slow_drain, slow_list
        running.cancel()
        async with asyncio.timeout(.2):
            with self.assertRaises(asyncio.CancelledError):
                await running
        self.assertTrue(agent._failed)
        self.assertTrue(agent._cleanup_failure)
        self.assertFalse(agent._lock.locked())

    async def test_cancel_during_error_cleanup_does_not_orphan_a_shielded_drain(self):
        agent, native = self.make(timeout=.1)
        lease = agent.leases.create()
        native.auto_finish = False
        running = asyncio.create_task(agent.turn(lease.guest_id, 'request before disconnect'))
        await native.started.wait()
        entered, finished = asyncio.Event(), asyncio.Event()
        drain_calls = 0
        async def stalled_drain():
            nonlocal drain_calls
            drain_calls += 1
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
        native.drain_queue = stalled_drain
        # A stale approval creates an error, so cancellation arrives while the
        # error handler owns cleanup rather than during ordinary event polling.
        await native.events.put({'id': 'stale-request', 'method': 'item/commandExecution/requestApproval',
                                 'params': {'threadId': THREAD, 'turnId': 'previous-guest'}})
        async with asyncio.timeout(.2):
            await entered.wait()
            running.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await running
        self.assertTrue(finished.is_set())
        self.assertEqual(drain_calls, 1)
        self.assertTrue(agent._failed)
        self.assertTrue(agent._cleanup_failure)
        self.assertFalse(agent._lock.locked())


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_multi_cursor_cycles_are_rejected_for_all_cleanup_lists(self):
        for method in ('thread/turns/list', 'thread/queue/list', 'thread/backgroundTerminals/list'):
            with self.subTest(method=method):
                session = RoomSession(THREAD)
                calls = []
                async def response(actual, params):
                    calls.append((actual, params))
                    return {'data': [], 'nextCursor': 'b' if params.get('cursor') == 'a' else 'a'}
                session._request = response
                operation = (session.list_turns if method == 'thread/turns/list'
                             else session.list_queue if method == 'thread/queue/list' else session.background_terminals)
                async with asyncio.timeout(.2):
                    with self.assertRaises(RoomSessionError):
                        await operation()
                self.assertEqual(len(calls), 3)
                self.assertTrue(session._reset_required)

    async def test_endlessly_new_empty_cursors_hit_a_page_limit(self):
        session = RoomSession(THREAD)
        calls = 0
        async def response(_method, _params):
            nonlocal calls
            calls += 1
            return {'data': [], 'nextCursor': 'page-' + str(calls)}
        session._request = response
        with self.assertRaises(RoomSessionError):
            await session.list_queue()
        self.assertEqual(calls, 16)
        self.assertTrue(session._reset_required)

    async def test_oversized_terminal_page_and_total_items_are_rejected(self):
        session = RoomSession(THREAD)
        async def oversized(_method, _params):
            return {'data': [{}] * 101, 'nextCursor': None}
        session._request = oversized
        with self.assertRaises(RoomSessionError): await session.list_turns()
        count = 0
        async def too_many(_method, _params):
            nonlocal count
            count += 1
            return {'data': [{}] * 100, 'nextCursor': None if count == 11 else str(count)}
        session._request = too_many
        with self.assertRaises(RoomSessionError): await session.list_turns()
        self.assertEqual(count, 11)

    async def test_all_valid_pages_are_retained_in_order(self):
        session = RoomSession(THREAD)
        requests = []
        async def pages(method, params):
            requests.append((method, params))
            if params.get('cursor') is None:
                return {'data': [{'id': 'setup'}], 'nextCursor': 'second'}
            return {'data': [{'id': 'guest'}], 'nextCursor': None}
        session._request = pages
        self.assertEqual(await session.list_turns(), [{'id': 'setup'}, {'id': 'guest'}])
        self.assertEqual(requests[1][1]['cursor'], 'second')
        self.assertEqual(requests[0][1]['sortDirection'], 'asc')


if __name__ == '__main__': unittest.main()
