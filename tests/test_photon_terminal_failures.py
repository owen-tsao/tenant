"""Typed terminal failure over Photon: fake provider/native, real controller.

No model, provider service, device, public UI or running-room interaction.
"""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from agent.room_session import RoomSessionError
from brain.channels.photon import PhotonChannel, PhotonError, stamp
from brain.config import Config
from brain.core.conversation_results import TerminalFailure, TerminalFailureFrames
from brain.main import create_app
from test_photon import FakeClient, PID, PHONE, LINE, HUMAN, AGENT, SPACE
from test_room_conversation import NativeSession, settings_for, THREAD


class PhotonTerminalFailureTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.native = NativeSession()
        self.app = create_app(Config('synthetic-device', 'synthetic-host', 'TEST', 'https://tenant.test'),
                              conversation=settings_for(self.native))
        self.core = self.app.state.core
        self.core.leases.clock = lambda: self.now
        self.temp = tempfile.TemporaryDirectory()
        self.client = FakeClient(lambda: self.now)
        self.channel = PhotonChannel(self.core, self.client, Path(self.temp.name) / 'photon.sqlite3')
        self.channel._ready = True
        self.spoken = []
        self.core.speech = SimpleNamespace(schedule_reply=self.spoken.append)

    async def asyncTearDown(self):
        await self.channel.close()
        try:
            await self.core.agent.close()
        except RoomSessionError:
            # The deliberately unconfirmed-cleanup case must remain blocked;
            # close truthfully reports it and still closes its fake session.
            self.assertTrue(self.core.agent._cleanup_failure)
        self.temp.cleanup()

    def message(self, message_id='pho_msg_terminal', text='An explicit synthetic request'):
        def user(id, handle, kind):
            return {'id': id, 'handle': handle, 'kind': kind, 'projectId': PID, 'platform': 'imessage'}
        return {'id': message_id, 'projectId': PID, 'platform': 'imessage', 'status': 'received',
                'createdAt': stamp(self.now), 'sentBy': user(HUMAN, PHONE, 'human'),
                'receivedBy': user(AGENT, LINE, 'agent'),
                'space': {'id': SPACE, 'projectId': PID, 'platform': 'imessage', 'kind': 'direct',
                          'participantIds': [HUMAN, AGENT]},
                'content': {'type': 'text', 'format': 'plain', 'text': text}}

    async def enqueue(self, message=None):
        self.client.pages.append({'items': [message or self.message()]})
        await self.channel.poll_once()

    def outcome(self, message_id='pho_msg_terminal'):
        row = self.channel.store.db.execute('SELECT outcome FROM claims WHERE message_id=?', (message_id,)).fetchone()
        return row[0] if row else None

    async def begin_failure(self, *, cleanup_confirmed=True, partial=False):
        lease = (await self.channel.enroll(PHONE)).lease
        self.native.auto_finish = False
        await self.enqueue()
        task = asyncio.create_task(self.channel.process_one())
        async with asyncio.timeout(2):
            await self.native.started.wait()
        self.native.fail_reset = not cleanup_confirmed
        if partial:
            await self.native.events.put({'method': 'item/completed', 'params': {
                'threadId': THREAD, 'turnId': 'native-1',
                'item': {'type': 'agentMessage', 'phase': 'final', 'text': 'SYNTHETIC_PRIVATE_PARTIAL'}}})
        self.native.active_turn_id = None
        await self.native.events.put({'method': 'turn/completed', 'params': {
            'threadId': THREAD, 'turn': {'id': 'native-1', 'status': 'failed'}}})
        return lease, task

    async def test_terminal_failure_is_accepted_once_without_success_receipt_or_speech(self):
        lease, task = await self.begin_failure(partial=True)
        await task
        self.assertEqual(self.outcome(), 'ACCEPTED')
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn('could not complete', self.client.sent[0][2])
        self.assertNotIn('SYNTHETIC_PRIVATE_PARTIAL', self.client.sent[0][2])
        self.assertEqual(self.client.sent[0][3], 'tenant-reply-pho_msg_terminal')
        self.assertEqual(self.spoken, [])
        self.assertFalse(self.core.agent._failed)
        receipt = next(iter(self.core.agent._terminal_failures.values()))
        frames = TerminalFailureFrames(receipt)
        self.assertTrue(self.channel._can_terminal_failure(frames, lease))
        self.assertFalse(hasattr(frames, 'completed_reply'))
        self.assertFalse(self.channel._can_reply(frames, lease))
        audit = [r['audit'] for r in self.core.log.audit_rows
                 if r.get('audit', {}).get('photon_status') == 'ACCEPTED_NOT_DELIVERED']
        self.assertEqual(audit[-1]['reply_kind'], 'terminal_failure')
        public = self.core.leases.sessions[lease.guest_id].transcript
        room = [row for row in public if row['role'] == 'room']
        self.assertEqual(len(room), 1)
        self.assertEqual(room[0]['text'], self.client.sent[0][2])
        self.assertNotIn('SYNTHETIC_PRIVATE_PARTIAL', str(public))
        await self.enqueue()
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(len(self.client.sent), 1)

    async def test_cleanup_blocked_notice_reaches_current_guest_but_cannot_speak_or_act(self):
        lease, task = await self.begin_failure(cleanup_confirmed=False)
        await task
        self.assertTrue(self.core.agent._failed)
        self.assertEqual(self.outcome(), 'ACCEPTED')
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn('blocked', self.client.sent[0][2])
        self.assertIn('cleanup', self.client.sent[0][2])
        public = self.core.leases.sessions[lease.guest_id].transcript
        self.assertEqual([r['text'] for r in public if r['role'] == 'room'], [self.client.sent[0][2]])
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.native.counter, 1)
        # The typed feedback authority does not reopen the next action.
        self.native.auto_finish = True
        await self.core.agent.turn(lease.guest_id, 'A new explicit action while blocked')
        self.assertEqual(self.native.counter, 1)

    async def test_confirmed_cleanup_allows_only_a_distinct_next_explicit_request(self):
        _lease, task = await self.begin_failure()
        await task
        self.native.auto_finish = True
        await self.enqueue(self.message('pho_msg_distinct', 'A distinct explicit next request'))
        await self.channel.process_one()
        self.assertEqual(self.native.counter, 2)
        self.assertEqual([c[1] for c in self.native.calls if c[0] == 'start'],
                         ['An explicit synthetic request', 'A distinct explicit next request'])
        self.assertEqual(len(self.client.sent), 2)
        self.assertEqual(self.outcome('pho_msg_distinct'), 'ACCEPTED')
        self.assertEqual(len(self.spoken), 1)  # Only the successful second reply.
        accepted = [r['audit'] for r in self.core.log.audit_rows
                    if r.get('audit', {}).get('photon_status') == 'ACCEPTED_NOT_DELIVERED']
        self.assertEqual([r['reply_kind'] for r in accepted], ['terminal_failure', 'completed_reply'])

    async def deny_before_send(self, transition):
        original = self.channel.store.outcome
        def interrupted(message_id, outcome):
            original(message_id, outcome)
            if outcome != 'SENDING':
                return
            lease = self.core.leases.leases[next(iter(self.core.leases.leases))]
            if transition == 'revoke':
                self.core.revoke(lease.guest_id)
            elif transition == 'expiry':
                self.now = lease.expires_at
            elif transition == 'replacement':
                other = self.core.leases.create()
                self.core.agent._admit(other.guest_id)
            elif transition == 'reset':
                self.core.leases.reset()
        self.channel.store.outcome = interrupted
        _lease, task = await self.begin_failure()
        await task
        self.assertEqual(self.outcome(), 'PERMISSION')
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.native.counter, 1)

    async def test_revoke_after_serialization_before_send_denies_terminal_notice(self):
        await self.deny_before_send('revoke')

    async def test_expiry_after_serialization_before_send_denies_terminal_notice(self):
        await self.deny_before_send('expiry')

    async def test_new_controller_after_serialization_before_send_denies_terminal_notice(self):
        await self.deny_before_send('replacement')

    async def test_reset_after_serialization_before_send_denies_terminal_notice(self):
        await self.deny_before_send('reset')

    async def test_plain_lists_and_unissued_typed_failure_cannot_gain_delivery_authority(self):
        lease = (await self.channel.enroll(PHONE)).lease
        await self.core.agent.turn(lease.guest_id, 'Admit the synthetic guest')
        forged = TerminalFailure(lease.guest_id, self.core.agent._generation, THREAD, 'native-1',
                                 'An unissued failure notice', lease, True)
        for number, frames in enumerate((
                [{'type': 'assistant', 'text': 'An arbitrary error list'}], TerminalFailureFrames(forged))):
            async def give_frames(*_args): return frames
            self.core.agent.turn = give_frames
            mid = 'pho_msg_forged_' + str(number)
            await self.enqueue(self.message(mid))
            await self.channel.process_one()
            self.assertEqual(self.outcome(mid), 'PERMISSION')
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.native.counter, 1)

    async def test_mutated_terminal_frames_cannot_publish_or_send_arbitrary_extra_text(self):
        original = self.core.agent.turn
        async def mutated(*args):
            frames = await original(*args)
            if isinstance(frames, TerminalFailureFrames):
                frames.append({'type': 'assistant', 'text': 'SYNTHETIC_PRIVATE_ADDITION'})
            return frames
        self.core.agent.turn = mutated
        _lease, task = await self.begin_failure()
        await task
        self.assertEqual(self.outcome(), 'PERMISSION')
        self.assertEqual(self.client.sent, [])
        self.assertEqual(self.spoken, [])

    async def test_unknown_failure_notice_send_is_not_replayed_or_spoken(self):
        self.client.send_error = PhotonError('UNKNOWN')
        _lease, task = await self.begin_failure()
        await task
        self.assertEqual(self.outcome(), 'UNKNOWN')
        self.assertEqual(len(self.client.sent), 1)
        await self.enqueue()
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.spoken, [])
        self.assertFalse(any(r['role'] == 'room' for session in self.core.leases.sessions.values() for r in session.transcript))

    async def test_cancelled_failure_notice_send_is_not_replayed_or_spoken(self):
        self.client.send_wait = asyncio.Event()
        _lease, task = await self.begin_failure()
        async with asyncio.timeout(2):
            while not self.client.sent:
                await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.outcome(), 'UNKNOWN')
        await self.enqueue()
        self.assertTrue(self.channel.queue.empty())
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.native.counter, 1)
        self.assertEqual(self.spoken, [])


if __name__ == '__main__':
    unittest.main()
