"""Synthetic PCM and fake processes/pipes only; never starts the real orb."""
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest import TestCase
from unittest.mock import Mock, patch
import wave

from agent.song_visual import EnergyEnvelope, OrbHost, VisualError


class FakeProcess:
    def __init__(self, ready=b'{"type":"ready","webgl":true,"transparent":true}\n'):
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        self.stdin = os.fdopen(input_write, 'wb', buffering=0)
        self.stdout = os.fdopen(output_read, 'rb', buffering=0)
        self.input_read, self.output_write = input_read, output_write
        self.code = None
        self.actions = []
        self.wait_failures = 0
        self.closed = False
        if ready:
            os.write(output_write, ready)

    def poll(self):
        return self.code

    def wait(self, timeout):
        self.actions.append(('wait', timeout))
        if self.wait_failures:
            self.wait_failures -= 1
            raise subprocess.TimeoutExpired('fake private host', timeout)
        self.code = 0
        return 0

    def terminate(self):
        self.actions.append(('terminate',))

    def kill(self):
        self.actions.append(('kill',))

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        for stream in (self.stdin, self.stdout):
            stream.close()
        os.close(self.input_read)
        os.close(self.output_write)


class EnvelopeTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'private.wav'

    def recording(self, values, *, channels=1, width=2, rate=8000):
        samples = array('h', values)
        if sys.byteorder != 'little':
            samples.byteswap()
        with wave.open(str(self.path), 'wb') as target:
            target.setnchannels(channels)
            target.setsampwidth(width)
            target.setframerate(rate)
            target.writeframes(samples.tobytes())
        return {'audio_path': str(self.path), 'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()}

    def test_silence_and_real_amplitude_follow_the_requested_playhead(self):
        envelope = EnergyEnvelope.from_recording(self.recording([0] * 400 + [16384] * 400))
        self.assertAlmostEqual(envelope.window_seconds, .025)
        self.assertEqual(envelope.level_at(0), 0)
        self.assertEqual(envelope.level_at(.049), 0)
        self.assertAlmostEqual(envelope.level_at(.05), .5)
        self.assertEqual(envelope.level_at(.1), 0)
        self.assertEqual(envelope.level_at(-1), 0)

    def test_opposite_phase_stereo_is_power_averaged_without_cancellation(self):
        envelope = EnergyEnvelope.from_recording(self.recording([16384, -16384] * 400, channels=2))
        self.assertAlmostEqual(envelope.level_at(.01), .5)

    def test_last_partial_window_uses_its_actual_sample_count(self):
        envelope = EnergyEnvelope.from_recording(self.recording([0] * 200 + [-32768] * 40))
        self.assertEqual(envelope.level_at(.027), 1)
        self.assertEqual(envelope.level_at(.031), 0)

    def test_cached_contour_still_requires_matching_current_file_bytes(self):
        recording = self.recording([1000] * 800)
        first = EnergyEnvelope.from_recording(recording)
        self.assertIs(EnergyEnvelope.from_recording(recording), first)
        self.path.write_bytes(b'changed private recording')
        with self.assertRaises(VisualError) as error:
            EnergyEnvelope.from_recording(recording)
        self.assertNotIn(str(self.path), str(error.exception))

    def test_unsupported_empty_or_invalid_audio_has_sanitized_error(self):
        for samples, options in (([], {}), ([1000] * 800, {'width': 1}),
                                 ([1000] * 900, {'channels': 3})):
            recording = self.recording(samples, **options)
            with self.subTest(options=options), self.assertRaises(VisualError) as error:
                EnergyEnvelope.from_recording(recording)
            self.assertNotIn(str(self.path), str(error.exception))
        self.path.write_bytes(b'malformed WAV with a valid checksum')
        invalid = ({'audio_path': str(self.path), 'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest()},
                   {'audio_path': str(self.path), 'sha256': '0' * 64}, {})
        for recording in invalid:
            with self.subTest(recording=recording), self.assertRaises(VisualError):
                EnergyEnvelope.from_recording(recording)

    def test_nonfinite_or_boolean_positions_are_rejected(self):
        envelope = EnergyEnvelope.from_recording(self.recording([1000] * 800))
        for value in (True, float('nan'), float('inf'), None, 'private', 10 ** 400):
            with self.subTest(value=value), self.assertRaises(VisualError):
                envelope.level_at(value)


class HostTests(TestCase):
    def process(self, ready=b'{"type":"ready","webgl":true,"transparent":true}\n'):
        process = FakeProcess(ready)
        self.addCleanup(process.dispose)
        return process

    def host(self, process=None, **kwargs):
        process = process if process is not None else self.process()
        popen = Mock(return_value=process)
        with patch.object(OrbHost, 'available', return_value=True):
            host = OrbHost(deadline=kwargs.pop('deadline', time.monotonic() + 2), popen=popen, **kwargs)
        self.addCleanup(host.close)
        return host, process, popen

    def test_readiness_and_exact_private_pipe_launch(self):
        host, process, popen = self.host()
        self.assertTrue(host.alive())
        argv = popen.call_args.args[0]
        self.assertTrue(Path(argv[0]).is_absolute())
        self.assertEqual(argv[1], '--assets')
        self.assertTrue(Path(argv[2]).is_absolute())
        self.assertEqual(len(argv), 3)
        self.assertEqual(popen.call_args.kwargs['stdin'], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs['stdout'], subprocess.PIPE)
        self.assertEqual(popen.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertEqual(popen.call_args.kwargs['bufsize'], 0)

    def test_available_only_checks_executable_and_complete_bundled_assets(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        binary, assets = base / 'TenantOrb', base / 'dist'
        assets.mkdir()
        binary.write_bytes(b'fake host, never executed')
        with patch('agent.song_visual.HOST_BINARY', binary), patch('agent.song_visual.ASSET_ROOT', assets):
            self.assertFalse(OrbHost.available())
            binary.chmod(0o700)
            for name in ('index.html', 'orb.js', 'style.css', 'perlin.png'):
                (assets / name).write_bytes(b'fake asset')
            self.assertTrue(OrbHost.available())
            (assets / 'orb.js').unlink()
            self.assertFalse(OrbHost.available())

    def test_invalid_ready_flags_types_shape_and_raw_errors_close_child(self):
        for ready in (b'private /secret/token\n', b'{"type":"error","message":"private"}\n',
                      b'{"type":"ready","webgl":1,"transparent":true}\n',
                      b'{"type":"ready","webgl":true,"transparent":false}\n',
                      b'{"type":"ready","webgl":true}\n'):
            process = self.process(ready)
            with self.subTest(ready=ready), patch.object(OrbHost, 'available', return_value=True):
                with self.assertRaises(VisualError) as error:
                    OrbHost(deadline=time.monotonic() + 1, popen=Mock(return_value=process))
                self.assertNotIn('private', str(error.exception))
                self.assertNotIn('secret', str(error.exception))
                self.assertIsNone(error.exception.owned_host)
                self.assertIsNotNone(process.poll())
                self.assertTrue(process.stdin.closed)

    def test_failed_readiness_retains_unreaped_host_for_exact_owned_cleanup(self):
        process = self.process(b'{"type":"error","message":"private /secret/token"}\n')
        process.wait_failures = 3
        with patch.object(OrbHost, 'available', return_value=True), self.assertRaises(VisualError) as caught:
            OrbHost(deadline=time.monotonic() + 1, popen=Mock(return_value=process))
        error = caught.exception
        self.assertIsNotNone(error.owned_host)
        self.assertIs(error.owned_host.process, process)
        self.assertIsNone(process.poll())
        self.assertEqual(error.args, ('The native visual host did not confirm readiness.',))
        self.assertNotIn('private', str(error))
        self.assertNotIn('secret', repr(error))
        self.assertNotIn('OrbHost', repr(error))
        self.assertTrue(error.owned_host.close())
        self.assertIsNotNone(process.poll())
        self.assertTrue(error.owned_host.close())

    def test_ready_accepts_geometry_extras_without_returning_private_fields(self):
        process = self.process(b'{"type":"ready","webgl":true,"transparent":true,"width":800,"height":600,"x":0,"y":0,"private":"secret"}\n')
        host, _, _ = self.host(process)
        self.assertTrue(host.alive())

    def test_fragmented_ready_line_is_assembled(self):
        process = self.process()
        with patch('agent.song_visual.os.read', side_effect=[b'{"type":"rea', b'dy","webgl":true,"transparent":true}\n']):
            host, _, _ = self.host(process)
        self.assertTrue(host.alive())

    def test_startup_timeout_is_bounded_and_closes_child(self):
        process = self.process(b'')
        now = [10.]
        def select_timeout(*args):
            now[0] += .1
            return [], [], []
        with patch.object(OrbHost, 'available', return_value=True), patch('agent.song_visual.select.select', side_effect=select_timeout):
            with self.assertRaises(VisualError):
                OrbHost(deadline=10.2, clock=lambda: now[0], popen=Mock(return_value=process))
        self.assertIsNotNone(process.poll())

    def test_frame_is_one_finite_json_line_and_no_runtime_command(self):
        host, process, _ = self.host()
        frame = {'playhead_seconds': 12.5, 'level': .4, 'playing': True}
        host.send(frame)
        self.assertEqual(json.loads(os.read(process.input_read, 4096)), frame)

    def test_invalid_frame_shapes_numbers_and_types_close_host_without_write(self):
        good = {'playhead_seconds': 1., 'level': .4, 'playing': True}
        for frame in ({}, dict(good, extra='private'), dict(good, level=True),
                      dict(good, level=math.inf), dict(good, level=-.1), dict(good, level=1.1),
                      dict(good, playhead_seconds=math.nan), dict(good, playhead_seconds=-1),
                      dict(good, playing=1)):
            host, process, _ = self.host()
            with self.subTest(frame=frame), patch('agent.song_visual.os.write') as write:
                with self.assertRaises(VisualError):
                    host.send(frame)
                write.assert_not_called()
            self.assertFalse(host.alive())

    def test_write_backpressure_and_partial_write_are_not_replayed(self):
        frame = {'playhead_seconds': 1., 'level': .4, 'playing': True}
        host, _, _ = self.host()
        with patch('agent.song_visual.select.select', return_value=([], [], [])), patch('agent.song_visual.os.write') as write:
            with self.assertRaises(VisualError):
                host.send(frame)
            write.assert_not_called()
        host, _, _ = self.host()
        with patch('agent.song_visual.os.write', return_value=1) as write:
            with self.assertRaises(VisualError):
                host.send(frame)
            self.assertEqual(write.call_count, 1)
        self.assertFalse(host.alive())

    def test_updates_continue_after_readiness_deadline_and_close_is_idempotent(self):
        host, process, _ = self.host()
        host.deadline = time.monotonic() - 1
        frame = {'playhead_seconds': 1., 'level': .4, 'playing': True}
        host.send(frame)
        self.assertEqual(json.loads(os.read(process.input_read, 4096)), frame)
        self.assertTrue(host.close())
        self.assertTrue(host.close())
        self.assertEqual(len(process.actions), 1)

    def test_cleanup_escalates_only_the_owned_child_when_eof_does_not_exit(self):
        host, process, _ = self.host()
        process.wait_failures = 2
        self.assertTrue(host.close())
        self.assertEqual([action[0] for action in process.actions], ['wait', 'terminate', 'wait', 'kill', 'wait'])

    def test_cleanup_reports_unconfirmed_when_owned_process_does_not_exit(self):
        host, process, _ = self.host()
        process.wait_failures = 3
        self.assertFalse(host.close())
        self.assertFalse(host.alive())
        self.assertIsNone(process.poll())

    def test_deadline_before_start_refuses_process_creation(self):
        spawn = Mock()
        with patch.object(OrbHost, 'available', return_value=True), self.assertRaises(VisualError):
            OrbHost(deadline=1, clock=lambda: 2, popen=spawn)
        spawn.assert_not_called()

    def test_missing_runtime_or_spawn_failure_never_leaks_private_errors(self):
        for available, error in ((False, None), (True, OSError('private /secret/token'))):
            spawn = Mock(side_effect=error)
            with self.subTest(available=available), patch.object(OrbHost, 'available', return_value=available):
                with self.assertRaises(VisualError) as failure:
                    OrbHost(deadline=time.monotonic() + 1, popen=spawn)
                self.assertNotIn('private', str(failure.exception))
            if not available:
                spawn.assert_not_called()
