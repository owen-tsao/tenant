"""Generated beat/phone scheduling with synthetic bridges. No sound or hardware."""
import asyncio
from collections import defaultdict
import math
import time
from types import SimpleNamespace
import unittest

from agent.beat_audio import capabilities
from brain.core.bus import Bus
from brain.core.leases import Leases
from brain.core.log import EventLog
from brain.core.registry import Registry
from brain.core.room_programs import RoomPrograms, next_beat_index
from brain.state import Room


class Socket:
    def __init__(self, bus, *, audio=False, ack=True):
        self.bus, self.audio, self.ack = bus, audio, ack
        self.frames, self.processes = [], {}
        self.events = asyncio.Queue()
        self.device = None
        self.fail_status = False

    async def send_json(self, frame):
        self.frames.append(frame)
        self.events.put_nowait(frame)
        if not self.ack:
            return
        args, cap = frame['args'], frame['cap']
        if cap == 'beat.prepare':
            data = {'state': 'prepared', 'program_id': args['program_id']}
            self.processes[args['program_id']] = data
        elif cap == 'beat.start':
            data = {'state': 'launched', 'program_id': args['program_id'], 'launched_at_ms': time.time() * 1000}
            self.processes[args['program_id']] = data
        elif cap == 'beat.stop':
            data = {'state': 'stopped', 'program_id': args['program_id'], 'stopped': True}
            self.processes[args['program_id']] = data
        elif cap == 'beat.status':
            data = dict(self.processes[args['program_id']])
            if self.fail_status:
                data['state'] = 'failed'
        else:
            data = {'on': args['on']}
        self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': data})


class PhaseTests(unittest.TestCase):
    def test_late_join_clock_jump_and_nonbinary_boundaries_choose_future_grid(self):
        self.assertEqual(10 + next_beat_index(10, 10.37, .5) * .5, 10.5)
        self.assertEqual(10.5 + .5 / 4, 10.625)
        self.assertEqual(10 + next_beat_index(10, 12.3, .5) * .5, 12.5)
        self.assertEqual(10 + next_beat_index(10, 10.0001, .6) * .6, 10.6)
        self.assertEqual(10 + next_beat_index(10, 10.6, .6) * .6, 11.2)


class ProgramTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = time.time()
        self.registry = Registry(Room('TEST', 'Synthetic room'))
        self.bus = Bus(self.registry)
        self.leases = Leases(self.registry.room, clock=lambda: self.now)
        self.lease = self.leases.create()
        self.leases.current(self.lease.guest_id, activate=True)
        self.generation = 1
        self.locks = defaultdict(asyncio.Lock)
        self.engine = RoomPrograms(self.registry, self.bus, self.leases, EventLog(),
            lambda owner: owner.generation == self.generation, action_timeout=.2, device_locks=self.locks)
        self.grant = self.grant_for(self.lease)
        self.audio = self.register('laptop', audio=True)
        self.phone = self.register('phone')

    async def asyncTearDown(self):
        await self.engine.close()

    def grant_for(self, lease):
        return SimpleNamespace(guest_id=lease.guest_id, generation=self.generation, lease=lease,
            thread_id='native-room', room_id=self.registry.room.id, epoch=self.registry.room.epoch, closed=False)

    def register(self, device_id, *, audio=False, ack=True):
        socket = Socket(self.bus, audio=audio, ack=ack)
        caps = capabilities() if audio else {'light': {'description': 'Phone light', 'args': {'on': {'type': 'boolean'}}}}
        socket.device = self.registry.register({'type': 'hello', 'room': 'TEST', 'id': device_id,
            'label': device_id, 'caps': caps}, socket)
        return socket

    async def start(self, bpm=600):
        result = await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'start', 'device_id': 'laptop', 'bpm': bpm}, authorized=lambda: not self.grant.closed)
        self.assertTrue(result['ok'], result)
        return self.engine.programs[result['result']['program_id']]

    async def update(self, program, **changes):
        return await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'update', 'program_id': program.id, **changes}, authorized=lambda: not self.grant.closed)

    async def test_beat_survives_native_turn_and_later_turn_attaches_phone_to_same_clock(self):
        program = await self.start()
        self.grant.closed = True
        await asyncio.sleep(.01)
        self.assertTrue(program.active)
        self.grant = self.grant_for(self.lease)
        self.assertTrue((await self.update(program, light_device_id='phone'))['ok'])
        frames = [await asyncio.wait_for(self.phone.events.get(), 1) for _ in range(3)]
        self.assertEqual([f['args']['on'] for f in frames], [True, False, True])
        self.assertEqual(program.id, self.engine.inventory(self.grant)['programs'][0]['program_id'])
        targets = [row['target_monotonic_ms'] for row in program.timings]
        self.assertAlmostEqual(targets[2] - targets[0], 100, delta=1)
        self.assertTrue(all(row['dispatch_monotonic_ms'] is not None for row in program.timings))
        self.assertFalse(self.engine._status(program)['physical_sync_measured'])

    async def test_detach_confirms_off_then_allows_steady_light_while_music_keeps_running(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        await asyncio.wait_for(self.phone.events.get(), 1)
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        result = await self.update(program, remove_light_device_id='phone')
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
        self.assertFalse(self.locks['phone'].locked())
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertTrue(program.active)
        self.assertEqual([f['cap'] for f in self.audio.frames], ['beat.prepare', 'beat.start'])
        result = await self.bus.call('phone', 'light', {'on': True}, authorize=lambda *_: True)
        self.assertTrue(result.ok)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': True})

    async def test_attach_conflicts_with_existing_logical_operation_without_waiting(self):
        program = await self.start()
        await self.locks['phone'].acquire()
        try:
            result = await asyncio.wait_for(self.update(program, light_device_id='phone'), .1)
            self.assertEqual(result['code'], 'CONFLICT')
            self.assertEqual(self.phone.frames, [])
        finally:
            self.locks['phone'].release()

    async def test_independent_program_ids_have_no_one_job_cap_and_stop_only_their_own_audio(self):
        first, second = await self.start(), await self.start()
        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.run_id, second.run_id)
        await self.engine.dispatch(self.grant, 'program-stop', {'request_id': 'stop', 'program_id': first.id})
        self.assertFalse(first.active)
        self.assertTrue(second.active)
        self.assertEqual(self.audio.frames[-1]['args'], {'program_id': first.run_id})

    async def test_tempo_update_restarts_own_loop_on_new_phase_and_keeps_participants(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        old_run = program.run_id
        result = await self.update(program, bpm=300)
        self.assertTrue(result['ok'], result)
        self.assertNotEqual(program.run_id, old_run)
        self.assertEqual(program.bpm, 300)
        self.assertEqual(result['result']['light_device_ids'], ['phone'])
        self.assertEqual([f['cap'] for f in self.audio.frames], ['beat.prepare', 'beat.start', 'beat.stop', 'beat.prepare', 'beat.start'])

    async def test_revoked_queued_phone_never_gets_on_and_is_not_reassigned_to_new_guest(self):
        program = await self.start()
        await self.bus.locks['phone'].acquire()
        await self.update(program, light_device_id='phone')
        await asyncio.sleep(.12)
        self.leases.revoke(self.lease.guest_id)
        self.engine.access_ended(self.lease.guest_id)
        self.generation = 2
        other = self.leases.create()
        grant = self.grant_for(other)
        result = await self.engine.dispatch(grant, 'program-update',
            {'request_id': 'steal', 'program_id': program.id, 'light_device_id': 'phone'})
        self.assertEqual(result['code'], 'PERMISSION')
        self.bus.locks['phone'].release()
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertTrue(all(frame['args']['on'] is False for frame in self.phone.frames))
        self.assertFalse(program.active)

    async def test_unsent_stale_on_skips_to_future_beat_without_backlog(self):
        program = await self.start()
        lock = self.bus.locks['phone']
        await lock.acquire()
        try:
            await self.update(program, light_device_id='phone')
            await asyncio.sleep(.16)
            self.assertEqual(self.phone.frames, [])
            self.assertGreaterEqual(program.missed_ticks, 1)
        finally:
            lock.release()
        first = await asyncio.wait_for(self.phone.events.get(), 1)
        self.assertEqual(first['args'], {'on': True})
        self.assertTrue(program.active)
        self.assertEqual(program.timings[0]['ack_code'], 'TIMEOUT')
        self.assertIsNone(program.timings[0]['dispatch_monotonic_ms'])

    async def test_lease_expiry_stops_future_steps_without_waiting_for_a_native_turn(self):
        program = await self.start()
        self.now += 601
        await asyncio.sleep(.08)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertFalse(program.active)
        self.assertEqual(program.cleanup['audio'], 'confirmed')

    async def test_unknown_phone_edge_stops_program_without_retry_and_keeps_phone_reserved(self):
        self.phone.ack = False
        program = await self.start()
        await self.update(program, light_device_id='phone')
        await asyncio.wait_for(self.phone.events.get(), 1)
        await asyncio.sleep(.08)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(len(self.phone.frames), 1)
        self.assertFalse(program.active)
        self.assertEqual(program.cleanup['phone'], 'unknown')
        self.assertEqual(self.engine.device_busy('phone'), program.id)
        self.assertTrue(self.locks['phone'].locked())

    async def test_unknown_phone_cleanup_recovers_only_from_quiescent_exact_host_reset_off_receipt(self):
        self.phone.ack = False
        program = await self.start()
        await self.update(program, light_device_id='phone')
        frame = await asyncio.wait_for(self.phone.events.get(), 1)
        await asyncio.sleep(.08)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.leases.reset()
        self.engine.access_ended(self.lease.guest_id)
        self.assertFalse(await self.engine.quiesce())
        self.assertFalse(self.engine.cleanup_confirmed())
        self.bus.receive(self.phone.device, {'type': 'ok', 'req': frame['req'], 'result': {'on': True}})
        self.phone.ack = True
        connection = self.phone.device.ws
        result = await self.bus.call('phone', 'light', {'on': False},
            authorize=lambda dev, cap, args: dev is self.phone.device and cap == 'light' and args == {'on': False})
        self.assertTrue(result.ok)
        self.assertFalse(self.engine.confirm_host_off(self.phone.device, object(), result))
        self.assertTrue(self.locks['phone'].locked())
        self.assertTrue(self.engine.confirm_host_off(self.phone.device, connection, result))
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked())
        self.assertTrue(self.engine.cleanup_confirmed())
        self.assertEqual(program.recovery['phone']['req'], result.req)

    async def test_unknown_detach_never_retries_and_reports_reserved_phone_while_music_continues(self):
        program = await self.start()
        await self.update(program, light_device_id='phone')
        self.phone.ack = False
        result = await self.update(program, remove_light_device_id='phone')
        self.assertEqual(result['code'], 'UNKNOWN')
        count = len(self.phone.frames)
        second = await self.update(program, remove_light_device_id='phone')
        self.assertEqual(second['code'], 'UNKNOWN')
        self.assertEqual(len(self.phone.frames), count)
        self.assertTrue(program.active)
        self.assertIn('phone', result['result']['reserved_light_ids'])

    async def test_exact_offline_device_is_not_silently_substituted(self):
        program = await self.start()
        other = self.register('other')
        self.registry.offline(self.phone.device)
        result = await self.update(program, light_device_id='phone')
        self.assertEqual(result['code'], 'OFFLINE')
        self.assertEqual(other.frames, [])

    async def test_invalid_tempo_and_program_ids_are_rejected_without_new_effects(self):
        for bpm in (0, -1, math.nan, math.inf, True):
            result = await self.engine.dispatch(self.grant, 'program-start',
                {'request_id': 'invalid', 'device_id': 'laptop', 'bpm': bpm})
            self.assertEqual(result['code'], 'INVALID')
        result = await self.engine.dispatch(self.grant, 'program-status', {'request_id': 'invalid', 'program_id': []})
        self.assertEqual(result['code'], 'INVALID')
        self.assertEqual(self.audio.frames, [])

    async def test_turn_authority_ending_during_prepare_never_sends_playback_start(self):
        send = self.audio.send_json
        async def finish_grant_after_prepare(frame):
            await send(frame)
            if frame['cap'] == 'beat.prepare':
                self.grant.closed = True
        self.audio.send_json = finish_grant_after_prepare
        result = await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'start', 'device_id': 'laptop', 'bpm': 120}, authorized=lambda: not self.grant.closed)
        self.assertFalse(result['ok'])
        program = next(iter(self.engine.programs.values()))
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertNotIn('beat.start', [frame['cap'] for frame in self.audio.frames])

    async def test_cancellation_during_prepare_cannot_send_a_late_playback_start(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        send = self.audio.send_json
        async def hold_prepare(frame):
            if frame['cap'] == 'beat.prepare':
                entered.set()
                await release.wait()
            await send(frame)
        self.audio.send_json = hold_prepare
        task = asyncio.create_task(self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'start', 'device_id': 'laptop', 'bpm': 120}))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        release.set()
        program = next(iter(self.engine.programs.values()))
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertNotIn('beat.start', [frame['cap'] for frame in self.audio.frames])

    async def test_disappearing_audio_process_stops_program_and_reports_failure_honestly(self):
        program = await self.start()
        await asyncio.sleep(0)  # Establish the monitor's first status deadline.
        self.audio.fail_status = True
        original = self.engine.clock
        self.engine.clock = lambda: original() + 2
        await asyncio.sleep(.08)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertFalse(program.active)
        self.assertEqual(program.reason, 'AUDIO_STOPPED')
        self.assertTrue(all(frame['cap'].startswith('beat.') for frame in self.audio.frames))

    async def test_status_queued_behind_long_speech_does_not_false_stop_and_cleanup_has_queue_budget(self):
        program = await self.start()
        await asyncio.sleep(0)
        self.engine.action_timeout = .05
        self.engine.audio_queue_timeout = .4
        await self.bus.locks['laptop'].acquire()  # Accepted speech owns this existing device Bus.
        original = self.engine.clock
        self.engine.clock = lambda: original() + 2
        try:
            await asyncio.sleep(.12)
            self.assertTrue(program.active)
            self.assertNotIn('beat.status', [f['cap'] for f in self.audio.frames])
            stop = asyncio.create_task(self.engine.dispatch(self.grant, 'program-stop',
                {'request_id': 'stop', 'program_id': program.id}))
            await asyncio.sleep(.12)  # Longer than an ordinary action deadline, within accepted speech+stop budget.
        finally:
            self.bus.locks['laptop'].release()
        result = await asyncio.wait_for(stop, 1)
        self.assertTrue(result['ok'], result)
        self.assertEqual(program.cleanup['audio'], 'confirmed')

    async def test_cancelled_quiesce_settles_shielded_output_cleanup_without_late_dispatch(self):
        program = await self.start()
        self.engine.audio_queue_timeout = 1
        lock = self.bus.locks['laptop']
        await lock.acquire()
        self.leases.revoke(self.lease.guest_id)
        self.engine.access_ended(self.lease.guest_id)
        settle = asyncio.create_task(self.engine.quiesce())
        await asyncio.sleep(.01)
        settle.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await settle
        self.assertTrue(all(task.done() for task in program.output_cleanup.values()))
        before = len(self.audio.frames)
        lock.release()
        await asyncio.sleep(0)
        self.assertEqual(len(self.audio.frames), before)
        self.assertEqual(program.cleanup['audio'], 'unknown')


if __name__ == '__main__':
    unittest.main()
