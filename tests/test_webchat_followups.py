"""Concurrent guest receive/cleanup with a real agent and an offline native session."""
import asyncio
import unittest
from collections import Counter
from unittest.mock import patch

from starlette.websockets import WebSocketDisconnect

from brain.channels.webchat import guest_socket
from brain.config import Config
from brain.core.conversation_speech import ReplyFrames
from brain.main import create_app
from tests.test_access_core import Clock
from tests.test_guest_view import ChannelSocket
from tests.test_room_conversation import NativeSession, settings_for


class SteerSession(NativeSession):
    def __init__(self):
        super().__init__()
        self.auto_finish = False
        self.steers = []
        self.block_steers = False
        self.release_steers = asyncio.Event()

    async def steer_turn(self, text, *, expected_turn_id, authorize):
        if not authorize() or self.active_turn_id != expected_turn_id:
            raise AssertionError('Stale steering authority')
        self.steers.append((text, expected_turn_id))
        if self.block_steers:
            await self.release_steers.wait()
        if not authorize() or self.active_turn_id != expected_turn_id:
            raise AssertionError('Steering authority changed')
        return expected_turn_id


class WebchatFollowupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.native = SteerSession()
        self.app = create_app(Config('offline-device', 'offline-host', 'TEST', 'https://testserver'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.clock = Clock()
        self.core.leases.clock = self.clock
        self.lease = self.core.leases.create()
        self.tasks = []
        self.entered = []
        self.running = set()
        self.cancelled = Counter()
        self.errors = {}
        self.receipts = []
        original = self.core.agent.turn

        async def tracked(guest_id, text):
            key = (guest_id, text)
            self.entered.append(key)
            self.running.add(asyncio.current_task())
            try:
                if text in self.errors:
                    raise self.errors[text]
                return await original(guest_id, text)
            except asyncio.CancelledError:
                self.cancelled[key] += 1
                raise
            finally:
                self.running.remove(asyncio.current_task())

        self.core.agent.turn = tracked
        schedule = self.core.speech.schedule_reply

        def tracked_schedule(frames):
            self.receipts.append(isinstance(frames, ReplyFrames))
            return schedule(frames)

        self.core.speech.schedule_reply = tracked_schedule
        self.interval = patch('brain.channels.webchat.PUBLISH_INTERVAL', .005)
        self.interval.start()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.core.agent.close()
        self.interval.stop()
        self.assertFalse(self.running)

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def open(self, lease=None):
        lease = lease or self.lease
        token = self.core.issue_credential(lease.guest_id)
        socket = ChannelSocket(self.app, lease.guest_id, token)
        task = asyncio.create_task(guest_socket(socket))
        self.tasks.append(task)
        initial = await asyncio.wait_for(socket.outgoing.get(), 1)
        self.assertEqual(initial['type'], 'lease')
        return socket, task

    async def receive(self, socket, kind):
        async with asyncio.timeout(1):
            while True:
                frame = await socket.outgoing.get()
                if frame.get('type') == kind:
                    return frame

    async def start(self, socket, text='first request'):
        socket.incoming.put_nowait({'type': 'user', 'text': text})
        await self.until(lambda: self.native.active_turn_id is not None)

    async def test_followup_is_accepted_before_original_final_and_only_original_has_receipt(self):
        socket, _ = await self.open()
        self.assertEqual(self.lease.state, 'joining')
        await self.start(socket)
        turn_id = self.native.active_turn_id
        socket.incoming.put_nowait({'type': 'user', 'text': 'make it blue'})
        action = await self.receive(socket, 'action')
        self.assertEqual(action['text'], 'Added to current request')
        self.assertEqual(self.native.steers, [('make it blue', turn_id)])
        self.assertEqual(self.native.counter, 1)
        self.assertFalse(any(frame['type'] == 'assistant' for frame in socket.frames))
        await self.until(lambda: len(self.receipts) == 1)
        self.assertEqual(self.receipts, [False])
        await self.native.finish(turn_id, 'Finished the combined request.')
        final = await self.receive(socket, 'assistant')
        self.assertEqual(final['text'], 'Finished the combined request.')
        await self.until(lambda: len(self.receipts) == 2)
        self.assertEqual(self.receipts, [False, True])
        self.assertEqual(len([f for f in socket.frames if f['type'] == 'assistant']), 1)
        await self.until(lambda: not self.core.speech._tasks)  # No opted-in speaker to dispatch to.

    async def test_overload_is_bounded_rejected_text_is_not_replayed_and_slots_recover(self):
        self.native.block_steers = True
        with patch('brain.channels.webchat.MAX_TURN_WORKERS', 2):
            socket, _ = await self.open()
            await self.start(socket)
            socket.incoming.put_nowait({'type': 'user', 'text': 'held followup'})
            await self.until(lambda: len(self.entered) == 2)
            socket.incoming.put_nowait({'type': 'user', 'text': 'overflow text'})
            self.assertIn('Too many', (await self.receive(socket, 'action'))['text'])
            self.assertEqual(len(self.running), 2)
            self.assertNotIn((self.lease.guest_id, 'overflow text'), self.entered)
            self.native.release_steers.set()
            self.assertEqual((await self.receive(socket, 'action'))['text'], 'Added to current request')
            await self.until(lambda: len(self.receipts) == 1)
            socket.incoming.put_nowait({'type': 'user', 'text': 'new followup'})
            self.assertEqual((await self.receive(socket, 'action'))['text'], 'Added to current request')
            self.assertEqual([text for text, _ in self.native.steers], ['held followup', 'new followup'])
            self.assertNotIn((self.lease.guest_id, 'overflow text'), self.entered)

    async def test_leave_has_reserved_capacity_cancels_pending_workers_and_settles_once(self):
        self.native.block_steers = True
        with patch('brain.channels.webchat.MAX_TURN_WORKERS', 2):
            socket, _ = await self.open()
            await self.start(socket)
            socket.incoming.put_nowait({'type': 'user', 'text': 'held followup'})
            await self.until(lambda: len(self.entered) == 2)
            socket.incoming.put_nowait({'type': 'user', 'text': 'Leave'})
            final = await self.receive(socket, 'assistant')
            self.assertIn('access has ended', final['text'])
            await self.until(lambda: not self.running)
            self.assertEqual(self.lease.state, 'released')
            self.assertEqual(self.cancelled[(self.lease.guest_id, 'first request')], 1)
            self.assertEqual(self.cancelled[(self.lease.guest_id, 'held followup')], 1)
            self.assertEqual(len([f for f in socket.frames if f['type'] == 'assistant']), 1)
            self.assertFalse(any(self.receipts))
            socket.incoming.put_nowait({'type': 'user', 'text': 'after leave'})
            self.assertIn('no longer', (await self.receive(socket, 'assistant'))['text'])
            self.assertNotIn((self.lease.guest_id, 'after leave'), self.entered)

    async def test_revoke_cancels_followups_and_new_guest_never_receives_or_replays_old_text(self):
        self.native.block_steers = True
        old, _ = await self.open()
        await self.start(old)
        for text in ('held followup', 'waiting followup'):
            old.incoming.put_nowait({'type': 'user', 'text': text})
        await self.until(lambda: len(self.entered) == 3)
        self.core.revoke(self.lease.guest_id)
        await self.until(lambda: not self.running)
        self.assertEqual(self.native.active_turn_id, None)
        self.assertEqual(self.cancelled[(self.lease.guest_id, 'held followup')], 1)
        self.assertEqual(self.cancelled[(self.lease.guest_id, 'waiting followup')], 1)
        new_lease = self.core.leases.create()
        new, _ = await self.open(new_lease)
        self.native.auto_finish = True
        new.incoming.put_nowait({'type': 'user', 'text': 'new guest request'})
        self.assertEqual((await self.receive(new, 'assistant'))['text'], 'Native reply: new guest request')
        self.assertEqual([call[1] for call in self.native.calls if call[0] == 'start'],
                         ['first request', 'new guest request'])
        self.assertFalse(any('followup' in str(frame) or 'first request' in str(frame) for frame in new.frames))
        old.incoming.put_nowait({'type': 'user', 'text': 'stale socket request'})
        self.assertIn('no longer', (await self.receive(old, 'assistant'))['text'])
        self.assertNotIn((self.lease.guest_id, 'stale socket request'), self.entered)

    async def test_expiry_stops_native_worker_without_waiting_for_model(self):
        socket, _ = await self.open()
        await self.start(socket)
        self.clock.now = self.lease.expires_at
        await self.until(lambda: not self.running)
        self.assertEqual(self.lease.state, 'expired')
        self.assertEqual(self.native.active_turn_id, None)
        self.assertFalse(any(self.receipts))

    async def test_disconnect_and_handler_cancellation_join_all_response_workers(self):
        for cancel_handler in (False, True):
            with self.subTest(cancel_handler=cancel_handler):
                self.native.started.clear()
                self.native.block_steers = True
                socket, task = await self.open()
                await self.start(socket, 'disconnect request')
                socket.incoming.put_nowait({'type': 'user', 'text': 'disconnect followup'})
                await self.until(lambda: len(self.running) == 2)
                if cancel_handler:
                    task.cancel()
                else:
                    socket.incoming.put_nowait(WebSocketDisconnect(1000))
                await asyncio.wait_for(task, 1)
                self.assertFalse(self.running)
                self.assertIsNone(self.native.active_turn_id)
                self.assertEqual(socket.closed, 1001)
                self.assertEqual(self.cancelled[(self.lease.guest_id, 'disconnect request')],
                                 1 + int(cancel_handler))

    async def test_worker_application_error_propagates_and_cancels_sibling(self):
        for error in (RuntimeError('model failed'), ValueError('model failed')):
            with self.subTest(error=type(error).__name__):
                socket, task = await self.open()
                await self.start(socket, 'held request')
                self.errors['fail request'] = error
                socket.incoming.put_nowait({'type': 'user', 'text': 'fail request'})
                with self.assertRaises(type(error)) as raised:
                    await asyncio.wait_for(task, 1)
                self.assertIs(raised.exception, error)
                self.assertFalse(self.running)
                self.assertEqual(socket.closed, 1001)

    async def test_worker_send_failure_closes_socket_and_cancels_original_turn(self):
        socket, task = await self.open()
        await self.start(socket)
        socket.fail_send = OSError('synthetic transport close')
        socket.incoming.put_nowait({'type': 'user', 'text': 'followup'})
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.running)
        self.assertIsNone(self.native.active_turn_id)
        self.assertEqual(socket.closed, 1001)

    async def test_malformed_json_closes_socket_and_cancels_original_turn(self):
        socket, task = await self.open()
        await self.start(socket)
        socket.incoming.put_nowait(ValueError('malformed JSON'))
        await asyncio.wait_for(task, 1)
        self.assertFalse(self.running)
        self.assertEqual(socket.closed, 1001)


if __name__ == '__main__':
    unittest.main()
