"""Guest metadata and socket ordering; no provider calls or physical effects."""
import asyncio
import copy
import json
import unittest
from unittest.mock import patch

from fastapi import WebSocketDisconnect
from brain.channels.webchat import guest_socket
from brain.core.guest_view import GuestPublisher, lease_frame
from brain.state import CapSpec
from test_access_core import Clock, HEADERS, Planner, make_app, register


class GuestViewTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.planner = Planner()
        self.app, self.core = make_app(clock=self.clock, planner=self.planner)
        self.phone = register(self.core, 'private-phone', label='Jay phone')
        self.lease = self.core.leases.create()

    def test_initial_view_has_two_deadlines_and_does_not_activate_or_renew(self):
        issued = self.lease.expires_at
        self.clock.now += 15
        first = lease_frame(self.core, self.lease.guest_id)
        self.assertEqual(first, {'type': 'lease', 'state': 'joining', 'expires_in': 105,
                                 'access_expires_in': 585,
                                 'controls': [{'label': 'Jay phone', 'caps': ['light']}]})
        self.clock.now += 10
        second = lease_frame(self.core, self.lease.guest_id)
        self.assertEqual(second['expires_in'], 95)
        self.assertEqual(self.lease.state, 'joining')
        self.assertEqual(self.lease.expires_at, issued)
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    def test_activation_uses_original_expiry_not_another_600_seconds(self):
        issued = self.lease.expires_at
        self.clock.now += 100
        self.core.leases.current(self.lease.guest_id, activate=True)
        view = lease_frame(self.core, self.lease.guest_id)
        self.assertEqual((view['state'], view['expires_in'], view['access_expires_in']), ('active', 500, 500))
        self.assertEqual(self.lease.expires_at, issued)

    def test_joining_and_active_exact_expiry_are_authoritative(self):
        self.clock.now = self.lease.joining_until - .1
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['expires_in'], 1)
        self.clock.now = self.lease.joining_until
        self.assert_terminal(lease_frame(self.core, self.lease.guest_id), 'expired')
        second = self.core.leases.create()
        self.core.leases.current(second.guest_id, activate=True)
        self.clock.now = second.expires_at
        self.assert_terminal(lease_frame(self.core, second.guest_id), 'expired')

    def assert_terminal(self, frame, reason):
        self.assertEqual(frame, {'type': 'lease', 'state': 'released', 'reason': reason,
                                 'expires_in': 0, 'access_expires_in': 0, 'controls': []})

    def test_released_missing_and_unhealthy_leases_fail_closed(self):
        self.core.registry.persistence_healthy = False
        self.assert_terminal(lease_frame(self.core, self.lease.guest_id), 'unavailable')
        self.assertEqual(self.lease.state, 'joining')
        self.core.registry.persistence_healthy = True
        self.core.revoke(self.lease.guest_id)
        self.assert_terminal(lease_frame(self.core, self.lease.guest_id), 'ended')
        self.assert_terminal(lease_frame(self.core, 'unknown'), 'ended')

    def test_inspection_failure_yields_no_controls_or_error_text(self):
        with patch.object(self.core.leases, 'current', side_effect=RuntimeError('private error details')):
            frame = lease_frame(self.core, self.lease.guest_id)
        self.assert_terminal(frame, 'unavailable')
        self.assertNotIn('private', json.dumps(frame))

    def test_controls_filter_room_online_scope_and_shipped_capabilities(self):
        self.phone.dev.caps['say'] = CapSpec('say', {'text': {'type': 'string'}}, 'Do not forward this description')
        self.phone.dev.caps['camera.capture'] = CapSpec('camera.capture', {}, 'Gated')
        self.lease.scopes = {'say', 'camera.capture'}
        offline = register(self.core, 'offline', label='Offline phone')
        self.core.bus.disconnect(offline.dev)
        foreign = register(self.core, 'foreign', label='Foreign phone')
        foreign.dev.room_id = 'another-room'
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'],
                         [{'label': 'Jay phone', 'caps': ['say']}])
        self.lease.scopes.clear()
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'], [])

    def test_duplicate_normalized_labels_are_not_offered_as_distinct_controls(self):
        self.phone.dev.label = 'Owen phone'
        other = register(self.core, 'private-other', label='OWEN  phone')
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'], [])
        # Match the Agent's conservative rule even if the duplicate goes offline.
        self.core.bus.disconnect(other.dev)
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'], [])
        other.dev.label = 'Backup phone'
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['controls'],
                         [{'label': 'Owen phone', 'caps': ['light']}])

    def test_view_contains_no_identity_credentials_chat_schemas_or_other_guests(self):
        secret = self.core.issue_credential(self.lease.guest_id)
        other = self.core.leases.create()
        self.core.leases.sessions[self.lease.guest_id].messages.append({'role': 'user', 'content': 'private transcript'})
        self.core.log.append('err', 'private audit row')
        frame = lease_frame(self.core, self.lease.guest_id)
        self.assertEqual(set(frame), {'type', 'state', 'expires_in', 'access_expires_in', 'controls'})
        self.assertEqual(set(frame['controls'][0]), {'label', 'caps'})
        encoded = json.dumps(frame)
        for value in (self.lease.guest_id, other.guest_id, other.display_name, secret,
                      'private-phone', 'private transcript', 'private audit row', 'args', 'description'):
            self.assertNotIn(value, encoded)


class ChannelSocket:
    def __init__(self, app, guest_id, token, *, origin='https://testserver'):
        self.app = app
        self.query_params = {'guest_id': guest_id, 'token': token}
        self.headers = {'origin': origin}
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.frames = []
        self.accepted = False
        self.closed = None
        self.fail_send = False

    async def accept(self):
        self.accepted = True

    async def close(self, code):
        self.closed = code

    async def receive_json(self):
        frame = await self.incoming.get()
        if isinstance(frame, BaseException):
            raise frame
        return frame

    async def send_json(self, frame):
        if self.fail_send:
            if isinstance(self.fail_send, BaseException):
                raise self.fail_send
            raise WebSocketDisconnect(1006)
        frame = copy.deepcopy(frame)
        self.frames.append(frame)
        self.outgoing.put_nowait(frame)
        await asyncio.sleep(0)  # Exercise possible interleaving of socket sends.


class SlowPlanner:
    def __init__(self):
        self.called = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.calls = 0

    async def plan(self, text, inventory, history):
        self.calls += 1
        self.called.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return {'kind': 'action', 'device_id': 'phone', 'cap': 'light', 'args': {'on': True}}


class GuestChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.planner = Planner()
        self.app, self.core = make_app(clock=self.clock, planner=self.planner)
        self.phone = register(self.core, label='Jay phone')
        self.lease = self.core.leases.create()
        self.token = self.core.issue_credential(self.lease.guest_id)
        self.tasks = []
        self.interval_patch = patch('brain.channels.webchat.PUBLISH_INTERVAL', .005)
        self.interval_patch.start()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.interval_patch.stop()

    async def open(self):
        socket = ChannelSocket(self.app, self.lease.guest_id, self.token)
        task = asyncio.create_task(guest_socket(socket))
        self.tasks.append(task)
        frame = await asyncio.wait_for(socket.outgoing.get(), 1)
        self.assertEqual(frame['type'], 'lease')
        return socket, task, frame

    async def receive(self, socket, predicate):
        async with asyncio.timeout(1):
            while True:
                frame = await socket.outgoing.get()
                if predicate(frame):
                    return frame

    async def test_authenticated_initial_state_and_reconnect_do_not_activate(self):
        for _ in range(2):
            socket, task, initial = await self.open()
            self.assertTrue(socket.accepted)
            self.assertEqual(initial['state'], 'joining')
            self.assertEqual((initial['expires_in'], initial['access_expires_in']), (120, 600))
            socket.incoming.put_nowait(WebSocketDisconnect(1000))
            await asyncio.wait_for(task, 1)
        self.assertEqual(self.lease.state, 'joining')
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_bad_token_or_origin_gets_no_initial_metadata(self):
        for token, origin, expected in [('wrong', 'https://testserver', 4401),
                                        (self.token, 'https://evil.invalid', 1008)]:
            socket = ChannelSocket(self.app, self.lease.guest_id, token, origin=origin)
            await guest_socket(socket)
            self.assertFalse(socket.accepted)
            self.assertEqual(socket.frames, [])
            self.assertEqual(socket.closed, expected)

    async def test_idle_joining_expiry_notifies_without_a_message(self):
        socket, _, _ = await self.open()
        self.clock.now = self.lease.joining_until
        terminal = await self.receive(socket, lambda f: f.get('state') == 'released')
        self.assertEqual(terminal['reason'], 'expired')
        self.assertEqual(terminal['controls'], [])
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_first_message_activates_without_renewal_then_idle_active_expiry_notifies(self):
        self.planner.output = {'kind': 'message', 'text': 'Room help'}
        socket, _, _ = await self.open()
        issued = self.lease.expires_at
        self.clock.now += 30
        socket.incoming.put_nowait({'type': 'user', 'text': 'what can I do'})
        active, answered = None, False
        async with asyncio.timeout(1):
            while active is None or not answered:
                frame = await socket.outgoing.get()
                if frame.get('state') == 'active':
                    active = frame
                elif frame['type'] == 'assistant':
                    answered = True
                else:
                    self.fail('Unexpected conversation frame during activation')
        self.assertEqual((active['expires_in'], active['access_expires_in']), (570, 570))
        self.assertEqual(self.lease.expires_at, issued)
        self.clock.now = issued
        expired = await self.receive(socket, lambda f: f.get('state') == 'released')
        self.assertEqual(expired['reason'], 'expired')
        self.assertEqual(len(self.planner.calls), 1)
        self.assertEqual(self.phone.frames, [])

    async def test_host_revoke_and_reset_notify_idle_socket_without_planning(self):
        socket, _, _ = await self.open()
        self.core.revoke(self.lease.guest_id)
        ended = await self.receive(socket, lambda f: f.get('state') == 'released')
        self.assertEqual(ended['reason'], 'ended')
        self.lease = self.core.leases.create()
        self.token = self.core.issue_credential(self.lease.guest_id)
        socket, _, _ = await self.open()
        await self.core.reset()
        ended = await self.receive(socket, lambda f: f.get('state') == 'released')
        self.assertEqual(ended['reason'], 'ended')
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_online_scope_and_health_changes_publish_controls_without_action(self):
        socket, _, initial = await self.open()
        self.assertTrue(initial['controls'])
        self.lease.scopes.clear()
        empty = await self.receive(socket, lambda f: f['type'] == 'lease' and not f['controls'])
        self.assertEqual(empty['state'], 'joining')
        self.lease.scopes.add('light')
        await self.receive(socket, lambda f: f['type'] == 'lease' and bool(f['controls']))
        self.core.bus.disconnect(self.phone.dev)
        await self.receive(socket, lambda f: f['type'] == 'lease' and not f['controls'])
        self.core.registry.persistence_healthy = False
        blocked = await self.receive(socket, lambda f: f.get('reason') == 'unavailable')
        self.assertEqual(blocked['expires_in'], 0)
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_health_recovery_restores_only_a_still_valid_lease_without_renewal(self):
        socket, _, _ = await self.open()
        issued = self.lease.expires_at
        self.core.registry.persistence_healthy = False
        await self.receive(socket, lambda f: f.get('reason') == 'unavailable')
        self.clock.now += 20
        self.core.registry.persistence_healthy = True
        recovered = await self.receive(socket, lambda f: f.get('state') == 'joining')
        self.assertEqual((recovered['expires_in'], recovered['access_expires_in']), (100, 580))
        self.assertTrue(recovered['controls'])
        self.assertEqual(self.lease.expires_at, issued)
        self.assertEqual(self.lease.state, 'joining')
        self.core.revoke(self.lease.guest_id)
        await self.receive(socket, lambda f: f.get('reason') == 'ended')
        self.core.registry.persistence_healthy = False
        self.core.registry.persistence_healthy = True
        self.assertEqual(lease_frame(self.core, self.lease.guest_id)['state'], 'released')
        self.assertEqual(self.planner.calls, [])
        self.assertEqual(self.phone.frames, [])

    async def test_slow_planning_does_not_delay_revocation_notice_or_dispatch(self):
        slow = SlowPlanner()
        self.core.agent.planner = slow
        socket, _, _ = await self.open()
        socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
        await asyncio.wait_for(slow.called.wait(), 1)
        self.core.revoke(self.lease.guest_id)
        await self.receive(socket, lambda f: f.get('state') == 'released')
        self.assertFalse(slow.release.is_set())
        self.assertEqual(self.phone.frames, [])
        slow.release.set()
        denied = await self.receive(socket, lambda f: f['type'] == 'assistant')
        self.assertIn('no longer', denied['text'])
        socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
        await self.receive(socket, lambda f: f['type'] == 'assistant')
        self.assertEqual(slow.calls, 1)
        self.assertEqual(self.phone.frames, [])

    async def test_inflight_completion_is_truthful_and_action_assistant_batch_stays_adjacent(self):
        self.phone.auto = False
        socket, _, _ = await self.open()
        socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
        await asyncio.wait_for(self.phone.sent.wait(), 1)
        self.core.revoke(self.lease.guest_id)
        await self.receive(socket, lambda f: f.get('state') == 'released')
        self.core.bus.receive(self.phone.dev, {'type': 'ok', 'req': self.phone.frames[0]['req'], 'result': {'on': True}})
        action = await self.receive(socket, lambda f: f['type'] == 'action')
        assistant = await asyncio.wait_for(socket.outgoing.get(), 1)
        self.assertEqual(assistant['type'], 'assistant')
        self.assertEqual(action['text'], 'Jay phone turned its flashlight on.')
        self.assertEqual(assistant['text'], action['text'])
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(len(self.planner.calls), 1)

    async def test_send_failure_cancels_blocked_receiver_and_planner(self):
        for error in (WebSocketDisconnect(1006), OSError('closed transport'), RuntimeError('closed ASGI socket')):
            with self.subTest(error=type(error).__name__):
                self.lease = self.core.leases.create()
                self.token = self.core.issue_credential(self.lease.guest_id)
                slow = SlowPlanner()
                self.core.agent.planner = slow
                socket, task, _ = await self.open()
                socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
                await asyncio.wait_for(slow.called.wait(), 1)
                socket.fail_send = error
                self.core.revoke(self.lease.guest_id)
                await asyncio.wait_for(task, 1)
                self.assertTrue(slow.cancelled.is_set())
                self.assertEqual(socket.closed, 1001)
                self.assertEqual(self.phone.frames, [])

    async def test_lost_action_reply_does_not_hide_audit_or_repeat_confirmed_action(self):
        socket, task, _ = await self.open()
        original = socket.send_json
        async def lose_action(frame):
            if frame['type'] == 'action':
                raise OSError('connection closed after effect')
            await original(frame)
        socket.send_json = lose_action
        socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
        await asyncio.wait_for(task, 1)
        self.assertEqual(len(self.phone.frames), 1)
        self.assertEqual(len(self.planner.calls), 1)
        self.assertEqual(socket.closed, 1001)
        self.assertTrue(self.core.log.audit_rows[-1]['audit']['ok'])
        self.assertEqual(self.core.log.audit_rows[-1]['audit']['req'], self.phone.frames[0]['req'])

    async def test_disconnect_cancels_watcher(self):
        stopped = asyncio.Event()
        original = GuestPublisher.run
        async def tracked(publisher):
            try:
                await original(publisher)
            finally:
                stopped.set()
        with patch.object(GuestPublisher, 'run', tracked):
            socket, task, _ = await self.open()
            # The receive and watch tasks start after the initial frame.
            await asyncio.sleep(0)
            socket.incoming.put_nowait(WebSocketDisconnect(1000))
            await asyncio.wait_for(task, 1)
            self.assertTrue(stopped.is_set())

    async def test_handler_cancellation_stops_receiver_planner_and_watcher(self):
        slow = SlowPlanner()
        self.core.agent.planner = slow
        stopped = asyncio.Event()
        original = GuestPublisher.run
        async def tracked(publisher):
            try:
                await original(publisher)
            finally:
                stopped.set()
        with patch.object(GuestPublisher, 'run', tracked):
            socket, task, _ = await self.open()
            socket.incoming.put_nowait({'type': 'user', 'text': 'turn on Jay phone'})
            await asyncio.wait_for(slow.called.wait(), 1)
            task.cancel()  # ASGI teardown can cancel before receive sees a disconnect.
            await asyncio.wait_for(task, 1)
        self.assertTrue(slow.cancelled.is_set())
        self.assertTrue(stopped.is_set())
        self.assertEqual(self.phone.frames, [])

    async def test_unchanged_snapshots_are_not_repeated_and_batches_share_send_lock(self):
        socket = ChannelSocket(self.app, self.lease.guest_id, self.token)
        publisher = GuestPublisher(self.core, self.lease.guest_id, socket)
        await publisher.publish()
        await publisher.publish()
        self.assertEqual(len(socket.frames), 1)
        batch = asyncio.create_task(publisher.send_batch([{'type': 'action', 'text': 'confirmed'},
                                                        {'type': 'assistant', 'text': 'confirmed'}]))
        await asyncio.sleep(0)
        self.clock.now += 1
        publish = asyncio.create_task(publisher.publish())
        await asyncio.gather(batch, publish)
        self.assertEqual([f['type'] for f in socket.frames], ['lease', 'action', 'assistant', 'lease'])
        self.assertEqual(socket.frames[-1]['expires_in'], 119)
        self.assertEqual(self.phone.frames, [])


if __name__ == '__main__':
    unittest.main()
