"""One composed voice journey: real channel/core/helper/Bus, synthetic native/audio.

Natural input is preserved, but helper choices are explicitly driven by this
fixture. This does not establish live model intent recognition or audibility.
"""
import asyncio
import unittest

from agent.tenant_device import invoke
from tests import test_conversation_speech as fixtures


class ReplyVoiceAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ConversationSpeechIntegrationTests.asyncSetUp
    asyncTearDown = fixtures.ConversationSpeechIntegrationTests.asyncTearDown
    register = fixtures.ConversationSpeechIntegrationTests.register
    open = fixtures.ConversationSpeechIntegrationTests.open
    until = fixtures.ConversationSpeechIntegrationTests.until

    async def turn(self, guest, text, *, operation=None, payload=None):
        """Deliver unchanged user text, drive a declared helper choice, finish text."""
        self.native.auto_finish = False
        count = self.native.counter + 1
        finals = sum(frame['type'] == 'assistant' for frame in guest.frames)
        guest.incoming.put_nowait({'type': 'user', 'text': text})
        await self.until(lambda: self.native.counter == count and any(
            grant.turn_id == 'native-' + str(count) and not grant.closed
            for grant in self.core.agent.device_tools._grants.values()))
        grant = next(grant for grant in self.core.agent.device_tools._grants.values()
                     if grant.turn_id == 'native-' + str(count) and not grant.closed)
        if operation is not None:
            result = await asyncio.to_thread(invoke, grant.path, operation, payload(grant))
            self.assertTrue(result['ok'], result)
        await self.native.finish(grant.turn_id, 'Reply received.')
        await self.until(lambda: sum(frame['type'] == 'assistant' for frame in guest.frames) == finals + 1)
        await self.core.speech.drain()
        self.assertEqual(self.native.calls[-1], ('start', text, grant.turn_id))
        return grant

    def opt_in(self, grant):
        choice = self.core.speech.inventory(grant)['speakers'][0]
        return {'request_id': 'consent', 'enabled': True,
                'device_id': choice['device_id'], 'speaker_ref': choice['speaker_ref']}

    async def test_default_opt_in_opt_out_one_off_and_new_guest_without_unsolicited_voice(self):
        speaker = self.register()
        first, _ = await self.open()
        first_lease = self.lease
        expiry = first_lease.expires_at
        marker = 'The harmless context marker is copper meadow.'
        grant = await self.turn(first, marker)
        self.assertEqual(speaker.frames, [])
        self.assertEqual(self.core.log.audit_rows[-1]['audit']['audio_status'], 'TEXT_DEFAULT')

        grant = await self.turn(first, 'Use the Room speaker for spoken replies from now on.',
                                operation='reply-voice', payload=self.opt_in)
        self.assertTrue(self.core.speech.inventory(grant)['enabled'])
        self.assertEqual(len(speaker.frames), 1)
        await self.turn(first, 'What can I control here?')
        self.assertEqual(len(speaker.frames), 2)

        grant = await self.turn(first, 'Keep future replies text only.', operation='reply-voice',
                                payload=lambda _: {'request_id': 'text-only', 'enabled': False})
        self.assertFalse(self.core.speech.inventory(grant)['enabled'])
        await self.turn(first, 'What is the current mode?')
        self.assertEqual(len(speaker.frames), 2)

        grant = await self.turn(first, 'Say Tenant test ready once.', operation='call',
            payload=lambda _: {'request_id': 'requested-phrase', 'device_id': 'laptop',
                               'cap': 'say', 'args': {'text': 'Tenant test ready'}})
        self.assertEqual(len(speaker.frames), 3)
        self.assertEqual(speaker.frames[-1]['args'], {'text': 'Tenant test ready'})
        self.assertEqual(self.core.log.audit_rows[-1]['audit']['audio_status'], 'EXPLICIT_SPEECH_ATTEMPTED')
        self.assertFalse(self.core.speech.inventory(grant)['enabled'])
        await self.turn(first, 'Thanks. What else can I ask?')
        self.assertEqual(len(speaker.frames), 3)
        self.assertEqual(first_lease.expires_at, expiry, 'Voice changes renewed access.')

        # Enable again so the new-controller check actually detects inheritance.
        await self.turn(first, 'Enable spoken replies again.', operation='reply-voice', payload=self.opt_in)
        self.assertEqual(len(speaker.frames), 4)
        self.lease = self.core.leases.create()
        self.token = self.core.issue_credential(self.lease.guest_id)
        second, _ = await self.open()
        current = await self.turn(second, 'Hello, I am a new guest.')
        self.assertFalse(self.core.speech.inventory(current)['enabled'])
        self.assertEqual(first_lease.state, 'released')
        self.assertNotIn(marker, [turn.get('text') for turn in self.native.history])
        self.assertEqual(len(speaker.frames), 4)
        before = self.native.counter
        denied = await self.core.agent.turn(first_lease.guest_id, 'Say this after my access ended.')
        self.assertIn('no longer', denied[-1]['text'])
        self.assertEqual(self.native.counter, before)
        self.assertEqual(len(speaker.frames), 4)
        self.assertEqual({frame['cap'] for frame in speaker.frames}, {'say'})
        self.assertEqual(self.core.bus.uncertain, {})


if __name__ == '__main__':
    unittest.main()
