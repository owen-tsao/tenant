"""First-cycle attachment and coarse phase checks; no devices, audio or models.

The raw acknowledgment sample is a live counterexample reported by root. The
controlled-clock tests establish backend dispatch/receipt behavior only; they
cannot establish optical/acoustic synchronization or physical flashlight state.
"""
import asyncio
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

    async def begin_attach(self, *, native_deadline=None):
        program = await self.start(bpm=60)
        program.phase = 100.0
        self.timeline.advance_to(100.37)
        if native_deadline is not None:
            self.grant.deadline = native_deadline
        task = asyncio.create_task(self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'attach', 'program_id': program.id, 'light_device_id': 'phone'}))
        self.requests.append(task)
        await self.until(lambda: self.engine.device_busy('phone') == program.id)
        await self.until(lambda: any(abs(due - 101.0) < 1e-6 for due, _future in self.timeline.waiters))
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


if __name__ == '__main__':
    unittest.main()
