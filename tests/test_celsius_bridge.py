"""Offline scene/protocol checks: injected sessions and synthetic image bytes only."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.room_session import RoomSession, RoomSessionError
from brain.config import Config
from brain.core.celsius import CelsiusBridge
from brain.core.celsius_install import install_celsius
from brain.core.integration import Core
from brain.core.registry import Registry
from brain.core.bus import Bus
from brain.state import Room
from brain.main import create_app
from tests.test_room_conversation import NativeSession, settings_for
from tests.test_room_session import Socket, THREAD


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZucAAAAASUVORK5CYII=')


class ProfileSocket(Socket):
    def __init__(self):
        super().__init__()
        self.model, self.effort = 'ordinary-model', 'high'
        self.ignore_restore = False

    async def send(self, raw):
        frame = json.loads(raw)
        method = frame.get('method')
        if method == 'thread/read':
            self.sent.append(frame)
            await self.emit({'id': frame['id'], 'result': {'thread': {
                'id': THREAD, 'model': self.model, 'reasoningEffort': self.effort}}})
        elif method == 'model/list':
            self.sent.append(frame)
            await self.emit({'id': frame['id'], 'result': {'data': [{'model': 'scene-fast',
                'inputModalities': ['text', 'image'], 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]}})
        elif method == 'thread/settings/update':
            self.sent.append(frame)
            if not self.ignore_restore:
                self.model, self.effort = frame['params']['model'], frame['params']['effort']
            await self.emit({'id': frame['id'], 'result': {}})
        else:
            if method == 'turn/start':
                self.model = frame['params'].get('model', self.model)
                self.effort = frame['params'].get('effort', self.effort)
            await super().send(raw)


class CelsiusProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / 'synthetic.png'
        self.image.write_bytes(PNG)
        self.socket = ProfileSocket()
        async def connector(*_a, **_k): return self.socket
        self.session = RoomSession(THREAD, connector=connector, request_timeout=.1)
        await self.session.connect()
        self.addAsyncCleanup(self.session.close)

    async def test_supported_image_schema_profile_and_verified_restoration_on_same_thread(self):
        baseline = await self.session.scene_baseline('scene-fast')
        schema = {'type': 'object', 'properties': {}}
        await self.session.start_turn('Scene observation', application_context='Untrusted source data',
            image_paths=[str(self.image)], output_schema=schema, model='scene-fast', effort='low',
            turn_trigger='celsius_observation')
        params = next(f['params'] for f in self.socket.sent if f.get('method') == 'turn/start')
        self.assertEqual(params['input'][1], {'type': 'localImage', 'path': str(self.image.resolve())})
        self.assertEqual(params['outputSchema'], schema)
        self.assertEqual((params['model'], params['effort']), ('scene-fast', 'low'))
        await self.session.restore_scene_baseline(baseline)
        self.assertEqual((self.socket.model, self.socket.effort), ('ordinary-model', 'high'))
        self.assertEqual([f['method'] for f in self.socket.sent].count('thread/resume'), 1)
        self.assertFalse(any(f.get('method') == 'thread/start' for f in self.socket.sent))

    async def test_missing_baseline_or_unsupported_profile_never_starts_a_turn(self):
        for model, effort in [('missing-model', 'low'), ('scene-fast', 'ultra')]:
            with self.assertRaises(RoomSessionError):
                await self.session.scene_baseline(model, effort)
        self.socket.effort = None
        with self.assertRaises(RoomSessionError):
            await self.session.scene_baseline('scene-fast')
        self.assertFalse(any(f.get('method') in ('turn/start', 'thread/settings/update') for f in self.socket.sent))

    async def test_failed_restoration_blocks_later_native_submission(self):
        baseline = await self.session.scene_baseline('scene-fast')
        self.socket.model, self.socket.effort = 'scene-fast', 'low'
        self.socket.ignore_restore = True
        with self.assertRaises(RoomSessionError):
            await self.session.restore_scene_baseline(baseline)
        self.assertTrue(self.session._reset_required)
        with self.assertRaises(RoomSessionError):
            await self.session.start_turn('Ordinary guest must not inherit the scene profile')

    async def test_invalid_image_and_oversized_context_fail_before_model_dispatch(self):
        bad = Path(self.temp.name) / 'not-image.png'
        bad.write_text('not pixels')
        for options in ({'image_paths': [str(bad)]}, {'image_paths': ['relative.png']},
                        {'application_context': 'x' * 8001}):
            with self.assertRaises(ValueError):
                await self.session.start_turn('scene', **options)
        self.assertFalse(any(f.get('method') == 'turn/start' for f in self.socket.sent))


class SceneNative(NativeSession):
    def __init__(self):
        super().__init__()
        self.profile = ('ordinary-model', 'high')
        self.restore_calls = 0
        self.fail_restore = False
        self.reset_required = False
        self.options = []
        self.steers = []

    async def scene_baseline(self, model, effort):
        if (model, effort) != ('scene-fast', 'low'):
            raise RoomSessionError('unsupported model')
        return self.profile

    async def restore_scene_baseline(self, baseline):
        self.restore_calls += 1
        if self.fail_restore:
            raise RoomSessionError('unconfirmed restoration')
        self.profile = baseline

    def require_reset(self): self.reset_required = True

    async def start_turn(self, text, *, authorize=None, application_context=None, **options):
        self.options.append(options)
        if 'model' in options:
            self.profile = (options['model'], options['effort'])
        was_auto = self.auto_finish
        self.auto_finish = False
        turn = await super().start_turn(text, authorize=authorize, application_context=application_context)
        self.auto_finish = was_auto
        if was_auto:
            if options.get('turn_trigger') == 'celsius_observation':
                event = json.loads(application_context.split('UNTRUSTED OBSERVATION JSON:\n', 1)[1])
                answer = json.dumps({'event_id': event['event_id'], 'pickup_detected': True,
                    'action': 'say', 'text': 'Is that Celsius you picked up?'})
            else:
                answer = 'Native reply: ' + text
            await self.finish(turn, answer)
        return turn

    async def steer_turn(self, text, *, expected_turn_id, authorize, image_paths=None):
        if not authorize() or self.active_turn_id != expected_turn_id:
            raise RoomSessionError('stale steer')
        self.steers.append((text, expected_turn_id, image_paths))
        return expected_turn_id


class Reader:
    def __init__(self, root):
        self.root = self.folder = root
        self.session_id = 'synthetic-capture'
        self.alive = True
        self.pending = []
        self.image = root / 'synthetic.png'
        self.image.write_bytes(PNG)
        (root / 'events.jsonl').write_text('')

    def still_current(self, packet):
        return self.alive and packet.get('session_id') == self.session_id

    def poll(self):
        result, self.pending = self.pending, []
        return result

    def packet(self, kind='celsius_label_moved', text=None):
        value = {'session_id': self.session_id, 'event_id': str(uuid4()), 'kind': kind,
                 'unix': time.time(), 'monotonic': time.monotonic(), 'frame_ref': str(self.image),
                 'latest': {'captured_monotonic': time.monotonic(), 'frame_id': 'synthetic', 'label': None},
                 'transcript_tail': '[room_speech] Synthetic utterance; not a real person.'}
        if text is not None: value.update(text=text, segment_id='segment', provisional=True)
        return value


class Control:
    def __init__(self, reader):
        self.reader = reader
        self.calls = []
        self.delayed = {}
        self.cancelled = set()
        self.delay_effects = False

    def current(self, _root):
        return {'session_id': self.reader.session_id, 'running': self.reader.alive}, self.reader.folder

    def prepare_command(self, _root, kind, text, *, session_id, expires_unix=None):
        assert session_id == self.reader.session_id
        self.calls.append((kind, text))
        identity = str(uuid4())
        path = self.reader.folder / (identity + '.json')
        if self.delay_effects and kind != 'stop':
            self.delayed[identity] = path
        else:
            path.write_text(json.dumps({'id': identity, 'session_id': session_id, 'ok': True}))
        if kind == 'stop':
            self.reader.alive = False
            with (self.reader.folder / 'events.jsonl').open('a') as stream:
                stream.write(json.dumps({'kind': 'capture_stopped'}) + '\n')
        return identity, path

    def cancel_command(self, _root, session_id, identity):
        assert session_id == self.reader.session_id
        self.cancelled.add(identity)


class CelsiusBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.native = SceneNative()
        self.app = create_app(Config('offline-device', 'offline-host', 'TEST', 'https://testserver'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.lease = self.core.leases.create()
        self.reader = Reader(Path(self.temp.name))
        self.control = Control(self.reader)
        self.bridge = CelsiusBridge(self.core, self.reader, self.control, model='scene-fast',
                                    effects=('say',), poll_interval=.001)

    async def asyncTearDown(self):
        await self.bridge.close()
        await self.core.agent.close()

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate(): await asyncio.sleep(0)

    async def test_real_agent_receipt_drives_brief_effect_once_and_restores_settings(self):
        await self.bridge.start(self.lease.guest_id)
        packet = self.reader.packet('scene_movement_candidate')
        before = self.reader.root / 'before.png'
        before.write_bytes(PNG)
        packet['before_frame_ref'] = str(before)
        self.reader.pending.append(packet)
        await self.until(lambda: any(kind == 'say' for kind, _ in self.control.calls))
        self.assertEqual(self.control.calls, [('say', 'Is that Celsius you picked up?')])
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.native.profile, ('ordinary-model', 'high'))
        self.assertEqual(self.native.restore_calls, 1)
        self.assertEqual(self.core.leases.sessions[self.lease.guest_id].transcript, [])
        self.assertEqual(self.native.options[0]['turn_trigger'], 'celsius_observation')
        self.assertEqual(self.native.options[0]['image_paths'], [str(before), str(self.reader.image)])

    async def test_room_speech_alone_does_not_fake_a_pickup_or_trigger_a_photo(self):
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet('speech_pause', 'Please pick up the can'))
        await self.until(lambda: not self.reader.pending)
        self.assertEqual(self.native.counter, 0)
        self.assertEqual(self.control.calls, [])
        self.assertIsNone(self.bridge.motion_packet)

    async def test_first_question_reaches_effect_before_later_speech_can_replace_it(self):
        self.native.auto_finish = False
        await self.bridge.start(self.lease.guest_id)
        motion = self.reader.packet('scene_movement_candidate')
        self.reader.pending.append(motion)
        await self.until(lambda: self.native.active_turn_id is not None)
        turn = self.native.active_turn_id
        self.reader.pending.append(self.reader.packet('speech_pause', 'Synthetic ongoing speech'))
        await self.until(lambda: not self.reader.pending)
        self.assertEqual(self.native.steers, [])
        self.assertEqual(self.bridge.latest_packet['event_id'], motion['event_id'])
        await self.native.finish(turn, json.dumps({'event_id': motion['event_id'],
            'pickup_detected': True, 'action': 'say', 'text': 'Is that Celsius you picked up?'}))
        await self.until(lambda: bool(self.control.calls))
        self.assertEqual(self.control.calls, [('say', 'Is that Celsius you picked up?')])
        self.assertEqual(self.bridge.phase, 'awaiting_response')

    async def test_followup_steers_original_turn_without_guest_publication_or_second_model(self):
        self.native.auto_finish = False
        await self.bridge.start(self.lease.guest_id)
        motion = self.reader.packet()
        self.reader.pending.append(motion)
        await self.until(lambda: self.native.active_turn_id is not None)
        turn = self.native.active_turn_id
        self.bridge.phase = 'awaiting_response'
        speech = self.reader.packet('speech_pause', 'I know it is Celsius, not medicine')
        self.reader.pending.append(speech)
        await self.until(lambda: bool(self.native.steers))
        self.assertIn(speech['text'], self.native.steers[0][0])
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.core.leases.sessions[self.lease.guest_id].transcript, [])
        await self.native.finish(turn, json.dumps({'event_id': speech['event_id'],
            'pickup_detected': True, 'action': 'none', 'text': ''}))
        await self.until(lambda: self.native.restore_calls == 1)
        self.assertEqual(self.control.calls, [])

    async def test_source_stop_cancels_native_and_restores_before_releasing_permit(self):
        self.native.auto_finish = False
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet())
        await self.until(lambda: self.native.active_turn_id is not None)
        self.reader.alive = False
        with (self.reader.folder / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps({'kind': 'capture_stopped'}) + '\n')
        await asyncio.wait_for(self.bridge.task, 1)
        self.assertIsNone(self.native.active_turn_id)
        self.assertEqual(self.native.restore_calls, 1)
        self.assertEqual(self.native.profile, ('ordinary-model', 'high'))
        self.assertIsNone(self.core.agent._observation_permit)
        self.assertEqual(self.control.calls, [])

    async def test_pending_effect_revocation_cancels_without_waiting_for_receipt(self):
        self.control.delay_effects = True
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet())
        await self.until(lambda: bool(self.control.delayed))
        self.core.revoke(self.lease.guest_id)
        with self.assertRaises(RoomSessionError):
            await asyncio.wait_for(asyncio.shield(self.bridge.task), .3)
        self.assertEqual(set(self.control.delayed), self.control.cancelled)
        self.assertEqual(self.bridge.cleanup, 'source_stopped')
        self.assertFalse(self.bridge._pending_effects)
        self.assertEqual([kind for kind, _ in self.control.calls], ['say', 'stop'])

    async def test_pending_effect_task_cancellation_tombstones_before_cleanup(self):
        self.control.delay_effects = True
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet())
        await self.until(lambda: bool(self.control.delayed))
        self.bridge.task.cancel()
        await asyncio.gather(self.bridge.task, return_exceptions=True)
        self.assertEqual(set(self.control.delayed), self.control.cancelled)
        self.assertEqual(self.bridge.cleanup, 'source_stopped')

    async def test_fresh_steer_keeps_original_turn_alive_after_original_packet_ages(self):
        self.native.auto_finish = False
        await self.bridge.start(self.lease.guest_id)
        motion = self.reader.packet()
        self.reader.pending.append(motion)
        await self.until(lambda: self.native.active_turn_id is not None)
        turn = self.native.active_turn_id
        self.bridge.phase = 'awaiting_response'
        motion['monotonic'] -= 3
        speech = self.reader.packet('speech_pause', 'Correction: I know this is a drink')
        self.reader.pending.append(speech)
        await self.until(lambda: bool(self.native.steers))
        await self.native.finish(turn, json.dumps({'event_id': speech['event_id'],
            'pickup_detected': True, 'action': 'none', 'text': ''}))
        await self.until(lambda: self.native.restore_calls == 1)
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.control.calls, [])

    async def test_superseded_completed_final_preserves_newly_queued_observation(self):
        await self.bridge.start(self.lease.guest_id)
        old = self.reader.packet()
        new = self.reader.packet('speech_pause', 'Actually I know what this is')
        self.bridge.latest_packet = new
        self.bridge._seen_observations.update([old['event_id'], new['event_id']])
        reply = SimpleNamespace(lease=self.lease, generation=self.bridge.permit.generation,
            text=json.dumps({'event_id': old['event_id'], 'pickup_detected': True,
                'action': 'say', 'text': 'Old decision.'}))
        # Preserve the real agent reply-authority checks while isolating ordering.
        self.core.agent.allows_reply = lambda completed: completed is reply
        from brain.core.conversation_speech import ReplyFrames
        frames = ReplyFrames(reply)
        await self.bridge._accept(frames, time.monotonic())
        self.assertTrue(self.bridge.active)
        self.assertEqual(self.control.calls, [])
        self.bridge.motion_packet = old
        self.reader.pending.append(new)
        await self.until(lambda: self.native.counter == 1)

    async def test_revocation_cancels_scene_and_only_stops_original_source(self):
        self.native.auto_finish = False
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet())
        await self.until(lambda: self.native.active_turn_id is not None)
        self.core.revoke(self.lease.guest_id)
        await asyncio.wait_for(self.bridge.task, 1)
        self.assertEqual(self.control.calls, [('stop', '')])
        self.assertEqual(self.bridge.cleanup, 'source_stopped')
        self.assertIsNone(self.native.active_turn_id)

    async def test_ordinary_guest_input_stops_scene_then_keeps_exact_normal_input(self):
        await self.bridge.start(self.lease.guest_id)
        exact = '  Ordinary text.\nKeep spacing. '
        reply = await self.core.agent.turn(self.lease.guest_id, exact)
        self.assertEqual(reply[-1]['text'], 'Native reply: ' + exact)
        self.assertEqual(self.control.calls, [('stop', '')])
        self.assertIsNone(self.core.agent._observation_permit)
        self.assertNotIn('model', self.native.options[-1])
        self.assertEqual([call[1] for call in self.native.calls if call[0] == 'start'], [exact])

    async def test_restore_failure_blocks_normal_turn_and_never_speaks(self):
        self.native.fail_restore = True
        await self.bridge.start(self.lease.guest_id)
        self.reader.pending.append(self.reader.packet())
        await self.until(lambda: self.bridge.task.done())
        self.assertTrue(self.core.agent._failed)
        self.assertTrue(self.native.reset_required)
        self.assertFalse(any(kind == 'say' for kind, _ in self.control.calls))
        result = await self.core.agent.turn(self.lease.guest_id, 'ordinary')
        self.assertIn('could not verify', result[-1]['text'])
        self.assertEqual(self.native.counter, 1)

    async def test_stale_packet_and_other_controller_cannot_admit_model_work(self):
        await self.bridge.start(self.lease.guest_id)
        stale = self.reader.packet()
        stale['monotonic'] -= 10
        self.reader.pending.append(stale)
        await self.until(lambda: not self.reader.pending)
        self.assertEqual(self.native.counter, 0)
        await self.bridge.close()
        other = self.core.leases.create()
        await self.core.agent.turn(other.guest_id, 'Current real controller')
        reader = Reader(Path(self.temp.name))
        blocked = CelsiusBridge(self.core, reader, Control(reader), model='scene-fast')
        with self.assertRaises(RoomSessionError):
            await blocked.start(self.lease.guest_id)


class CelsiusHostRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.state.config = Config('offline-device', 'offline-host', 'TEST', 'https://testserver')
        self.app.state.registry = Registry(Room('TEST', 'offline'))
        self.app.state.bus = Bus(self.app.state.registry)
        self.core = Core(self.app, None)
        self.core.agent = SimpleNamespace(agent_mode='conversation')
        self.source_calls = []
        self.bridges = []
        self.headers = {'Authorization': 'Bearer offline-host', 'Origin': 'https://testserver'}
        self.lease = self.core.leases.create()
        self.body = {'guest_id': self.lease.guest_id, 'session_id': str(uuid4()), 'model': 'scene-fast'}

        def source(root, session):
            self.source_calls.append((root, session))
            return SimpleNamespace(), SimpleNamespace()

        bridges = self.bridges
        class FakeBridge:
            def __init__(self, _core, _reader, _control, *, model, effects):
                self.active = False
                self.phase, self.cleanup = 'watching', 'not_started'
                self.last_error, self.timings = None, []
                self.effects = effects
                bridges.append(self)
            async def start(self, _guest): self.active = True
            async def close(self, **_kw):
                self.active, self.cleanup = False, 'source_stopped'

        install_celsius(self.app, self.core, source_factory=source, bridge_factory=FakeBridge)
        self.client = TestClient(self.app, base_url='https://testserver')
        self.addCleanup(self.client.close)

    def test_registration_and_status_are_dormant_and_private(self):
        self.assertIsNone(self.core.celsius)
        self.assertEqual(self.client.get('/host/celsius').status_code, 403)
        status = self.client.get('/host/celsius', headers=self.headers)
        self.assertEqual(status.json(), {'armed': False, 'phase': 'idle', 'cleanup': 'no_owned_source'})
        self.assertEqual(self.source_calls, [])
        self.assertEqual(self.bridges, [])

    def test_arm_requires_explicit_host_origin_live_lease_and_bounded_shape(self):
        self.assertEqual(self.client.post('/host/celsius/arm', json=self.body).status_code, 403)
        bad_origin = dict(self.headers, Origin='https://other.invalid')
        self.assertEqual(self.client.post('/host/celsius/arm', json=self.body, headers=bad_origin).status_code, 403)
        invalid = dict(self.body, root='/private/untrusted')
        self.assertEqual(self.client.post('/host/celsius/arm', json=invalid, headers=self.headers).status_code, 400)
        invalid = dict(self.body, effects=['volume'])
        self.assertEqual(self.client.post('/host/celsius/arm', json=invalid, headers=self.headers).status_code, 400)
        self.core.leases.revoke(self.lease.guest_id)
        self.assertEqual(self.client.post('/host/celsius/arm', json=self.body, headers=self.headers).status_code, 403)
        self.assertEqual(self.source_calls, [])

    def test_no_implicit_effects_duplicate_start_or_unauthorized_stop(self):
        first = self.client.post('/host/celsius/arm', json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()['armed'])
        self.assertEqual(self.bridges[0].effects, [])
        self.assertEqual(self.client.post('/host/celsius/arm', json=self.body, headers=self.headers).status_code, 409)
        self.assertEqual(len(self.source_calls), 1)
        self.assertEqual(self.client.post('/host/celsius/stop').status_code, 403)
        self.assertTrue(self.bridges[0].active)
        stopped = self.client.post('/host/celsius/stop', headers=self.headers).json()
        self.assertFalse(stopped['armed'])
        self.assertEqual(stopped['cleanup'], 'source_stopped')

    def test_planner_mode_never_loads_lab_or_starts_a_model(self):
        self.core.agent.agent_mode = 'planner'
        self.assertEqual(self.client.post('/host/celsius/arm', json=self.body, headers=self.headers).status_code, 503)
        self.assertEqual(self.source_calls, [])

    def test_real_app_lifespan_does_not_connect_native_session_or_arm_source(self):
        native = SceneNative()
        app = create_app(Config('offline-device', 'offline-host', 'TEST', 'https://testserver'),
                         conversation=settings_for(native))
        with TestClient(app, base_url='https://testserver') as client:
            status = client.get('/host/celsius', headers=self.headers)
            self.assertFalse(status.json()['armed'])
            self.assertEqual(native.connect_count, 0)
            self.assertEqual(native.counter, 0)
            self.assertIsNone(app.state.core.celsius)


if __name__ == '__main__':
    unittest.main()
