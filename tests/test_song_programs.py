"""Selected-recording coordination on real Bus/Registry, synthetic players only.

These checks prove recording-clock dispatch and lifecycle behavior. They cannot
prove hearing, optical phase, browser access, or source availability on a Mac.
"""
import asyncio
import copy
import io
import json
import time
import unittest
from unittest.mock import patch

from agent.song_audio import capabilities as song_capabilities
from agent.beat_audio import capabilities as beat_capabilities
from agent.tenant_device import invoke, main
from brain.core.native_devices import NativeDevices
from brain.core.song_timing import SongTimeline
from tests import test_room_programs as fixtures


def recording():
    beats = [0.0]
    for index in range(200):
        beats.append(round(beats[-1] + (.12, .13, .11, .15)[index % 4], 6))
    return {'song_id': 'selected-recording', 'sha256': 'a' * 64,
            'artist': 'Daniel Caesar', 'title': 'Synthetic timing fixture only',
            'duration_seconds': 30., 'beat_seconds': beats}


class SongSocket(fixtures.Socket):
    def __init__(self, bus):
        super().__init__(bus, audio=True)
        self.recording = recording()
        self.started = None
        self.state = 'playing'
        self.drop = set()
        self.prepare_hook = None
        self.snapshot_hook = None

    async def send_json(self, frame):
        if not frame['cap'].startswith('song.'):
            return await super().send_json(frame)
        self.frames.append(frame)
        self.events.put_nowait(frame)
        cap, args = frame['cap'], frame['args']
        if cap in self.drop:
            return
        data = {'program_id': args['program_id']}
        if cap == 'song.prepare':
            data.update(state='prepared', recording=copy.deepcopy(self.recording))
            if self.prepare_hook:
                self.prepare_hook()
        elif cap == 'song.stop':
            data.update(state='stopped', stopped=True)
        else:
            if cap == 'song.start':
                self.started = time.monotonic()
            data.update(state=self.state, song_id=self.recording['song_id'],
                        sha256=self.recording['sha256'], rate=1,
                        position_seconds=max(0, time.monotonic() - self.started))
            if self.snapshot_hook:
                self.snapshot_hook(data)
        self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': data})


class SongProgramTests(unittest.IsolatedAsyncioTestCase):
    grant_for = fixtures.ProgramTests.grant_for
    register = fixtures.ProgramTests.register
    update = fixtures.ProgramTests.update
    asyncTearDown = fixtures.ProgramTests.asyncTearDown

    async def asyncSetUp(self):
        await fixtures.ProgramTests.asyncSetUp(self)
        self.audio = self.register_song()

    def register_song(self):
        previous = self.registry.devices.get('laptop')
        if previous is not None:
            self.registry.offline(previous)
        socket = SongSocket(self.bus)
        socket.device = self.registry.register({'type': 'hello', 'room': 'TEST', 'id': 'laptop',
            'label': 'Selected recording bridge',
            'caps': {**beat_capabilities(), **song_capabilities(socket.recording)}}, socket)
        return socket

    async def start_song(self, **changes):
        return await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'song-start', 'device_id': 'laptop',
             'song_id': 'selected-recording', **changes}, authorized=lambda: not self.grant.closed)

    async def running(self):
        result = await self.start_song()
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['result']['source'], 'selected_recording')
        self.assertEqual(result['result']['song_clock']['state'], 'ready')
        self.assertFalse(result['result']['song_clock']['physical_alignment_verified'])
        return self.engine.programs[result['result']['program_id']]

    async def stop(self, program):
        return await self.engine.dispatch(self.grant, 'program-stop',
            {'request_id': 'stop-song', 'program_id': program.id})

    async def test_nonuniform_recording_beats_drive_phone_phase_instead_of_median_bpm(self):
        program = await self.running()
        attached = await asyncio.wait_for(self.update(program, light_device_id='phone'), 2)
        self.assertTrue(attached['ok'], attached)
        await asyncio.sleep(.35)
        edges = [row for row in program.timings if row['ack_code'] == 'OK']
        self.assertGreaterEqual(len(edges), 4)
        self.assertEqual([row['on'] for row in edges[:4]], [True, False, True, False])
        self.assertEqual([row['song_beat_number'] for row in edges[:4]], [2, 3, 4, 5])
        self.assertEqual([row['song_time_seconds'] for row in edges[:4]], [.25, .36, .51, .63])
        for left, right in zip(edges, edges[1:]):
            self.assertAlmostEqual(right['target_monotonic_ms'] - left['target_monotonic_ms'],
                (right['song_time_seconds'] - left['song_time_seconds']) * 1000, delta=3)
        self.assertTrue(program.participants['phone']['durations_are_estimates'])

    async def test_completed_turn_and_later_detach_leave_exact_song_running(self):
        program = await self.running()
        self.grant.closed = True
        await asyncio.sleep(.02)
        self.grant = self.grant_for(self.lease)
        self.assertTrue((await self.update(program, light_device_id='phone'))['ok'])
        result = await self.update(program, remove_light_device_id='phone')
        self.assertTrue(result['ok'], result)
        count = len(self.phone.frames)
        await asyncio.sleep(.3)
        self.assertEqual(len(self.phone.frames), count)
        self.assertFalse(self.phone.frames[-1]['args']['on'])
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked())
        self.assertTrue(program.active)
        self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
        self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)

    async def test_fresh_independent_off_stops_phone_while_song_continues_then_full_stop(self):
        program = await self.running()
        self.assertTrue((await self.update(program, light_device_id='phone'))['ok'])
        off = await self.engine.explicit_off(self.grant, 'phone')
        self.assertTrue(off['ok'], off)
        self.assertTrue(program.active)
        self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
        self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
        result = await self.stop(program)
        self.assertTrue(result['ok'], result)
        self.assertEqual(program.cleanup['audio'], 'confirmed')
        self.assertEqual(program.state, 'stopped')
        self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.stop'), 1)
        self.assertTrue(self.engine.cleanup_confirmed())

    async def test_stop_with_attached_phone_cleans_both_outputs_without_start_replay(self):
        program = await self.running()
        await self.update(program, light_device_id='phone')
        result = await self.stop(program)
        self.assertTrue(result['ok'], result)
        self.assertEqual(program.cleanup, {'audio': 'confirmed', 'phone': 'confirmed'})
        self.assertFalse(self.phone.frames[-1]['args']['on'])
        self.assertIsNone(self.engine.device_busy('phone'))
        self.assertFalse(self.locks['phone'].locked())
        self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)

    async def test_each_manage_scope_is_required_before_any_prepare(self):
        scopes = {'song.' + name for name in ('prepare', 'start', 'status', 'stop')}
        for missing in sorted(scopes):
            with self.subTest(missing=missing):
                self.lease.scopes = scopes - {missing}
                result = await self.start_song()
                self.assertEqual(result['code'], 'PERMISSION')
                self.assertEqual(self.audio.frames, [])
        self.lease.scopes = {'*'}
        result = await self.start_song(song_id='different-recording')
        self.assertEqual(result['code'], 'INVALID')
        self.assertEqual(self.audio.frames, [])

    async def test_reconnected_audio_during_queued_prepare_gets_no_migrated_start(self):
        old = self.audio
        await self.bus.locks['laptop'].acquire()
        pending = asyncio.create_task(self.start_song())
        await asyncio.sleep(.01)
        self.audio = self.register_song()
        self.bus.locks['laptop'].release()
        result = await asyncio.wait_for(pending, 1)
        self.assertFalse(result['ok'], result)
        program = next(iter(self.engine.programs.values()))
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(old.frames, [])
        self.assertEqual(self.audio.frames, [])
        self.assertEqual(program.cleanup['audio'], 'unknown')

    async def test_scope_revoked_after_prepare_fences_start(self):
        self.audio.prepare_hook = lambda: self.lease.scopes.discard('song.start')
        self.lease.scopes = {'song.' + name for name in ('prepare', 'start', 'status', 'stop')}
        result = await self.start_song()
        self.assertEqual(result['code'], 'PERMISSION')
        program = next(iter(self.engine.programs.values()))
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual([frame['cap'] for frame in self.audio.frames], ['song.prepare', 'song.stop'])

    async def test_unknown_start_is_not_replayed_or_replaced_by_new_program(self):
        self.audio.drop.add('song.start')
        result = await self.start_song()
        self.assertEqual(result['code'], 'UNKNOWN')
        program = next(iter(self.engine.programs.values()))
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(program.state, 'unknown')
        again = await self.start_song()
        self.assertEqual(again['code'], 'CONFLICT')
        update = await self.update(program, light_device_id='phone')
        self.assertEqual(update['code'], 'STOPPED')
        self.assertEqual([frame['cap'] for frame in self.audio.frames], ['song.prepare', 'song.start'])
        self.assertEqual(self.phone.frames, [])

    async def test_speech_queue_stales_playhead_and_fences_new_on_until_refresh(self):
        program = await self.running()
        await self.update(program, light_device_id='phone')
        await self.bus.locks['laptop'].acquire()
        try:
            await asyncio.sleep(program.song_timeline.ttl + .08)
            self.assertFalse(program.song_timeline.ready(self.engine.clock()))
            on_count = sum(frame['args']['on'] for frame in self.phone.frames)
            await asyncio.sleep(.3)
            self.assertEqual(sum(frame['args']['on'] for frame in self.phone.frames), on_count)
            self.assertTrue(program.active)
            self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
        finally:
            self.bus.locks['laptop'].release()
        await asyncio.sleep(.4)
        self.assertTrue(program.active)
        self.assertTrue(program.song_timeline.ready(self.engine.clock()))
        self.assertGreater(sum(frame['args']['on'] for frame in self.phone.frames), on_count)

    async def test_paused_and_ended_player_states_trigger_owned_cleanup(self):
        for state in ('paused', 'ended'):
            with self.subTest(state=state):
                program = await self.running()
                self.audio.state = state
                await asyncio.sleep(.18)
                self.assertFalse(program.active)
                await asyncio.wait_for(program.cleanup_task, 1)
                self.assertEqual(program.reason, 'SONG_' + state.upper())
                self.assertEqual(program.cleanup['audio'], 'confirmed')
                self.audio.state = 'playing'

    async def test_song_tempo_edit_rejected_without_audio_change_or_phone_attach(self):
        program = await self.running()
        before = len(self.audio.frames)
        result = await self.update(program, bpm=120, light_device_id='phone')
        self.assertEqual(result['code'], 'UNSUPPORTED')
        self.assertEqual(len(self.audio.frames), before)
        self.assertEqual(self.phone.frames, [])
        self.assertTrue(program.active)

    async def test_song_claim_conflicts_with_second_song_or_generated_clock_until_clean_stop(self):
        program = await self.running()
        result = await self.start_song()
        self.assertEqual(result['code'], 'CONFLICT')
        result = await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'beat-start', 'device_id': 'laptop', 'bpm': 120})
        self.assertEqual(result['code'], 'CONFLICT')
        self.assertEqual([frame['cap'] for frame in self.audio.frames], ['song.prepare', 'song.start'])
        self.assertTrue((await self.stop(program))['ok'])
        self.assertTrue((await self.start_song())['ok'])

    async def test_buffering_start_stays_pending_until_real_playhead_then_attaches(self):
        self.audio.state = 'buffering'
        result = await self.start_song()
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['complete'])
        self.assertEqual(result['code'], 'PENDING')
        program = self.engine.programs[result['result']['program_id']]
        attached = asyncio.create_task(self.update(program, light_device_id='phone'))
        await asyncio.sleep(.2)
        self.assertEqual(self.phone.frames, [])
        self.audio.state = 'playing'
        self.assertTrue((await asyncio.wait_for(attached, 2))['ok'])
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames[:2]], [True, False])

    async def test_wrong_recording_live_clock_stops_instead_of_using_plausible_bpm(self):
        program = await self.running()
        self.audio.snapshot_hook = lambda data: data.update(sha256='b' * 64)
        await asyncio.sleep(.18)
        self.assertFalse(program.active)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(program.reason, 'INVALID_SONG_CLOCK')
        self.assertEqual(program.cleanup['audio'], 'confirmed')
        self.assertEqual(self.phone.frames, [])

    async def test_active_audio_disconnect_does_not_stop_replacement_and_cleans_phone(self):
        program = await self.running()
        await self.update(program, light_device_id='phone')
        old_audio = self.audio
        self.audio = self.register_song()
        await asyncio.sleep(.08)
        self.assertFalse(program.active)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(program.cleanup['audio'], 'unknown')
        self.assertEqual(program.cleanup['phone'], 'confirmed')
        self.assertEqual(self.audio.frames, [])
        self.assertNotIn('song.stop', [frame['cap'] for frame in old_audio.frames])
        self.assertFalse(self.phone.frames[-1]['args']['on'])

    async def test_lease_revoke_stops_owned_audio_and_fences_all_future_phone_on(self):
        program = await self.running()
        await self.update(program, light_device_id='phone')
        count = len(self.phone.frames)
        self.leases.revoke(self.lease.guest_id)
        self.engine.access_ended(self.lease.guest_id)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertFalse(program.active)
        self.assertEqual(program.cleanup, {'audio': 'confirmed', 'phone': 'confirmed'})
        self.assertTrue(all(frame['args']['on'] is False for frame in self.phone.frames[count:]))
        self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)

    async def test_real_private_helper_selects_inventory_song_deduplicates_and_manages_phone(self):
        tools = NativeDevices(self.registry, self.bus, self.leases, self.engine.log,
            lambda owner: owner.generation == self.generation, action_timeout=.2, turn_timeout=5)
        tools.programs = self.engine
        tools.device_locks = self.locks
        grant = await tools.prepare(self.lease.guest_id, self.generation, self.lease, 'native-room')
        tools.activate(grant, 'synthetic-song-turn')
        try:
            inventory = await asyncio.to_thread(invoke, grant.path, 'inventory')
            self.assertTrue(inventory['ok'], inventory)
            selected = inventory['programs']['audio_devices'][0]
            self.assertEqual(selected['device_id'], 'laptop')
            song_id = selected['songs'][0]['song_id']
            self.assertEqual(song_id, self.audio.recording['song_id'])
            laptop = next(row for row in inventory['devices'] if row['id'] == 'laptop')
            self.assertFalse(any(cap['name'].startswith('song.') for cap in laptop['caps']))
            payload = {'request_id': 'helper-song', 'device_id': selected['device_id'], 'song_id': song_id}
            mixed = await asyncio.to_thread(invoke, grant.path, 'program-start', {**payload, 'bpm': 120})
            self.assertEqual(mixed['code'], 'INVALID')
            self.assertEqual(self.audio.frames, [])
            started = await asyncio.to_thread(invoke, grant.path, 'program-start', payload)
            self.assertTrue(started['ok'], started)
            duplicate = await asyncio.to_thread(invoke, grant.path, 'program-start', payload)
            self.assertEqual(duplicate, started)
            self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)
            program_id = started['result']['program_id']
            attached = await asyncio.to_thread(invoke, grant.path, 'program-update',
                {'request_id': 'helper-attach', 'program_id': program_id, 'light_device_id': 'phone'})
            self.assertTrue(attached['ok'], attached)
            self.assertEqual([frame['args']['on'] for frame in self.phone.frames[:2]], [True, False])
            detached = await asyncio.to_thread(invoke, grant.path, 'program-update',
                {'request_id': 'helper-detach', 'program_id': program_id, 'remove_light_device_id': 'phone'})
            self.assertTrue(detached['ok'], detached)
            self.assertTrue(self.engine.programs[program_id].active)
            self.assertEqual(self.phone.frames[-1]['args'], {'on': False})
            self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
            stopped = await asyncio.to_thread(invoke, grant.path, 'program-stop',
                {'request_id': 'helper-stop', 'program_id': program_id})
            self.assertTrue(stopped['ok'], stopped)
            self.assertEqual(stopped['result']['cleanup']['audio'], 'confirmed')
            self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.stop'), 1)
        finally:
            await tools.close()

    def test_cli_exact_song_start_shape_is_forwarded_and_mixed_clock_shape_is_rejected(self):
        payload = {'request_id': 'selected-song', 'device_id': 'laptop', 'song_id': 'selected-recording'}
        with patch('agent.tenant_device.invoke', return_value={'ok': True}) as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/synthetic-context', 'program-start']), 0)
            dispatch.assert_called_once_with('/private/synthetic-context', 'program-start', payload)
        with patch('agent.tenant_device.invoke') as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps({**payload, 'bpm': 120}))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/synthetic-context', 'program-start']), 1)
            dispatch.assert_not_called()

    async def test_frozen_playing_audio_pts_cannot_repeat_same_on_and_resumes_future_beats(self):
        await self.assert_unreliable_pts_is_fenced(0)

    async def test_slow_positive_audio_pts_cannot_repeat_on_and_resumes_after_coherent_progress(self):
        await self.assert_unreliable_pts_is_fenced(.0001)

    async def assert_unreliable_pts_is_fenced(self, increment):
        # Exact pre-fix counterexample: refreshes said playing at audio-PTS 1.3,
        # on a .75s map, repeatedly moving beat 2 into the future and emitting ON.
        self.audio.recording['beat_seconds'] = [index * .75 for index in range(40)]
        reads = [0]
        def unreliable_pts(data):
            reads[0] += 1
            data['position_seconds'] = 1.3 + increment * reads[0]
        self.audio.snapshot_hook = unreliable_pts
        program = await self.running()
        attached = await asyncio.wait_for(self.update(program, light_device_id='phone'), 1)
        self.assertTrue(attached['ok'], attached)
        self.assertTrue(program.song_timeline.stalled)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames], [True, False])
        await asyncio.sleep(1.)
        on_rows = [row for row in program.timings if row['on'] and row['ack_code'] == 'OK']
        self.assertEqual([row['song_beat_number'] for row in on_rows], [2])
        self.assertFalse(program.song_timeline.ready(self.engine.clock()))
        self.assertEqual(self.engine._status(program)['song_clock']['state'], 'pending')
        self.assertTrue(program.active)
        self.assertGreaterEqual(reads[0], 4)
        # A fresh independent OFF must remain available while the clock is bad.
        off = await self.engine.explicit_off(self.grant, 'phone')
        self.assertTrue(off['ok'], off)
        self.assertTrue(program.active)
        self.assertFalse(self.phone.frames[-1]['args']['on'])
        self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
        reattach = asyncio.create_task(self.update(program, light_device_id='phone'))
        # Forward progress is a new observation, not permission to catch up all
        # skipped beats. Resume before beat 6 and wait for exactly that future ON.
        resumed_at = time.monotonic()
        self.audio.snapshot_hook = lambda data: data.update(
            position_seconds=3.1 + time.monotonic() - resumed_at)
        async with asyncio.timeout(2):
            while sum(frame['args']['on'] for frame in self.phone.frames) < 2:
                await asyncio.sleep(.02)
        self.assertTrue(program.song_timeline.ready(self.engine.clock()))
        self.assertFalse(program.song_timeline.stalled)
        await asyncio.sleep(.1)
        on_rows = [row for row in program.timings if row['on'] and row['ack_code'] == 'OK']
        self.assertEqual([row['song_beat_number'] for row in on_rows], [2, 6])
        self.assertGreater(on_rows[1]['target_monotonic_ms'], resumed_at * 1000)
        self.assertEqual([frame['args']['on'] for frame in self.phone.frames[:4]], [True, False, False, True])
        self.assertTrue((await asyncio.wait_for(reattach, 1))['ok'])

    def test_fast_tiny_progress_reads_do_not_reset_cumulative_clock_allowance(self):
        timeline = SongTimeline(recording())
        def observe(at, position):
            timeline.observe({'state': 'playing', 'song_id': timeline.recording['song_id'],
                'sha256': timeline.recording['sha256'], 'rate': 1,
                'position_seconds': position}, at, at)
        observe(100., 1.3)
        self.assertTrue(timeline.ready(100.))
        # Every adjacent read is comfortably within the 100ms allowance. Across
        # these 50 fresh reads, however, audio advances 5ms in 500ms of wall time.
        for index in range(1, 51):
            at = 100. + index * .01
            observe(at, 1.3 + index * .0001)
            if index >= 12:
                self.assertFalse(timeline.ready(at))
        self.assertEqual(timeline.status(at)['state'], 'pending')
        self.assertTrue(timeline.stalled)
        # A jump alone cannot restore readiness. A subsequent coherent segment
        # longer than the allowance can, even when sampled in small reads.
        observe(100.6, 3.1)
        self.assertFalse(timeline.ready(100.6))
        for index in range(1, 14):
            at = 100.6 + index * .01
            observe(at, 3.1 + index * .01)
            if index <= 9:
                self.assertFalse(timeline.ready(at))
        self.assertTrue(timeline.ready(at))
        self.assertFalse(timeline.stalled)

    async def test_song_lease_expiry_cleans_audio_and_phone_without_a_new_native_turn(self):
        program = await self.running()
        await self.update(program, light_device_id='phone')
        count = len(self.phone.frames)
        self.now = self.lease.expires_at
        async with asyncio.timeout(.3):
            while program.cleanup_task is None:
                await asyncio.sleep(.01)
            await program.cleanup_task
        self.assertFalse(program.active)
        self.assertEqual(self.lease.state, 'expired')
        self.assertEqual(program.cleanup, {'audio': 'confirmed', 'phone': 'confirmed'})
        self.assertTrue(all(frame['args']['on'] is False for frame in self.phone.frames[count:]))
        self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)
