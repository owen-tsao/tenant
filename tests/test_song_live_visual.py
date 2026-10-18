"""Offline live-overlay lifecycle tests; synthetic WAV and fake players only."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
import wave

from agent.song_audio import SongAudio, SongError


class Player:
    def __init__(self, recording, *, binary):
        self.recording, self.binary = recording, binary
        self.process = SimpleNamespace(poll=lambda: self.exit_code)
        self.exit_code = None
        self.state, self.position, self.rate = 'paused', .25, 1
        self.starts, self.closes = 0, 0
        self.reads = []
        self.error = None

    def start(self, deadline):
        self.starts += 1
        self.state = 'playing'

    def snapshot(self, deadline):
        self.reads.append(deadline)
        if self.error:
            raise self.error
        return {'state': self.state, 'position_seconds': self.position, 'rate': self.rate}

    def close(self):
        self.closes += 1
        self.exit_code = 0
        self.state = 'stopped'
        return True


class Host:
    def __init__(self, *, deadline):
        self.deadline = deadline
        self.frames = []
        self.closes = 0
        self.is_alive = True
        self.close_result = True
        self.error = None

    def send(self, frame):
        if self.error:
            raise self.error
        self.frames.append(copy.deepcopy(frame))
        return True

    def alive(self):
        return self.is_alive

    def close(self):
        self.closes += 1
        if self.close_result:
            self.is_alive = False
        return self.close_result


class Envelope:
    def __init__(self):
        self.positions = []

    def level_at(self, position):
        self.positions.append(position)
        return .625


class SongLiveVisualTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / 'selected.wav'
        with wave.open(str(self.path), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(8000)
            stream.writeframes(b'\0\0' * 16000)
        self.record = {'song_id': 'daniel-caesar-selected', 'artist': 'Daniel Caesar',
            'title': 'Selected test fixture', 'audio_path': str(self.path),
            'sha256': hashlib.sha256(self.path.read_bytes()).hexdigest(),
            'duration_seconds': 2, 'beat_seconds': [.1, .7, 1.3],
            'analysis': {'physical_alignment_verified': False}}
        self.manifest = Path(self.directory) / 'song.json'
        self.manifest.write_text(json.dumps(self.record))
        self.now, self.wall = 10., 1000.
        self.players, self.hosts, self.energy_recordings = [], [], []
        self.envelope = Envelope()
        self.audio = self.make_audio()
        self.addCleanup(self.audio.stop_all)

    def make_audio(self, **overrides):
        def player(recording, *, binary):
            result = Player(recording, binary=binary)
            self.players.append(result)
            return result
        def visual(*, deadline):
            result = Host(deadline=deadline)
            self.hosts.append(result)
            return result
        def energy(recording):
            self.energy_recordings.append(recording)
            return self.envelope
        options = dict(factory=player, clock=lambda: self.now, wall_clock=lambda: self.wall,
                       watch=False, binary='/fake/mpv', visual_factory=visual,
                       energy_factory=energy, visual_available=lambda: True)
        options.update(overrides)
        return SongAudio(self.manifest, **options)

    def prepare(self, identifier='one'):
        return self.audio.dispatch('song.prepare', {'program_id': identifier,
            'song_id': self.record['song_id'], 'expires_at_ms': (self.wall + 30) * 1000})

    def action(self, name, identifier='one'):
        return self.audio.dispatch('song.' + name, {'program_id': identifier})

    def visual(self, show=True, identifier='one'):
        return self.audio.dispatch('song.visual', {'program_id': identifier, 'visible': show})

    def playing(self):
        self.prepare()
        self.action('start')
        return self.audio.jobs['one'], self.players[0]

    def shown(self):
        job, player = self.playing()
        self.visual()
        return job, player, self.hosts[0]

    def advance(self, job, player, delta=.1):
        self.now += delta
        player.position += delta
        self.audio._visual_tick(job)

    def test_visual_capability_requires_available_host_and_loaded_energy(self):
        capability = self.audio.capabilities()['song.visual']
        self.assertEqual(set(capability['args']), {'program_id', 'visible'})
        unavailable = self.make_audio(visual_available=lambda: False)
        self.addCleanup(unavailable.stop_all)
        self.assertNotIn('song.visual', unavailable.capabilities())
        def broken(recording):
            raise RuntimeError('private media path must not escape')
        no_energy = self.make_audio(energy_factory=broken)
        self.addCleanup(no_energy.stop_all)
        self.assertIn('song.start', no_energy.capabilities())
        self.assertNotIn('song.visual', no_energy.capabilities())
        self.assertEqual(self.players, [])
        self.assertEqual(self.hosts, [])

    def test_legacy_prepared_mp4_never_advertises_second_overlay(self):
        old = Path(self.directory) / 'old.mp4'
        old.write_bytes(b'old reviewed fixture')
        self.record['visual'] = {'path': str(old), 'sha256': hashlib.sha256(old.read_bytes()).hexdigest(),
            'source_sha256': self.record['sha256'], 'width': 64, 'height': 64, 'fps': 30,
            'duration_seconds': 2, 'description': 'legacy fixture'}
        self.manifest.write_text(json.dumps(self.record))
        legacy = self.make_audio()
        self.addCleanup(legacy.stop_all)
        self.assertIn('song.start', legacy.capabilities())
        self.assertNotIn('song.visual', legacy.capabilities())

    def test_show_requires_existing_started_playing_program(self):
        with self.assertRaises(SongError):
            self.visual()
        self.prepare()
        with self.assertRaises(SongError):
            self.visual()
        self.assertEqual(self.hosts, [])
        self.assertEqual(self.players[0].starts, 0)

    def test_show_rejects_nonboolean_and_extra_arguments(self):
        self.playing()
        for args in ({'program_id': 'one', 'visible': 1}, {'program_id': 'one', 'visible': 'true'},
                     {'program_id': 'one', 'visible': True, 'path': '/private'}, {'program_id': 'one'}):
            with self.subTest(args=args), self.assertRaises(SongError):
                self.audio.dispatch('song.visual', args)
        self.assertEqual(self.hosts, [])

    def test_show_refuses_unverified_player_states_without_restarting(self):
        job, player = self.playing()
        for state in ('paused', 'ended', 'buffering', 'loading'):
            with self.subTest(state=state):
                player.state = state
                with self.assertRaises(SongError):
                    self.visual()
        self.assertEqual(self.hosts, [])
        self.assertEqual(len(self.players), 1)
        self.assertEqual(player.starts, 1)
        self.assertEqual(job.expires, 40.)

    def test_show_attaches_once_to_same_player_with_original_absolute_expiry(self):
        job, player = self.playing()
        self.now = 14.
        before = player.position
        first = self.visual()
        repeated = self.visual()
        self.assertEqual(first['program_id'], 'one')
        self.assertIs(first['visible'], True)
        self.assertEqual(first['visual_state'], 'attached')
        self.assertTrue(first['visual_ready'])
        self.assertFalse(first['physical_visibility_verified'])
        self.assertEqual(repeated['visual_state'], 'attached')
        self.assertEqual(len(self.players), 1)
        self.assertEqual(player.starts, 1)
        self.assertEqual(player.position, before)
        self.assertEqual(player.closes, 0)
        self.assertEqual(len(self.hosts), 1)
        self.assertEqual(self.hosts[0].deadline, min(self.now + 4, job.expires))
        self.assertEqual(job.expires, 40.)
        self.assertFalse(job.cancelled.is_set())

    def test_tick_uses_actual_playhead_and_energy_without_audio_mutation(self):
        job, player, host = self.shown()
        self.advance(job, player)
        frame = host.frames[-1]
        self.assertEqual(frame['playhead_seconds'], player.position)
        self.assertEqual(frame['level'], .625)
        self.assertIs(frame['playing'], True)
        self.assertEqual(self.envelope.positions[-1], player.position)
        self.assertEqual(player.starts, 1)
        self.assertEqual(player.closes, 0)
        self.assertEqual(len(self.players), 1)

    def test_hide_is_idempotent_and_only_closes_overlay(self):
        job, player, host = self.shown()
        result = self.visual(False)
        self.visual(False)
        self.assertEqual(result['program_id'], 'one')
        self.assertIs(result['visible'], False)
        self.assertEqual(result['visual_state'], 'hidden')
        self.assertFalse(result['visual_ready'])
        self.assertFalse(result['physical_visibility_verified'])
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.closes, 0)
        self.assertEqual(player.state, 'playing')
        self.assertEqual(player.starts, 1)
        self.assertEqual(job.expires, 40.)
        self.assertFalse(job.cancelled.is_set())
        count = len(host.frames)
        self.advance(job, player)
        self.assertEqual(len(host.frames), count)
        self.assertEqual(len(self.hosts), 1)

    def test_overlay_failure_does_not_stop_or_recreate_music(self):
        job, player, host = self.shown()
        host.error = RuntimeError('private overlay failure')
        self.advance(job, player)
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.closes, 0)
        self.assertEqual(player.state, 'playing')
        self.assertFalse(job.cancelled.is_set())
        self.assertEqual(player.starts, 1)
        self.assertEqual(len(self.players), 1)

    def test_exited_overlay_closes_without_stopping_music(self):
        job, player, host = self.shown()
        host.is_alive = False
        self.advance(job, player)
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.closes, 0)
        self.assertEqual(player.starts, 1)

    def test_pause_buffering_and_ended_close_overlay(self):
        for state in ('paused', 'buffering', 'ended'):
            with self.subTest(state=state):
                identifier = 'program_' + state
                self.prepare(identifier)
                self.action('start', identifier)
                self.visual(True, identifier)
                job, player, host = self.audio.jobs[identifier], self.players[-1], self.hosts[-1]
                player.state = state
                self.audio._visual_tick(job)
                self.assertEqual(host.closes, 1)
                self.action('stop', identifier)

    def test_zero_and_backward_playhead_close_overlay(self):
        for position in (0., .1):
            with self.subTest(position=position):
                identifier = 'program_' + str(position).replace('.', '_')
                self.prepare(identifier)
                self.action('start', identifier)
                self.visual(True, identifier)
                job, player, host = self.audio.jobs[identifier], self.players[-1], self.hosts[-1]
                player.position = position
                self.now += .1
                self.audio._visual_tick(job)
                self.assertEqual(host.closes, 1)
                self.action('stop', identifier)

    def test_rate_or_source_verification_error_closes_only_overlay(self):
        for kind in ('rate', 'source'):
            with self.subTest(kind=kind):
                identifier = 'program_' + kind
                self.prepare(identifier)
                self.action('start', identifier)
                self.visual(True, identifier)
                job, player, host = self.audio.jobs[identifier], self.players[-1], self.hosts[-1]
                if kind == 'rate':
                    player.rate = 2
                else:
                    player.error = SongError('FAILED', 'The selected recording changed.')
                self.audio._visual_tick(job)
                self.assertEqual(host.closes, 1)
                self.assertEqual(player.closes, 0)
                self.assertEqual(player.starts, 1)
                self.action('stop', identifier)

    def test_frozen_playhead_eventually_closes_without_audio_restart(self):
        job, player, host = self.shown()
        for _ in range(30):
            self.now += .1
            self.audio._visual_tick(job)
            if host.closes:
                break
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.starts, 1)
        self.assertEqual(player.closes, 0)

    def test_expiry_and_player_exit_close_both_owned_resources(self):
        job, player, host = self.shown()
        self.now = job.expires
        self.audio._watch('one')
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.closes, 1)
        self.assertTrue(job.stopped)
        self.prepare('two')
        self.action('start', 'two')
        self.visual(True, 'two')
        self.players[-1].exit_code = 0
        self.audio._watch('two')
        self.assertEqual(self.hosts[-1].closes, 1)
        self.assertEqual(self.players[-1].closes, 1)

    def test_stop_and_disconnect_close_overlay_and_player_once(self):
        job, player, host = self.shown()
        self.action('stop')
        self.audio.stop_all()
        self.audio.stop_all()
        self.assertEqual(host.closes, 1)
        self.assertEqual(player.closes, 1)
        self.assertTrue(job.stopped)

    def test_overlay_startup_racing_stop_never_leaks_or_claims_pending_cleanup(self):
        entered, release = threading.Event(), threading.Event()
        def delayed_factory(*, deadline):
            host = Host(deadline=deadline)
            self.hosts.append(host)
            entered.set()
            if not release.wait(2):
                raise RuntimeError('test release timed out')
            return host
        self.audio = self.make_audio(visual_factory=delayed_factory)
        self.addCleanup(self.audio.stop_all)
        job, player = self.playing()
        shows, stops = [], []
        def show():
            try:
                shows.append(self.visual())
            except Exception as error:
                shows.append(error)
        def stop():
            try:
                stops.append(self.action('stop'))
            except Exception as error:
                stops.append(error)
        show_thread = threading.Thread(target=show)
        stop_thread = threading.Thread(target=stop)
        show_thread.start()
        try:
            self.assertTrue(entered.wait(1))
            stop_thread.start()
            self.assertTrue(job.cancelled.wait(1))
            if stops and isinstance(stops[0], dict):
                self.assertFalse(stops[0].get('stopped'), 'in-flight host has not confirmed cleanup')
        finally:
            release.set()
            show_thread.join(2)
            if stop_thread.ident is not None:
                stop_thread.join(2)
        self.assertFalse(show_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.audio.stop_all()
        self.assertEqual(len(self.hosts), 1)
        self.assertEqual(self.hosts[0].closes, 1)
        self.assertEqual(player.closes, 1)
        self.assertEqual(player.starts, 1)
        self.assertTrue(job.stopped)

    def test_overlay_constructor_failure_is_private_and_keeps_music_playing(self):
        def broken(*, deadline):
            raise RuntimeError('PRIVATE-OVERLAY-DETAIL')
        self.audio = self.make_audio(visual_factory=broken)
        self.addCleanup(self.audio.stop_all)
        job, player = self.playing()
        with self.assertRaises(SongError) as caught:
            self.visual()
        self.assertNotIn('PRIVATE-OVERLAY-DETAIL', str(caught.exception))
        self.assertEqual(player.closes, 0)
        self.assertEqual(player.starts, 1)
        self.assertEqual(player.state, 'playing')
        self.assertFalse(job.cancelled.is_set())

    def test_unconfirmed_hide_retains_owned_host_for_honest_retry(self):
        job, player, host = self.shown()
        host.close_result = False
        with self.assertRaises(SongError) as caught:
            self.visual(False)
        self.assertEqual(caught.exception.code, 'UNKNOWN')
        self.assertTrue(host.alive())
        self.assertEqual(player.closes, 0)
        self.assertEqual(player.state, 'playing')
        host.close_result = True
        result = self.visual(False)
        self.assertEqual(result['program_id'], 'one')
        self.assertIs(result['visible'], False)
        self.assertEqual(result['visual_state'], 'hidden')
        self.assertFalse(host.alive())
        self.assertEqual(host.closes, 2)

    def test_cancelled_unpublished_host_cleanup_failure_stays_owned(self):
        def cancelled_factory(*, deadline):
            host = Host(deadline=deadline)
            host.close_result = False
            self.hosts.append(host)
            self.audio.jobs['one'].cancelled.set()
            return host
        self.audio = self.make_audio(visual_factory=cancelled_factory)
        self.addCleanup(self.audio.stop_all)
        job, player = self.playing()
        try:
            with self.assertRaises(SongError):
                self.visual()
            host = self.hosts[0]
            self.assertFalse(job.stopped and host.alive(), 'unconfirmed child cleanup cannot be reported stopped')
        finally:
            if self.hosts:
                self.hosts[0].close_result = True
                self.audio.stop_all()
        self.assertFalse(self.hosts[0].alive())
        self.assertTrue(job.stopped)

    def test_expired_program_never_creates_overlay(self):
        job, player = self.playing()
        self.now = job.expires
        try:
            self.visual()
        except SongError:
            pass
        self.assertEqual(self.hosts, [])
        self.assertEqual(player.starts, 1)


if __name__ == '__main__':
    unittest.main()
