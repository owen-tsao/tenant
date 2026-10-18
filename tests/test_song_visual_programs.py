"""Owned selected-song visual updates on a real Bus, with synthetic bridges only.

These checks never launch the orb, native audio, a browser, or any live device.
"""
import asyncio
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from agent.beat_audio import capabilities as beat_capabilities
from agent.song_audio import SongAudio, SongError, capabilities as song_capabilities
from agent.tenant_device import invoke, main
from brain.core.device_metadata import update_metadata
from brain.core.native_devices import CAPABILITIES, NativeDevices
from tests import test_room_programs as fixtures
from tests.test_song_programs import SongSocket
from tests.test_song_audio import FakePlayer


VISUAL_CAP = {'description': 'Show or hide this selected recording visual', 'args': {
    'program_id': {'type': 'string'}, 'visible': {'type': 'boolean'}}}


class VisualSocket(SongSocket):
    def __init__(self, bus):
        super().__init__(bus)
        self.visual_result = None
        self.visual_sent = asyncio.Event()
        self.visual_release = None
        self.visual_hook = None

    async def send_json(self, frame):
        if frame['cap'] != 'song.visual':
            return await super().send_json(frame)
        self.frames.append(frame)
        self.events.put_nowait(frame)
        self.visual_sent.set()
        if self.visual_release is not None:
            await self.visual_release.wait()
        if self.visual_hook:
            self.visual_hook()
        if frame['cap'] not in self.drop:
            result = self.visual_result if self.visual_result is not None else dict(frame['args'])
            self.bus.receive(self.device, {'type': 'ok', 'req': frame['req'], 'result': result})


class SongVisualProgramTests(unittest.IsolatedAsyncioTestCase):
    grant_for = fixtures.ProgramTests.grant_for
    register = fixtures.ProgramTests.register

    async def asyncSetUp(self):
        await fixtures.ProgramTests.asyncSetUp(self)
        self.tools = None
        self.audio = self.register_song()

    async def asyncTearDown(self):
        if self.tools is not None:
            await self.tools.close()
        await self.engine.close()

    def register_song(self, *, visual=True):
        previous = self.registry.devices.get('laptop')
        if previous is not None:
            self.registry.offline(previous)
        socket = VisualSocket(self.bus)
        caps = {**beat_capabilities(), **song_capabilities(socket.recording)}
        # Advertise the contract independently of the production bridge helper.
        caps.pop('song.visual', None)
        if visual:
            caps['song.visual'] = copy.deepcopy(VISUAL_CAP)
        socket.device = self.registry.register({'type': 'hello', 'room': 'TEST', 'id': 'laptop',
            'label': 'Synthetic recording bridge', 'caps': caps}, socket)
        return socket

    async def running(self):
        result = await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'song-start', 'device_id': 'laptop', 'song_id': 'selected-recording'})
        self.assertTrue(result['ok'], result)
        return self.engine.programs[result['result']['program_id']]

    async def visual(self, program, visible=True, **changes):
        return await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'visual-update', 'program_id': program.id, 'visual': visible, **changes},
            authorized=lambda: not self.grant.closed)

    def visual_frames(self, socket=None):
        return [frame for frame in (socket or self.audio).frames if frame['cap'] == 'song.visual']

    def metadata(self, **fields):
        core = SimpleNamespace(registry=self.registry, agent=SimpleNamespace(private_values=()),
            config=SimpleNamespace(host_token='synthetic-host', device_token='synthetic-device'))
        return update_metadata(core, 'laptop', fields)

    async def helper(self):
        self.tools = NativeDevices(self.registry, self.bus, self.leases, self.engine.log,
            lambda owner: owner.generation == self.generation, action_timeout=.2, turn_timeout=5)
        self.tools.programs, self.tools.device_locks = self.engine, self.locks
        grant = await self.tools.prepare(self.lease.guest_id, self.generation, self.lease, 'native-room')
        self.tools.activate(grant, 'synthetic-visual-turn')
        return grant

    def request(self, grant, program, **changes):
        return {'token': grant.token, 'operation': 'program-update', 'request_id': 'helper-visual',
                'program_id': program.id, 'visual': True, **changes}

    async def test_show_and_hide_use_same_run_without_audio_restart_or_light_rewrite(self):
        program = await self.running()
        attached = await self.engine.dispatch(self.grant, 'program-update',
            {'request_id': 'attach', 'program_id': program.id, 'light_device_id': 'phone'})
        self.assertTrue(attached['ok'], attached)
        before = (program.run_id, program.phase, program.bpm, program.song_timeline,
                  program.light_tasks['phone'], copy.deepcopy(program.light_cadences))
        for visible in (True, False):
            result = await self.visual(program, visible)
            self.assertTrue(result['ok'], result)
            self.assertEqual(result['result']['visual']['state'], 'shown' if visible else 'hidden')
            self.assertIs(result['result']['visual']['acknowledged_visible'], visible)
            self.assertFalse(result['result']['visual']['physical_rendering_verified'])
        self.assertEqual([f['args'] for f in self.visual_frames()], [
            {'program_id': before[0], 'visible': True}, {'program_id': before[0], 'visible': False}])
        self.assertEqual((program.run_id, program.phase, program.bpm, program.song_timeline,
                          program.light_tasks['phone'], program.light_cadences), before)
        self.assertTrue(program.active)
        self.assertEqual([f['cap'] for f in self.audio.frames].count('song.start'), 1)
        self.assertNotIn('song.stop', [f['cap'] for f in self.audio.frames])

    async def test_visual_only_bypasses_preexisting_unrepresentable_light_cadence(self):
        program = await self.running()
        program.light_cadences['existing-unrepresentable-cadence'] = float('inf')
        before = dict(program.light_cadences)
        result = await self.visual(program)
        self.assertTrue(result['ok'], result)
        self.assertEqual(program.light_cadences, before)
        self.assertEqual(len(self.visual_frames()), 1)

    async def test_visual_rejects_nonboolean_and_mixed_timing_or_light_mutations(self):
        program = await self.running()
        for value in (1, 0, None, 'true', [], {}):
            with self.subTest(value=value):
                self.assertEqual((await self.visual(program, value))['code'], 'INVALID')
        for change in ({'bpm': 120}, {'light_device_id': 'phone'},
                       {'remove_light_device_id': 'phone'}, {'light_beats_per_state': 1}):
            with self.subTest(change=change):
                self.assertEqual((await self.visual(program, **change))['code'], 'INVALID')
        self.assertEqual(self.visual_frames(), [])
        self.assertEqual(self.phone.frames, [])

    async def test_missing_capability_is_unsupported_without_audio_or_visual_effects(self):
        self.audio = self.register_song(visual=False)
        program = await self.running()
        before = len(self.audio.frames)
        self.assertEqual((await self.visual(program))['code'], 'UNSUPPORTED')
        self.assertEqual(len(self.audio.frames), before)
        self.assertTrue(program.active)

    async def test_generated_program_is_unsupported_even_when_bridge_has_visual_capability(self):
        result = await self.engine.dispatch(self.grant, 'program-start',
            {'request_id': 'beat-start', 'device_id': 'laptop', 'bpm': 120})
        self.assertTrue(result['ok'], result)
        program = self.engine.programs[result['result']['program_id']]
        self.assertEqual((await self.visual(program))['code'], 'UNSUPPORTED')
        self.assertEqual(self.visual_frames(), [])

    async def test_stopped_program_is_not_restarted_for_visual(self):
        program = await self.running()
        await self.engine.dispatch(self.grant, 'program-stop', {'request_id': 'stop', 'program_id': program.id})
        self.assertEqual((await self.visual(program))['code'], 'STOPPED')
        self.assertEqual(self.visual_frames(), [])

    async def test_visual_scope_is_required_without_revoking_other_song_scopes(self):
        program = await self.running()
        self.lease.scopes = {'song.' + name for name in ('prepare', 'start', 'status', 'stop')}
        self.assertEqual((await self.visual(program))['code'], 'PERMISSION')
        self.assertEqual(self.visual_frames(), [])
        self.assertTrue(program.active)

    async def test_other_guest_cannot_toggle_owned_recording(self):
        program = await self.running()
        lease = self.leases.create()
        self.leases.current(lease.guest_id, activate=True)
        result = await self.engine.dispatch(self.grant_for(lease), 'program-update',
            {'request_id': 'foreign', 'program_id': program.id, 'visual': True})
        self.assertEqual(result['code'], 'PERMISSION')
        self.assertEqual(self.visual_frames(), [])

    async def queued_change(self, change, *, control=False):
        program = await self.running()
        old = self.audio
        lock = self.engine._control if control else self.bus.locks['laptop']
        await lock.acquire()
        pending = asyncio.create_task(self.visual(program))
        await asyncio.sleep(.01)
        try:
            change(program)
        finally:
            lock.release()
        result = await asyncio.wait_for(pending, 1)
        self.assertFalse(result['ok'], result)
        self.assertEqual(self.visual_frames(old), [])
        self.assertEqual(self.visual_frames(), [])

    async def test_metadata_deny_then_reenable_while_control_queued_cannot_send(self):
        def change(_):
            self.metadata(allowed=False)
            self.metadata(allowed=True)
        await self.queued_change(change, control=True)

    async def test_metadata_deny_then_reenable_while_bus_queued_cannot_send(self):
        def change(_):
            self.metadata(allowed=False)
            self.metadata(allowed=True)
        await self.queued_change(change)

    async def test_visual_scope_loss_while_bus_queued_cannot_send(self):
        self.lease.scopes = {'song.' + name for name in ('prepare', 'start', 'status', 'stop', 'visual')}
        await self.queued_change(lambda _: self.lease.scopes.discard('song.visual'))

    async def test_reconnected_bridge_while_control_queued_gets_no_migrated_visual(self):
        def change(_):
            self.audio = self.register_song()
        await self.queued_change(change, control=True)

    async def test_reconnected_bridge_while_bus_queued_gets_no_migrated_visual(self):
        def change(_):
            self.audio = self.register_song()
        await self.queued_change(change)

    async def test_run_replacement_while_bus_queued_cannot_send_old_run_visual(self):
        await self.queued_change(lambda program: setattr(program, 'run_id', 'replacement-run'))

    async def test_run_replacement_while_control_queued_cannot_send_old_run_visual(self):
        await self.queued_change(lambda program: setattr(program, 'run_id', 'replacement-run'), control=True)

    async def test_expired_lease_while_bus_queued_cannot_send(self):
        await self.queued_change(lambda _: setattr(self, 'now', self.lease.expires_at))

    async def test_generation_change_while_bus_queued_cannot_send(self):
        await self.queued_change(lambda _: setattr(self, 'generation', 2))

    async def test_room_epoch_change_while_bus_queued_cannot_send(self):
        await self.queued_change(lambda _: setattr(self.registry.room, 'epoch', self.registry.room.epoch + 1))

    async def test_turn_end_while_bus_queued_cannot_send(self):
        await self.queued_change(lambda _: setattr(self.grant, 'closed', True))

    async def test_late_ack_after_owned_cancellation_cannot_report_visual_success(self):
        program = await self.running()
        self.audio.visual_release = asyncio.Event()
        pending = asyncio.create_task(self.visual(program))
        await asyncio.wait_for(self.audio.visual_sent.wait(), 1)
        self.engine._invalidate(program, 'requested_stop')
        self.audio.visual_release.set()
        result = await asyncio.wait_for(pending, 1)
        self.assertFalse(result['ok'], result)
        await asyncio.wait_for(program.cleanup_task, 1)
        self.assertEqual(program.cleanup['audio'], 'confirmed')
        self.assertEqual(len(self.visual_frames()), 1)

    async def test_native_helper_caches_duplicate_visual_and_keeps_raw_capability_private(self):
        program = await self.running()
        grant = await self.helper()
        request = self.request(grant, program)
        first = await self.tools.dispatch(request)
        self.assertTrue(first['ok'], first)
        self.assertEqual(await self.tools.dispatch(request), first)
        self.assertEqual(len(self.visual_frames()), 1)
        self.assertNotIn('song.visual', CAPABILITIES)
        inventory = await self.tools.dispatch({'token': grant.token, 'operation': 'inventory'})
        laptop = next(row for row in inventory['devices'] if row['id'] == 'laptop')
        self.assertNotIn('song.visual', [cap['name'] for cap in laptop['caps']])
        self.assertIn('visual', self.tools.context(grant))
        self.assertIn('orb', self.tools.context(grant).lower())
        audio = next(row for row in inventory['programs']['audio_devices'] if row['device_id'] == 'laptop')
        self.assertTrue(audio['song_visual'])

    async def test_real_private_helper_socket_forwards_visual_shape_once(self):
        program = await self.running()
        grant = await self.helper()
        payload = {'request_id': 'socket-visual', 'program_id': program.id, 'visual': True}
        result = await asyncio.to_thread(invoke, grant.path, 'program-update', payload)
        self.assertTrue(result['ok'], result)
        self.assertEqual(await asyncio.to_thread(invoke, grant.path, 'program-update', payload), result)
        self.assertEqual([frame['args'] for frame in self.visual_frames()],
                         [{'program_id': program.run_id, 'visible': True}])

    def test_cli_visual_only_exact_shape_is_forwarded(self):
        payload = {'request_id': 'cli-visual', 'program_id': 'owned-program', 'visual': True}
        with patch('agent.tenant_device.invoke', return_value={'ok': True}) as dispatch:
            with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(main(['--context', '/private/synthetic-context', 'program-update']), 0)
            dispatch.assert_called_once_with('/private/synthetic-context', 'program-update', payload)

    def test_cli_nonboolean_visual_values_are_rejected_without_forwarding(self):
        for value in (1, 0, None, 'true', [], {}):
            payload = {'request_id': 'cli-visual', 'program_id': 'owned-program', 'visual': value}
            with self.subTest(value=value), patch('agent.tenant_device.invoke') as dispatch:
                with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(main(['--context', '/private/synthetic-context', 'program-update']), 1)
                dispatch.assert_not_called()

    def test_cli_mixed_visual_clock_or_light_updates_are_rejected_without_forwarding(self):
        for change in ({'bpm': 120}, {'light_device_id': 'phone'},
                       {'remove_light_device_id': 'phone'}, {'light_beats_per_state': 1}):
            payload = {'request_id': 'cli-visual', 'program_id': 'owned-program', 'visual': True, **change}
            with self.subTest(change=change), patch('agent.tenant_device.invoke') as dispatch:
                with patch('sys.stdin', io.StringIO(json.dumps(payload))), patch('sys.stdout', new_callable=io.StringIO):
                    self.assertEqual(main(['--context', '/private/synthetic-context', 'program-update']), 1)
                dispatch.assert_not_called()

    async def test_wrong_visual_ack_is_unknown_cached_and_blocks_new_effect_request(self):
        program = await self.running()
        grant = await self.helper()
        self.audio.visual_result = {'program_id': 'wrong-run', 'visible': True}
        request = self.request(grant, program)
        first = await self.tools.dispatch(request)
        self.assertEqual(first['code'], 'UNKNOWN', first)
        self.assertIn('laptop', first['unknown_device_ids'])
        self.assertIn('laptop', grant.unknown_devices)
        self.assertEqual(await self.tools.dispatch(request), first)
        again = await self.tools.dispatch({**request, 'request_id': 'different-request'})
        self.assertEqual(again['code'], 'UNKNOWN')
        self.assertEqual(len(self.visual_frames()), 1)
        self.tools.finish(grant)
        next_grant = await self.tools.prepare(self.lease.guest_id, self.generation, self.lease, 'native-room')
        self.tools.activate(next_grant, 'next-synthetic-visual-turn')
        next_result = await self.tools.dispatch(self.request(next_grant, program, request_id='next-turn'))
        self.assertEqual(next_result['code'], 'UNKNOWN')
        self.assertEqual(len(self.visual_frames()), 1)
        status = await self.tools.dispatch({'token': next_grant.token, 'operation': 'program-status',
            'request_id': 'status-unknown', 'program_id': program.id})
        self.assertTrue(status['ok'], status)
        self.assertEqual(status['result']['visual']['state'], 'unknown')
        stopped = await self.tools.dispatch({'token': next_grant.token, 'operation': 'program-stop',
            'request_id': 'stop-unknown', 'program_id': program.id})
        self.assertTrue(stopped['ok'], stopped)

    async def invalid_visible_ack(self, value):
        program = await self.running()
        self.audio.visual_result = {'program_id': program.run_id, **value}
        reply = await self.visual(program)
        self.assertEqual(reply['code'], 'UNKNOWN', reply)
        self.assertEqual(len(self.visual_frames()), 1)

    async def test_mismatched_visible_ack_is_unknown(self):
        await self.invalid_visible_ack({'visible': False})

    async def test_bool_like_visible_ack_is_unknown(self):
        await self.invalid_visible_ack({'visible': 1})

    async def test_missing_visible_ack_is_unknown(self):
        await self.invalid_visible_ack({})

    async def test_late_ack_after_scope_loss_is_not_a_success_receipt(self):
        program = await self.running()
        self.lease.scopes = {'song.' + name for name in ('prepare', 'start', 'status', 'stop', 'visual')}
        self.audio.visual_hook = lambda: self.lease.scopes.discard('song.visual')
        result = await self.visual(program)
        self.assertFalse(result['ok'], result)
        self.assertEqual(len(self.visual_frames()), 1)

    async def test_real_song_dispatcher_composes_with_program_visual_without_restarting_audio_or_light(self):
        """Use the actual bridge result schema, not a test-authored visual ACK."""
        players, hosts = [], []

        class AdvancingPlayer(FakePlayer):
            def start(self, deadline):
                super().start(deadline)
                self.started_at = time.monotonic()

            def snapshot(self, deadline):
                sample = super().snapshot(deadline)
                sample['position_seconds'] = (time.monotonic() - self.started_at
                    if self.state == 'playing' else 0.)
                return sample

        class FakeVisual:
            def __init__(self, *, deadline):
                self.deadline, self.frames, self.closes = deadline, [], 0
                hosts.append(self)

            def alive(self):
                return self.closes == 0

            def send(self, frame):
                self.frames.append(dict(frame))

            def close(self):
                self.closes += 1
                return True

        def player_factory(recording, *, binary):
            player = AdvancingPlayer(recording, binary=binary)
            players.append(player)
            return player

        class BridgeSocket(VisualSocket):
            async def send_json(socket, frame):
                socket.frames.append(frame)
                socket.events.put_nowait(frame)
                try:
                    result = bridge.dispatch(frame['cap'], frame['args'], timeout=.2)
                    reply = {'type': 'ok', 'req': frame['req'], 'result': result}
                except SongError as error:
                    reply = {'type': 'err', 'req': frame['req'], 'code': error.code, 'message': error.message}
                socket.bus.receive(socket.device, reply)

        with tempfile.TemporaryDirectory() as directory:
            audio_path = Path(directory) / 'synthetic.wav'
            with wave.open(str(audio_path), 'wb') as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8000)
                output.writeframes(b'\0\0' * 32000)
            manifest = Path(directory) / 'song.json'
            manifest.write_text(json.dumps({'song_id': 'selected-recording', 'artist': 'Daniel Caesar',
                'title': 'Synthetic composition fixture', 'audio_path': str(audio_path),
                'sha256': hashlib.sha256(audio_path.read_bytes()).hexdigest(), 'duration_seconds': 4.,
                'beat_seconds': [round(.12 * index, 6) for index in range(33)],
                'analysis': {'physical_alignment_verified': False}}))
            bridge = SongAudio(manifest, factory=player_factory, binary='/fake/mpv', watch=False,
                visual_factory=FakeVisual, energy_factory=lambda _: SimpleNamespace(level_at=lambda position: .4),
                visual_available=lambda: True)
            self.assertIn('song.visual', bridge.capabilities())
            self.registry.offline(self.audio.device)
            self.audio = BridgeSocket(self.bus)
            self.audio.device = self.registry.register({'type': 'hello', 'room': 'TEST', 'id': 'laptop',
                'label': 'Real dispatcher, synthetic renderer and player', 'caps': bridge.capabilities()}, self.audio)
            try:
                program = await self.running()
                attached = await self.engine.dispatch(self.grant, 'program-update',
                    {'request_id': 'composed-attach', 'program_id': program.id, 'light_device_id': 'phone'})
                self.assertTrue(attached['ok'], attached)
                baseline = (program.run_id, program.phase, program.song_timeline,
                            program.light_tasks['phone'], dict(program.light_cadences))
                for visible in (True, False):
                    result = await self.visual(program, visible)
                    self.assertTrue(result['ok'], result)
                    self.assertIs(result['result']['visual']['acknowledged_visible'], visible)
                    self.assertFalse(result['result']['visual']['physical_rendering_verified'])
                self.assertEqual((program.run_id, program.phase, program.song_timeline,
                                  program.light_tasks['phone'], program.light_cadences), baseline)
                self.assertTrue(program.active)
                self.assertEqual([player.starts for player in players], [1])
                self.assertEqual([player.closes for player in players], [0])
                self.assertEqual(len(hosts), 1)
                self.assertEqual(hosts[0].closes, 1)
                self.assertEqual(len(hosts[0].frames), 1)
                self.assertEqual(hosts[0].frames[0]['level'], .4)
                self.assertEqual([frame['cap'] for frame in self.audio.frames].count('song.start'), 1)
                self.assertNotIn('song.stop', [frame['cap'] for frame in self.audio.frames])
                self.assertEqual([frame['args'] for frame in self.visual_frames()], [
                    {'program_id': program.run_id, 'visible': True},
                    {'program_id': program.run_id, 'visible': False}])
                stop = await self.engine.dispatch(self.grant, 'program-stop',
                    {'request_id': 'composed-stop', 'program_id': program.id})
                self.assertTrue(stop['ok'], stop)
                self.assertEqual(players[0].closes, 1)
            finally:
                bridge.stop_all()


if __name__ == '__main__':
    unittest.main()
