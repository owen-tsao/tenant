"""First-cycle attachment and coarse phase checks; no devices, audio or models.

The raw acknowledgment sample is a live counterexample reported by root. The
controlled-clock tests establish backend dispatch/receipt behavior only; they
cannot establish optical/acoustic synchronization or physical flashlight state.
"""
import asyncio
import math
import unittest

from tests import test_room_programs as fixtures


OBSERVED_ACK_MS = (57, 165, 197, 56, 141, 46, 68, 140, 51, 65)


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waiters = []

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        if delay <= 0:
            await asyncio.sleep(0)
            return
        future = asyncio.get_running_loop().create_future()
        item = (self.now + delay, future)
        self.waiters.append(item)
        try:
            await future
        finally:
            self.waiters.remove(item)

    def advance_to(self, value):
        if value < self.now:
            raise ValueError('Synthetic time cannot move backward')
        self.now = value
        for due, future in tuple(self.waiters):
            if due <= self.now + 1e-9 and not future.done():
                future.set_result(None)


class CounterexampleTests(unittest.TestCase):
    def test_measured_197ms_ack_disproves_old_90bpm_quarter_period_deadline(self):
        old_window_ms = 60 / 90 / 4 * 1000
        self.assertEqual(len(OBSERVED_ACK_MS), 10)
        self.assertAlmostEqual(old_window_ms, 166.66666666666666)
        self.assertEqual([sample for sample in OBSERVED_ACK_MS if sample > old_window_ms], [197])
        self.assertLess(max(OBSERVED_ACK_MS), 60 / 60 / 2 * 1000)


class FirstCycleSyncTests(unittest.IsolatedAsyncioTestCase):
    grant_for = fixtures.ProgramTests.grant_for
    register = fixtures.ProgramTests.register
    start = fixtures.ProgramTests.start

    async def asyncSetUp(self):
        await fixtures.ProgramTests.asyncSetUp(self)
        self.timeline = Clock()
        self.engine.clock = self.timeline
        self.engine.sleep = self.timeline.sleep
        self.engine.action_timeout = 1
        self.requests = []
        self.phone.ack = False

        async def hold_monitor(_program):
            await asyncio.Event().wait()
        self.engine._monitor = hold_monitor  # Monitor behavior has separate tests.

    async def asyncTearDown(self):
        for task in self.requests:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.requests, return_exceptions=True)
        self.phone.ack = True  # Only synthetic cleanup commands can auto-ACK.
        await fixtures.ProgramTests.asyncTearDown(self)

    async def until(self, predicate):
        async with asyncio.timeout(.3):
            while not predicate():
                await asyncio.sleep(0)

    async def begin_attach(self, *, native_deadline=None, bpm=60, **changes):
        program = await self.start(bpm=bpm)
        program.phase = 100.0
        self.timeline.advance_to(100.37)
        if native_deadline is not None:
            self.grant.deadline = native_deadline
        cycle = 2 * changes.get('light_beats_per_state', .5) * (60 / bpm)
        first_on = program.phase + (math.floor((self.timeline() - program.phase) / cycle) + 1) * cycle
        task = asyncio.create_task(self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'attach', 'program_id': program.id, 'light_device_id': 'phone', **changes}))
        self.requests.append(task)
        await self.until(lambda: self.engine.device_busy('phone') == program.id)
        await self.until(lambda: any(abs(due - first_on) < 1e-6 for due, _future in self.timeline.waiters))
        return program, task

    async def status(self, program):
        response = await asyncio.wait_for(self.engine.dispatch(self.grant, 'program-status',
            {'request_id': 'status', 'program_id': program.id}), .2)
        self.assertTrue(response['ok'], response)
        return response['result']

    async def next_edge(self, on, at):
        self.timeline.advance_to(at)
        frame = await asyncio.wait_for(self.phone.events.get(), .3)
        self.assertEqual(frame['args'], {'on': on})
        return frame

    def acknowledge(self, frame):
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'],
                                           'result': {'on': frame['args']['on']}})

    def assert_first_cycle(self, status, *, state, on_ack, off_ack):
        participant = status['participants']['phone']
        self.assertEqual(participant['participant_state'], state)
        self.assertEqual(participant['first_cycle'],
                         {'on_ack': on_ack, 'off_ack': off_ack, 'physical_verified': False})
        self.assertFalse(status['physical_sync_measured'])

    def assert_cadence(self, status, *, beats, duration):
        participant = status['participants']['phone']
        self.assertEqual(participant['light_beats_per_state'], beats)
        self.assertEqual(participant['on_duration_ms'], duration * 1000)
        self.assertEqual(participant['off_duration_ms'], duration * 1000)

    async def confirm_cycle(self, program, attach, *, on_at, off_at):
        before = len(program.timings)
        on = await self.next_edge(True, on_at)
        self.assertFalse(attach.done())
        self.acknowledge(on)
        await self.until(lambda: len(program.timings) > before)
        self.assertFalse(attach.done())
        self.assert_first_cycle(await self.status(program), state='pending', on_ack=True, off_ack=False)
        off = await self.next_edge(False, off_at)
        self.assertFalse(attach.done())
        self.acknowledge(off)
        result = await asyncio.wait_for(attach, .3)
        self.assertTrue(result['ok'], result)
        self.assert_first_cycle(result['result'], state='following', on_ack=True, off_ack=True)
        return result

    async def test_attach_stays_pending_through_manual_on_then_off_ack_and_status_is_readable(self):
        program, attach = await self.begin_attach()
        pending = await self.status(program)
        self.assertFalse(attach.done(), 'Attachment succeeded before any first-cycle receipt.')
        self.assert_first_cycle(pending, state='pending', on_ack=False, off_ack=False)
        self.assertEqual(pending['light_device_ids'], [])
        self.assertEqual(self.phone.frames, [], 'Late join sent an immediate unphased ON.')

        on = await self.next_edge(True, 101.0)
        self.assertFalse(attach.done())
        self.assert_first_cycle(await self.status(program), state='pending', on_ack=False, off_ack=False)
        self.acknowledge(on)
        await self.until(lambda: len(program.timings) == 1)
        self.assertFalse(attach.done(), 'ON acknowledgment alone claimed a completed first cycle.')
        self.assert_first_cycle(await self.status(program), state='pending', on_ack=True, off_ack=False)

        off = await self.next_edge(False, 101.5)
        self.assertFalse(attach.done(), 'OFF dispatch was mistaken for OFF acknowledgment.')
        self.assert_first_cycle(await self.status(program), state='pending', on_ack=True, off_ack=False)
        self.acknowledge(off)
        result = await asyncio.wait_for(attach, .3)
        self.assertTrue(result['ok'], result)
        self.assert_first_cycle(result['result'], state='following', on_ack=True, off_ack=True)
        self.assertEqual(result['result']['light_device_ids'], ['phone'])
        targets = [row['target_monotonic_ms'] for row in program.timings[:2]]
        self.assertEqual(targets, [101000.0, 101500.0])

    async def test_197ms_ack_fits_baseline_500ms_edges_without_claiming_physical_sync(self):
        program, attach = await self.begin_attach()
        edges = ((True, 101.0), (False, 101.5), (True, 102.0), (False, 102.5))
        for index, (on, due) in enumerate(edges, 1):
            frame = await self.next_edge(on, due)
            self.assertGreater(frame['deadline_ms'], 197)
            self.timeline.advance_to(due + .197)
            self.acknowledge(frame)
            await self.until(lambda: len(program.timings) >= index)
        result = await asyncio.wait_for(attach, .3)
        self.assertTrue(result['ok'], result)
        self.assert_first_cycle(result['result'], state='following', on_ack=True, off_ack=True)
        self.assertEqual([row['ack_code'] for row in program.timings[:4]], ['OK'] * 4)
        self.assertEqual([row['target_monotonic_ms'] for row in program.timings[:4]],
                         [101000.0, 101500.0, 102000.0, 102500.0])
        for row in program.timings[:4]:
            self.assertAlmostEqual(row['ack_monotonic_ms'] - row['dispatch_monotonic_ms'], 197, delta=.001)

    async def test_unknown_first_on_never_reports_attach_success_or_replays_on(self):
        program, attach = await self.begin_attach()
        on = await self.next_edge(True, 101.0)
        self.phone.ack = True  # Permit any separate owned OFF cleanup, never another ON.
        self.bus.receive(self.phone.device, {'type': 'err', 'req': on['req'], 'code': 'UNKNOWN',
                                           'message': 'Synthetic uncertain first edge; do not replay.'})
        result = await asyncio.wait_for(attach, .3)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertEqual(result['unknown_device_ids'], ['phone'])
        await self.until(lambda: program.cleanup_task is not None)
        await asyncio.wait_for(program.cleanup_task, .3)
        status = await self.status(program)
        self.assert_first_cycle(status, state='unknown', on_ack=False, off_ack=False)
        self.assertEqual(status['light_device_ids'], [])
        self.assertEqual(sum(frame['args']['on'] is True for frame in self.phone.frames), 1)
        repeat = await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'another-attach', 'program_id': program.id, 'light_device_id': 'phone'})
        self.assertFalse(repeat['ok'], repeat)
        self.assertEqual(sum(frame['args']['on'] is True for frame in self.phone.frames), 1)

    async def test_native_wait_budget_ending_reports_pending_without_claiming_following(self):
        # The native turn has 130ms remaining; the next phased ON is 630ms away.
        # This uses its supplied deadline, not a new product attachment timeout.
        program, attach = await self.begin_attach(native_deadline=100.5)
        result = await asyncio.wait_for(attach, .3)
        self.assertTrue(result['ok'], result)  # Installed, not yet cycle-complete.
        self.assertFalse(result['complete'])
        self.assertEqual(result['code'], 'PENDING')
        self.assertIn('pending', result['message'].lower())
        self.assert_first_cycle(result['result'], state='pending', on_ack=False, off_ack=False)
        self.assertEqual(result['result']['light_device_ids'], [])
        self.assertEqual(self.phone.frames, [])
        self.assertTrue(program.active)
        self.assert_first_cycle(await self.status(program), state='pending', on_ack=False, off_ack=False)

    async def test_30bpm_default_is_one_second_each_state_on_original_phase(self):
        program, attach = await self.begin_attach(bpm=30)
        self.assertEqual(self.phone.frames, [])
        self.assert_cadence(await self.status(program), beats=.5, duration=1)
        result = await self.confirm_cycle(program, attach, on_at=102, off_at=103)
        self.assert_cadence(result['result'], beats=.5, duration=1)
        next_on = await self.next_edge(True, 104)
        self.acknowledge(next_on)
        await self.until(lambda: len(program.timings) == 3)
        self.assertEqual([row['target_monotonic_ms'] for row in program.timings],
                         [102000.0, 103000.0, 104000.0])

    async def test_30bpm_one_beat_per_state_is_two_seconds_each_with_ack_gating(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=1)
        pending = await self.status(program)
        self.assertEqual(self.phone.frames, [], 'Explicit cadence sent an immediate late-join ON.')
        self.assertEqual(pending['light_device_ids'], [])
        self.assert_cadence(pending, beats=1, duration=2)
        result = await self.confirm_cycle(program, attach, on_at=104, off_at=106)
        self.assert_cadence(result['result'], beats=1, duration=2)
        before = list(self.phone.frames)
        retained = await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'retain-cadence', 'program_id': program.id, 'light_device_id': 'phone'})
        self.assertTrue(retained['ok'], retained)
        self.assert_cadence(retained['result'], beats=1, duration=2)
        self.assertEqual(self.phone.frames, before, 'Omitting the cadence reset an existing participant.')
        next_on = await self.next_edge(True, 108)
        self.acknowledge(next_on)
        await self.until(lambda: len(program.timings) == 3)
        self.assertEqual([row['target_monotonic_ms'] for row in program.timings],
                         [104000.0, 106000.0, 108000.0])

    async def test_positive_fractional_cadence_is_supported_without_rounding_to_default(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=.25)
        result = await self.confirm_cycle(program, attach, on_at=101, off_at=101.5)
        self.assert_cadence(result['result'], beats=.25, duration=.5)

    async def test_positive_multiple_beat_cadence_is_supported_without_a_one_beat_cap(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=2)
        result = await self.confirm_cycle(program, attach, on_at=108, off_at=112)
        self.assert_cadence(result['result'], beats=2, duration=4)

    async def test_cadence_change_waits_for_detach_off_then_reattaches_without_audio_restart(self):
        program, attach = await self.begin_attach(bpm=30)
        await self.confirm_cycle(program, attach, on_at=102, off_at=103)
        phase, run_id = program.phase, program.run_id
        audio_frames = list(self.audio.frames)
        change = asyncio.create_task(self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'change-cadence', 'program_id': program.id,
             'light_device_id': 'phone', 'light_beats_per_state': 1}))
        self.requests.append(change)
        detach_off = await asyncio.wait_for(self.phone.events.get(), .3)
        self.assertEqual(detach_off['args'], {'on': False})
        self.assertFalse(change.done(), 'Cadence changed before detach OFF was acknowledged.')
        self.assertEqual((await self.status(program))['light_device_ids'], [])
        self.acknowledge(detach_off)
        await self.until(lambda: program.participants['phone']['participant_state'] == 'pending'
                         and program.participants['phone']['light_beats_per_state'] == 1)
        await self.until(lambda: any(abs(due - 104) < 1e-6 for due, _future in self.timeline.waiters))
        result = await self.confirm_cycle(program, change, on_at=104, off_at=106)
        self.assert_cadence(result['result'], beats=1, duration=2)
        self.assertEqual(program.phase, phase)
        self.assertEqual(program.run_id, run_id)
        self.assertEqual(self.audio.frames, audio_frames)

    async def test_invalid_cadence_and_cadence_without_phone_are_rejected_before_effects(self):
        program = await self.start(bpm=30)
        audio_frames = list(self.audio.frames)
        for value in (0, -1, math.nan, math.inf, -math.inf, True, False, None, '1', [], {},
                      1e308, 10 ** 1000, 5e-324):
            with self.subTest(value=value):
                result = await self.engine.dispatch(self.grant, 'program-update',
                    {'request_id': 'invalid-cadence', 'program_id': program.id,
                     'light_device_id': 'phone', 'light_beats_per_state': value})
                self.assertFalse(result['ok'], result)
                self.assertEqual(result['code'], 'INVALID')
                self.assertIsNone(self.engine.device_busy('phone'))
                self.assertEqual(self.phone.frames, [])
                self.assertEqual(self.audio.frames, audio_frames)
        result = await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'cadence-without-phone', 'program_id': program.id, 'light_beats_per_state': 1})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'INVALID')
        self.assertEqual(self.audio.frames, audio_frames)
        self.assertEqual(self.phone.frames, [])

    async def test_explicit_cadence_does_not_bypass_light_scope(self):
        program = await self.start(bpm=30)
        audio_frames = list(self.audio.frames)
        self.lease.scopes = {'beat.prepare', 'beat.start', 'beat.stop', 'beat.status'}
        result = await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'scope-denied', 'program_id': program.id,
             'light_device_id': 'phone', 'light_beats_per_state': 1})
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertEqual(self.phone.frames, [])
        self.assertEqual(self.audio.frames, audio_frames)

    async def test_revocation_while_explicit_cadence_is_pending_prevents_first_on(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=1)
        self.phone.ack = True  # Separate owned OFF cleanup is allowed.
        self.leases.revoke(self.lease.guest_id)
        self.engine.access_ended(self.lease.guest_id)
        result = await asyncio.wait_for(attach, .3)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual(result['result']['light_device_ids'], [])
        self.assertNotEqual(result['result']['participants']['phone']['participant_state'], 'following')
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertTrue(all(frame['args']['on'] is False for frame in self.phone.frames))

    async def test_explicit_cadence_unknown_first_on_is_not_completed_or_replayed(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=1)
        on = await self.next_edge(True, 104)
        self.phone.ack = True
        self.bus.receive(self.phone.device, {'type': 'err', 'req': on['req'], 'code': 'UNKNOWN',
                                           'message': 'Synthetic uncertain cadence edge; no replay.'})
        result = await asyncio.wait_for(attach, .3)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertEqual(result['unknown_device_ids'], ['phone'])
        self.assert_first_cycle(result['result'], state='unknown', on_ack=False, off_ack=False)
        self.assert_cadence(result['result'], beats=1, duration=2)
        await asyncio.wait_for(program.cleanup_task, .3)
        self.assertEqual(sum(frame['args']['on'] is True for frame in self.phone.frames), 1)

    async def test_explicit_cadence_outlasting_native_wait_remains_truthfully_pending(self):
        program, attach = await self.begin_attach(bpm=30, light_beats_per_state=1, native_deadline=100.5)
        result = await asyncio.wait_for(attach, .3)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['complete'])
        self.assertEqual(result['code'], 'PENDING')
        self.assertIn('pending', result['message'].lower())
        self.assert_first_cycle(result['result'], state='pending', on_ack=False, off_ack=False)
        self.assert_cadence(result['result'], beats=1, duration=2)
        self.assertEqual(result['result']['light_device_ids'], [])
        self.assertEqual(self.phone.frames, [])


if __name__ == '__main__':
    unittest.main()
