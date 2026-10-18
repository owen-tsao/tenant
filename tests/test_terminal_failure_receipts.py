"""Issued failure-text authority using fake native transport only."""
import asyncio
from contextlib import suppress
from dataclasses import replace
import json
import unittest

from agent.room_session import NativeTurnError, RoomSession, RoomSessionError
from brain.config import Config
from brain.core.conversation_results import TerminalFailure, TerminalFailureFrames
from brain.core.conversation_speech import ConversationSpeech, ReplyFrames
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.room_conversation import ConversationAgent, ConversationSettings
from brain.main import create_app
from brain.state import Room
from tests.test_native_terminal_events import ANCHOR, PRIVATE, THREAD, NativeSocket


class TerminalFailureReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1000
        self.socket = NativeSocket()

        async def connector(*_args, **_kwargs):
            return self.socket

        self.session = RoomSession(THREAD, connector=connector, request_timeout=.1)
        self.leases = Leases(Room('OFFLINE', 'Offline'), clock=lambda: self.now)
        self.log = EventLog(clock=lambda: self.now)
        settings = ConversationSettings(THREAD, (ANCHOR,), turn_timeout=2,
                                        cleanup_timeout=.05, poll_interval=.002,
                                        session_factory=lambda *_a, **_k: self.session)
        self.agent = ConversationAgent(self.leases, self.log, settings, private_values=(PRIVATE,))
        self.guest = self.leases.create()

    async def asyncTearDown(self):
        with suppress(RoomSessionError):
            await self.agent.close()
        await self.session.close()

    async def begin(self, *, guest=None):
        guest = guest or self.guest
        task = asyncio.create_task(self.agent.turn(guest.guest_id, 'An explicit offline request.'))
        self.addAsyncCleanup(self.cancel_task, task)
        turn_id = await asyncio.wait_for(self.socket.started.get(), .4)
        return task, turn_id

    @staticmethod
    async def cancel_task(task):
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def terminal_failure(self, status='interrupted'):
        task, turn_id = await self.begin()
        await self.socket.finish(turn_id, status, text='Do not publish this partial success.')
        frames = await asyncio.wait_for(task, .4)
        self.assertIsInstance(frames, TerminalFailureFrames)
        self.assertNotIsInstance(frames, ReplyFrames)
        self.assertFalse(hasattr(frames, 'completed_reply'))
        return frames

    async def test_actual_terminal_failure_has_exact_issued_receipt_and_no_private_wire_fields(self):
        for status in ('interrupted', 'failed', 'cancelled'):
            with self.subTest(status=status):
                frames = await self.terminal_failure(status)
                receipt = frames.terminal_failure
                self.assertIs(type(receipt), TerminalFailure)
                self.assertIs(receipt.lease, self.guest)
                self.assertEqual(receipt.guest_id, self.guest.guest_id)
                self.assertEqual(receipt.thread_id, THREAD)
                self.assertEqual(receipt.turn_id, 'offline-turn-' + str(self.socket.turn_number))
                self.assertEqual(receipt.generation, self.agent._generation)
                self.assertEqual(receipt.text, frames[-1]['text'])
                self.assertTrue(receipt.cleanup_confirmed)
                self.assertTrue(self.agent.allows_terminal_failure(receipt))
                self.assertFalse(self.agent.allows_reply(receipt))
                wire = json.dumps(frames)
                for private in (PRIVATE, THREAD, receipt.turn_id, self.guest.guest_id, 'partial success'):
                    self.assertNotIn(private, wire)
        self.assertEqual(len(self.socket.requests('turn/start')), 3)

    async def test_unconfirmed_cleanup_can_deliver_only_current_failure_and_never_replays(self):
        self.socket.complete_on_interrupt = False
        task, turn_id = await self.begin()
        await self.socket.emit('error', turnId=turn_id, error={'message': PRIVATE}, willRetry=False)
        frames = await asyncio.wait_for(task, .4)
        self.assertIsInstance(frames, TerminalFailureFrames)
        receipt = frames.terminal_failure
        self.assertFalse(receipt.cleanup_confirmed)
        self.assertTrue(self.agent._failed)
        self.assertTrue(self.agent.allows_terminal_failure(receipt))
        self.assertIn('Control remains blocked', receipt.text)
        later = await self.agent.turn(self.guest.guest_id, 'Another explicit request.')
        self.assertNotIsInstance(later, TerminalFailureFrames)
        self.assertFalse(hasattr(later, 'terminal_failure'))
        self.assertEqual(len(self.socket.requests('turn/start')), 1)
        self.assertEqual(len(self.socket.requests('turn/interrupt')), 1)

    async def test_exact_clone_and_modified_receipt_are_not_issued_authority(self):
        receipt = (await self.terminal_failure()).terminal_failure
        self.assertFalse(self.agent.allows_terminal_failure(replace(receipt)))
        for change in ({'guest_id': 'another-guest'}, {'generation': receipt.generation + 1},
                       {'thread_id': 'another-thread'}, {'turn_id': 'another-turn'},
                       {'text': 'Forged result.'}, {'lease': replace(self.guest)},
                       {'cleanup_confirmed': False}):
            with self.subTest(change=tuple(change)):
                self.assertFalse(self.agent.allows_terminal_failure(replace(receipt, **change)))
        self.assertFalse(self.agent.allows_terminal_failure(object()))

    async def test_scope_stop_and_exact_lease_replacement_revoke_feedback(self):
        receipt = (await self.terminal_failure()).terminal_failure
        self.guest.scopes = {'light'}
        self.assertFalse(self.agent.allows_terminal_failure(receipt))
        self.guest.scopes = {'computer'}
        self.assertTrue(self.agent.allows_terminal_failure(receipt))
        self.agent._stop.set()
        self.assertFalse(self.agent.allows_terminal_failure(receipt))
        self.agent._stop.clear()
        self.leases.leases[self.guest.guest_id] = replace(self.guest)
        self.assertFalse(self.agent.allows_terminal_failure(receipt))

    async def test_expiry_ends_feedback_without_renewing_lease(self):
        receipt = (await self.terminal_failure()).terminal_failure
        expiry = self.guest.expires_at
        self.now = expiry
        self.assertFalse(self.agent.allows_terminal_failure(receipt))
        self.assertEqual(self.guest.expires_at, expiry)
        self.agent.check_access()
        self.assertEqual(self.agent._terminal_failures, {})

    async def test_handoff_clears_old_issued_receipts_before_new_native_start(self):
        receipt = (await self.terminal_failure()).terminal_failure
        next_guest = self.leases.create()
        task, turn_id = await self.begin(guest=next_guest)
        self.assertEqual(self.agent._terminal_failures, {})
        self.assertFalse(self.agent.allows_terminal_failure(receipt))
        await self.socket.finish(turn_id, text='Fresh guest reply.')
        frames = await asyncio.wait_for(task, .4)
        self.assertIsInstance(frames, ReplyFrames)
        self.assertFalse(hasattr(frames, 'terminal_failure'))

    async def test_revoke_during_failure_mints_no_receipt(self):
        task, turn_id = await self.begin()
        self.leases.revoke(self.guest.guest_id)
        self.agent.access_ended(self.guest.guest_id)
        await self.socket.finish(turn_id, 'interrupted')
        frames = await asyncio.wait_for(task, .4)
        self.assertNotIsInstance(frames, TerminalFailureFrames)
        self.assertIn('no longer', frames[-1]['text'])
        self.assertEqual(self.agent._terminal_failures, {})

    async def test_browser_cancellation_and_unknown_native_start_do_not_mint_receipts(self):
        task, _turn_id = await self.begin()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.agent._terminal_failures, {})
        self.socket.start_status = 'unrecognized-native-status'
        later = await self.agent.turn(self.guest.guest_id, 'A distinct explicit request.')
        self.assertNotIsInstance(later, TerminalFailureFrames)
        self.assertEqual(self.agent._terminal_failures, {})
        self.assertEqual(len(self.socket.requests('turn/start')), 2)

    async def test_error_before_an_actual_start_cannot_mint_a_receipt(self):
        async def unsupported_failure(*_args, **_kwargs):
            raise NativeTurnError('failed', turn_id='not-an-actual-start')

        self.agent._native_turn = unsupported_failure
        frames = await self.agent.turn(self.guest.guest_id, 'An explicit request.')
        self.assertNotIsInstance(frames, TerminalFailureFrames)
        self.assertEqual(self.agent._terminal_failures, {})
        self.assertEqual(len(self.socket.requests('turn/start')), 0)

    async def test_failure_frames_cannot_schedule_or_dispatch_automatic_speech(self):
        frames = await self.terminal_failure()
        speech = ConversationSpeech(None, None, self.leases, self.log,
                                    lambda _receipt: self.fail('Unexpected speech authority check'))
        self.assertIsNone(speech.schedule_reply(frames))
        await speech.speak_reply(frames)
        self.assertEqual(speech._tasks, {})
        self.assertEqual(speech._seen, set())
        await speech.close()

    async def test_real_core_projects_only_accepted_exact_failure_text_and_deduplicates(self):
        app = create_app(Config('offline-device-secret', 'offline-host-secret', 'OFFLINE',
                                'https://offline-tenant.test'), conversation=self.agent.settings)
        core = app.state.core
        self.agent, self.leases = core.agent, core.leases
        self.leases.clock = lambda: self.now
        self.guest = self.leases.create()
        frames = await self.terminal_failure()
        text = frames.terminal_failure.text
        transcript = self.leases.sessions[self.guest.guest_id].transcript
        self.assertEqual([row['role'] for row in transcript], ['guest'])
        core.published_reply(self.guest.guest_id, frames, 'A different text.')
        core.published_reply(self.guest.guest_id, list(frames), text)
        self.assertEqual([row['role'] for row in transcript], ['guest'])
        core.published_reply(self.guest.guest_id, frames, text)
        core.published_reply(self.guest.guest_id, frames, text)
        self.assertEqual([row['role'] for row in transcript], ['guest', 'room'])
        self.assertEqual(transcript[-1]['text'], text)
        self.assertNotIn(PRIVATE, json.dumps(transcript))

        next_guest = self.leases.create()
        task, turn_id = await self.begin(guest=next_guest)
        core.published_reply(self.guest.guest_id, frames, text)
        self.assertEqual(self.leases.sessions[self.guest.guest_id].transcript, [])
        await self.socket.finish(turn_id, 'interrupted')
        next_frames = await asyncio.wait_for(task, .4)
        next_text = next_frames.terminal_failure.text
        core.revoke(next_guest.guest_id)
        core.published_reply(next_guest.guest_id, next_frames, next_text)
        self.assertEqual(self.leases.sessions[next_guest.guest_id].transcript, [])

    async def test_issued_registry_is_bounded_and_ending_access_clears_it(self):
        first = None
        for _ in range(33):
            receipt = (await self.terminal_failure()).terminal_failure
            first = first or receipt
        self.assertEqual(len(self.agent._terminal_failures), 32)
        self.assertFalse(self.agent.allows_terminal_failure(first))
        self.assertTrue(self.agent.allows_terminal_failure(receipt))
        self.leases.revoke(self.guest.guest_id)
        self.agent.access_ended(self.guest.guest_id)
        self.assertEqual(self.agent._terminal_failures, {})
        self.assertFalse(self.agent.allows_terminal_failure(receipt))


if __name__ == '__main__':
    unittest.main()
