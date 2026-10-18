"""Backend/controller checks with an injected native session; no models or OS effects."""
import asyncio
import unittest
from fastapi.testclient import TestClient
from brain.config import Config
from brain.main import create_app
from brain.state import Room
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.room_conversation import ConversationAgent, ConversationSettings
from agent.room_session import RoomSessionError

THREAD = 'fixed-native-room'
ANCHOR = 'clean-setup'


class Clock:
    def __init__(self): self.now = 1000
    def __call__(self): return self.now


class NativeSession:
    def __init__(self):
        self.thread_id = THREAD
        self.history = [{'id': ANCHOR}]
        self.calls = []
        self.events = asyncio.Queue()
        self.active_turn_id = None
        self.queue = []
        self.jobs = []
        self.auto_finish = True
        self.started = asyncio.Event()
        self.fail_reset = False
        self.fail_start = False
        self.counter = 0
        self.closed = False
        self.answers = []
        self.connect_count = 0
    async def connect(self): self.connect_count += 1
    async def list_turns(self): return list(self.history)
    async def drain_queue(self):
        self.calls.append(('drain', len(self.queue)))
        self.queue.clear()
    async def assert_queue_empty(self):
        if self.queue:
            raise RoomSessionError('Native queue is not empty')
    async def background_terminals(self): return list(self.jobs)
    async def terminate_background_terminal(self, process_id):
        self.calls.append(('terminate', process_id))
        self.jobs = [j for j in self.jobs if j['processId'] != process_id]
        return {'terminated': True}
    async def confirm_clean(self, anchors):
        if self.fail_reset or [t['id'] for t in self.history] != list(anchors): raise RoomSessionError('bad anchor')
        self.calls.append(('confirm', tuple(anchors)))
    async def revert(self, before_turn_id, *, expected_retained_turn_ids):
        self.calls.append(('revert', before_turn_id))
        if self.fail_reset: raise RoomSessionError('reset unavailable')
        index = next(i for i, t in enumerate(self.history) if t['id'] == before_turn_id)
        self.history = self.history[:index]
        await self.confirm_clean(expected_retained_turn_ids)
        while not self.events.empty(): self.events.get_nowait()
    async def start_turn(self, text, *, authorize=None):
        if authorize is not None and not authorize(): raise RoomSessionError('access ended')
        self.counter += 1
        turn_id = 'native-' + str(self.counter)
        self.active_turn_id = turn_id
        self.history.append({'id': turn_id, 'text': text})
        self.calls.append(('start', text, turn_id))
        self.started.set()
        if self.fail_start: raise RoomSessionError('unknown start', outcome_unknown=True)
        if self.auto_finish: await self.finish(turn_id, 'Native reply: ' + text)
        return turn_id
    async def finish(self, turn_id, text):
        await self.events.put({'method': 'item/completed', 'params': {'threadId': THREAD, 'turnId': turn_id,
            'item': {'type': 'agentMessage', 'phase': 'final', 'text': text}}})
        self.active_turn_id = None
        await self.events.put({'method': 'turn/completed', 'params': {'threadId': THREAD,
            'turn': {'id': turn_id, 'status': 'completed'}}})
    async def next_event(self): return await self.events.get()
    async def interrupt(self):
        self.calls.append(('interrupt', self.active_turn_id))
        if self.active_turn_id:
            turn_id = self.active_turn_id
            self.active_turn_id = None
            await self.events.put({'method': 'turn/completed', 'params': {'threadId': THREAD,
                'turn': {'id': turn_id, 'status': 'interrupted'}}})
            return True
        return False
    async def answer(self, request_id, result): self.answers.append((request_id, result))
    async def close(self): self.closed = True


def settings_for(native):
    return ConversationSettings(THREAD, (ANCHOR,), turn_timeout=1, cleanup_timeout=.3, poll_interval=.005,
                                session_factory=lambda *_args, **_kwargs: native)


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.leases = Leases(Room('TEST', 'Test'), clock=self.clock)
        self.native = NativeSession()
        self.agent = ConversationAgent(self.leases, EventLog(), settings_for(self.native), private_values=('host-private',))
        self.a = self.leases.create()
    async def asyncTearDown(self): await self.agent.close()

    async def test_arbitrary_guest_text_reaches_actual_native_session_and_returns_its_reply(self):
        text = 'Explain why the sky changes color at sunset.'
        frames = await self.agent.turn(self.a.guest_id, text)
        self.assertEqual(frames, [{'type': 'assistant', 'text': 'Native reply: ' + text}])
        self.assertEqual([c[1] for c in self.native.calls if c[0] == 'start'], [text])
        self.assertEqual(self.native.connect_count, 1)

    async def test_same_lease_keeps_native_context_without_reset_or_resend(self):
        await self.agent.turn(self.a.guest_id, 'My name is Alice.')
        frames = await self.agent.turn(self.a.guest_id, 'What is my name?')
        self.assertEqual([t.get('text') for t in self.native.history], [None, 'My name is Alice.', 'What is my name?'])
        self.assertEqual(len([c for c in self.native.calls if c[0] == 'start']), 2)
        self.assertFalse(any(c[0] == 'revert' for c in self.native.calls))
        self.assertEqual(frames[-1]['text'], 'Native reply: What is my name?')

    async def test_new_lease_resets_exact_anchor_and_previous_lease_is_denied(self):
        await self.agent.turn(self.a.guest_id, 'A private guest context')
        b = self.leases.create()
        await self.agent.turn(b.guest_id, 'B new context')
        self.assertEqual(self.a.state, 'released')
        self.assertEqual([t.get('text') for t in self.native.history], [None, 'B new context'])
        before = self.native.counter
        self.assertIn('no longer', (await self.agent.turn(self.a.guest_id, 'A returns'))[-1]['text'])
        self.assertEqual(self.native.counter, before)
        self.assertIn(('revert', 'native-1'), self.native.calls)

    async def test_new_guest_interrupts_previous_turn_before_it_gets_control(self):
        self.native.auto_finish = False
        first = asyncio.create_task(self.agent.turn(self.a.guest_id, 'A long request'))
        await self.native.started.wait()
        b = self.leases.create()
        second = asyncio.create_task(self.agent.turn(b.guest_id, 'B request'))
        result_a = await first
        self.assertIn('no longer', result_a[-1]['text'])
        for _ in range(100):
            if self.native.counter == 2: break
            await asyncio.sleep(.001)
        await self.native.finish('native-2', 'Real B response')
        self.assertEqual((await second)[-1]['text'], 'Real B response')
        self.assertIn(('interrupt', 'native-1'), self.native.calls)
        self.assertEqual([t.get('text') for t in self.native.history], [None, 'B request'])

    async def test_cancelled_new_controller_waiting_for_lock_still_resets_on_reconnect(self):
        await self.agent.turn(self.a.guest_id, 'A private secret')
        b = self.leases.create()
        await self.agent._lock.acquire()
        waiting = asyncio.create_task(self.agent.turn(b.guest_id, 'B first attempt'))
        await asyncio.sleep(0)
        self.assertEqual(self.agent._controller, b.guest_id)
        waiting.cancel()
        with self.assertRaises(asyncio.CancelledError): await waiting
        self.agent._lock.release()
        result = await self.agent.turn(b.guest_id, 'B reconnect')
        self.assertEqual(result[-1]['text'], 'Native reply: B reconnect')
        self.assertEqual([t.get('text') for t in self.native.history], [None, 'B reconnect'])
        self.assertIn(('revert', 'native-1'), self.native.calls)

    async def test_cancel_during_new_controller_reset_cannot_bless_previous_history(self):
        await self.agent.turn(self.a.guest_id, 'A private secret')
        b = self.leases.create()
        original_revert = self.native.revert
        reset_started = asyncio.Event()
        async def delayed_reset(*args, **kwargs):
            reset_started.set()
            await asyncio.Event().wait()
        self.native.revert = delayed_reset
        pending = asyncio.create_task(self.agent.turn(b.guest_id, 'B initial'))
        await reset_started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        self.native.revert = original_revert
        await self.agent.turn(b.guest_id, 'B reconnect')
        self.assertEqual([t.get('text') for t in self.native.history], [None, 'B reconnect'])

    async def test_exact_expiry_during_turn_interrupts_and_denies_next_message(self):
        self.native.auto_finish = False
        running = asyncio.create_task(self.agent.turn(self.a.guest_id, 'A request'))
        await self.native.started.wait()
        self.clock.now = self.a.expires_at
        result = await running
        self.assertIn('no longer', result[-1]['text'])
        self.assertIn(('interrupt', 'native-1'), self.native.calls)
        self.assertIn('no longer', (await self.agent.turn(self.a.guest_id, 'retry'))[-1]['text'])
        self.assertEqual(self.native.counter, 1)

    async def test_revoke_without_new_message_cleans_idle_background_and_context(self):
        await self.agent.turn(self.a.guest_id, 'A context')
        self.native.jobs = [{'processId': 'job1'}]
        self.leases.revoke(self.a.guest_id)
        self.agent.access_ended(self.a.guest_id)
        await asyncio.gather(*tuple(self.agent._cleanup_tasks))
        self.assertEqual(self.native.history, [{'id': ANCHOR}])
        self.assertEqual(self.native.jobs, [])
        self.assertIn(('terminate', 'job1'), self.native.calls)

    async def test_failed_reset_never_submits_or_falls_back(self):
        self.native.fail_reset = True
        self.assertIn('could not confirm', (await self.agent.turn(self.a.guest_id, 'first'))[-1]['text'])
        self.native.fail_reset = False
        b = self.leases.create()
        self.assertIn('could not verify', (await self.agent.turn(b.guest_id, 'second'))[-1]['text'])
        self.assertEqual(self.native.counter, 0)

    async def test_unknown_start_is_never_retried(self):
        self.native.fail_start = True
        self.assertIn('nothing was retried', (await self.agent.turn(self.a.guest_id, 'first'))[-1]['text'])
        await self.agent.turn(self.a.guest_id, 'second')
        self.assertEqual(self.native.counter, 1)
        self.assertIn(('interrupt', 'native-1'), self.native.calls)

    async def test_native_queue_is_deleted_before_first_message(self):
        self.native.queue = [{'id': 'old-native-queued-input'}]
        await self.agent.turn(self.a.guest_id, 'new message')
        self.assertEqual(self.native.queue, [])
        self.assertEqual(self.native.counter, 1)

    async def test_same_lease_disconnect_cancels_without_resubmitting_or_revoking(self):
        self.native.auto_finish = False
        running = asyncio.create_task(self.agent.turn(self.a.guest_id, 'request before disconnect'))
        await self.native.started.wait()
        running.cancel()
        with self.assertRaises(asyncio.CancelledError): await running
        self.assertEqual(self.a.state, 'active')
        self.native.auto_finish = True
        result = await self.agent.turn(self.a.guest_id, 'new message after reconnect')
        self.assertEqual(result[-1]['text'], 'Native reply: new message after reconnect')
        self.assertEqual([c[1] for c in self.native.calls if c[0] == 'start'],
                         ['request before disconnect', 'new message after reconnect'])

    async def test_wrong_turn_output_is_not_forwarded_to_current_guest(self):
        await self.native.events.put({'method': 'item/completed', 'params': {'threadId': THREAD, 'turnId': 'old-guest',
            'item': {'type': 'agentMessage', 'text': 'old private text'}}})
        frames = await self.agent.turn(self.a.guest_id, 'current message')
        self.assertNotIn('old private', str(frames))
        self.assertEqual(frames[-1]['text'], 'Native reply: current message')

    async def test_host_secret_not_exposed_in_native_reply(self):
        self.native.auto_finish = False
        running = asyncio.create_task(self.agent.turn(self.a.guest_id, 'request'))
        await self.native.started.wait()
        await self.native.finish('native-1', 'A value: host-private')
        self.assertNotIn('host-private', str(await running))

    async def test_restricted_scope_has_no_native_computer_authority(self):
        self.a.scopes = {'light'}
        result = await self.agent.turn(self.a.guest_id, 'Use the computer')
        self.assertIn('does not include', result[-1]['text'])
        self.assertEqual(self.native.connect_count, 0)

    async def test_scope_removed_during_turn_stops_native_work(self):
        self.native.auto_finish = False
        running = asyncio.create_task(self.agent.turn(self.a.guest_id, 'A request'))
        await self.native.started.wait()
        self.a.scopes.clear()
        result = await running
        self.assertIn('no longer', result[-1]['text'])
        self.assertIn(('interrupt', 'native-1'), self.native.calls)

    async def test_denied_guest_never_connects_native_session(self):
        self.leases.revoke(self.a.guest_id)
        self.assertIn('no longer', (await self.agent.turn(self.a.guest_id, 'anything'))[-1]['text'])
        self.assertEqual(self.native.connect_count, 0)


class ConversationEndpointTests(unittest.TestCase):
    def test_conversation_metadata_omits_duplicate_device_labels(self):
        from brain.core.guest_view import lease_frame
        native = NativeSession()
        app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        for device_id, label in (('phone-a', 'Room phone'), ('phone-b', 'room phone')):
            app.state.registry.register({'type': 'hello', 'id': device_id, 'label': label, 'room': 'TEST',
                'caps': {'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}}}}, object())
        lease = app.state.core.leases.create()
        frame = lease_frame(app.state.core, lease.guest_id)
        self.assertEqual(frame['controls'], [])
        self.assertEqual(frame['computer_control'], 'broad')

    def test_existing_websocket_frames_deliver_native_reply_and_reconnect_keeps_context(self):
        native = NativeSession()
        app = create_app(Config('device-private', 'host-private', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        class DeviceSocket:
            async def send_json(self, _frame): pass
        app.state.registry.register({'type': 'hello', 'id': 'internal-phone-id', 'label': 'Room phone', 'room': 'TEST',
            'caps': {'light': {'description': 'Light', 'args': {'on': {'type': 'boolean'}}}}}, DeviceSocket())
        with TestClient(app, base_url='https://tenant.test') as client:
            response = client.post('/join', json={'room_code': 'TEST'}, headers={'Origin': 'https://tenant.test'})
            self.assertEqual(response.status_code, 200)
            guest = response.json()
            url = 'wss://tenant.test/ws/guest?guest_id=' + guest['guest_id'] + '&token=' + guest['guest_token']
            for text in ('Tell me something creative.', 'Continue our conversation.'):
                with client.websocket_connect(url, headers={'Origin': 'https://tenant.test'}) as ws:
                    metadata = ws.receive_json()
                    self.assertEqual(metadata['type'], 'lease')
                    self.assertEqual(metadata['agent_mode'], 'conversation')
                    self.assertEqual(metadata['computer_control'], 'broad')
                    self.assertTrue(metadata['controls_are_advisory'])
                    ws.send_json({'type': 'user', 'text': text})
                    while True:
                        frame = ws.receive_json()
                        if frame['type'] == 'assistant': break
                    self.assertEqual(frame, {'type': 'assistant', 'text': 'Native reply: ' + text})
            self.assertEqual(native.counter, 2)
            self.assertFalse(any(c[0] == 'revert' for c in native.calls))
            self.assertEqual(client.post('/leave', json={'guest_id': guest['guest_id']},
                                         headers={'Origin': 'https://tenant.test'}).status_code, 200)


if __name__ == '__main__': unittest.main()
