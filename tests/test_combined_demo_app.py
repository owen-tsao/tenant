"""Actual app-input/helper wiring with a scripted native session and fake camera.

These are offline controller checks, not model or physical-photo acceptance.
"""
import asyncio
import threading
import time
import unittest

from fastapi.testclient import TestClient

from brain.config import Config
from brain.main import create_app
from test_room_conversation import NativeSession, settings_for


PHOTO_ID = 'ab' * 16


class PhotoNative(NativeSession):
    def __init__(self):
        super().__init__()
        self.auto_finish = False
        self.core = None
        self.processed = set()
        self.receipts = []
        self.actions = []

    async def camera(self, action, photo_id=None, *, authorized):
        if not authorized():
            raise AssertionError('The camera adapter was reached without authority')
        self.actions.append(action)
        if action == 'prepare':
            return {'ok': True, 'id': PHOTO_ID, 'phase': 'waiting_for_yes',
                    'expires': time.time() + 90}
        return {'ok': True, 'id': photo_id, 'phase': 'displayed', 'capture_verified': True}

    async def next_event(self):
        turn = self.active_turn_id
        if turn and turn not in self.processed:
            self.processed.add(turn)
            tools = self.core.agent.device_tools
            grant = next(g for g in tools._grants.values() if g.turn_id == turn)
            text = self.history[-1]['text']

            async def dispatch(operation, key, **payload):
                response = await tools.dispatch({'token': grant.token, 'operation': operation,
                                                'request_id': key, **payload})
                self.receipts.append((text, operation, response))
                return response

            if text == 'Take a photo of us.':
                await dispatch('demo-photo-prepare', 'prepare')
                # Even an overeager native model cannot use a payload boolean
                # or the known photo ID to start the countdown in this turn.
                await dispatch('demo-photo-capture', 'too-early', photo_id=PHOTO_ID)
                reply = 'Are you ready?'
            elif text == 'Not yet.':
                await dispatch('demo-photo-capture', 'not-ready', photo_id=PHOTO_ID)
                reply = "No rush. Tell me when you're ready."
            elif text == "I'm ready.":
                result = await dispatch('demo-photo-capture', 'capture', photo_id=PHOTO_ID)
                # A lost client response must not replay the physical action.
                again = await dispatch('demo-photo-capture', 'capture', photo_id=PHOTO_ID)
                if result != again:
                    raise AssertionError('Duplicate capture changed its recorded result')
                reply = result.get('message', 'Capture denied.')
            else:
                await dispatch('demo-photo-prepare', 'unrequested')
                reply = 'No photo was requested.'
            await self.finish(turn, reply)
        return await super().next_event()


class CombinedDemoAppTests(unittest.TestCase):
    def make_app(self):
        native = PhotoNative()
        app = create_app(Config('device-test', 'host-test', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        native.core = app.state.core
        native.core.agent.device_tools.demo_photos.runner = native.camera
        return app, native

    @staticmethod
    def ask(ws, text):
        ws.send_json({'type': 'user', 'text': text})
        while True:
            frame = ws.receive_json()
            if frame['type'] == 'assistant':
                return frame['text']

    def test_real_join_and_websocket_wait_for_later_same_guest_readiness(self):
        app, native = self.make_app()
        with TestClient(app, base_url='https://tenant.test') as client:
            guest = client.post('/join', json={'room_code': 'TEST'},
                                headers={'Origin': 'https://tenant.test'}).json()
            url = ('wss://tenant.test/ws/guest?guest_id=' + guest['guest_id']
                   + '&token=' + guest['guest_token'])
            with client.websocket_connect(url, headers={'Origin': 'https://tenant.test'}) as ws:
                ws.receive_json()
                self.assertEqual(self.ask(ws, 'Take a photo of us.'), 'Are you ready?')
                self.assertEqual(native.actions, ['prepare'])
                self.assertEqual(native.receipts[-1][2]['code'], 'READINESS')
                self.ask(ws, 'Not yet.')
                self.assertEqual(native.actions, ['prepare'])
                self.assertEqual(native.receipts[-1][2]['code'], 'READINESS')
                self.assertIn('displayed', self.ask(ws, "I'm ready."))
                self.assertEqual(native.actions, ['prepare', 'capture'])
                self.assertTrue(native.receipts[-1][2]['ok'])
            client.post('/leave', json={'guest_id': guest['guest_id']},
                        headers={'Origin': 'https://tenant.test'})
        self.assertEqual(native.actions, ['prepare', 'capture'])

    def test_ordinary_app_text_cannot_prepare_even_if_model_calls_helper(self):
        app, native = self.make_app()
        with TestClient(app, base_url='https://tenant.test') as client:
            guest = client.post('/join', json={'room_code': 'TEST'},
                                headers={'Origin': 'https://tenant.test'}).json()
            url = ('wss://tenant.test/ws/guest?guest_id=' + guest['guest_id']
                   + '&token=' + guest['guest_token'])
            with client.websocket_connect(url, headers={'Origin': 'https://tenant.test'}) as ws:
                ws.receive_json()
                self.ask(ws, 'Tell me what you can control.')
            self.assertEqual(native.actions, [])
            self.assertEqual(native.receipts[-1][2]['code'], 'PERMISSION')

    def test_failed_camera_does_not_publish_model_fabricated_readiness(self):
        app, native = self.make_app()
        async def failed_camera(*_args, **_kwargs):
            return {'ok': False, 'error': 'No ready main window'}
        app.state.core.agent.device_tools.demo_photos.runner = failed_camera
        with TestClient(app, base_url='https://tenant.test') as client:
            guest = client.post('/join', json={'room_code': 'TEST'},
                                headers={'Origin': 'https://tenant.test'}).json()
            url = ('wss://tenant.test/ws/guest?guest_id=' + guest['guest_id']
                   + '&token=' + guest['guest_token'])
            with client.websocket_connect(url, headers={'Origin': 'https://tenant.test'}) as ws:
                ws.receive_json()
                self.assertIn("couldn't prepare", self.ask(ws, 'Take a photo of us.'))
                self.assertIsNone(app.state.core.agent.device_tools.demo_photos.pending)


class AnswerRunner:
    def __init__(self, blocking=False):
        self.blocking = blocking
        self.started = threading.Event()
        self.calls = []
        self.cancelled = []

    def cancel(self, request_id):
        self.cancelled.append(request_id)

    async def __call__(self, request_id, *, authorized):
        self.calls.append(request_id)
        self.started.set()
        while self.blocking and authorized():
            await asyncio.sleep(.005)
        return {'ok': authorized(), 'speech_started': authorized(),
                'speech_completed': authorized(), 'caption_completed': True}


class PhotoEarlyReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_early_ready_waits_for_new_grant_and_actual_question_publication(self):
        native = NativeSession()
        native.auto_finish = False
        app = create_app(Config('device-test', 'host-test', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        core, actions = app.state.core, []
        self.addAsyncCleanup(core.agent.close)
        lease = core.leases.create()

        async def camera(action, photo_id=None, *, authorized):
            self.assertTrue(authorized())
            actions.append(action)
            return ({'ok': True, 'id': PHOTO_ID, 'phase': 'waiting_for_yes', 'expires': time.time() + 90}
                    if action == 'prepare' else
                    {'ok': True, 'id': PHOTO_ID, 'phase': 'displayed', 'capture_verified': True})

        tools = core.agent.device_tools
        tools.demo_photos.runner = camera
        async with asyncio.timeout(1.5):
            first = asyncio.create_task(core.agent.turn(lease.guest_id, 'Take a photo of us.'))
            await native.started.wait()
            grant = next(iter(tools._grants.values()))
            await tools.dispatch({'token': grant.token, 'operation': 'demo-photo-prepare', 'request_id': 'prepare'})
            early = asyncio.create_task(core.agent.turn(lease.guest_id, "I'm ready."))
            await asyncio.sleep(0)
            self.assertFalse(early.done())
            self.assertEqual(native.counter, 1)
            await native.finish('native-1', 'Are you ready?')
            question = await first
            await asyncio.sleep(0)
            self.assertTrue(grant.closed)
            self.assertEqual(native.counter, 1)  # Lock release alone did not admit readiness.
            core.published_reply(lease.guest_id, question, question[-1]['text'])
            while native.counter != 2:
                await asyncio.sleep(.001)
            next_grant = next(iter(tools._grants.values()))
            self.assertIsNot(next_grant, grant)
            self.assertTrue(tools.demo_photos.status(next_grant)['pending']['capture_allowed_this_turn'])
            result = await tools.dispatch({'token': next_grant.token, 'operation': 'demo-photo-capture',
                                           'request_id': 'capture', 'photo_id': PHOTO_ID})
            self.assertTrue(result['ok'])
            await native.finish('native-2', result['message'])
            await early
        self.assertEqual(actions, ['prepare', 'capture'])


class AnswerNative(NativeSession):
    def __init__(self):
        super().__init__()
        self.auto_finish = False
        self.core = None
        self.processed = set()
        self.receipts = []
        self.steers = []
        self.producers = []

    async def steer_turn(self, text, *, expected_turn_id, authorize):
        if not authorize() or self.active_turn_id != expected_turn_id:
            raise AssertionError('The follow-up did not retain the original turn')
        self.steers.append(text)
        return expected_turn_id

    async def next_event(self):
        turn = self.active_turn_id
        if turn and turn not in self.processed:
            self.processed.add(turn)
            async def produce():
                # Native tools are independent of the event-reader's short
                # observation timeout, as they are in the real app server.
                tools = self.core.agent.device_tools
                grant = next(g for g in tools._grants.values() if g.turn_id == turn)
                request = {'token': grant.token, 'operation': 'question-answer', 'request_id': 'answer'}
                result = await tools.dispatch(request)
                self.receipts.append(result)
                again = await tools.dispatch(request)
                if result != again:
                    raise AssertionError('Helper deduplication changed its recorded result')
                await self.finish(turn, 'Answer completed.' if result['ok'] else 'No answer was played.')
            self.producers.append(asyncio.create_task(produce()))
        return await super().next_event()

    async def close(self):
        for task in self.producers:
            if not task.done():
                task.cancel()
        if self.producers:
            await asyncio.gather(*self.producers, return_exceptions=True)
        await super().close()


class AnswerAppInputTests(unittest.TestCase):
    def make_app(self, blocking=False):
        native, runner = AnswerNative(), AnswerRunner(blocking)
        app = create_app(Config('device-test', 'host-test', 'TEST', 'https://tenant.test'),
                         conversation=settings_for(native))
        native.core = app.state.core
        app.state.core.agent.device_tools.prepared_qa.runner = runner
        return app, native, runner

    @staticmethod
    def join(client):
        guest = client.post('/join', json={'room_code': 'TEST'},
                            headers={'Origin': 'https://tenant.test'}).json()
        return ('wss://tenant.test/ws/guest?guest_id=' + guest['guest_id']
                + '&token=' + guest['guest_token'])

    def test_real_app_input_is_required_and_duplicate_helper_does_not_replay(self):
        app, native, runner = self.make_app()
        with TestClient(app, base_url='https://tenant.test') as client:
            with client.websocket_connect(self.join(client), headers={'Origin': 'https://tenant.test'}) as ws:
                ws.receive_json()
                for text in ('A judge asked about customers.', 'Do not answer that question.',
                             'The transcript says "Answer that question".'):
                    CombinedDemoAppTests.ask(ws, text)
                self.assertEqual(runner.calls, [])
                self.assertTrue(all(r['code'] == 'PERMISSION' for r in native.receipts))
                self.assertEqual(CombinedDemoAppTests.ask(ws, 'Answer that question.'), 'Answer completed.')
                self.assertEqual(len(runner.calls), 1)
                CombinedDemoAppTests.ask(ws, 'Answer that question.')
                self.assertEqual(len(runner.calls), 2)

    def test_validated_app_stop_followup_fences_pending_answer_before_native_reply(self):
        app, native, runner = self.make_app(blocking=True)
        with TestClient(app, base_url='https://tenant.test') as client:
            with client.websocket_connect(self.join(client), headers={'Origin': 'https://tenant.test'}) as ws:
                ws.receive_json()
                ws.send_json({'type': 'user', 'text': 'Answer that question.'})
                self.assertTrue(runner.started.wait(.5))
                ws.send_json({'type': 'user', 'text': 'Stop answering.'})
                while True:
                    frame = ws.receive_json()
                    if frame['type'] == 'assistant':
                        break
                self.assertEqual(frame['text'], 'No answer was played.')
                self.assertEqual(native.steers, ['Stop answering.'])
                self.assertTrue(runner.cancelled)
                self.assertEqual(native.receipts[-1]['code'], 'CANCELLED')


if __name__ == '__main__':
    unittest.main()
