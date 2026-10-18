"""Deterministic program ownership/cleanup races; synthetic bridges only."""
import asyncio
import threading
import unittest

from tests import test_room_programs as fixtures
from tests import test_beat_audio as audio_fixtures
from agent.beat_audio import BeatAudio, render_beat


class ProgramRaceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProgramTests.asyncSetUp
    asyncTearDown = fixtures.ProgramTests.asyncTearDown
    grant_for = fixtures.ProgramTests.grant_for
    register = fixtures.ProgramTests.register
    start = fixtures.ProgramTests.start
    update = fixtures.ProgramTests.update

    async def test_tempo_restart_retains_its_phone_lock_until_final_cleanup(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        await asyncio.wait_for(self.phone.events.get(), 1)
        original = self.audio.send_json
        restart_waiting, allow_restart = asyncio.Event(), asyncio.Event()
        ordinary_entered, allow_ordinary_finish = asyncio.Event(), asyncio.Event()

        async def delayed_start(frame):
            if frame['cap'] == 'beat.start':
                restart_waiting.set()
                await allow_restart.wait()
            await original(frame)

        async def ordinary_operation():
            async with self.locks['phone']:
                ordinary_entered.set()
                await allow_ordinary_finish.wait()

        self.audio.send_json = delayed_start
        update = asyncio.create_task(self.update(program, bpm=300))
        ordinary = None
        try:
            await asyncio.wait_for(restart_waiting.wait(), 1)
            ordinary = asyncio.create_task(ordinary_operation())
            await asyncio.sleep(0)
            self.assertFalse(ordinary_entered.is_set(), 'Tempo restart surrendered its owned logical phone lock.')
            allow_restart.set()
            result = await asyncio.wait_for(update, 1)
            self.assertTrue(result['ok'], result)
            self.assertFalse(ordinary_entered.is_set(), 'Restart stole an ordinary operation\'s held lock.')
            await self.engine.dispatch(self.grant, 'program-stop', {'request_id': 'stop', 'program_id': program.id})
            await asyncio.wait_for(ordinary_entered.wait(), 1)
            self.assertTrue(self.locks['phone'].locked())
            await self.engine.dispatch(self.grant, 'program-stop', {'request_id': 'stop-again', 'program_id': program.id})
            self.assertTrue(self.locks['phone'].locked(), 'Repeated program cleanup released another operation\'s lock.')
        finally:
            allow_restart.set()
            allow_ordinary_finish.set()
            await asyncio.gather(update, return_exceptions=True)
            if ordinary is not None:
                await asyncio.gather(ordinary, return_exceptions=True)

    async def test_detach_and_access_end_share_one_confirmed_phone_cleanup(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        await asyncio.wait_for(self.phone.events.get(), 1)
        original = self.engine._stop_output
        detach_waiting, allow_detach = asyncio.Event(), asyncio.Event()
        phone_cleanup_calls = 0

        async def delayed_phone_cleanup(*args):
            nonlocal phone_cleanup_calls
            if args[5] == 'phone':
                phone_cleanup_calls += 1
                if phone_cleanup_calls == 1:
                    detach_waiting.set()
                    await allow_detach.wait()
            return await original(*args)

        self.engine._stop_output = delayed_phone_cleanup
        baseline_off = sum(frame['args'].get('on') is False for frame in self.phone.frames)
        detach = asyncio.create_task(self.update(program, remove_light_device_id='phone'))
        try:
            await asyncio.wait_for(detach_waiting.wait(), 1)
            self.engine.access_ended(self.lease.guest_id)
            # Cleanup may coalesce behind the paused detach, so release it after
            # both work paths have had a chance to observe the same operation.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            allow_detach.set()
            result = await asyncio.wait_for(detach, 1)
            await asyncio.wait_for(program.cleanup_task, 1)
            self.assertEqual(program.cleanup['phone'], 'confirmed')
            self.assertEqual(program.state, 'stopped')
            self.assertIsNone(self.engine.device_busy('phone'))
            self.assertFalse(self.locks['phone'].locked())
            self.assertNotEqual(result.get('code'), 'UNKNOWN', result)
            self.assertNotIn('stays reserved', result.get('message', '').lower())
            self.assertNotIn('music continues', result.get('message', '').lower())
            final_off = sum(frame['args'].get('on') is False for frame in self.phone.frames)
            self.assertEqual(final_off - baseline_off, 1, 'Detach and access-end independently repeated OFF cleanup.')
        finally:
            allow_detach.set()
            await asyncio.gather(detach, return_exceptions=True)

    async def test_permission_loss_after_tempo_cleanup_releases_known_clean_phone(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        original = self.engine._cleanup

        async def revoke_after_cleanup(current):
            await original(current)
            if current.reason == 'tempo_change':
                self.leases.revoke(self.lease.guest_id)
                self.engine.access_ended(self.lease.guest_id)

        self.engine._cleanup = revoke_after_cleanup
        result = await self.update(program, bpm=300)
        self.assertEqual(result.get('code'), 'PERMISSION', result)
        self.assertFalse(program.active)
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked(), 'An aborted tempo restart stranded its known-clean phone lock.')
        self.assertEqual(program.cleanup['phone'], 'confirmed')
        self.assertEqual(sum(frame['cap'] == 'beat.start' for frame in self.audio.frames), 1)


class DriverPreparationRaceTests(unittest.TestCase):
    def test_rendering_another_job_cannot_block_owned_audio_stop(self):
        processes = []
        errors = []
        rendering, allow_render = threading.Event(), threading.Event()

        def popen(*_args, **_kwargs):
            process = audio_fixtures.Process()
            processes.append(process)
            return process

        audio = BeatAudio(popen=popen, wall_clock=lambda: 1000, watch=False)
        audio.dispatch('beat.prepare', {'program_id': 'playing', 'bpm': 120, 'expires_at_ms': 1000400})
        audio.dispatch('beat.start', {'program_id': 'playing'})

        def blocked_render(*args, **kwargs):
            rendering.set()
            if not allow_render.wait(1):
                raise AssertionError('Test failed to release its synthetic renderer.')
            return render_beat(*args, **kwargs)

        def prepare_second():
            try:
                audio.dispatch('beat.prepare', {'program_id': 'preparing', 'bpm': 120, 'expires_at_ms': 1000400})
            except BaseException as error:
                errors.append(error)

        audio.render = blocked_render
        preparing = threading.Thread(target=prepare_second)
        stopping = threading.Thread(target=lambda: audio.stop('playing'))
        try:
            preparing.start()
            self.assertTrue(rendering.wait(1))
            stopping.start()
            stopping.join(.2)
            self.assertFalse(stopping.is_alive(), "Another job's renderer blocked an already owned audio stop.")
            self.assertTrue(processes[0].terminated)
            self.assertEqual(len(processes), 1, 'Preparation must never launch audio.')
        finally:
            allow_render.set()
            preparing.join(1)
            if stopping.ident is not None:
                stopping.join(1)
            audio.close()
        self.assertFalse(preparing.is_alive())
        self.assertEqual(errors, [])


class FirstCycleMutationRaceTests(unittest.IsolatedAsyncioTestCase):
    """Pending attach has no mutation lock and cannot affect a replacement run."""
    from tests import test_room_program_sync as _sync
    asyncSetUp = _sync.FirstCycleSyncTests.asyncSetUp
    asyncTearDown = _sync.FirstCycleSyncTests.asyncTearDown
    grant_for = _sync.FirstCycleSyncTests.grant_for
    register = _sync.FirstCycleSyncTests.register
    start = _sync.FirstCycleSyncTests.start
    until = _sync.FirstCycleSyncTests.until
    begin_attach = _sync.FirstCycleSyncTests.begin_attach
    next_edge = _sync.FirstCycleSyncTests.next_edge
    acknowledge = _sync.FirstCycleSyncTests.acknowledge

    async def test_stop_settles_pending_attach_without_waiting_for_its_first_on(self):
        program, attach = await self.begin_attach()
        self.phone.ack = True  # Synthetic cleanup only, no first ON has been sent.
        stopped = await asyncio.wait_for(self.engine.dispatch(self.grant, 'program-stop',
            {'request_id': 'stop', 'program_id': program.id}), .3)
        original = await asyncio.wait_for(attach, .3)
        self.assertTrue(stopped['ok'], stopped)
        self.assertFalse(original['ok'], original)
        self.assertIn(original['code'], ('STOPPED', 'requested_stop'))
        self.assertFalse(program.active)
        self.timeline.advance_to(110)
        await asyncio.sleep(0)
        self.assertEqual(sum(frame['args'].get('on') is True for frame in self.phone.frames), 0)
        self.assertEqual(original['result']['light_device_ids'], [])

    async def test_detach_settles_original_attach_as_stopped_instead_of_vacuous_success(self):
        program, attach = await self.begin_attach()
        self.phone.ack = True
        detached = await asyncio.wait_for(self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'detach', 'program_id': program.id, 'remove_light_device_id': 'phone'}), .3)
        original = await asyncio.wait_for(attach, .3)
        self.assertTrue(detached['ok'], detached)
        self.assertFalse(original['ok'], original)
        self.assertEqual(original['code'], 'STOPPED')
        self.assertTrue(program.active, 'Detaching a pending phone must preserve its independent beat.')
        self.assertNotIn('phone', program.lights)
        self.assertEqual(original['result']['light_device_ids'], [])
        self.assertEqual(sum(frame['args'].get('on') is True for frame in self.phone.frames), 0)

    async def test_cancelled_old_attach_wait_cannot_invalidate_replacement_tempo_run(self):
        from unittest.mock import patch
        wait_original = asyncio.wait
        old_ready, release_old = asyncio.Event(), asyncio.Event()
        attach = None

        async def hold_old_wait(*args, **kwargs):
            result = await wait_original(*args, **kwargs)
            if asyncio.current_task() is attach:
                old_ready.set()
                await release_old.wait()
            return result

        with patch('brain.core.room_programs.asyncio.wait', hold_old_wait):
            program, attach = await self.begin_attach()
            old_run = program.run_id
            self.phone.ack = True  # Confirm the old run's separate OFF cleanup.
            tempo = asyncio.create_task(self.engine.dispatch(self.grant, 'program-update',
                {'request_id': 'tempo', 'program_id': program.id, 'bpm': 120}))
            self.requests.append(tempo)
            try:
                await asyncio.wait_for(old_ready.wait(), .3)
                await self.until(lambda: program.run_id != old_run and program.active)
                attach.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await attach
                self.assertTrue(program.active, 'Cancellation from the old cycle stopped its replacement run.')
                self.assertEqual(program.participants['phone']['participant_state'], 'pending')
                self.phone.ack = False
                while not self.phone.events.empty():
                    self.phone.events.get_nowait()  # Ignore only acknowledged old-run OFF cleanup.
                due = program.phase + .5
                await self.until(lambda: any(abs(at - due) < 1e-6 for at, _ in self.timeline.waiters))
                on = await self.next_edge(True, due)
                self.acknowledge(on)
                await self.until(lambda: program.participants['phone']['first_cycle']['on_ack'])
                off = await self.next_edge(False, due + .25)
                self.acknowledge(off)
                result = await asyncio.wait_for(tempo, .3)
                self.assertTrue(result['ok'], result)
                self.assertEqual(result['result']['light_device_ids'], ['phone'])
                self.assertTrue(program.active)
            finally:
                release_old.set()


if __name__ == '__main__':
    unittest.main()
