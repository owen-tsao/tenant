"""Optional checksum-bound song visuals; fake assets and players, no OS effects."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock, patch

from agent.song_audio import MpvPlayer, SongAudio, SongError, load_recording, validate_map


class FakePlayer:
    def __init__(self, recording, *, binary):
        self.recording = recording
        self.starts = self.closes = 0
        self.state = 'paused'
        self.process = Mock()
        self.process.poll.return_value = None

    def snapshot(self, deadline):
        return {'state': self.state, 'position_seconds': .25, 'rate': 1}

    def start(self, deadline):
        self.starts += 1
        self.state = 'playing'

    def close(self):
        self.closes += 1
        self.process.poll.return_value = 0
        return True


class SongVisualTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name).resolve()
        self.audio_path = self.directory / 'private-selected.wav'
        self.audio_path.write_bytes(b'fake canonical audio, never decoded')
        self.visual_path = self.directory / 'private-vibe.mp4'
        self.visual_path.write_bytes(b'fake silent video, never decoded')
        self.record = {
            'song_id': 'daniel-caesar-selected', 'artist': 'Daniel Caesar',
            'title': 'Selected fixture', 'audio_path': str(self.audio_path),
            'sha256': self.digest(self.audio_path), 'duration_seconds': 2.,
            'beat_seconds': [.1, .7, 1.3], 'analysis': {'physical_alignment_verified': False},
        }
        self.visual = {
            'path': str(self.visual_path), 'sha256': self.digest(self.visual_path),
            'source_sha256': self.record['sha256'], 'width': 1280, 'height': 720,
            'fps': 30., 'duration_seconds': 2.,
            'description': 'Prepared vibe video with circular audio-reactive spectrum.',
        }
        self.record['visual'] = copy.deepcopy(self.visual)
        self.manifest = self.directory / 'song.json'
        self.write_manifest()
        self.now, self.wall = 10., 1000.
        self.players = []
        self.bridges = []
        self.addCleanup(self.stop_all)

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.record))

    def stop_all(self):
        for bridge in self.bridges:
            bridge.stop_all()

    def bridge(self):
        def factory(recording, *, binary):
            player = FakePlayer(recording, binary=binary)
            self.players.append(player)
            return player
        bridge = SongAudio(self.manifest, factory=factory, clock=lambda: self.now,
                           wall_clock=lambda: self.wall, watch=False, binary='/fake/mpv')
        self.bridges.append(bridge)
        return bridge

    def prepare(self, bridge, identifier='one'):
        return bridge.dispatch('song.prepare', {'program_id': identifier,
            'song_id': self.record['song_id'], 'expires_at_ms': (self.wall + 30) * 1000})

    def test_valid_visual_is_resolved_and_preserved_without_reading_media(self):
        loaded = load_recording(self.manifest)
        self.assertEqual(loaded['visual'], self.visual)
        self.assertEqual(loaded['audio_path'], str(self.audio_path.resolve()))

    def test_invalid_visual_metadata_rejects_discovery_before_any_factory(self):
        invalid = {
            'sha256': ['x' * 64, 'a' * 63, True],
            'source_sha256': ['0' * 64, None],
            'width': [0, -1, True, 1280.5, 63, 1279, 4098],
            'height': [0, False, float('inf'), 63, 721, 4098],
            'fps': [0, -1, True, float('nan'), float('inf'), .5, 61],
            'duration_seconds': [0, -1, True, float('nan'), float('inf'), 2.1],
            'description': [None, '', 'x' * 161, ' ' + 'x' * 160, 'private\x00content', 'private\ncontent',
                            'private\tcontent', '/private/path', 'private\\path', 'https://example.invalid/private'],
            'path': [None, '', str(self.directory / 'missing.mp4')],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.record['visual'] = dict(self.visual, **{field: value})
                    self.write_manifest()
                    self.assertEqual(self.bridge().capabilities(), {})
                    self.assertEqual(self.players, [])

    def test_missing_visual_fields_and_non_objects_are_rejected(self):
        for field in self.visual:
            with self.subTest(field=field):
                self.record['visual'] = dict(self.visual)
                del self.record['visual'][field]
                self.write_manifest()
                self.assertEqual(self.bridge().capabilities(), {})
        for value in (None, [], 'not an object', True):
            with self.subTest(value=value):
                self.record['visual'] = value
                self.write_manifest()
                self.assertEqual(self.bridge().capabilities(), {})

    def test_one_frame_duration_tolerance_both_directions(self):
        for direction in (-1, 1):
            with self.subTest(direction=direction):
                self.record['visual'] = dict(self.visual,
                    duration_seconds=2 + direction * (.999999 / self.visual['fps']))
                self.write_manifest()
                self.assertIn('visual', load_recording(self.manifest))
                self.record['visual']['duration_seconds'] = 2 + direction * (1 / self.visual['fps'] + 1e-5)
                self.write_manifest()
                self.assertEqual(self.bridge().capabilities(), {})

    def test_description_accepts_160_characters(self):
        self.record['visual']['description'] = 'x' * 160
        self.write_manifest()
        self.assertIn('song.prepare', self.bridge().capabilities())

    def test_exact_one_frame_and_numeric_boundaries_are_accepted(self):
        for duration in (1.75, 2.25):
            with self.subTest(duration=duration):
                self.record['visual'] = dict(self.visual, fps=4., duration_seconds=duration)
                self.write_manifest()
                self.assertIn('visual', load_recording(self.manifest))
        for size, fps in ((64, 1), (4096, 60)):
            with self.subTest(size=size, fps=fps):
                self.record['visual'] = dict(self.visual, width=size, height=size, fps=fps)
                self.write_manifest()
                self.assertIn('song.prepare', self.bridge().capabilities())

    def test_changed_visual_bytes_rejected_at_load_and_before_prepare(self):
        bridge = self.bridge()
        self.visual_path.write_bytes(b'replaced visual bytes')
        self.assertEqual(self.bridge().capabilities(), {})
        with self.assertRaises(SongError) as error:
            self.prepare(bridge)
        self.assertEqual(error.exception.code, 'INVALID')
        self.assertNotIn(str(self.visual_path), str(error.exception))
        self.assertEqual(self.players, [])

    def test_removed_visual_rejected_before_prepare_with_sanitized_error(self):
        bridge = self.bridge()
        self.visual_path.unlink()
        with self.assertRaises(SongError) as error:
            self.prepare(bridge)
        self.assertNotIn(str(self.visual_path), str(error.exception))
        self.assertEqual(self.players, [])

    def test_replaced_manifest_cannot_redirect_visual_revalidation(self):
        bridge = self.bridge()
        substitute = self.directory / 'different-private.mp4'
        substitute.write_bytes(self.visual_path.read_bytes())
        self.record['visual']['path'] = str(substitute)
        self.write_manifest()
        self.visual_path.write_bytes(b'original selected asset changed')
        with self.assertRaises(SongError):
            self.prepare(bridge)
        self.assertEqual(self.players, [])

    def test_public_visual_and_capability_description_do_not_expose_paths(self):
        bridge = self.bridge()
        prepared = self.prepare(bridge)
        public = prepared['recording']['visual']
        self.assertEqual(public, {k: v for k, v in self.visual.items() if k != 'path'})
        self.assertEqual(validate_map(prepared['recording']), prepared['recording'])
        caps = bridge.capabilities()
        self.assertIn(self.visual['description'], json.dumps(caps))
        for serialized in (json.dumps(prepared), json.dumps(caps)):
            self.assertNotIn(str(self.directory), serialized)
            self.assertNotIn('audio_path', serialized)
        self.assertEqual(self.players[0].starts, 0)

    def capture_argv(self, recording):
        connection, child = Mock(), Mock()
        child.fileno.return_value = 77
        process = Mock()
        process.poll.return_value = 0
        popen = Mock(return_value=process)
        with patch('agent.song_audio.socket.socketpair', return_value=(connection, child)):
            player = MpvPlayer(recording, binary='/fake/mpv', popen=popen)
        self.addCleanup(player.close)
        return popen.call_args.args[0], popen.call_args.kwargs

    def test_visual_argv_keeps_canonical_audio_main_and_one_owned_process(self):
        argv, kwargs = self.capture_argv(load_recording(self.manifest))
        required = ['--aid=1', '--vid=1', '--video-sync=audio', '--audio-display=embedded-first',
                    '--fullscreen=no', '--screen=1', '--geometry=1600x900+160+70']
        for flag in required:
            self.assertEqual(argv.count(flag), 1, flag)
        self.assertEqual(argv[-2:], ['--', str(self.audio_path)])
        self.assertIn('--external-file=' + str(self.visual_path), argv)
        self.assertNotIn('--audio-display=no', argv)
        self.assertFalse(any(arg.startswith(('--audio-file', '--audio-device', '--volume',
                                               '--af=', '--ao=')) for arg in argv))
        self.assertEqual(kwargs['pass_fds'], (77,))

    def test_absent_visual_preserves_exact_existing_player_arguments(self):
        del self.record['visual']
        self.write_manifest()
        loaded = load_recording(self.manifest)
        argv, _ = self.capture_argv(loaded)
        self.assertEqual(argv, ['/fake/mpv', '--no-config', '--pause=yes', '--idle=no',
            '--terminal=no', '--force-window=yes', '--audio-display=no', '--keep-open=yes',
            '--loop-file=no', '--input-ipc-client=fd://77',
            '--title=Daniel Caesar — Selected fixture', '--osd-level=3',
            '--osd-msg1=Daniel Caesar — Selected fixture', '--', str(self.audio_path)])
        public = self.prepare(self.bridge())['recording']
        self.assertNotIn('visual', public)

    def test_visual_expiry_keeps_original_deadline_and_closes_same_player_once(self):
        bridge = self.bridge()
        self.prepare(bridge)
        original_expiry = bridge.jobs['one'].expires
        bridge.dispatch('song.start', {'program_id': 'one'})
        self.now += 15
        bridge.dispatch('song.status', {'program_id': 'one'})
        self.assertEqual(bridge.jobs['one'].expires, original_expiry)
        self.now = original_expiry
        bridge._watch('one')
        bridge.dispatch('song.stop', {'program_id': 'one'})
        self.assertEqual(len(self.players), 1)
        self.assertEqual(self.players[0].starts, 1)
        self.assertEqual(self.players[0].closes, 1)

    def test_disconnect_and_explicit_stop_close_only_owned_visual_player(self):
        bridge = self.bridge()
        self.prepare(bridge)
        bridge.dispatch('song.start', {'program_id': 'one'})
        bridge.dispatch('song.stop', {'program_id': 'one'})
        bridge.stop_all()
        self.assertEqual(len(self.players), 1)
        self.assertEqual(self.players[0].closes, 1)

    def snapshot_fixture(self, *, tracks=None, visual=True, paused=False):
        player = MpvPlayer.__new__(MpvPlayer)
        player.path = str(self.audio_path)
        player.visual_path = str(self.visual_path) if visual else None
        default_tracks = [
            {'type': 'audio', 'id': 1, 'selected': True, 'external': False},
            {'type': 'video', 'id': 1, 'selected': True, 'external': True,
             'external-filename': str(self.visual_path), 'image': False},
        ]
        values = {'pause': paused, 'paused-for-cache': False, 'eof-reached': False,
                  'speed': 1, 'path': str(self.audio_path), 'time-pos': .9,
                  'audio-pts': .75, 'track-list': default_tracks if tracks is None else tracks}
        player.command = Mock(side_effect=lambda command, deadline: values[command[1]])
        return player, values

    def test_selected_silent_video_uses_original_canonical_audio_playhead(self):
        player, values = self.snapshot_fixture()
        self.assertEqual(player.snapshot(99), {'state': 'playing', 'position_seconds': .75, 'rate': 1})
        self.assertNotEqual(values['audio-pts'], values['time-pos'])
        player.command.assert_any_call(['get_property', 'track-list'], 99)
        player.command.assert_any_call(['get_property', 'audio-pts'], 99)
        values['pause'] = True
        player.command.reset_mock()
        self.assertEqual(player.snapshot(99)['state'], 'paused')
        self.assertFalse(any(call.args[0][1] == 'audio-pts' for call in player.command.call_args_list))

    def test_absent_visual_snapshot_does_not_query_video_or_track_selection(self):
        player, values = self.snapshot_fixture(visual=False)
        del values['track-list']
        self.assertEqual(player.snapshot(99)['position_seconds'], .75)
        self.assertFalse(any(call.args[0][1] == 'track-list' for call in player.command.call_args_list))

    def test_visual_track_startup_waits_without_claiming_playing(self):
        for tracks in ([], None, [{'type': 'audio', 'id': 1, 'selected': True},
                {'type': 'video', 'id': 1, 'selected': False, 'external': True,
                 'external-filename': str(self.visual_path)}]):
            with self.subTest(tracks=tracks):
                player, values = self.snapshot_fixture()
                values['track-list'] = tracks
                self.assertEqual(player.snapshot(99)['state'], 'loading')
                self.assertFalse(any(call.args[0][1] == 'audio-pts'
                                     for call in player.command.call_args_list))

    def test_changed_visual_or_external_audio_fails_closed_with_sanitized_error(self):
        player, values = self.snapshot_fixture()
        good = values['track-list']
        bad_tracks = [
            'bad tracks', [None], [],
            good + [{'type': 'audio', 'id': 2, 'selected': False, 'external': True}],
            [dict(good[0], external=True), good[1]],
            [dict(good[0], id=2), good[1]],
            [dict(good[0], selected=False), good[1]],
            [good[0]], [good[1]],
            [good[0], dict(good[1], id=2)],
            [good[0], dict(good[1], external=False)],
            [good[0], dict(good[1], **{'external-filename': str(self.directory / 'other.mp4')})],
            [good[0], dict(good[1], image=True)],
            good + [dict(good[1], id=2)],
        ]
        # An empty track list is a legitimate decoder-startup state, tested above.
        for tracks in (tracks for tracks in bad_tracks if tracks != []):
            with self.subTest(tracks=tracks):
                values['track-list'] = tracks
                with self.assertRaises(SongError) as error:
                    player.snapshot(99)
                self.assertEqual(error.exception.code, 'FAILED')
                self.assertNotIn(str(self.directory), str(error.exception))

    def test_visual_snapshot_rejects_canonical_path_or_speed_change(self):
        for field, value in (('path', str(self.directory / 'other.wav')), ('speed', 1.25)):
            with self.subTest(field=field):
                player, values = self.snapshot_fixture()
                values[field] = value
                with self.assertRaises(SongError):
                    player.snapshot(99)
