"""Reply speech checks with the real Bus and synthetic sockets; no audio or models."""
import asyncio
import json
import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from brain.core.bus import Bus
from brain.core.conversation_speech import (
    CompletedReply, ConversationSpeech, FALLBACK, ReplyFrames, spoken_sentence,
)
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.registry import Registry
from brain.state import Room


class Socket:
    def __init__(self, bus, *, auto=True, result=None):
        self.bus, self.auto = bus, auto
        self.result = {'spoken': True} if result is None else result
        self.frames = []
        self.sent = asyncio.Event()
        self.device = None

    async def send_json(self, frame):
        self.frames.append(frame)
        self.sent.set()
        if self.auto:
            self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': self.result})


class SentenceTests(unittest.TestCase):
    def test_short_first_sentence_is_read_without_following_detail(self):
        self.assertEqual(spoken_sentence('Hi! What can I help you with?'), 'Hi! What can I help you with?')
        self.assertEqual(spoken_sentence('Hey! What can I help you with?'), 'Hey! What can I help you with?')
        self.assertEqual(spoken_sentence('Done. ' + ' '.join(['detail'] * 30)), 'Done.')
        self.assertEqual(spoken_sentence('Tenant is ready.'), 'Tenant is ready.')
        self.assertEqual(spoken_sentence('  Hello from Tenant  '), 'Hello from Tenant')
        self.assertEqual(spoken_sentence('Done.\n```python\nprint(123)\n```'), 'Done.')
        ordinary = 'Done, I blinked the phone five times and spoke the phrase.'
        self.assertEqual(spoken_sentence(ordinary), ordinary)
        more_than_twelve_words = 'The phone can blink while the room speaker plays this short spoken reply.'
        self.assertGreater(len(more_than_twelve_words.split()), 12)
        self.assertEqual(spoken_sentence(more_than_twelve_words), more_than_twelve_words)

    def test_long_code_links_private_markers_and_structured_content_use_safe_fallback(self):
        for text in (
            ' '.join(['word'] * 33) + '.', 'x' * 161,
            '```python\nprint(123)\n```', '`open example`',
            'Visit https://example.invalid for details.',
            'Visit example.invalid for details.', 'print("Hello")',
            'Email me@example.invalid for details.',
            'Saved to /Users/synthetic/demo.txt.',
            '**Everything is ready.**', '[private value]',
            'Your API key is abc.', 'The password is synthetic.',
            'abcde12345abcde12345abcde12345abcde',
            'Here is the code:', '[]{}', '\x00Hello',
        ):
            with self.subTest(text=text):
                self.assertEqual(spoken_sentence(text), FALLBACK)
        self.assertIsNone(spoken_sentence('  '))
        self.assertIsNone(spoken_sentence(None))


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000
        self.registry = Registry(Room('TEST', 'Synthetic room'))
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.log = EventLog()
        self.generation = 1
        self.speech = ConversationSpeech(
            self.registry, self.bus, self.leases, self.log,
            lambda receipt: receipt.generation == self.generation,
            timeout=.04)
        self.voice_counter = 0

    async def asyncTearDown(self):
        await self.speech.close()

    def grant(self):
        return SimpleNamespace(guest_id=self.lease.guest_id, generation=self.generation,
            lease=self.lease, thread_id="native-room", room_id=self.registry.room.id,
            epoch=self.registry.room.epoch, turn_id="policy-turn", closed=False,
            deadline=asyncio.get_running_loop().time() + 1)

    def enable(self, speaker):
        grant = self.grant()
        choice = next(item for item in self.speech.inventory(grant)["speakers"]
                      if item["device_id"] == speaker.device.id)
        self.voice_counter += 1
        result = self.speech.set_voice(grant, {"request_id": "voice-" + str(self.voice_counter),
            "enabled": True, "device_id": choice["device_id"], "speaker_ref": choice["speaker_ref"]})
        self.assertTrue(result["ok"], result)

    def register(self, device_id='laptop', *, auto=True, result=None):
        socket = Socket(self.bus, auto=auto, result=result)
        socket.device = self.registry.register({
            'type': 'hello', 'room': 'TEST', 'id': device_id, 'label': device_id,
            'caps': {'say': {'description': 'Speech', 'args': {'text': {'type': 'string', 'maxLength': 160}}}},
        }, socket)
        return socket

    def reply(self, text='Hello from Tenant.', *, turn_id='native-1', explicit_speech_attempted=False):
        return ReplyFrames(CompletedReply(self.lease.guest_id, 1, 'native-room', turn_id, text, self.lease,
                                         explicit_speech_attempted=explicit_speech_attempted,
                                         voice_revision=self.speech.revision_for(self.grant())))

    def status(self):
        return self.log.audit_rows[-1]['audit']['audio_status']

    async def test_short_native_reply_speaks_once_only_and_does_not_log_its_text(self):
        speaker = self.register()
        self.enable(speaker)
        reply = self.reply()
        await self.speech.speak_reply(reply)
        await self.speech.speak_reply(reply)
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(speaker.frames[0]['cap'], 'say')
        self.assertEqual(speaker.frames[0]['args'], {'text': 'Hello from Tenant.'})
        self.assertEqual(self.status(), 'ACKNOWLEDGED')
        self.assertNotIn('Hello from Tenant', str(self.log.audit_rows))
        self.assertEqual(reply, [{'type': 'assistant', 'text': 'Hello from Tenant.'}])

    async def test_plain_history_error_or_interpreter_frames_never_speak(self):
        speaker = self.register()
        self.enable(speaker)
        await self.speech.speak_reply([{'type': 'assistant', 'text': 'Hello from Tenant.'}])
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.log.rows, [])

    async def test_explicit_speech_receipt_skips_auto_narration_once_without_parsing_text(self):
        speaker = self.register()
        self.enable(speaker)
        reply = self.reply('Done.', explicit_speech_attempted=True)
        await self.speech.speak_reply(reply)
        await self.speech.speak_reply(reply)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.status(), 'EXPLICIT_SPEECH_ATTEMPTED')
        self.assertEqual(len(self.log.audit_rows), 1)
        self.assertEqual(json.loads(json.dumps(reply)), [{'type': 'assistant', 'text': 'Done.'}])
        with self.assertRaises(FrozenInstanceError):
            reply.completed_reply.explicit_speech_attempted = False

    async def test_explicit_speech_receipt_does_not_queue_or_substitute_after_unknown(self):
        speaker = self.register(auto=False)
        self.enable(speaker)
        reply = self.reply('The spoken result is uncertain.', explicit_speech_attempted=True)
        await self.bus.locks['laptop'].acquire()
        try:
            await asyncio.wait_for(self.speech.speak_reply(reply), .05)
        finally:
            self.bus.locks['laptop'].release()
        other = self.register('other')
        await self.speech.speak_reply(reply)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(other.frames, [])
        self.assertEqual(self.status(), 'EXPLICIT_SPEECH_ATTEMPTED')

    async def test_mentioning_speech_in_text_is_not_a_dispatch_receipt(self):
        speaker = self.register()
        self.enable(speaker)
        await self.speech.speak_reply(self.reply('I spoke.'))
        self.assertEqual(speaker.frames[0]['args'], {'text': 'I spoke.'})

    async def test_speech_request_budget_cannot_outlast_the_current_lease(self):
        speaker = self.register()
        self.enable(speaker)
        self.speech.timeout = 15
        self.lease.expires_at = self.now + .125
        await self.speech.speak_reply(self.reply())
        self.assertEqual(len(speaker.frames), 1)
        self.assertGreater(speaker.frames[0]['deadline_ms'], 0)
        self.assertLessEqual(speaker.frames[0]['deadline_ms'], 125)
        self.assertEqual(self.status(), 'ACKNOWLEDGED')

    async def test_unsafe_long_reply_uses_only_short_screen_fallback(self):
        speaker = self.register()
        self.enable(speaker)
        await self.speech.speak_reply(self.reply('```python\nprint("synthetic-private")\n```'))
        self.assertEqual(speaker.frames[0]['args'], {'text': FALLBACK})

    async def test_text_default_and_lost_binding_never_discover_or_substitute_a_speaker(self):
        await self.speech.speak_reply(self.reply(turn_id='none'))
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        first = self.register()
        self.enable(first)
        self.registry.offline(first.device)
        await self.speech.speak_reply(self.reply(turn_id='offline'))
        self.assertEqual(first.frames, [])
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        first.device.online = True
        second = self.register('second')
        reply = self.reply(turn_id='requires-new-choice')
        await self.speech.speak_reply(reply)
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        self.assertEqual(first.frames, [])
        self.assertEqual(second.frames, [])
        self.enable(first)
        await self.speech.speak_reply(self.reply(turn_id='chosen-first'))
        self.assertEqual(len(first.frames), 1)
        self.assertEqual(second.frames, [])

    async def test_configured_missing_speaker_does_not_substitute(self):
        other = self.register('other')
        self.speech.speaker_device_id = 'laptop'
        await self.speech.speak_reply(self.reply())
        self.assertEqual(other.frames, [])
        self.assertEqual(self.status(), 'TEXT_DEFAULT')

    async def test_lease_scope_is_rechecked_and_volume_is_never_called(self):
        speaker = self.register()
        self.enable(speaker)
        self.lease.scopes = {'computer'}
        await self.speech.speak_reply(self.reply())
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.status(), 'TEXT_DEFAULT')

    async def test_revoke_expiry_new_guest_and_reset_while_queued_send_nothing(self):
        for transition in ('revoke', 'expiry', 'new_guest', 'reset'):
            with self.subTest(transition=transition):
                self.setUp()
                speaker = self.register()
                self.enable(speaker)
                lock = self.bus.locks['laptop']
                await lock.acquire()
                task = asyncio.create_task(self.speech.speak_reply(self.reply()))
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                if transition == 'revoke':
                    self.leases.revoke(self.lease.guest_id)
                elif transition == 'expiry':
                    self.now += 601
                elif transition == 'new_guest':
                    self.generation += 1
                else:
                    self.leases.reset()
                lock.release()
                await task
                self.assertEqual(speaker.frames, [])
                self.assertEqual(self.status(), 'PERMISSION')

    async def test_another_speaker_after_queueing_cannot_change_the_explicit_selection(self):
        speaker = self.register()
        self.enable(speaker)
        lock = self.bus.locks['laptop']
        await lock.acquire()
        task = asyncio.create_task(self.speech.speak_reply(self.reply()))
        await asyncio.sleep(0)
        other = self.register('other')
        lock.release()
        await task
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(other.frames, [])
        self.assertEqual(self.status(), 'ACKNOWLEDGED')

    async def test_connection_replacement_does_not_migrate_pending_speech(self):
        speaker = self.register()
        self.enable(speaker)
        lock = self.bus.locks['laptop']
        await lock.acquire()
        task = asyncio.create_task(self.speech.speak_reply(self.reply()))
        await asyncio.sleep(0)
        self.bus.disconnect(speaker.device)
        replacement = self.register()
        lock.release()
        await task
        self.assertEqual(speaker.frames, [])
        self.assertEqual(replacement.frames, [])
        self.assertEqual(self.status(), 'OFFLINE')

    async def test_unknown_is_not_replayed_even_after_late_ack_or_another_speaker_appears(self):
        speaker = self.register(auto=False)
        self.enable(speaker)
        reply = self.reply()
        await self.speech.speak_reply(reply)
        self.assertEqual(self.status(), 'UNKNOWN')
        self.bus.receive(speaker.device, {'type': 'ok', 'req': speaker.frames[0]['req'], 'result': {'spoken': True}})
        other = self.register('other')
        await self.speech.speak_reply(reply)
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(other.frames, [])

    async def test_disconnect_after_send_is_unknown_without_retry(self):
        speaker = self.register(auto=False)
        self.enable(speaker)
        reply = self.reply()
        task = asyncio.create_task(self.speech.speak_reply(reply))
        await speaker.sent.wait()
        self.bus.disconnect(speaker.device)
        await task
        await self.speech.speak_reply(reply)
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(self.status(), 'UNKNOWN')

    async def test_cancellation_after_send_is_unknown_and_same_turn_cannot_replay(self):
        speaker = self.register(auto=False)
        self.enable(speaker)
        reply = self.reply()
        task = asyncio.create_task(self.speech.speak_reply(reply))
        await speaker.sent.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.status(), 'UNKNOWN')
        self.bus.receive(speaker.device, {'type': 'ok', 'req': speaker.frames[0]['req'], 'result': {'spoken': True}})
        await self.speech.speak_reply(reply)
        self.assertEqual(len(speaker.frames), 1)

    async def test_ack_without_spoken_payload_is_not_claimed_as_playback(self):
        speaker = self.register(result={'accepted': True})
        self.enable(speaker)
        await self.speech.speak_reply(self.reply())
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(self.status(), 'UNCONFIRMED')


class ChannelSocket:
    def __init__(self, app, guest_id, token, *, fail_final=False):
        self.app = app
        self.query_params = {'guest_id': guest_id, 'token': token}
        self.headers = {'origin': 'https://tenant.test'}
        self.incoming, self.outgoing = asyncio.Queue(), asyncio.Queue()
        self.frames = []
        self.fail_final = fail_final

    async def accept(self):
        pass

    async def close(self, code=1000):
        pass

    async def receive_json(self):
        frame = await self.incoming.get()
        if isinstance(frame, BaseException):
            raise frame
        return frame

    async def send_json(self, frame):
        if self.fail_final and frame['type'] == 'assistant':
            raise OSError('Synthetic closed transport')
        self.frames.append(frame)
        self.outgoing.put_nowait(frame)


class ConversationSpeechIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from brain.config import Config
        from brain.main import create_app
        from tests.test_room_conversation import NativeSession, settings_for
        self.native = NativeSession()
        self.app = create_app(Config('private-device', 'private-host', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.lease = self.core.leases.create()
        self.token = self.core.issue_credential(self.lease.guest_id)
        self.tasks = []

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.core.agent.close()

    def register(self, *, auto=True):
        socket = Socket(self.core.bus, auto=auto)
        socket.device = self.core.registry.register({
            'type': 'hello', 'room': 'TEST', 'id': 'laptop', 'label': 'Room speaker',
            'caps': {'say': {'description': 'Speech', 'args': {'text': {'type': 'string', 'maxLength': 160}}}},
        }, socket)
        return socket

    async def open(self, *, fail_final=False):
        from brain.channels.webchat import guest_socket
        socket = ChannelSocket(self.app, self.lease.guest_id, self.token, fail_final=fail_final)
        task = asyncio.create_task(guest_socket(socket))
        self.tasks.append(task)
        self.assertEqual((await asyncio.wait_for(socket.outgoing.get(), 1))['type'], 'lease')
        return socket, task

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    async def voice_turn(self, guest, text):
        self.native.auto_finish = False
        guest.incoming.put_nowait({'type': 'user', 'text': text})
        await self.until(lambda: any(grant.turn_id is not None and not grant.closed
                                    for grant in self.core.agent.device_tools._grants.values()))
        grant = next(grant for grant in self.core.agent.device_tools._grants.values()
                     if grant.turn_id is not None and not grant.closed)
        choice = self.core.speech.inventory(grant)['speakers'][0]
        result = await self.core.agent.device_tools.dispatch({'token': grant.token, 'operation': 'reply-voice',
            'request_id': 'explicit-opt-in', 'enabled': True,
            'device_id': choice['device_id'], 'speaker_ref': choice['speaker_ref']})
        self.assertTrue(result['ok'], result)
        self.native.auto_finish = True
        await self.native.finish(grant.turn_id, 'Native reply: ' + text)

    async def test_delivered_genuine_final_is_spoken_and_reconnect_does_not_replay_it(self):
        speaker = self.register()
        guest, task = await self.open()
        delivered_before_audio = []
        send = speaker.send_json
        async def check_delivery(frame):
            delivered_before_audio.append(any(item['type'] == 'assistant' for item in guest.frames))
            await send(frame)
        speaker.send_json = check_delivery
        await self.voice_turn(guest, 'Hello')
        await asyncio.wait_for(speaker.sent.wait(), 1)
        final = [frame for frame in guest.frames if frame['type'] == 'assistant']
        self.assertEqual(final, [{'type': 'assistant', 'text': 'Native reply: Hello'}])
        self.assertEqual(delivered_before_audio, [True])
        self.assertEqual(speaker.frames[0]['args'], {'text': 'Native reply: Hello'})
        task.cancel()
        await task
        reconnect, _ = await self.open()
        self.assertEqual([f['type'] for f in reconnect.frames], ['lease'])
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(self.native.counter, 1)

    async def test_failed_final_delivery_never_starts_audio(self):
        speaker = self.register()
        guest, task = await self.open(fail_final=True)
        await self.voice_turn(guest, 'Hello')
        await asyncio.wait_for(task, 1)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.native.counter, 1)

    async def test_text_is_already_delivered_when_audio_waits_and_cancellation_never_replays(self):
        speaker = self.register(auto=False)
        self.core.speech.timeout = 1
        guest, task = await self.open()
        await self.voice_turn(guest, 'Hello')
        await asyncio.wait_for(speaker.sent.wait(), 1)
        self.assertTrue(any(frame['type'] == 'assistant' for frame in guest.frames))
        voice_task = next(iter(self.core.speech._tasks))
        voice_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await voice_task
        task.cancel()
        await task
        self.assertEqual(self.core.log.audit_rows[-1]['audit']['audio_status'], 'UNKNOWN')
        reconnect, _ = await self.open()
        self.assertEqual(len(speaker.frames), 1)
        reconnect.incoming.put_nowait({'type': 'user', 'text': 'Continue'})
        while True:
            frame = await asyncio.wait_for(reconnect.outgoing.get(), 1)
            if frame['type'] == 'assistant':
                break
        self.assertEqual(frame['text'], 'Native reply: Continue')
        self.assertEqual(self.native.counter, 2)
        self.assertFalse(self.core.agent._failed)
        self.assertEqual(len(speaker.frames), 1)  # Unresolved audio never blocks the model reply.

    async def test_receipt_is_internal_immutable_and_invalidated_by_new_controller(self):
        speaker = self.register()
        reply = await self.core.agent.turn(self.lease.guest_id, 'Hello')
        self.assertIsInstance(reply, ReplyFrames)
        self.assertTrue(self.core.agent.allows_reply(reply.completed_reply))
        self.assertEqual(json.loads(json.dumps(reply)), [{'type': 'assistant', 'text': 'Native reply: Hello'}])
        with self.assertRaises(FrozenInstanceError):
            reply.completed_reply.generation = 99
        next_guest = self.core.leases.create()
        await self.core.agent.turn(next_guest.guest_id, 'Hello again')
        self.assertFalse(self.core.agent.allows_reply(reply.completed_reply))
        await self.core.speech.speak_reply(reply)
        self.assertEqual(speaker.frames, [])

    async def test_access_error_or_local_leave_has_no_successful_native_receipt(self):
        reply = await self.core.agent.turn(self.lease.guest_id, 'leave')
        self.assertNotIsInstance(reply, ReplyFrames)
        await self.core.speech.speak_reply(reply)
        self.assertEqual(self.native.counter, 0)


if __name__ == '__main__':
    unittest.main()
