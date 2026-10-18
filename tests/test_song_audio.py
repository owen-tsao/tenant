"""Selected recording lifecycle with synthetic WAV/fake players; never makes sound."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from agent.song_audio import MpvPlayer, SongAudio, SongError, load_recording, validate_map
from agent.prepare_song import SOURCE, SOURCE_ID, prepare as prepare_source
from agent.laptop import AudioDispatcher, AudioError, DeviceAgent


class FakeProcess:
    def __init__(self):
        self.code = None

    def poll(self):
        return self.code


class FakePlayer:
    def __init__(self, recording, *, binary):
        self.recording, self.binary = recording, binary
        self.process = FakeProcess()
        self.starts, self.closes = 0, 0
        self.state = 'paused'
        self.start_error = None
        self.snapshot_error = None

    def start(self, deadline):
        self.starts += 1
        self.state = 'playing'
        if self.start_error:
            raise self.start_error

    def snapshot(self, deadline):
        if self.snapshot_error:
            raise self.snapshot_error
        return {'state': self.state, 'position_seconds': .25, 'rate': 1}

    def close(self):
        self.closes += 1
        self.process.code = 0
        self.state = 'stopped'
        return True


class SongAudioTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'selected.wav'
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
        self.manifest = Path(self.directory.name) / 'song.json'
        self.write_manifest()
        self.now, self.wall = 10., 1000.
        self.players = []

        def factory(recording, *, binary):
            player = FakePlayer(recording, binary=binary)
            self.players.append(player)
            return player

        self.audio = SongAudio(self.manifest, factory=factory, clock=lambda: self.now,
            wall_clock=lambda: self.wall, watch=False, binary='/fake/mpv')
        self.addCleanup(self.audio.stop_all)

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.record))

    def prepare(self, identifier='one'):
        return self.audio.dispatch('song.prepare', {'program_id': identifier,
            'song_id': self.record['song_id'], 'expires_at_ms': (self.wall + 30) * 1000})

    def dispatch(self, capability, identifier='one'):
        return self.audio.dispatch('song.' + capability, {'program_id': identifier})

    def test_missing_asset_or_player_advertises_no_song_actions(self):
        self.assertEqual(SongAudio().capabilities(), {})
        self.assertEqual(SongAudio(self.manifest, binary='/fake/mpv').capabilities().keys(),
                         self.audio.capabilities().keys())
        with patch('agent.song_audio.shutil.which', return_value=None):
            self.assertEqual(SongAudio(self.manifest).capabilities(), {})
        self.path.unlink()
        self.assertEqual(SongAudio(self.manifest, binary='/fake/mpv').capabilities(), {})
        self.assertEqual(self.players, [])

    def test_invalid_beat_map_and_identity_rejected(self):
        bad_fields = {'song_id': '../other', 'artist': 'Other artist', 'sha256': 'x' * 64,
            'duration_seconds': float('nan'), 'beat_seconds': [0, .5, .5]}
        for key, value in bad_fields.items():
            with self.subTest(key=key), self.assertRaises(SongError):
                validate_map(dict(self.record, **{key: value}))
        for beats in ([0, 1, 2], [0, True, 1], [0, .5], [0, .5, float('inf')]):
            with self.subTest(beats=beats), self.assertRaises(SongError):
                validate_map(dict(self.record, beat_seconds=beats))

    def test_changed_recording_rejected_both_at_load_and_before_prepare(self):
        self.path.write_bytes(b'different bytes')
        with self.assertRaises(SongError):
            load_recording(self.manifest)
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players, [])

    def test_replaced_manifest_cannot_hide_mutation_of_original_playback_asset(self):
        substitute = self.path.with_name('substitute.wav')
        substitute.write_bytes(self.path.read_bytes())
        self.record['audio_path'] = str(substitute)
        self.write_manifest()
        self.path.write_bytes(b'original recording was replaced')
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players, [], 'Manifest substitution cannot redirect validation away from played bytes')

    def test_exact_song_selection_required_and_private_path_never_returned(self):
        with self.assertRaises(SongError):
            self.audio.dispatch('song.prepare', {'program_id': 'wrong',
                'song_id': 'some-other-song', 'expires_at_ms': (self.wall + 30) * 1000})
        result = self.prepare()
        self.assertEqual(result['recording']['song_id'], self.record['song_id'])
        self.assertEqual(result['recording']['sha256'], self.record['sha256'])
        self.assertNotIn('audio_path', result['recording'])
        self.assertNotIn(str(self.path), json.dumps(result))
        self.assertEqual(len(self.players), 1)

    def test_prepare_never_starts_and_cancel_prevents_late_start(self):
        result = self.prepare()
        self.assertEqual(result['state'], 'prepared')
        self.assertFalse(result['audible_verified'])
        self.assertEqual(self.players[0].starts, 0)
        self.dispatch('stop')
        self.dispatch('start')
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)

    def test_start_once_and_used_program_cannot_be_prepared_again(self):
        self.prepare()
        result = self.dispatch('start')
        self.assertEqual(result['state'], 'playing')
        self.assertFalse(result['audible_verified'])
        with self.assertRaises(SongError):
            self.dispatch('start')
        self.dispatch('stop')
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players[0].starts, 1)
        self.assertEqual(len(self.players), 1)

    def test_uncertain_start_is_not_replayed(self):
        self.prepare()
        self.players[0].start_error = SongError('UNKNOWN', 'Synthetic lost receipt')
        with self.assertRaises(SongError) as first:
            self.dispatch('start')
        self.assertEqual(first.exception.code, 'UNKNOWN')
        with self.assertRaises(SongError) as second:
            self.dispatch('start')
        self.assertEqual(second.exception.code, 'CONFLICT')
        self.assertEqual(self.players[0].starts, 1)
        self.dispatch('stop')
        self.assertEqual(self.players[0].closes, 1)

    def test_expired_access_cannot_create_or_start_player(self):
        with self.assertRaises(SongError):
            self.audio.dispatch('song.prepare', {'program_id': 'expired',
                'song_id': self.record['song_id'], 'expires_at_ms': self.wall * 1000})
        self.assertEqual(self.players, [])
        self.prepare()
        self.now += 31
        result = self.dispatch('start')
        self.assertEqual(result['state'], 'stopped')
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)

    def test_watchdog_expiry_and_player_exit_clean_owned_resources(self):
        self.prepare()
        self.now += 31
        self.audio._watch('one')
        self.assertEqual(self.players[0].closes, 1)
        self.prepare('two')
        self.players[1].process.code = 7
        self.audio._watch('two')
        self.assertEqual(self.players[1].closes, 1)
        self.assertTrue(self.audio.jobs['two'].stopped)

    def test_disconnect_stop_all_is_idempotent_and_allows_new_program(self):
        self.prepare()
        self.dispatch('start')
        self.audio.stop_all()
        self.audio.stop_all()
        self.assertEqual(self.players[0].closes, 1)
        self.prepare('two')
        self.audio.stop_all()
        self.assertEqual([player.closes for player in self.players], [1, 1])

    def test_status_and_wall_clock_changes_never_extend_original_monotonic_expiry(self):
        self.prepare()
        original_expiry = self.audio.jobs['one'].expires
        deadlines = []
        player = self.players[0]
        original_snapshot = player.snapshot

        def snapshot(deadline):
            deadlines.append(deadline)
            return original_snapshot(deadline)

        player.snapshot = snapshot
        self.now, self.wall = 20., 1_000_000.
        self.assertEqual(self.dispatch('status')['state'], 'paused')
        self.now, self.wall = 30., -1_000_000.
        self.assertEqual(self.dispatch('status')['state'], 'paused')
        self.now = original_expiry - .5
        self.assertEqual(self.dispatch('start')['state'], 'playing')
        self.assertEqual(self.audio.jobs['one'].expires, original_expiry)
        self.assertEqual(deadlines[-1], original_expiry)
        self.now = original_expiry
        self.assertEqual(self.dispatch('status')['state'], 'stopped')
        self.assertEqual(self.audio.jobs['one'].expires, original_expiry)
        self.assertEqual(player.starts, 1)
        self.assertEqual(player.closes, 1)

    def test_dispatcher_routes_exact_selected_song_without_running_other_audio_adapters(self):
        beats, runner = Mock(), Mock(side_effect=AssertionError('OS runner must not be used'))
        dispatcher = AudioDispatcher(system='Darwin', exists=lambda path: False,
            beats=beats, songs=self.audio, runner=runner)
        self.assertEqual(set(dispatcher.capabilities()),
            {'song.prepare', 'song.start', 'song.status', 'song.stop'})
        wrong = {'program_id': 'wrong', 'song_id': 'not-the-selected-song',
                 'expires_at_ms': (self.wall + 30) * 1000}
        with self.assertRaises(AudioError) as error:
            dispatcher.dispatch('song.prepare', wrong)
        self.assertEqual(error.exception.code, 'INVALID')
        self.assertEqual(self.players, [])
        prepared = dispatcher.dispatch('song.prepare', {'program_id': 'one',
            'song_id': self.record['song_id'], 'expires_at_ms': (self.wall + 30) * 1000})
        self.assertEqual(prepared['recording']['song_id'], self.record['song_id'])
        self.assertEqual(self.players[0].starts, 0)
        started = dispatcher.dispatch('song.start', {'program_id': 'one'})
        self.assertEqual(started['song_id'], self.record['song_id'])
        self.assertEqual(started['sha256'], self.record['sha256'])
        self.assertEqual(dispatcher.dispatch('song.status', {'program_id': 'one'})['state'], 'playing')
        self.assertTrue(dispatcher.dispatch('song.stop', {'program_id': 'one'})['stopped'])
        beats.dispatch.assert_not_called()
        runner.assert_not_called()
        self.assertEqual(self.players[0].starts, 1)
        self.assertEqual(self.players[0].closes, 1)

    def test_device_disconnect_closes_song_even_when_generated_beat_cleanup_raises(self):
        self.prepare()
        self.dispatch('start')
        beats = Mock()
        beats.close.side_effect = RuntimeError('Synthetic beat cleanup failure')
        dispatcher = AudioDispatcher(system='Darwin', exists=lambda path: False,
            beats=beats, songs=self.audio,
            runner=Mock(side_effect=AssertionError('OS runner must not be used')))

        class DisconnectedSocket:
            def __init__(self):
                self.sent = []

            async def send(self, payload):
                self.sent.append(json.loads(payload))

            async def __aiter__(self):
                for frame in ():
                    yield frame

        socket = DisconnectedSocket()
        with self.assertRaisesRegex(RuntimeError, 'Synthetic beat cleanup failure'):
            asyncio.run(DeviceAgent(dispatcher, 'ROOM').session(socket))
        self.assertEqual(len(socket.sent), 1)
        self.assertEqual(socket.sent[0]['type'], 'hello')
        beats.close.assert_called_once_with()
        self.assertEqual(self.players[0].closes, 1)
        self.assertTrue(self.audio.jobs['one'].stopped)

    def test_failed_preparation_closes_player_and_consumes_identifier(self):
        original = self.audio.factory

        def failing_factory(*args, **kwargs):
            player = original(*args, **kwargs)
            player.snapshot_error = SongError('UNKNOWN', 'Synthetic preparation failure')
            return player

        self.audio.factory = failing_factory
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players[0].closes, 1)
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(len(self.players), 1)

    def test_preparation_must_confirm_paused_and_close_unexpected_playing_player(self):
        original = self.audio.factory

        def unpaused_factory(*args, **kwargs):
            player = original(*args, **kwargs)
            player.state = 'playing'
            return player

        self.audio.factory = unpaused_factory
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)
        self.assertTrue(self.audio.jobs['one'].stopped)

    def test_preparation_that_outlasts_access_closes_without_starting(self):
        original = self.audio.factory

        def late_factory(*args, **kwargs):
            player = original(*args, **kwargs)
            self.now += 31
            return player

        self.audio.factory = late_factory
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)

    def test_failed_spawn_is_consumed_and_a_new_program_can_be_prepared(self):
        original = self.audio.factory
        attempts = []

        def fail(*args, **kwargs):
            attempts.append(1)
            raise OSError('Synthetic spawn failure')

        self.audio.factory = fail
        with self.assertRaises(OSError):
            self.prepare()
        with self.assertRaises(SongError):
            self.prepare()
        self.assertEqual(len(attempts), 1)
        self.audio.factory = original
        self.assertEqual(self.prepare('two')['state'], 'prepared')

    def test_cancel_during_blocked_preparation_returns_promptly_and_never_becomes_ready(self):
        entered, release, stop_done = threading.Event(), threading.Event(), threading.Event()
        errors, results = [], []
        original = self.audio.factory

        def blocked_factory(*args, **kwargs):
            player = original(*args, **kwargs)
            entered.set()
            release.wait(2)
            return player

        self.audio.factory = blocked_factory

        def preparing():
            try:
                results.append(self.prepare())
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=preparing)
        worker.start()
        self.assertTrue(entered.wait(1))

        def stopping():
            self.audio.stop('one')
            stop_done.set()

        stopper = threading.Thread(target=stopping)
        stopper.start()
        try:
            self.assertTrue(stop_done.wait(.2), 'Stop blocked behind in-flight player creation')
        finally:
            release.set()
            worker.join(2)
            stopper.join(2)
        self.assertFalse(worker.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual(results, [], 'Cancelled preparation was incorrectly reported ready')
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)


    def test_stop_during_hashing_fences_late_factory(self):
        entered, release = threading.Event(), threading.Event()
        errors, results = [], []
        original_read = Path.read_bytes

        def blocked_read(path):
            if path.resolve() == self.path.resolve():
                entered.set()
                release.wait(2)
            return original_read(path)

        def preparing():
            try:
                results.append(self.prepare())
            except Exception as error:
                errors.append(error)

        with patch.object(Path, 'read_bytes', blocked_read):
            worker = threading.Thread(target=preparing)
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(self.audio.stop('one')['stopped'])
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.players, [], 'Cancelled hash must not launch a late player')

    def test_stop_during_preparation_snapshot_closes_player_without_waiting_for_read(self):
        entered, release, closed = threading.Event(), threading.Event(), threading.Event()
        errors, results = [], []
        original = self.audio.factory

        def blocked_factory(*args, **kwargs):
            player = original(*args, **kwargs)
            original_close = player.close

            def snapshot(deadline):
                entered.set()
                release.wait(2)
                return {'state': 'paused', 'position_seconds': 0, 'rate': 1}

            def close():
                original_close()
                closed.set()
                release.set()  # model owner socket shutdown interrupting the read
                return True

            player.snapshot, player.close = snapshot, close
            return player

        self.audio.factory = blocked_factory

        def preparing():
            try:
                results.append(self.prepare())
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=preparing)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.audio.stop('one')['stopped'])
            self.assertTrue(closed.is_set())
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [], 'A closed preparation must not report ready')
        self.assertEqual(len(errors), 1)
        self.assertEqual(self.players[0].closes, 1)
        self.assertEqual(self.players[0].starts, 0)

    def test_read_only_loading_poll_reaches_paused_without_starting(self):
        original = self.audio.factory
        samples, deadlines = ['loading', 'loading', 'paused'], []

        def loading_factory(*args, **kwargs):
            player = original(*args, **kwargs)

            def snapshot(deadline):
                deadlines.append(deadline)
                return {'state': samples.pop(0), 'position_seconds': 0, 'rate': 1}

            player.snapshot = snapshot
            return player

        self.audio.factory = loading_factory
        with patch('agent.song_audio.time.sleep'):
            result = self.prepare()
        self.assertEqual(result['state'], 'prepared')
        self.assertEqual(samples, [])
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(len(deadlines), 3)
        self.assertTrue(all(deadline <= self.now + 4 for deadline in deadlines))

    def test_loading_cannot_poll_past_lease_and_closes_without_start(self):
        original = self.audio.factory
        deadlines = []

        def loading_factory(*args, **kwargs):
            player = original(*args, **kwargs)

            def snapshot(deadline):
                deadlines.append(deadline)
                self.now += .1
                return {'state': 'loading', 'position_seconds': 0, 'rate': 1}

            player.snapshot = snapshot
            return player

        self.audio.factory = loading_factory
        with patch('agent.song_audio.time.sleep'), self.assertRaises(SongError):
            self.audio.dispatch('song.prepare', {'program_id': 'one',
                'song_id': self.record['song_id'], 'expires_at_ms': (self.wall + .25) * 1000}, timeout=4)
        self.assertTrue(all(deadline == 10.25 for deadline in deadlines))
        self.assertEqual(self.players[0].starts, 0)
        self.assertEqual(self.players[0].closes, 1)


class MpvSnapshotTests(unittest.TestCase):
    def player(self, **changes):
        player = MpvPlayer.__new__(MpvPlayer)
        player.path = '/synthetic/selected.wav'
        values = {'pause': False, 'paused-for-cache': False, 'eof-reached': False,
            'speed': 1, 'path': player.path, 'time-pos': 4.2, 'audio-pts': 4.1}
        values.update(changes)
        player.queries = []

        def command(request, deadline):
            player.queries.append(request[1])
            return values[request[1]]

        player.command = command
        return player

    def test_property_unavailable_is_read_only_loading_and_never_retries_writes(self):
        for command, allowed in ((['get_property', 'time-pos'], True),
                                 (['set_property', 'pause', False], False)):
            with self.subTest(command=command):
                player = MpvPlayer.__new__(MpvPlayer)
                player.buffer, player.counter = b'', 0
                player.lock = threading.RLock()
                player.connection = Mock()
                player.connection.recv.return_value = (json.dumps(
                    {'request_id': 1, 'error': 'property unavailable'}) + '\n').encode()
                with patch('agent.song_audio.time.monotonic', return_value=0):
                    if allowed:
                        self.assertIsNone(player.command(command, 1))
                    else:
                        with self.assertRaises(SongError):
                            player.command(command, 1)
                self.assertEqual(player.connection.sendall.call_count, 1)

    def test_playing_clock_uses_audio_pts_and_reports_buffering_without_audibility_claim(self):
        player = self.player(**{'paused-for-cache': True})
        self.assertEqual(player.snapshot(50), {'state': 'buffering', 'position_seconds': 4.1, 'rate': 1})
        self.assertIn('audio-pts', player.queries)

    def test_paused_and_ended_sources_do_not_require_audio_pts(self):
        for changes, expected in (({'pause': True}, 'paused'), ({'eof-reached': True}, 'ended')):
            player = self.player(**changes)
            result = player.snapshot(50)
            self.assertEqual(result['state'], expected)
            self.assertNotIn('audio-pts', player.queries)

    def test_missing_initial_audio_pts_reports_buffering_without_inventing_phase(self):
        for value in (None, float('nan'), float('inf'), -1, True):
            with self.subTest(audio_pts=value):
                player = self.player(**{'audio-pts': value})
                self.assertEqual(player.snapshot(50),
                    {'state': 'buffering', 'position_seconds': 0, 'rate': 1})

    def test_unavailable_startup_property_reports_loading(self):
        player = self.player(**{'time-pos': None, 'pause': True})
        self.assertEqual(player.snapshot(50),
            {'state': 'loading', 'position_seconds': 0, 'rate': 1})
        self.assertNotIn('audio-pts', player.queries)

    def test_manual_source_or_speed_mutation_fails_closed(self):
        for changes in ({'path': '/other.wav'}, {'speed': .5}, {'speed': 2}, {'speed': True}):
            with self.subTest(changes=changes), self.assertRaises(SongError) as error:
                self.player(**changes).snapshot(50)
            self.assertEqual(error.exception.code, 'FAILED')


    def test_source_or_speed_mutation_is_rejected_even_before_audio_clock_ready(self):
        for changes in ({'path': '/other.wav', 'audio-pts': None},
                        {'speed': True, 'audio-pts': None},
                        {'path': '/other.wav', 'time-pos': None}):
            with self.subTest(changes=changes), self.assertRaises(SongError):
                self.player(**changes).snapshot(50)


class SelectedSourcePreparationTests(unittest.TestCase):
    def test_unconfigured_source_never_resolves_or_decodes(self):
        with tempfile.TemporaryDirectory() as directory, patch('agent.prepare_song.subprocess.run') as run:
            with self.assertRaises(ValueError):
                prepare_source(directory, source='https://example.test/other-song')
            run.assert_not_called()

    def test_wrong_official_identity_is_rejected_before_decode(self):
        for change in ({'id': 'other-video'}, {'artist': 'Other'}, {'title': 'Other'}, {'is_live': True}):
            info = {'id': SOURCE_ID, 'artist': 'Daniel Caesar', 'title': 'CYANIDE',
                    'url': 'https://example.test/synthetic-stream', 'is_live': False}
            info.update(change)
            result = SimpleNamespace(returncode=0, stdout=json.dumps(info))
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                with patch('agent.prepare_song.subprocess.run', return_value=result) as run:
                    with self.assertRaises(ValueError):
                        prepare_source(directory)
                    self.assertEqual(run.call_count, 1)
                    self.assertEqual(run.call_args.args[0][-1], SOURCE)
                    self.assertIn('--retries', run.call_args.args[0])
                    self.assertNotIn('--cookies-from-browser', run.call_args.args[0])
                self.assertFalse((Path(directory) / 'song.json').exists())

    def test_decode_failure_removes_partial_asset_and_never_advertises_manifest(self):
        info = {'id': SOURCE_ID, 'artist': 'Daniel Caesar', 'title': 'CYANIDE',
                'url': 'https://example.test/synthetic-stream', 'is_live': False}
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            def run(argv, **kwargs):
                calls.append(argv)
                if len(calls) == 1:
                    return SimpleNamespace(returncode=0, stdout=json.dumps(info))
                Path(argv[-1]).write_bytes(b'partial decode')
                return SimpleNamespace(returncode=1)

            with patch('agent.prepare_song.subprocess.run', side_effect=run):
                with self.assertRaises(ValueError):
                    prepare_source(directory)
            self.assertEqual(len(calls), 2)
            self.assertFalse((Path(directory) / 'cyanide.wav').exists())
            self.assertFalse((Path(directory) / 'song.json').exists())


if __name__ == '__main__':
    unittest.main()
