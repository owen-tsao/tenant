"""STOP and fresh explicit OFF recovery with real Bus and synthetic bridges.

Before the fix, the captured offline counterexample was: pending ON -> STOP
cancelled its loop -> Bus uncertainty blocked cleanup OFF. A late exact ON ACK
cleared Bus uncertainty, but repeated STOP retained the old UNKNOWN cleanup and
phone claim, with only one ON ever sent. These tests require safe recovery;
they never run audio, torch, native model or service commands.
"""
import asyncio
import unittest

from tests import test_room_programs as fixtures
from tests.test_room_program_sync import Clock


class StopRecoveryTests(unittest.IsolatedAsyncioTestCase):
    grant_for = fixtures.ProgramTests.grant_for
    register = fixtures.ProgramTests.register
    start = fixtures.ProgramTests.start

    async def asyncSetUp(self):
        await fixtures.ProgramTests.asyncSetUp(self)
        self.timeline = Clock()
        self.engine.clock, self.engine.sleep = self.timeline, self.timeline.sleep
        self.engine.action_timeout = .2
        self.phone.ack = False
        self.requests = []

        async def hold_monitor(_program):
            await asyncio.Event().wait()
        self.engine._monitor = hold_monitor

    async def asyncTearDown(self):
        for task in self.requests:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.requests, return_exceptions=True)
        self.phone.ack = True
        await fixtures.ProgramTests.asyncTearDown(self)

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0)

    def task(self, coroutine):
        result = asyncio.create_task(coroutine)
        self.requests.append(result)
        return result

    async def pending_on(self):
        program = await self.start(bpm=60)
        program.phase = 100
        self.task(self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'attach', 'program_id': program.id, 'light_device_id': 'phone'}))
        await self.until(lambda: any(abs(due - 101) < 1e-6 for due, _future in self.timeline.waiters))
        self.timeline.advance_to(101)
        frame = await asyncio.wait_for(self.phone.events.get(), 1)
        self.assertEqual(frame['args'], {'on': True})
        return program, frame

    def acknowledge(self, frame, *, device=None, on=None, req=None):
        self.bus.receive(device or self.phone.device,
                         {'type': 'ok', 'req': req or frame['req'],
                          'result': {'on': frame['args']['on'] if on is None else on}})

    async def stop(self, program, *, request_id='stop'):
        return await self.engine.dispatch(self.grant, 'program-stop',
            {'request_id': request_id, 'program_id': program.id})

    async def stopped_unknown(self):
        program, on = await self.pending_on()
        result = await asyncio.wait_for(self.stop(program), 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertEqual(program.cleanup['phone'], 'unknown')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertIn(on['req'], self.bus.uncertain)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])
        return program, on

    def fresh_off(self, *, grant=None, timeout=.5):
        grant = self.grant if grant is None else grant
        return self.task(self.engine.explicit_off(grant, 'phone',
            authorized=lambda: not grant.closed, timeout=timeout))

    async def next_off(self):
        frame = await asyncio.wait_for(self.phone.events.get(), 1)
        self.assertEqual(frame['args'], {'on': False})
        return frame

    async def test_graceful_stop_ends_future_on_but_waits_held_on_then_held_off_ack(self):
        program, on = await self.pending_on()
        stopping = self.task(self.stop(program))
        await self.until(lambda: not program.active)
        await asyncio.sleep(0)
        self.assertFalse(stopping.done())
        self.assertEqual(self.bus.uncertain, {}, 'STOP cancelled an already-sent ON instead of settling it.')
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])
        self.acknowledge(on)
        off = await self.next_off()
        self.assertFalse(stopping.done(), 'OFF dispatch was mistaken for confirmed cleanup.')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(off)
        result = await asyncio.wait_for(stopping, 1)
        self.assertTrue(result['ok'], result)
        self.assertEqual(program.cleanup['phone'], 'confirmed')
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked())
        self.timeline.advance_to(110)
        await asyncio.sleep(0)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_never_acknowledged_on_stays_unknown_without_cleanup_bypass_or_repeated_on(self):
        program, on = await self.stopped_unknown()
        repeated = await self.stop(program, request_id='another-stop')
        self.assertFalse(repeated['ok'], repeated)
        self.assertEqual(repeated['code'], 'UNKNOWN')
        self.assertIn(on['req'], self.bus.uncertain)
        self.assertTrue(self.locks['phone'].locked())
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])

    async def test_never_acknowledged_scheduled_off_is_not_resent_by_stop(self):
        program, on = await self.pending_on()
        self.acknowledge(on)
        await self.until(lambda: any(abs(due - 101.5) < 1e-6 for due, _future in self.timeline.waiters))
        self.timeline.advance_to(101.5)
        off = await self.next_off()
        result = await asyncio.wait_for(self.stop(program), 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertIn(off['req'], self.bus.uncertain)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_fresh_explicit_off_waits_late_on_ack_and_releases_only_matching_off_ack(self):
        program, on = await self.stopped_unknown()
        recovery = self.fresh_off()
        await asyncio.sleep(0)
        self.assertFalse(recovery.done())
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])
        self.acknowledge(on)
        off = await self.next_off()
        self.assertFalse(recovery.done())
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(off, req='wrong-request')
        other = self.register('other-phone')
        self.acknowledge(off, device=other.device)
        await asyncio.sleep(0)
        self.assertFalse(recovery.done(), 'An unrelated request or bridge cleared the phone claim.')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(off)
        result = await asyncio.wait_for(recovery, 1)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['on'], False)
        self.assertEqual(result['req'], off['req'])
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked())
        self.assertEqual(program.recovery['phone']['req'], off['req'])
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_fresh_explicit_off_cannot_bypass_a_never_resolved_prior_on(self):
        program, on = await self.stopped_unknown()
        result = await asyncio.wait_for(self.fresh_off(timeout=.04), 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertIn(on['req'], self.bus.uncertain)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(on)
        await asyncio.sleep(.01)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True],
                         'An expired explicit OFF request dispatched later after a late ACK.')

    async def test_wrong_off_result_keeps_claim_and_does_not_repeat(self):
        program, on = await self.stopped_unknown()
        self.acknowledge(on)
        recovery = self.fresh_off()
        off = await self.next_off()
        self.acknowledge(off, on=True)
        result = await asyncio.wait_for(recovery, 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertTrue(self.locks['phone'].locked())
        self.assertNotIn('phone', program.recovery)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_fresh_off_sent_without_ack_is_unknown_and_late_ack_does_not_retry(self):
        program, on = await self.stopped_unknown()
        self.acknowledge(on)
        recovery = self.fresh_off(timeout=.04)
        off = await self.next_off()
        result = await asyncio.wait_for(recovery, 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'UNKNOWN')
        self.assertIn(off['req'], self.bus.uncertain)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(off)
        await asyncio.sleep(.01)
        self.assertEqual(self.bus.uncertain, {})
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_cancellation_after_fresh_off_dispatch_keeps_uncertainty_and_claim(self):
        program, on = await self.stopped_unknown()
        self.acknowledge(on)
        recovery = self.fresh_off()
        off = await self.next_off()
        recovery.cancel()
        await asyncio.gather(recovery, return_exceptions=True)
        self.assertIn(off['req'], self.bus.uncertain)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.acknowledge(off)
        await asyncio.sleep(.01)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])
        self.assertEqual(self.engine.device_busy('phone'), program.id)

    async def test_connection_change_while_waiting_never_migrates_fresh_off_or_clears_claim(self):
        program, _on = await self.stopped_unknown()
        recovery = self.fresh_off()
        await asyncio.sleep(0)
        original = self.phone
        self.bus.disconnect(original.device)
        replacement = self.register('phone')
        result = await asyncio.wait_for(recovery, 1)
        self.assertFalse(result['ok'], result)
        self.assertIn(result['code'], ('OFFLINE', 'UNKNOWN'))
        self.assertEqual(original.frames[0]['args'], {'on': True})
        self.assertEqual(len(original.frames), 1)
        self.assertEqual(replacement.frames, [])
        self.assertEqual(self.engine.device_busy('phone'), program.id)

    async def test_revocation_while_fresh_off_is_bus_queued_sends_nothing(self):
        program, on = await self.stopped_unknown()
        self.acknowledge(on)
        await self.bus.locks['phone'].acquire()
        try:
            recovery = self.fresh_off()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.leases.revoke(self.lease.guest_id)
        finally:
            self.bus.locks['phone'].release()
        result = await asyncio.wait_for(recovery, 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])

    async def test_cancelled_fresh_off_wait_never_dispatches_after_a_late_ack(self):
        program, on = await self.stopped_unknown()
        recovery = self.fresh_off()
        await asyncio.sleep(0)
        recovery.cancel()
        await asyncio.gather(recovery, return_exceptions=True)
        self.acknowledge(on)
        self.timeline.advance_to(110)
        await asyncio.sleep(.01)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True])

    async def test_current_guest_can_off_inactive_previous_owner_claim_without_adopting_job(self):
        program, on = await self.stopped_unknown()
        old_owner = program.owner
        self.acknowledge(on)
        self.leases.revoke(self.lease.guest_id)
        self.generation += 1
        current = self.leases.create()
        self.leases.current(current.guest_id, activate=True)
        grant = self.grant_for(current)
        recovery = self.fresh_off(grant=grant)
        off = await self.next_off()
        self.acknowledge(off)
        result = await asyncio.wait_for(recovery, 1)
        self.assertTrue(result['ok'], result)
        self.assertIs(program.owner, old_owner)
        self.assertFalse(program.active)
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_unclaimed_phone_explicit_off_is_scoped_and_confirmed_without_a_program(self):
        self.lease.scopes = {'say'}
        denied = await self.engine.explicit_off(self.grant, 'phone', authorized=lambda: True, timeout=.5)
        self.assertFalse(denied['ok'], denied)
        self.assertEqual(denied['code'], 'PERMISSION')
        self.assertEqual(self.phone.frames, [])
        self.lease.scopes = {'light'}
        recovery = self.fresh_off()
        off = await self.next_off()
        self.assertFalse(recovery.done())
        self.acknowledge(off)
        result = await asyncio.wait_for(recovery, 1)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['on'], False)
        self.assertEqual(result['req'], off['req'])
        self.assertEqual(self.engine.programs, {})

    async def test_fresh_off_quiesces_only_the_claimed_phone_while_audio_remains_running(self):
        program, on = await self.pending_on()
        audio_frames = list(self.audio.frames)
        recovery = self.fresh_off()
        await asyncio.sleep(0)
        self.assertTrue(program.active)
        self.acknowledge(on)
        off = await self.next_off()
        self.acknowledge(off)
        result = await asyncio.wait_for(recovery, 1)
        self.assertTrue(result['ok'], result)
        self.assertTrue(program.active)
        self.assertEqual(self.audio.frames, audio_frames)
        self.assertIsNone(self.engine.device_busy('phone'))
        self.timeline.advance_to(110)
        await asyncio.sleep(0)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])

    async def test_fresh_phone_off_finishes_while_aggregate_mac_cleanup_is_still_queued(self):
        program, on = await self.pending_on()
        self.engine.audio_queue_timeout = 5
        audio_lock = self.bus.locks['laptop']
        await audio_lock.acquire()  # Another accepted Mac operation owns its queue.
        try:
            stopping = self.task(self.stop(program))
            await self.until(lambda: program.cleanup.get('phone') == 'unknown')
            self.assertIn(on['req'], self.bus.uncertain)
            self.assertFalse(program.cleanup_task.done())
            self.assertFalse(stopping.done())
            self.assertNotIn('beat.stop', [frame['cap'] for frame in self.audio.frames])

            recovery = self.fresh_off(timeout=.5)
            await asyncio.sleep(0)
            self.acknowledge(on)
            off = await self.next_off()
            self.assertFalse(program.cleanup_task.done(), 'Phone recovery waited for aggregate Mac cleanup.')
            self.acknowledge(off)
            result = await asyncio.wait_for(recovery, 1)
            self.assertTrue(result['ok'], result)
            self.assertIsNone(self.engine.device_busy('phone'))
            self.assertFalse(self.locks['phone'].locked())
            self.assertFalse(program.cleanup_task.done())
            self.assertFalse(stopping.done())
            self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])
        finally:
            audio_lock.release()
        result = await asyncio.wait_for(stopping, 1)
        self.assertTrue(result['ok'], result)
        await asyncio.sleep(0)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False],
                         'Late aggregate cleanup sent another phone OFF after fresh recovery.')
        self.assertIsNone(self.engine.device_busy('phone'))


if __name__ == '__main__':
    unittest.main()
