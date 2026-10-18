"""Guest-owned reply voice and real channel queues; no models, audio or network."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from brain.core.conversation_speech import CompletedReply, ReplyFrames
from tests import test_conversation_speech as fixtures


class VoicePolicyTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.SpeechTests.setUp
    asyncTearDown = fixtures.SpeechTests.asyncTearDown
    register = fixtures.SpeechTests.register
    grant = fixtures.SpeechTests.grant
    enable = fixtures.SpeechTests.enable
    reply = fixtures.SpeechTests.reply
    status = fixtures.SpeechTests.status

    def disable(self):
        result = self.speech.set_voice(self.grant(), {'request_id': 'disable', 'enabled': False})
        self.assertTrue(result['ok'], result)
        return result

    async def test_new_guest_defaults_to_text_despite_multiple_available_speakers(self):
        first, second = self.register(), self.register('other')
        policy = self.speech.inventory(self.grant())
        self.assertFalse(policy['enabled'])
        self.assertEqual(policy['mode'], 'text')
        self.assertEqual(len(policy['speakers']), 2)
        task = self.speech.schedule_reply(self.reply())
        self.assertIsInstance(task, asyncio.Task)
        await task
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        self.assertEqual(first.frames + second.frames, [])
        self.assertIsNone(self.speech.schedule_reply(self.reply()))

    async def test_explicit_choice_persists_between_turns_and_disable_restores_text(self):
        speaker = self.register()
        self.enable(speaker)
        await self.speech.speak_reply(self.reply(turn_id='first'))
        await self.speech.speak_reply(self.reply(turn_id='second'))
        self.assertTrue(self.speech.inventory(self.grant())['enabled'])
        self.assertEqual(len(speaker.frames), 2)
        result = self.disable()
        self.assertIn('already started', result['message'].lower())
        await self.speech.speak_reply(self.reply(turn_id='third'))
        self.assertEqual(len(speaker.frames), 2)
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        self.assertEqual({frame['cap'] for frame in speaker.frames}, {'say'})

    async def test_exact_selected_speaker_is_never_replaced_by_discovery(self):
        first, second = self.register(), self.register('chosen')
        self.enable(second)
        third = self.register('third')
        await self.speech.speak_reply(self.reply())
        self.assertEqual(first.frames + third.frames, [])
        self.assertEqual(len(second.frames), 1)
        self.assertEqual(self.speech.inventory(self.grant())['selected_device_id'], 'chosen')
        self.registry.offline(second.device)
        await self.speech.speak_reply(self.reply(turn_id='offline'))
        self.assertEqual(first.frames + third.frames, [])
        self.assertEqual(len(second.frames), 1)
        self.assertFalse(self.speech.inventory(self.grant())['enabled'])

    async def test_reconnect_requires_a_fresh_connection_choice_and_never_replays(self):
        old = self.register()
        self.enable(old)
        owner = self.grant()
        stale = self.speech.inventory(owner)['speakers'][0]
        prior = self.reply(turn_id='before-reconnect')
        self.bus.disconnect(old.device)
        new = self.register()
        denied = self.speech.set_voice(owner, {'request_id': 'stale-ref', 'enabled': True,
            'device_id': stale['device_id'], 'speaker_ref': stale['speaker_ref']})
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['code'], 'OFFLINE')
        await self.speech.speak_reply(prior)
        self.assertEqual(old.frames + new.frames, [])
        fresh = self.speech.inventory(owner)['speakers'][0]
        self.assertNotEqual(fresh['speaker_ref'], stale['speaker_ref'])
        self.enable(new)
        await self.speech.speak_reply(prior)
        self.assertEqual(new.frames, [])
        await self.speech.speak_reply(self.reply(turn_id='fresh-choice'))
        self.assertEqual(len(new.frames), 1)

    async def test_old_text_receipt_cannot_become_spoken_after_a_later_opt_in(self):
        speaker = self.register()
        old = self.reply(turn_id='text-era')
        self.enable(speaker)
        await self.speech.speak_reply(old)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.status(), 'POLICY_CHANGED')
        await self.speech.speak_reply(self.reply(turn_id='voice-era'))
        self.assertEqual(len(speaker.frames), 1)

    async def test_reset_expiry_generation_and_revocation_deny_stale_policy_changes(self):
        for transition in ('reset', 'expiry', 'generation', 'revoke'):
            with self.subTest(transition=transition):
                self.setUp()
                speaker = self.register()
                self.enable(speaker)
                owner = self.grant()
                if transition == 'reset': self.leases.reset()
                elif transition == 'expiry': self.now += 601
                elif transition == 'generation': self.generation += 1
                else: self.leases.revoke(self.lease.guest_id)
                result = self.speech.set_voice(owner, {'request_id': 'stale-disable', 'enabled': False})
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['code'], 'PERMISSION')
                self.assertEqual(self.speech.inventory(owner)['speakers'], [])
                await self.speech.speak_reply(self.reply(turn_id='stale'))
                self.assertEqual(speaker.frames, [])
                await self.speech.close()

    async def test_new_controller_gets_text_default_and_a_fresh_speaker_offer(self):
        speaker = self.register()
        self.enable(speaker)
        previous = self.grant()
        self.leases.revoke(self.lease.guest_id)
        self.generation += 1
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        current = self.grant()
        self.assertFalse(self.speech.inventory(current)['enabled'])
        self.assertTrue(self.speech.context(current)['offer_speaker_choice'])
        self.assertFalse(self.speech.set_voice(previous, {'request_id': 'old', 'enabled': False})['ok'])
        receipt = ReplyFrames(CompletedReply(current.guest_id, current.generation, current.thread_id,
            'new-guest', 'Hello.', current.lease, voice_revision=self.speech.revision_for(current)))
        await self.speech.speak_reply(receipt)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.status(), 'TEXT_DEFAULT')

    async def test_closed_expired_and_unapproved_turns_cannot_change_policy(self):
        speaker = self.register()
        for mutation in ('closed', 'deadline', 'turn_id'):
            owner = self.grant()
            setattr(owner, mutation, True if mutation == 'closed' else
                    asyncio.get_running_loop().time() - 1 if mutation == 'deadline' else None)
            result = self.speech.set_voice(owner, {'request_id': 'denied', 'enabled': False})
            self.assertEqual(result.get('code'), 'PERMISSION', result)
        result = self.speech.set_voice(self.grant(), {'request_id': 'denied', 'enabled': False}, authorized=lambda: False)
        self.assertEqual(result.get('code'), 'PERMISSION', result)
        self.assertEqual(speaker.frames, [])

    async def test_say_scope_and_exact_choice_are_required_even_for_one_available_speaker(self):
        speaker = self.register()
        owner = self.grant()
        choice = self.speech.inventory(owner)['speakers'][0]
        self.lease.scopes = {'computer'}
        result = self.speech.set_voice(owner, {'request_id': 'scope-denied', 'enabled': True,
            'device_id': choice['device_id'], 'speaker_ref': choice['speaker_ref']})
        self.assertFalse(result['ok'], result)
        self.assertEqual(self.speech.inventory(owner)['speakers'], [])
        self.assertEqual(speaker.frames, [])
        self.lease.scopes = {'*'}
        for payload in ({'request_id': 'missing-choice', 'enabled': True},
                        {'request_id': 'not-bool', 'enabled': 1},
                        {'request_id': 'extra', 'enabled': False, 'device_id': 'laptop'}):
            self.assertEqual(self.speech.set_voice(owner, payload).get('code'), 'INVALID')
        self.assertFalse(self.speech.inventory(owner)['enabled'])

    async def test_opt_out_cancels_a_queued_reply_before_bus_dispatch_and_never_replays(self):
        speaker = self.register()
        self.enable(speaker)
        lock = self.bus.locks['laptop']
        await lock.acquire()
        reply = self.reply()
        task = self.speech.schedule_reply(reply)
        try:
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.disable()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            lock.release()
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.bus.uncertain, {})
        self.assertIsNone(self.speech.schedule_reply(reply))
        await self.speech.speak_reply(self.reply(turn_id='after-disable'))
        self.assertEqual(speaker.frames, [])

    async def test_rebinding_drops_queued_old_voice_instead_of_rerouting_it(self):
        first, second = self.register(), self.register('second')
        self.enable(first)
        lock = self.bus.locks['laptop']
        await lock.acquire()
        old = self.reply(turn_id='old-selection')
        task = self.speech.schedule_reply(old)
        try:
            await asyncio.sleep(0)
            self.enable(second)
            await asyncio.gather(task, return_exceptions=True)
        finally:
            lock.release()
        self.assertEqual(first.frames + second.frames, [])
        self.assertIsNone(self.speech.schedule_reply(old))
        await self.speech.speak_reply(self.reply(turn_id='new-selection'))
        self.assertEqual(first.frames, [])
        self.assertEqual(len(second.frames), 1)

    async def test_speaker_offers_are_once_per_guest_and_enrolled_connection(self):
        owner = self.grant()
        self.assertFalse(self.speech.context(owner)['offer_speaker_choice'])
        old = self.register()
        self.assertTrue(self.speech.context(owner)['offer_speaker_choice'])
        self.assertFalse(self.speech.context(self.grant())['offer_speaker_choice'])
        self.register('another')
        self.assertTrue(self.speech.context(owner)['offer_speaker_choice'])
        self.assertFalse(self.speech.context(owner)['offer_speaker_choice'])
        self.bus.disconnect(old.device)
        replacement = self.register()
        self.assertTrue(self.speech.context(owner)['offer_speaker_choice'])
        self.assertFalse(self.speech.context(owner)['offer_speaker_choice'])
        self.assertFalse(self.speech.inventory(owner)['enabled'])
        self.assertEqual(old.frames + replacement.frames, [])

    async def test_close_cancels_queued_audio_without_dispatching_or_replaying(self):
        speaker = self.register()
        self.enable(speaker)
        lock = self.bus.locks['laptop']
        await lock.acquire()
        reply = self.reply()
        task = self.speech.schedule_reply(reply)
        try:
            await asyncio.sleep(0)
            await asyncio.wait_for(self.speech.close(), .2)
        finally:
            lock.release()
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.done())
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.bus.uncertain, {})
        self.assertIsNone(self.speech.schedule_reply(reply))

    async def test_close_settles_already_sent_audio_without_cancellation_or_replay(self):
        speaker = self.register(auto=False)
        self.enable(speaker)
        reply = self.reply()
        task = self.speech.schedule_reply(reply)
        await speaker.sent.wait()
        closing = asyncio.create_task(self.speech.close())
        await asyncio.sleep(0)
        self.assertFalse(closing.done())
        self.assertEqual(self.bus.uncertain, {})
        self.bus.receive(speaker.device, {'type': 'ok', 'req': speaker.frames[0]['req'], 'result': {'spoken': True}})
        await asyncio.wait_for(closing, .2)
        await task
        self.assertEqual(len(speaker.frames), 1)
        self.assertEqual(self.status(), 'ACKNOWLEDGED')
        self.assertIsNone(self.speech.schedule_reply(reply))

    async def test_explicit_one_off_speech_does_not_enable_future_voice(self):
        speaker = self.register()
        await self.speech.speak_reply(self.reply(explicit_speech_attempted=True))
        self.assertEqual(self.status(), 'EXPLICIT_SPEECH_ATTEMPTED')
        self.assertFalse(self.speech.inventory(self.grant())['enabled'])
        await self.speech.speak_reply(self.reply(turn_id='ordinary-next'))
        self.assertEqual(self.status(), 'TEXT_DEFAULT')
        self.assertEqual(speaker.frames, [])


class WebPolicyTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ConversationSpeechIntegrationTests.asyncSetUp
    asyncTearDown = fixtures.ConversationSpeechIntegrationTests.asyncTearDown
    register = fixtures.ConversationSpeechIntegrationTests.register
    open = fixtures.ConversationSpeechIntegrationTests.open
    until = fixtures.ConversationSpeechIntegrationTests.until
    voice_turn = fixtures.ConversationSpeechIntegrationTests.voice_turn

    async def active_grant(self, counter):
        await self.until(lambda: self.native.counter == counter and any(
            grant.turn_id is not None and not grant.closed for grant in self.core.agent.device_tools._grants.values()))
        return next(grant for grant in self.core.agent.device_tools._grants.values()
                    if grant.turn_id is not None and not grant.closed)

    async def set_policy(self, grant, enabled):
        payload = {'token': grant.token, 'operation': 'reply-voice', 'request_id': 'voice-policy', 'enabled': enabled}
        if enabled:
            choice = self.core.speech.inventory(grant)['speakers'][0]
            payload.update(device_id=choice['device_id'], speaker_ref=choice['speaker_ref'])
        result = await self.core.agent.device_tools.dispatch(payload)
        self.assertTrue(result['ok'], result)

    async def test_web_guest_text_default_delivers_actual_reply_without_audio(self):
        speaker = self.register()
        guest, _ = await self.open()
        guest.incoming.put_nowait({'type': 'user', 'text': 'Hello'})
        await self.until(lambda: any(frame['type'] == 'assistant' for frame in guest.frames))
        await self.core.speech.drain()
        self.assertEqual([frame['text'] for frame in guest.frames if frame['type'] == 'assistant'], ['Native reply: Hello'])
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.native.counter, 1)

    async def test_web_receiver_accepts_next_opt_out_while_previous_voice_is_bus_queued(self):
        speaker = self.register()
        lock = self.core.bus.locks['laptop']
        await lock.acquire()
        try:
            guest, _ = await self.open()
            await self.voice_turn(guest, 'Hello')
            await self.until(lambda: any(frame['type'] == 'assistant' for frame in guest.frames)
                             and bool(self.core.speech._tasks))
            self.native.auto_finish = False
            guest.incoming.put_nowait({'type': 'user', 'text': 'Keep replies text only.'})
            grant = await self.active_grant(2)
            await self.set_policy(grant, False)
            await self.native.finish(grant.turn_id, 'Native reply: Text only.')
            await self.until(lambda: len([f for f in guest.frames if f['type'] == 'assistant']) == 2)
            self.assertEqual(self.native.counter, 2)
            self.assertEqual(speaker.frames, [])
        finally:
            lock.release()
        await self.core.speech.drain()
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.core.bus.uncertain, {})


class PhotonTransport:
    """Only in-memory API-shaped data; deliberately has no HTTP implementation."""
    project_id = 'pho_prj_' + '0' * 25 + '1'

    def __init__(self, clock):
        self.clock, self.current, self.pages, self.sent = clock, [], [], []

    async def assignments(self):
        return list(self.current)

    async def assign(self, handle, _key):
        from brain.channels.photon import stamp
        row = {'assignmentId': 'assignment-1', 'assignedPhoneNumber': '+14155550202', 'handle': handle,
               'projectId': self.project_id, 'platform': 'imessage', 'createdAt': stamp(self.clock())}
        self.current.append(row)
        return row

    async def release(self, assignment_id):
        self.current = [row for row in self.current if row['assignmentId'] != assignment_id]

    async def messages(self, _query):
        return self.pages.pop(0) if self.pages else {'items': []}

    async def send(self, space_id, sender_id, text, key):
        self.sent.append((space_id, sender_id, text, key))
        return {'id': 'pho_msg_outgoing'}

    async def close(self):
        pass

    def incoming(self, message_id, text):
        from brain.channels.photon import stamp
        def identity(identifier, handle, kind):
            return {'id': identifier, 'handle': handle, 'kind': kind,
                    'projectId': self.project_id, 'platform': 'imessage'}
        return {'id': message_id, 'projectId': self.project_id, 'platform': 'imessage', 'status': 'received',
                'createdAt': stamp(self.clock()),
                'sentBy': identity('pho_usr_human', '+14155550101', 'human'),
                'receivedBy': identity('pho_usr_agent', '+14155550202', 'agent'),
                'space': {'id': 'pho_spc_direct', 'projectId': self.project_id, 'platform': 'imessage',
                          'kind': 'direct', 'participantIds': ['pho_usr_human', 'pho_usr_agent']},
                'content': {'type': 'text', 'format': 'plain', 'text': text}}


class PhotonPolicyTests(unittest.IsolatedAsyncioTestCase):
    register = fixtures.ConversationSpeechIntegrationTests.register
    until = fixtures.ConversationSpeechIntegrationTests.until
    active_grant = WebPolicyTests.active_grant
    set_policy = WebPolicyTests.set_policy

    async def asyncSetUp(self):
        from brain.channels.photon import PhotonChannel
        await fixtures.ConversationSpeechIntegrationTests.asyncSetUp(self)
        self.now = 1000
        self.core.leases.clock = lambda: self.now
        # Replace the existing joining lease to use the same synthetic clock.
        self.lease.expires_at, self.lease.joining_until = 1600, 1120
        self.directory = tempfile.TemporaryDirectory()
        self.transport = PhotonTransport(lambda: self.now)
        self.channel = PhotonChannel(self.core, self.transport, Path(self.directory.name) / 'photon.sqlite3')
        self.channel._ready = True
        result = await self.channel.enroll('+14155550101', guest_id=self.lease.guest_id)
        self.assertIs(result.lease, self.lease)

    async def asyncTearDown(self):
        await self.channel.close()
        await fixtures.ConversationSpeechIntegrationTests.asyncTearDown(self)
        self.directory.cleanup()

    async def process(self, message_id, text):
        self.transport.pages.append({'items': [self.transport.incoming(message_id, text)]})
        await self.channel.poll_once()
        task = asyncio.create_task(self.channel.process_one())
        self.tasks.append(task)
        return task

    async def test_photon_next_opt_out_is_processed_while_prior_voice_waits_after_text_acceptance(self):
        speaker = self.register()
        lock = self.core.bus.locks['laptop']
        await lock.acquire()
        try:
            self.native.auto_finish = False
            first = await self.process('pho_msg_first', 'Hello')
            grant = await self.active_grant(1)
            await self.set_policy(grant, True)
            await self.native.finish(grant.turn_id, 'Native reply: Hello')
            await asyncio.wait_for(first, .3)
            self.assertEqual(self.transport.sent[0][2], 'Native reply: Hello')
            self.assertEqual(speaker.frames, [])
            self.assertTrue(self.core.speech._tasks)
            second = await self.process('pho_msg_second', 'Keep replies text only.')
            grant = await self.active_grant(2)
            await self.set_policy(grant, False)
            await self.native.finish(grant.turn_id, 'Native reply: Text only.')
            await asyncio.wait_for(second, .3)
            self.assertEqual([row[2] for row in self.transport.sent],
                             ['Native reply: Hello', 'Native reply: Text only.'])
            self.assertEqual(self.native.counter, 2)
        finally:
            lock.release()
        await self.core.speech.drain()
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.core.bus.uncertain, {})
        outcomes = self.channel.store.db.execute('SELECT outcome FROM claims ORDER BY message_id').fetchall()
        self.assertEqual([row[0] for row in outcomes], ['ACCEPTED', 'ACCEPTED'])


class OptionalSpeechCloseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from dataclasses import replace
        await fixtures.ConversationSpeechIntegrationTests.asyncSetUp(self)
        self.core.agent.settings = replace(self.core.agent.settings, cleanup_timeout=.01)
        # Exercise the real session and private helper lifecycle, not only spies.
        frames = await self.core.agent.turn(self.lease.guest_id, 'Initialize teardown fixture')
        self.assertIsInstance(frames, ReplyFrames)
        self.assertIs(self.core.agent._session, self.native)
        self.assertIsNotNone(self.core.agent.device_tools._server)
        self.assertFalse(self.core.agent.programs._closed)
        self.assertFalse(self.core.agent.device_tools._closed)
        self.assertFalse(self.native.closed)
        self.original_speech_close = self.core.speech.close

    async def asyncTearDown(self):
        self.core.speech.close = self.original_speech_close
        await fixtures.ConversationSpeechIntegrationTests.asyncTearDown(self)

    def assert_required_cleanup_finished(self):
        self.assertTrue(self.core.agent.programs._closed, 'Optional audio prevented program teardown.')
        self.assertTrue(self.native.closed, 'Optional audio prevented native session teardown.')
        self.assertTrue(self.core.agent.device_tools._closed, 'Optional audio prevented helper teardown.')
        self.assertTrue(self.core.agent._failed, 'Unconfirmed optional audio cleanup must remain visible.')
        self.assertIsNone(self.core.leases.current(self.lease.guest_id))
        self.assertEqual(self.core.agent.device_tools._grants, {})

    async def test_failing_optional_speech_close_cannot_skip_required_real_teardown(self):
        async def broken_close():
            raise RuntimeError('synthetic-sensitive-close-error')
        self.core.speech.close = broken_close
        await asyncio.wait_for(self.core.agent.close(), .5)
        self.assert_required_cleanup_finished()
        self.assertNotIn('synthetic-sensitive-close-error', str(self.core.log.audit_rows))
        self.assertNotIn('synthetic-sensitive-close-error', str(self.core.log.rows))

    async def test_hung_optional_speech_close_is_bounded_and_required_teardown_still_finishes(self):
        cancelled = asyncio.Event()
        async def hung_close():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        self.core.speech.close = hung_close
        # Production reserves its configured optional cleanup budget plus the
        # existing one-second drain allowance. The outer test deadline detects
        # an uncontained hang without asserting a scheduler-sensitive duration.
        await asyncio.wait_for(self.core.agent.close(), 1.5)
        self.assertTrue(cancelled.is_set(), 'Timed-out optional cleanup was left running.')
        self.assert_required_cleanup_finished()


if __name__ == '__main__':
    unittest.main()
