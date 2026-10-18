"""WAV inspection and fake processes only. Never invokes afplay or makes sound."""
from array import array
from pathlib import Path
import tempfile
import threading
import unittest
import wave

from agent.beat_audio import BeatAudio, BeatError, render_beat
from agent.laptop import AudioDispatcher


class Process:
    def __init__(self):
        self.code = None
        self.terminated = False
    def poll(self): return self.code
    def terminate(self): self.terminated, self.code = True, 0
    def wait(self, timeout): return self.code
    def kill(self): self.code = -9


class BeatTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000
        self.calls, self.processes = [], []
        def popen(argv, **kwargs):
            self.calls.append((argv, kwargs))
            process = Process()
            self.processes.append(process)
            return process
        self.audio = BeatAudio(popen=popen, wall_clock=lambda: self.now,
                               sleep=lambda delay: setattr(self, 'now', self.now + delay), watch=False)

    def tearDown(self):
        self.audio.close()

    def start(self, program='one', bpm=120):
        self.audio.dispatch('beat.prepare', {'program_id': program, 'bpm': bpm,
            'expires_at_ms': (self.now + .4) * 1000})
        return self.audio.dispatch('beat.start', {'program_id': program})

    def test_rendered_wave_has_requested_duration_and_deterministic_nonzero_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('a.wav', 'b.wav')]
            for path in paths: render_beat(path, 120, 1)
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
            with wave.open(str(paths[0])) as audio:
                self.assertEqual(audio.getnframes(), 22050)
                self.assertEqual(audio.getnchannels(), 1)
                samples = array('h', audio.readframes(audio.getnframes()))
                self.assertGreater(max(samples), 0)
                self.assertLessEqual(max(abs(x) for x in samples), round(.4 * 32767))

    def test_noninteger_sample_period_does_not_accumulate_phase_rounding_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'phase.wav'
            render_beat(path, 137, 10)
            with wave.open(str(path)) as audio:
                samples = array('h', audio.readframes(audio.getnframes()))
            self.assertGreater(samples[1], 0)
            for beat in range(1, 22):
                boundary = round(beat * 22050 * 60 / 137)
                self.assertEqual(samples[boundary + 1], samples[1])

    def test_launch_uses_default_afplay_only_and_stop_is_scoped_to_program_id(self):
        first, second = self.start('one'), self.start('two')
        self.assertEqual(first['state'], 'launched')
        self.assertFalse(first['audible_verified'])
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(all(call[0][0] == '/usr/bin/afplay' and len(call[0]) == 2 for call in self.calls))
        result = self.audio.dispatch('beat.stop', {'program_id': 'one'})
        self.assertTrue(result['stopped'])
        self.assertTrue(self.processes[0].terminated)
        self.assertFalse(self.processes[1].terminated)
        self.assertEqual(self.audio.status('two')['state'], second['state'])

    def test_same_program_id_is_never_replayed(self):
        self.start()
        with self.assertRaises(BeatError): self.start()
        self.audio.stop('one')
        with self.assertRaises(BeatError): self.start()
        self.assertEqual(len(self.calls), 1)

    def test_failed_spawn_consumes_prepared_program_without_retry(self):
        self.audio.dispatch('beat.prepare', {'program_id': 'one', 'bpm': 120,
            'expires_at_ms': (self.now + 1) * 1000})
        attempts = []
        def fail(*args, **kwargs):
            attempts.append(args)
            raise OSError('Synthetic spawn failure')
        self.audio.popen = fail
        with self.assertRaises(BeatError): self.audio.dispatch('beat.start', {'program_id': 'one'})
        with self.assertRaises(BeatError): self.audio.dispatch('beat.start', {'program_id': 'one'})
        self.assertEqual(len(attempts), 1)

    def test_expiry_and_invalid_timing_start_nothing(self):
        for bpm in (0, -1, float('nan'), True):
            with self.assertRaises(BeatError): self.start(bpm=bpm)
        with self.assertRaises(BeatError):
            self.audio.dispatch('beat.prepare', {'program_id': 'expired', 'bpm': 120,
                'expires_at_ms': 999999})
        self.assertEqual(self.calls, [])

    def test_watchdog_stops_expired_owned_program_and_disconnect_stops_all(self):
        self.start()
        self.now += 1
        self.audio._watch(self.audio.jobs['one'])
        self.assertEqual(self.audio.status('one')['state'], 'expired')
        self.start('two')
        self.assertTrue(self.audio.close())
        self.assertTrue(all(p.terminated for p in self.processes))

    def test_generated_beat_capabilities_do_not_require_music_library(self):
        dispatcher = AudioDispatcher(system='Darwin', exists=lambda path: path.endswith('afplay'), beats=self.audio)
        self.assertEqual(set(dispatcher.capabilities()), {'beat.prepare', 'beat.start', 'beat.stop', 'beat.status'})
        prepared = dispatcher.dispatch('beat.prepare', {'program_id': 'one', 'bpm': 120,
            'expires_at_ms': (self.now + .4) * 1000})
        self.assertEqual(prepared['state'], 'prepared')
        result = dispatcher.dispatch('beat.start', {'program_id': 'one'})
        self.assertEqual(result['state'], 'launched')

    def test_preparation_never_plays_and_cancel_before_start_prevents_late_playback(self):
        result = self.audio.dispatch('beat.prepare', {'program_id': 'one', 'bpm': 120,
            'expires_at_ms': (self.now + 1) * 1000})
        self.assertEqual(result['state'], 'prepared')
        self.assertEqual(self.calls, [])
        self.audio.stop('one')
        with self.assertRaises(BeatError):
            self.audio.dispatch('beat.start', {'program_id': 'one'})
        self.assertEqual(self.calls, [])

    def test_blocked_preparation_does_not_block_another_jobs_stop_or_spawn_after_cancel(self):
        self.start('one')
        entered, release = threading.Event(), threading.Event()
        errors = []
        def gated_render(path, bpm, duration, *, permitted):
            entered.set()
            release.wait(1)
            if not permitted():
                raise BeatError('FAILED', 'Stopped during preparation.')
            render_beat(path, bpm, duration, permitted=permitted)
        self.audio.render = gated_render
        def prepare():
            try:
                self.audio.dispatch('beat.prepare', {'program_id': 'two', 'bpm': 120,
                    'expires_at_ms': (self.now + 1) * 1000})
            except BeatError as error:
                errors.append(error.code)
        worker = threading.Thread(target=prepare)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            self.assertTrue(self.audio.stop('one')['stopped'])
            self.assertTrue(self.processes[0].terminated)
            self.audio.stop('two')
        finally:
            release.set()
            worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ['FAILED'])
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
