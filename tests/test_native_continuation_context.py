"""Private continuation guidance delivered over a fake native transport.

These tests verify context construction, delivery and privacy. No model executes
the guidance, so they do not establish model compliance or real playback state.
No deployed service, desktop app, device or audio output is used.
"""
import asyncio
from contextlib import suppress
import json
from types import SimpleNamespace
import unittest

from agent.room_session import MAX_APPLICATION_CONTEXT, RoomSession, RoomSessionError
from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.registry import Registry
from brain.core.room_conversation import ConversationAgent, ConversationSettings
from brain.state import Room
import test_native_terminal_events as native_fixture


class NativeContinuationContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socket = native_fixture.NativeSocket()

        async def connector(*_args, **_kwargs):
            return self.socket

        self.session = RoomSession(native_fixture.THREAD, connector=connector, request_timeout=.2)
        room = Room('OFFLINE', 'Offline continuation room')
        self.registry = Registry(room)
        self.bus = Bus(self.registry)
        self.leases = Leases(room, clock=lambda: 1000)
        self.log = EventLog(clock=lambda: 1000)
        settings = ConversationSettings(native_fixture.THREAD, (native_fixture.ANCHOR,),
                                        turn_timeout=2, cleanup_timeout=.2, poll_interval=.002,
                                        session_factory=lambda *_a, **_k: self.session)
        self.private = 'offline-configured-private-value'
        self.agent = ConversationAgent(self.leases, self.log, settings,
                                       private_values=(self.private,), registry=self.registry, bus=self.bus)
        self.guest = self.leases.create()

    async def asyncTearDown(self):
        with suppress(RoomSessionError):
            await self.agent.close()
        await self.session.close()

    def enable_all_context_branches(self):
        # Only the context producers are enabled: no program, speech or photo
        # execution machinery is installed or invoked by this fixture.
        tools = self.agent.device_tools
        tools.programs = object()
        tools.reply_voice = SimpleNamespace(context=lambda _grant: {
            'enabled': True, 'selected_device_id': 'speaker-' + 'x' * 120,
            'offer_speaker_choice': False})
        tools.photos = SimpleNamespace(enabled=True)

    async def begin(self, text, *, guest=None):
        guest = guest or self.guest
        task = asyncio.create_task(self.agent.turn(guest.guest_id, text))
        self.addAsyncCleanup(self.cancel_task, task)
        turn_id = await asyncio.wait_for(self.socket.started.get(), .8)
        grant = next(iter(self.agent.device_tools._grants.values()))
        params = self.socket.requests('turn/start')[-1]['params']
        return task, turn_id, grant, params

    @staticmethod
    async def cancel_task(task):
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def finish(self, task, turn_id, text='The phone is off; playback is unconfirmed.'):
        await self.socket.finish(turn_id, text=text)
        return await asyncio.wait_for(task, .8)

    def context(self, params):
        context = params['additionalContext']
        self.assertEqual(set(context), {'tenant_devices'})
        self.assertEqual(context['tenant_devices']['kind'], 'application')
        return context['tenant_devices']['value']

    async def test_exact_guest_input_and_continuation_contract_reach_only_private_application_context(self):
        self.enable_all_context_branches()
        exact = '  Turn the Phone light OFF now, but keep CYANIDE playing unchanged.\n  '
        task, turn_id, grant, params = await self.begin(exact)
        context = self.context(params)
        self.assertEqual(params['input'], [{'type': 'text', 'text': exact}])
        self.assertNotIn('developerInstructions', params)
        self.assertNotIn('dynamicTools', params)
        self.assertNotIn('Audio continues through conversation.', context)
        # The contract must separate a light receipt from fresh music evidence.
        for required in ('program-status', 'request_id', 'program_id', 'ok:true',
                         'result.state=running', 'result.source=selected_recording',
                         'result.song_clock.state=ready', 'result.song_clock.playhead_advancing=true',
                         'exact current program/song identity'):
            self.assertIn(required, context)
        self.assertRegex(context.lower(), r'after.{0,80}(?:operation|off|detach)')
        self.assertRegex(context.lower(), r'(?:new|fresh).{0,30}request_id')
        self.assertRegex(context.lower(), r'(?:same|owned).{0,40}program')
        self.assertIn('unconfirmed', context.lower())
        self.assertIn('pending', context.lower())
        self.assertIn('stopped', context.lower())
        self.assertIn('stale', context.lower())
        self.assertIn('latest status showed it playing', context)
        self.assertIn('not a guarantee it continues', context)
        self.assertIn('never authority to resume/restart', context)
        self.assertIn('override any general expectation of continued playback', context)
        self.assertIn('Report observed program/player status and cleanup separately', context)
        self.assertIn('a stopped program alone does not confirm audio stopped when audio cleanup is unconfirmed', context)
        self.assertNotIn(grant.token, context)
        frames = await self.finish(task, turn_id)
        self.assertNotIn('program-status', str(frames))
        self.assertEqual(len(self.socket.requests('turn/start')), 1)

    async def test_same_guest_followup_receives_only_new_turn_helper_prefix(self):
        self.enable_all_context_branches()
        first, turn_one, grant_one, _params_one = await self.begin('First explicit request.')
        await self.finish(first, turn_one)
        second, turn_two, grant_two, params_two = await self.begin('A new explicit follow-up.')
        context = self.context(params_two)
        self.assertNotEqual(grant_one.path, grant_two.path)
        self.assertIn(str(grant_two.path), context)
        self.assertNotIn(str(grant_one.path), context)
        self.assertNotIn(grant_one.token, context)
        self.assertFalse(grant_one.path.exists())
        self.assertEqual(len(self.socket.requests('thread/revert')), 0,
                         'Same-guest conversation retains its history while turn authority rotates')
        await self.finish(second, turn_two)
        self.assertEqual(len(self.socket.requests('turn/start')), 2)

    async def test_current_helper_prefix_is_verbatim_and_rotates_without_previous_guest_context(self):
        self.enable_all_context_branches()
        first, turn_one, grant_one, params_one = await self.begin('First guest private request.')
        prefix_one = next(line for line in self.context(params_one).splitlines()
                          if line.startswith('Helper command prefix: '))
        self.assertIn(str(grant_one.path), prefix_one)
        await self.finish(first, turn_one)
        self.assertTrue(grant_one.closed)
        self.assertFalse(grant_one.path.exists())
        other = self.leases.create()
        second, turn_two, grant_two, params_two = await self.begin('Fresh guest request.', guest=other)
        context_two = self.context(params_two)
        prefix_two = next(line for line in context_two.splitlines()
                          if line.startswith('Helper command prefix: '))
        self.assertIn(str(grant_two.path), prefix_two)
        self.assertNotEqual(prefix_one, prefix_two)
        self.assertNotIn(str(grant_one.path), context_two)
        self.assertNotIn(grant_one.token, context_two)
        self.assertRegex(context_two.lower(), r'(?:copy|use).{0,100}verbatim')
        self.assertRegex(context_two.lower(), r'(?:current|this).{0,20}turn')
        for forbidden in ('reconstruct', 'glob', 'guess'):
            self.assertIn(forbidden, context_two.lower())
        self.assertEqual([row.get('text') for row in self.socket.history], [None, 'Fresh guest request.'])
        self.assertEqual(self.leases.sessions[self.guest.guest_id].transcript, [])
        await self.finish(second, turn_two)

    async def test_echoed_current_private_grant_and_context_path_are_redacted_from_reply_and_logs(self):
        self.enable_all_context_branches()
        task, turn_id, grant, params = await self.begin('Please explain the result.')
        self.assertIn(str(grant.path), self.context(params))
        frames = await self.finish(task, turn_id,
            f'Accidental private echo: {grant.token} {grant.path} {self.private}')
        public = json.dumps({'reply': frames, 'log': self.log.rows,
                             'audit': self.log.audit_rows,
                             'transcript': self.leases.sessions[self.guest.guest_id].transcript})
        for secret in (grant.token, str(grant.path), str(grant.path.parent), self.private):
            self.assertNotIn(secret, public)
        self.assertIn('[private turn grant]', str(frames))
        self.assertIn('[private helper]', str(frames))
        self.assertEqual(self.agent.device_tools._grants, {})

    async def test_full_program_voice_photo_context_fits_bounded_native_transport(self):
        self.enable_all_context_branches()
        task, turn_id, _grant, params = await self.begin('Only a text explanation, please.')
        context = self.context(params)
        for branch in ('Room programs:', 'Reply voice context:', 'Photos:'):
            self.assertIn(branch, context)
        self.assertLessEqual(len(context), MAX_APPLICATION_CONTEXT)
        self.assertGreater(len(context), 4000, 'Exercise the previously insufficient context budget')
        await self.finish(task, turn_id)
        self.assertEqual(len(self.socket.requests('turn/start')), 1)


class NativeApplicationContextBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def session(self):
        socket = native_fixture.NativeSocket()

        async def connector(*_args, **_kwargs):
            return socket

        session = RoomSession(native_fixture.THREAD, connector=connector, request_timeout=.2)
        await session.connect()
        self.addAsyncCleanup(session.close)
        return session, socket

    async def test_budget_accepts_previous_limit_and_current_boundary_exactly_once(self):
        for size in (4001, 6000, 6001, MAX_APPLICATION_CONTEXT):
            with self.subTest(size=size):
                session, socket = await self.session()
                context = 'x' * size
                await session.start_turn('Exact unchanged input.', application_context=context)
                requests = socket.requests('turn/start')
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0]['params']['input'],
                                 [{'type': 'text', 'text': 'Exact unchanged input.'}])
                self.assertEqual(requests[0]['params']['additionalContext']['tenant_devices']['value'], context)

    async def test_oversize_or_invalid_context_never_submits_and_does_not_poison_next_explicit_request(self):
        session, socket = await self.session()
        for invalid in ('x' * (MAX_APPLICATION_CONTEXT + 1), '', 6000, {'value': 'text'}):
            with self.subTest(kind=type(invalid).__name__, size=len(invalid) if isinstance(invalid, str) else None):
                with self.assertRaises(ValueError):
                    await session.start_turn('Do not submit.', application_context=invalid)
        self.assertEqual(socket.requests('turn/start'), [])
        self.assertIsNone(session.active_turn_id)
        self.assertEqual(session._pending, {})
        await session.start_turn('A fresh explicit request.', application_context='Valid context.')
        self.assertEqual(len(socket.requests('turn/start')), 1)
        self.assertEqual(socket.requests('turn/start')[0]['params']['input'][0]['text'], 'A fresh explicit request.')


if __name__ == '__main__':
    unittest.main()
