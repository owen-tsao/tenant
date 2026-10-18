"""Offline native failure regressions: fake daemon, real transport/controller.

No model, desktop, deployed service, browser, device, or physical output is used.
"""
import asyncio
from contextlib import suppress
import json
import unittest

from fastapi.testclient import TestClient

from agent.room_session import RoomSession, RoomSessionError
from brain.core.conversation_speech import ReplyFrames
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.room_conversation import ConversationAgent, ConversationSettings
from brain.state import Room
from brain.config import Config
from brain.main import create_app


THREAD = 'offline-terminal-room'
ANCHOR = 'offline-clean-anchor'
PRIVATE = 'private-native-detail-do-not-publish'


class NativeSocket:
    """Small deterministic app-server peer; records every outbound operation."""

    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.history = [{'id': ANCHOR}]
        self.turn_number = 0
        self.started = asyncio.Queue()
        self.active = None
        self.complete_on_interrupt = True
        self.start_status = 'inProgress'
        self.complete_before_start_response = False
        self.response_items = None

    async def emit(self, method, **params):
        await self.incoming.put(json.dumps({'method': method, 'params': {'threadId': THREAD, **params}}))

    async def respond(self, frame, result):
        await self.incoming.put(json.dumps({'id': frame['id'], 'result': result}))

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        method = frame.get('method')
        if method == 'initialize':
            await self.respond(frame, {'userAgent': 'offline-fake'})
        elif method == 'thread/resume':
            await self.respond(frame, {'thread': {'id': THREAD, 'status': {'type': 'idle'}}})
        elif method in ('thread/queue/list', 'thread/backgroundTerminals/list'):
            await self.respond(frame, {'data': [], 'nextCursor': None})
        elif method == 'thread/turns/list':
            await self.respond(frame, {'data': list(self.history), 'nextCursor': None})
        elif method == 'thread/revert':
            before = frame['params']['beforeTurnId']
            index = next(i for i, turn in enumerate(self.history) if turn['id'] == before)
            self.history = self.history[:index]
            await self.respond(frame, {'thread': {'id': THREAD, 'turns': []}})
        elif method == 'turn/start':
            self.turn_number += 1
            turn = {'id': f'offline-turn-{self.turn_number}', 'status': 'inProgress'}
            self.active = turn['id']
            self.history.append({'id': turn['id'], 'text': frame['params']['input'][0]['text']})
            await self.emit('turn/started', turn=turn)
            if self.complete_before_start_response:
                await self.finish(turn['id'], self.start_status, text='One completed reply.')
            reply = dict(turn, status=self.start_status)
            if self.response_items is not None:
                reply['items'] = self.response_items
            await self.respond(frame, {'turn': reply})
            await self.started.put(turn['id'])
        elif method == 'turn/interrupt':
            await self.respond(frame, {})
            if self.complete_on_interrupt and self.active:
                await self.finish(self.active, 'interrupted')

    async def finish(self, turn_id, status='completed', *, text=None):
        if text is not None:
            await self.emit('item/completed', turnId=turn_id,
                            item={'type': 'agentMessage', 'phase': 'final', 'text': text})
        if self.active == turn_id:
            self.active = None
        await self.emit('turn/completed', turn={'id': turn_id, 'status': status,
                                               'error': {'message': PRIVATE} if status == 'failed' else None})

    def requests(self, method):
        return [frame for frame in self.sent if frame.get('method') == method]

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self.incoming.get()
        if raw is None:
            raise StopAsyncIteration
        return raw

    async def close(self):
        await self.incoming.put(None)


class NativeTerminalEventsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = NativeSocket()

        async def connector(*_args, **_kwargs):
            return self.socket

        self.session = RoomSession(THREAD, connector=connector, request_timeout=.1)
        self.leases = Leases(Room('OFFLINE', 'Offline regression room'), clock=lambda: 1000)
        self.log = EventLog(clock=lambda: 1000)
        settings = ConversationSettings(THREAD, (ANCHOR,), turn_timeout=2,
                                        cleanup_timeout=.05, poll_interval=.002,
                                        session_factory=lambda *_a, **_k: self.session)
        self.agent = ConversationAgent(self.leases, self.log, settings, private_values=(PRIVATE,))
        self.guest = self.leases.create()

    async def asyncTearDown(self):
        # A deliberately unconfirmed native stop must stay blocked; teardown
        # closes only this fake socket and never retries the uncertain request.
        with suppress(RoomSessionError):
            await self.agent.close()
        await self.session.close()

    async def begin(self, text='Create my disposable welcome note.', *, guest=None):
        guest = guest or self.guest
        task = asyncio.create_task(self.agent.turn(guest.guest_id, text))
        self.addAsyncCleanup(self.cancel_task, task)
        turn_id = await asyncio.wait_for(self.socket.started.get(), .4)
        return task, turn_id

    @staticmethod
    async def cancel_task(task):
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def failure_reply(self, task):
        frames = await asyncio.wait_for(task, .4)
        self.assertIsInstance(frames, list)
        self.assertFalse(isinstance(frames, ReplyFrames), 'Failure must never earn an automatic speech receipt')
        text = ' '.join(frame.get('text', '') for frame in frames)
        self.assertTrue(text.strip(), 'The pending guest request needs a terminal response')
        self.assertRegex(text.lower(), r'could not|unavailable|interrupted|failed|stopped|cancel')
        self.assertRegex(text.lower(), r'not (?:automatically )?(?:retried|repeated)|nothing was retried|did not retry')
        for private in (PRIVATE, THREAD, 'quota', 'permission denied', 'rate limit'):
            self.assertNotIn(private, text.lower())
        self.assertEqual(len(self.socket.requests('turn/start')), 1, 'Failure must not resubmit the guest turn')
        self.assertFalse(any('result' in frame and frame.get('id') == 'late-approval'
                             for frame in self.socket.sent), 'A terminal failure must not replay a tool request')
        return frames

    async def test_interrupted_native_completion_is_prompt_failure_and_not_success(self):
        task, turn_id = await self.begin()
        await self.socket.finish(turn_id, 'interrupted', text='The note is ready.')
        frames = await self.failure_reply(task)
        self.assertNotIn('The note is ready.', str(frames))
        self.assertIsNone(self.session.active_turn_id)
        self.assertEqual(self.session._pending, {})

    async def test_cancelled_native_completion_is_not_confused_with_browser_cancellation(self):
        task, turn_id = await self.begin()
        await self.socket.finish(turn_id, 'cancelled')
        await self.failure_reply(task)
        self.assertFalse(task.cancelled())
        self.assertEqual(self.guest.state, 'active')

    async def test_failed_native_completion_does_not_publish_private_error_or_partial_success(self):
        task, turn_id = await self.begin()
        await self.socket.finish(turn_id, 'failed', text='I saved the note successfully.')
        frames = await self.failure_reply(task)
        self.assertNotIn('saved the note', str(frames))
        self.assertNotIn(PRIVATE, json.dumps(self.log.rows))
        self.assertNotIn(PRIVATE, json.dumps(self.leases.sessions[self.guest.guest_id].transcript))

    async def test_terminal_error_without_completion_settles_promptly_after_confirmed_interrupt(self):
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId=turn_id,
                               error={'message': PRIVATE, 'codexErrorInfo': 'other'}, willRetry=False)
        await self.failure_reply(task)
        self.assertIsNone(self.session.active_turn_id)
        self.assertEqual(self.session._pending, {})

    async def test_malformed_error_retry_flag_fails_closed_without_waiting_for_turn_timeout(self):
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId=turn_id, error={'message': PRIVATE})
        await self.failure_reply(task)

    async def test_unconfirmed_error_cleanup_blocks_new_request_without_repeated_interrupt(self):
        self.socket.complete_on_interrupt = False
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId=turn_id, error={'message': PRIVATE}, willRetry=False)
        await self.failure_reply(task)
        self.assertTrue(self.agent._failed)
        self.assertEqual(len(self.socket.requests('turn/interrupt')), 1)
        followup = await self.agent.turn(self.guest.guest_id, 'Do not replay the uncertain request.')
        self.assertIn('could not verify', followup[-1]['text'])
        self.assertEqual(len(self.socket.requests('turn/start')), 1)
        self.assertEqual(len(self.socket.requests('turn/interrupt')), 1)

    async def test_retriable_native_error_does_not_make_tenant_resubmit_or_publish_error(self):
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId=turn_id, error={'message': PRIVATE}, willRetry=True)
        await self.socket.finish(turn_id, text='The native turn recovered.')
        frames = await asyncio.wait_for(task, .4)
        self.assertEqual(frames[-1]['text'], 'The native turn recovered.')
        self.assertEqual(len(self.socket.requests('turn/start')), 1)
        self.assertNotIn(PRIVATE, str(frames))

    async def test_confirmed_interruption_allows_only_next_explicit_request_without_old_tool_replay(self):
        task, turn_id = await self.begin('First explicit request.')
        await self.socket.finish(turn_id, 'interrupted')
        await self.failure_reply(task)
        followup, fresh_turn = await self.begin('A different explicit follow-up.')
        await self.socket.finish(fresh_turn, text='Fresh request completed.')
        frames = await asyncio.wait_for(followup, .4)
        self.assertEqual(frames[-1]['text'], 'Fresh request completed.')
        self.assertEqual([frame['params']['input'][0]['text'] for frame in self.socket.requests('turn/start')],
                         ['First explicit request.', 'A different explicit follow-up.'])
        self.assertFalse(any(frame.get('id') == 'late-approval' and 'result' in frame
                             for frame in self.socket.sent))

    async def test_late_previous_turn_approval_is_not_accepted_or_replayed_by_fresh_request(self):
        task, turn_id = await self.begin('First explicit request.')
        await self.socket.finish(turn_id, 'interrupted')
        await self.failure_reply(task)
        followup, fresh_turn = await self.begin('A different explicit follow-up.')
        await self.socket.incoming.put(json.dumps({
            'id': 'late-approval', 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': THREAD, 'turnId': turn_id, 'itemId': 'stale-item'}}))
        frames = await asyncio.wait_for(followup, .4)
        self.assertNotIsInstance(frames, ReplyFrames)
        self.assertIn('could not confirm', frames[-1]['text'])
        self.assertFalse(any(frame.get('id') == 'late-approval' and 'result' in frame
                             for frame in self.socket.sent))
        self.assertEqual(len(self.socket.requests('turn/start')), 2)
        self.assertIsNone(self.session.active_turn_id)

    async def test_new_guest_after_confirmed_failure_removes_previous_private_context(self):
        task, turn_id = await self.begin('Previous guest confidential context.')
        await self.socket.finish(turn_id, 'failed')
        await self.failure_reply(task)
        next_guest = self.leases.create()
        next_task, next_turn = await self.begin('Fresh guest request.', guest=next_guest)
        await self.socket.finish(next_turn, text='Fresh guest reply.')
        self.assertEqual((await asyncio.wait_for(next_task, .4))[-1]['text'], 'Fresh guest reply.')
        self.assertEqual([turn.get('text') for turn in self.socket.history], [None, 'Fresh guest request.'])
        self.assertEqual(self.guest.state, 'released')
        self.assertEqual(self.leases.sessions[self.guest.guest_id].transcript, [])
        self.assertEqual(len(self.socket.requests('thread/revert')), 1)

    async def test_access_revoked_during_native_interruption_returns_denial_without_result_or_speech(self):
        task, turn_id = await self.begin()
        self.leases.revoke(self.guest.guest_id)
        self.agent.access_ended(self.guest.guest_id)
        await self.socket.finish(turn_id, 'interrupted', text='A stale result.')
        frames = await asyncio.wait_for(task, .4)
        self.assertIn('no longer', frames[-1]['text'])
        self.assertNotIn('stale result', str(frames))
        self.assertNotIsInstance(frames, ReplyFrames)
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_browser_cancellation_propagates_cancelled_error_and_never_replays(self):
        task, _turn_id = await self.begin('Request before browser disconnect.')
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.guest.state, 'active')
        self.assertEqual(len(self.socket.requests('turn/start')), 1)
        self.assertEqual(len(self.socket.requests('turn/interrupt')), 1)
        next_task, next_turn = await self.begin('Explicit message after reconnect.')
        await self.socket.finish(next_turn, text='Fresh reconnect response.')
        self.assertEqual((await asyncio.wait_for(next_task, .4))[-1]['text'], 'Fresh reconnect response.')

    async def test_other_room_terminal_error_cannot_end_the_current_request(self):
        task, turn_id = await self.begin()
        await self.socket.emit('error', threadId='unrelated-private-room', turnId=turn_id,
                               error={'message': PRIVATE}, willRetry=False)
        await self.socket.finish(turn_id, text='Only the current room reply.')
        self.assertEqual((await asyncio.wait_for(task, .4))[-1]['text'], 'Only the current room reply.')
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_previous_turn_error_does_not_fail_current_explicit_request(self):
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId='previous-private-turn', error={'message': PRIVATE}, willRetry=False)
        await self.socket.finish(turn_id, text='Current explicit reply.')
        self.assertEqual((await asyncio.wait_for(task, .4))[-1]['text'], 'Current explicit reply.')
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_terminal_start_response_without_completion_event_settles_guest_request(self):
        self.socket.start_status = 'interrupted'
        task, _turn_id = await self.begin()
        await self.failure_reply(task)
        self.assertIsNone(self.session.active_turn_id)
        self.assertEqual(self.session._pending, {})

    async def test_unknown_start_status_fails_closed_without_waiting_or_resubmission(self):
        self.socket.start_status = 'unrecognized-native-status'
        task, _turn_id = await self.begin()
        frames = await self.failure_reply(task)
        self.assertNotIn('unrecognized-native-status', str(frames))
        self.assertTrue(self.agent._failed)

    async def test_completed_event_before_start_response_is_not_duplicated_or_lost(self):
        self.socket.start_status = 'completed'
        self.socket.complete_before_start_response = True
        task, _turn_id = await self.begin()
        frames = await asyncio.wait_for(task, .4)
        self.assertEqual(frames[-1]['text'], 'One completed reply.')
        self.assertIsInstance(frames, ReplyFrames)
        self.assertTrue(self.session._events.empty(), 'Duplicate terminal event must not contaminate the next request')
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_completed_start_response_preserves_only_final_agent_message_items(self):
        self.socket.start_status = 'completed'
        self.socket.response_items = [
            {'type': 'agentMessage', 'phase': 'commentary', 'text': 'Do not publish this draft.'},
            {'type': 'commandExecution', 'aggregatedOutput': PRIVATE},
            {'type': 'agentMessage', 'phase': 'final', 'text': 'Final note description.'}]
        task, _turn_id = await self.begin()
        frames = await asyncio.wait_for(task, .4)
        self.assertEqual(frames[-1]['text'], 'Final note description.')
        self.assertIsInstance(frames, ReplyFrames)
        self.assertNotIn('draft', str(frames))
        self.assertNotIn(PRIVATE, str(frames))
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_late_terminal_notification_and_start_cannot_reopen_synthesized_completion(self):
        self.socket.start_status = 'completed'
        self.socket.response_items = [{'type': 'agentMessage', 'phase': 'final', 'text': 'One final reply.'}]
        task, turn_id = await self.begin()
        self.assertEqual((await asyncio.wait_for(task, .4))[-1]['text'], 'One final reply.')
        await self.socket.emit('turn/started', turn={'id': turn_id, 'status': 'inProgress'})
        await self.socket.finish(turn_id)
        # FIFO response forms a deterministic read barrier without real waits.
        await self.session.list_queue()
        self.assertIsNone(self.session.active_turn_id)
        self.assertTrue(self.session._events.empty())
        self.assertEqual(len(self.socket.requests('turn/start')), 1)


class NativeTerminalWebchatTests(unittest.TestCase):
    def test_fake_native_failure_reaches_socket_and_next_explicit_message_completes_once(self):
        class ScriptedSocket(NativeSocket):
            async def send(self, raw):
                await super().send(raw)
                if json.loads(raw).get('method') == 'turn/start':
                    await self.finish(self.active, 'interrupted' if self.turn_number == 1 else 'completed',
                                      text='Only the explicit follow-up reply.' if self.turn_number == 2 else None)

        # Every queue/transport operation occurs on TestClient's single app loop.
        socket = ScriptedSocket()

        async def connector(*_args, **_kwargs):
            return socket

        native = RoomSession(THREAD, connector=connector, request_timeout=.1)
        settings = ConversationSettings(THREAD, (ANCHOR,), turn_timeout=2,
                                        cleanup_timeout=.05, poll_interval=.002,
                                        session_factory=lambda *_a, **_k: native)
        origin = 'https://offline-tenant.test'
        app = create_app(Config('offline-device-secret', 'offline-host-secret', 'OFFLINE', origin),
                         conversation=settings)
        speech_receipts = []
        speech = app.state.core.speech
        original_schedule = speech.schedule_reply

        def track_schedule(frames):
            speech_receipts.append(isinstance(frames, ReplyFrames))
            return original_schedule(frames)

        speech.schedule_reply = track_schedule
        with TestClient(app, base_url=origin) as client:
            joined = client.post('/join', json={'room_code': 'OFFLINE'}, headers={'Origin': origin})
            self.assertEqual(joined.status_code, 200)
            guest = joined.json()
            url = '/ws/guest?guest_id=' + guest['guest_id'] + '&token=' + guest['guest_token']
            with client.websocket_connect(url, headers={'Origin': origin}) as ws:
                self.assertEqual(ws.receive_json()['type'], 'lease')
                replies = []
                for text in ('Create the first disposable note.', 'A different explicit follow-up.'):
                    ws.send_json({'type': 'user', 'text': text})
                    while True:
                        frame = ws.receive_json()
                        if frame.get('type') == 'assistant':
                            replies.append(frame['text'])
                            break
                self.assertIn('could not complete', replies[0])
                self.assertIn('nothing was retried', replies[0])
                self.assertEqual(replies[1], 'Only the explicit follow-up reply.')
                self.assertEqual(speech_receipts, [False, True])
                self.assertEqual([frame['params']['input'][0]['text'] for frame in socket.requests('turn/start')],
                                 ['Create the first disposable note.', 'A different explicit follow-up.'])


if __name__ == '__main__':
    unittest.main()
