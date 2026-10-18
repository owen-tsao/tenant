"""Offline protocol tests. No daemon, model, OS tools or real conversation calls."""
import asyncio
import json
import unittest
from agent.room_session import RoomSession, RoomSessionError


THREAD = 'configured-room'


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.hold_start = False
        self.start_sent = asyncio.Event()
        self.history = [{'id': 'setup'}]
        self.revert_error = False
        self.leak_history = False
        self.queue = []
        self.background = []
        self.emit_started = True
        self.background_checks = 0
        self.interleave_during_verification = False
    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        method = frame.get('method')
        if method == 'initialize':
            await self.emit({'id': frame['id'], 'result': {'userAgent': 'test'}})
        elif method == 'thread/resume':
            await self.emit({'id': frame['id'], 'result': {'thread': {'id': THREAD, 'status': {'type': 'idle'}}}})
        elif method == 'turn/start':
            self.start_sent.set()
            if self.emit_started:
                await self.emit({'method': 'turn/started', 'params': {'threadId': THREAD, 'turn': {'id': 'turn1'}}})
            if not self.hold_start:
                await self.emit({'id': frame['id'], 'result': {'turn': {'id': 'turn1', 'status': 'inProgress'}}})
        elif method == 'thread/queue/list':
            await self.emit({'id': frame['id'], 'result': {'data': list(self.queue), 'nextCursor': None}})
        elif method == 'thread/queue/delete':
            self.queue = [item for item in self.queue if item['id'] != frame['params']['queuedSubmissionId']]
            await self.emit({'id': frame['id'], 'result': {'deleted': True}})
        elif method == 'thread/backgroundTerminals/list':
            self.background_checks += 1
            if self.interleave_during_verification and self.background_checks == 2:
                self.history.append({'id': 'interleaved-native-guest'})
                await self.emit({'method': 'turn/started', 'params': {'threadId': THREAD, 'turn': {'id': 'interleaved-native-guest'}}})
                await self.emit({'method': 'turn/completed', 'params': {'threadId': THREAD, 'turn': {'id': 'interleaved-native-guest'}}})
            await self.emit({'id': frame['id'], 'result': {'data': list(self.background), 'nextCursor': None}})
        elif method == 'thread/backgroundTerminals/terminate':
            self.background = [item for item in self.background if item['processId'] != frame['params']['processId']]
            await self.emit({'id': frame['id'], 'result': {'terminated': True}})
        elif method == 'thread/read':
            await self.emit({'id': frame['id'], 'result': {'thread': {'id': THREAD, 'turns': []}}})
        elif method == 'thread/turns/list':
            await self.emit({'id': frame['id'], 'result': {'data': self.history, 'nextCursor': None}})
        elif method == 'thread/revert':
            if self.revert_error:
                await self.emit({'id': frame['id'], 'error': {'code': -32600, 'message': 'not allowed'}})
            else:
                if not self.leak_history: self.history = [{'id': 'setup'}]
                await self.emit({'id': frame['id'], 'result': {'thread': {'id': THREAD, 'turns': []}}})
        elif method == 'turn/interrupt':
            await self.emit({'id': frame['id'], 'result': {}})
    async def emit(self, frame): await self.incoming.put(json.dumps(frame))
    def __aiter__(self): return self
    async def __anext__(self):
        value = await self.incoming.get()
        if value is None: raise StopAsyncIteration
        return value
    async def close(self):
        self.closed = True
        await self.incoming.put(None)


class RoomSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = Socket()
        self.connect_args = None
        async def connector(path, **kwargs):
            self.connect_args = (path, kwargs)
            return self.socket
        self.client = RoomSession(THREAD, socket_path='/test/control.sock', connector=connector, request_timeout=.05)
        await self.client.connect()
        self.addAsyncCleanup(self.client.close)

    async def test_initialize_then_resume_fixed_thread_without_creating_or_permission_override(self):
        self.assertEqual([f['method'] for f in self.socket.sent], ['initialize', 'initialized', 'thread/resume'])
        self.assertEqual(self.socket.sent[-1]['params'], {'threadId': THREAD, 'excludeTurns': True})
        self.assertEqual(self.connect_args[0], '/test/control.sock')
        self.assertNotIn('sandbox', str(self.socket.sent))
        self.assertNotIn('approvalPolicy', str(self.socket.sent))

    async def test_start_text_and_interleaved_events_are_bound_to_room(self):
        self.assertEqual(await self.client.start_turn('Turn on the phone'), 'turn1')
        request = self.socket.sent[-1]
        self.assertEqual(request['params']['threadId'], THREAD)
        self.assertEqual(request['params']['input'], [{'type': 'text', 'text': 'Turn on the phone'}])
        self.assertEqual((await self.client.next_event())['method'], 'turn/started')
        await self.socket.emit({'method': 'item/agentMessage/delta', 'params': {'threadId': 'other-private-thread', 'delta': 'private'}})
        await self.socket.emit({'method': 'item/agentMessage/delta', 'params': {'threadId': THREAD, 'delta': 'Room response'}})
        self.assertEqual((await self.client.next_event())['params']['delta'], 'Room response')
        with self.assertRaises(RoomSessionError): await self.client.start_turn('second request')

    async def test_interrupt_ack_does_not_claim_completion_or_undo(self):
        await self.client.start_turn('Play music')
        self.assertTrue(await self.client.interrupt())
        self.assertEqual(self.client.active_turn_id, 'turn1')
        frame = self.socket.sent[-1]
        self.assertEqual(frame['params'], {'threadId': THREAD, 'turnId': 'turn1'})
        await self.socket.emit({'method': 'turn/completed', 'params': {'threadId': THREAD, 'turn': {'id': 'turn1', 'status': 'interrupted'}}})
        await self.client.next_event()
        await self.client.next_event()
        self.assertIsNone(self.client.active_turn_id)

    async def test_approval_surfaces_without_automatic_acceptance(self):
        await self.client.start_turn('Use a computer tool')
        await self.client.next_event()
        before = len(self.socket.sent)
        await self.socket.emit({'id': 'approval1', 'method': 'item/commandExecution/requestApproval',
                                'params': {'threadId': THREAD, 'turnId': 'turn1', 'itemId': 'item1'}})
        event = await self.client.next_event()
        self.assertEqual(event['id'], 'approval1')
        self.assertEqual(len(self.socket.sent), before)
        await self.client.answer('approval1', {'decision': 'decline'})
        self.assertEqual(self.socket.sent[-1], {'id': 'approval1', 'result': {'decision': 'decline'}})
        with self.assertRaises(RoomSessionError): await self.client.answer('approval1', {'decision': 'accept'})

    async def test_stale_approval_cannot_be_granted_after_turn_completed(self):
        await self.client.start_turn('Use a tool')
        await self.client.next_event()
        await self.socket.emit({'id': 'approval1', 'method': 'item/tool/call',
                                'params': {'threadId': THREAD, 'turnId': 'turn1', 'callId': 'c', 'tool': 'room'}})
        await self.client.next_event()
        await self.socket.emit({'method': 'turn/completed', 'params': {'threadId': THREAD, 'turn': {'id': 'turn1'}}})
        await self.client.next_event()
        with self.assertRaises(RoomSessionError): await self.client.answer('approval1', {'success': True, 'contentItems': []})

    async def test_start_timeout_does_not_retry_and_retains_interruptable_turn(self):
        self.socket.hold_start = True
        with self.assertRaises(RoomSessionError) as caught:
            await self.client.start_turn('Do one thing')
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.socket.sent), 1)
        self.assertEqual(self.client.active_turn_id, 'turn1')
        self.assertTrue(await self.client.interrupt())

    async def test_cancel_during_start_requests_best_effort_interrupt_without_replay(self):
        self.socket.hold_start = True
        task = asyncio.create_task(self.client.start_turn('Do one thing'))
        await self.socket.start_sent.wait()
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.socket.sent), 1)
        self.assertEqual(sum(f.get('method') == 'turn/interrupt' for f in self.socket.sent), 1)

    async def test_disconnection_reports_unknown_and_never_reconnects(self):
        await self.client.start_turn('Do one thing')
        await self.client.next_event()
        await self.socket.close()
        with self.assertRaises(RoomSessionError) as caught: await self.client.next_event()
        self.assertTrue(caught.exception.outcome_unknown)
        self.assertEqual(sum(f.get('method') == 'thread/resume' for f in self.socket.sent), 1)

    async def test_revert_uses_first_guest_turn_and_verifies_paginated_setup(self):
        self.socket.history = [{'id': 'setup'}, {'id': 'guestA'}]
        result = await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
        self.assertEqual(result['thread']['turns'], [])
        request = next(f for f in self.socket.sent if f.get('method') == 'thread/revert')
        self.assertEqual(request['params'], {'threadId': THREAD, 'beforeTurnId': 'guestA'})
        self.assertTrue(any(f.get('method') == 'thread/turns/list' for f in self.socket.sent))
        self.assertFalse(any(f.get('method') == 'thread/rollback' for f in self.socket.sent))
        self.assertEqual(await self.client.start_turn('Guest B'), 'turn1')

    async def test_failed_or_unverified_reset_blocks_new_guest(self):
        for failure in ('rpc', 'old_history'):
            self.socket.revert_error = failure == 'rpc'
            self.socket.leak_history = failure == 'old_history'
            self.socket.history = [{'id': 'setup'}, {'id': 'guestA'}]
            with self.assertRaises(RoomSessionError):
                await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
            with self.assertRaises(RoomSessionError): await self.client.start_turn('Guest B')
        self.assertFalse(any(f.get('method') == 'turn/start' for f in self.socket.sent))

    async def test_active_turn_prevents_context_revert_until_completion(self):
        await self.client.start_turn('Guest A')
        self.assertTrue(await self.client.interrupt())
        with self.assertRaises(RoomSessionError):
            await self.client.revert('turn1', expected_retained_turn_ids=['setup'])
        self.assertFalse(any(f.get('method') == 'thread/revert' for f in self.socket.sent))
        await self.socket.emit({'method': 'turn/completed', 'params': {'threadId': THREAD, 'turn': {'id': 'turn1'}}})
        await self.client.next_event()
        await self.client.next_event()
        await self.client.revert('turn1', expected_retained_turn_ids=['setup'])

    async def test_native_queued_prompt_blocks_new_turn_without_replay(self):
        self.socket.queue = [{'id': 'old-queued-message'}]
        with self.assertRaises(RoomSessionError): await self.client.start_turn('Guest B')
        self.assertFalse(any(f.get('method') == 'turn/start' for f in self.socket.sent))
        await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
        self.assertEqual(self.socket.queue, [])
        self.assertTrue(any(f.get('method') == 'thread/queue/delete' for f in self.socket.sent))
        self.assertEqual(await self.client.start_turn('Guest B'), 'turn1')

    async def test_background_job_blocks_reset_until_explicitly_terminated(self):
        self.socket.background = [{'processId': 'owned-process'}]
        with self.assertRaises(RoomSessionError):
            await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
        self.assertFalse(any(f.get('method') == 'thread/revert' for f in self.socket.sent))
        self.assertTrue((await self.client.terminate_background_terminal('owned-process'))['terminated'])
        await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
        self.assertEqual(self.socket.background, [])

    async def test_cancel_before_started_event_keeps_handoff_gate_closed(self):
        self.socket.emit_started = False
        self.socket.hold_start = True
        task = asyncio.create_task(self.client.start_turn('Guest A'))
        await self.socket.start_sent.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        with self.assertRaises(RoomSessionError): await self.client.start_turn('Guest B')
        self.assertEqual(sum(f.get('method') == 'turn/start' for f in self.socket.sent), 1)

    async def test_native_activity_during_final_reset_verification_keeps_gate_closed(self):
        self.socket.interleave_during_verification = True
        with self.assertRaises(RoomSessionError):
            await self.client.revert('guestA', expected_retained_turn_ids=['setup'])
        with self.assertRaises(RoomSessionError): await self.client.start_turn('Guest B')
        self.assertEqual(self.socket.history[-1]['id'], 'interleaved-native-guest')

    async def test_approval_without_exact_active_turn_cannot_be_granted(self):
        await self.client.start_turn('Guest A')
        await self.client.next_event()
        await self.socket.emit({'id': 'missing-turn', 'method': 'item/tool/call', 'params': {'threadId': THREAD}})
        await self.client.next_event()
        with self.assertRaises(RoomSessionError):
            await self.client.answer('missing-turn', {'success': True, 'contentItems': []})
        self.assertFalse(any(f.get('id') == 'missing-turn' and 'result' in f for f in self.socket.sent))

    async def test_authority_checked_after_native_queue_wait_before_model_submission(self):
        allowed = True
        original_send = self.socket.send
        async def changed_during_queue(raw):
            nonlocal allowed
            if json.loads(raw).get('method') == 'thread/queue/list':
                allowed = False
            await original_send(raw)
        self.socket.send = changed_during_queue
        with self.assertRaises(RoomSessionError):
            await self.client.start_turn('Guest request', authorize=lambda: allowed)
        self.assertFalse(any(f.get('method') == 'turn/start' for f in self.socket.sent))

    async def test_bounded_event_overflow_fails_instead_of_dropping_approval(self):
        self.client._events = asyncio.Queue(maxsize=1)
        await self.socket.emit({'method': 'item/agentMessage/delta', 'params': {'threadId': THREAD, 'delta': 'first'}})
        await self.socket.emit({'id': 'approval', 'method': 'item/tool/call', 'params': {'threadId': THREAD, 'turnId': 't'}})
        await asyncio.sleep(0)
        with self.assertRaises(RoomSessionError): await self.client.next_event()


if __name__ == '__main__': unittest.main()
