"""Pure recording-clock acceptance. No player, network, or physical actions."""
from copy import deepcopy
import unittest

from agent.song_audio import SongError
from brain.core.song_timing import SongTimeline


def recording(**changes):
    # Deliberately nonuniform: an average-BPM oscillator cannot produce these edges.
    data = {'song_id': 'selected-recording', 'artist': 'Daniel Caesar',
            'title': 'Test metadata only', 'sha256': 'a' * 64,
            'duration_seconds': 8., 'beat_seconds': [1., 1.4, 2.1, 2.6, 3.5],
            'analysis': {'method': 'fixture'}}
    data.update(changes)
    return data


def observation(**changes):
    data = {'song_id': 'selected-recording', 'sha256': 'a' * 64,
            'position_seconds': 1.2, 'rate': 1, 'state': 'playing'}
    data.update(changes)
    return data


class SongTimingTests(unittest.TestCase):
    def setUp(self):
        self.timeline = SongTimeline(recording())

    def observe(self, **changes):
        self.timeline.observe(observation(**changes), 100., 100.04)

    def test_exact_nonuniform_recording_edges_define_phase_not_descriptive_bpm(self):
        self.observe()
        for number, seconds in enumerate(self.timeline.beats):
            with self.subTest(number=number):
                self.assertAlmostEqual(self.timeline.beat_time(number), seconds)
                self.assertAlmostEqual(self.timeline.due(number), 100.02 + seconds - 1.2)
        gaps = [self.timeline.due(n + 1) - self.timeline.due(n) for n in range(4)]
        for actual, expected in zip(gaps, [.4, .7, .5, .9]):
            self.assertAlmostEqual(actual, expected)
        # A tempo label is useful metadata, but must never replace the actual map.
        self.assertAlmostEqual(self.timeline.bpm, 100.)
        self.assertNotAlmostEqual(gaps[0], 60 / self.timeline.bpm)

    def test_fractional_beats_interpolate_their_own_recording_interval(self):
        for number, seconds in ((.5, 1.2), (1.5, 1.75), (2.25, 2.225), (3.5, 3.05)):
            with self.subTest(number=number):
                self.assertAlmostEqual(self.timeline.beat_time(number), seconds)
                self.assertAlmostEqual(self.timeline.beat_number(seconds), number)

    def test_future_first_beat_and_fractional_cadence_schedule_in_recording_phase(self):
        self.observe(position_seconds=0.)
        self.assertEqual(self.timeline.next_cycle(100.04, .5), 0)
        self.assertGreater(self.timeline.due(0), 100.04)
        self.observe(position_seconds=1.5)
        # Half-beat ON/OFF: next whole-beat cycle starts at recorded beat 2 (2.1s).
        cycle = self.timeline.next_cycle(100.04, .5)
        self.assertEqual(cycle, 2)
        self.assertAlmostEqual(self.timeline.due(2 * cycle * .5), 100.62)
        self.assertAlmostEqual(self.timeline.due((2 * cycle + 1) * .5), 100.87)

    def test_no_constant_tempo_tail_is_fabricated_past_analysis(self):
        self.observe()
        for number in (-.01, 4.01, 10, float('inf'), float('-inf'), float('nan'), True):
            with self.subTest(number=number):
                self.assertIsNone(self.timeline.beat_time(number))
                self.assertIsNone(self.timeline.due(number))
        self.assertEqual(self.timeline.beat_time(4), 3.5)

    def test_bracket_uses_only_brain_clock_and_ignores_host_clock_fields(self):
        self.observe(host_monotonic=9e12, timestamp_ms=-9e12)
        due = self.timeline.due(2)
        shifted = SongTimeline(recording())
        shifted.observe(observation(host_monotonic=-9e12, timestamp_ms=9e12), 8100., 8100.04)
        self.assertAlmostEqual(shifted.due(2) - due, 8000.)
        self.assertAlmostEqual(shifted.position(8100.1), self.timeline.position(100.1))
        self.assertEqual(shifted.status(8100.04)['sample_uncertainty_ms'], 20.)

    def test_readiness_requires_fresh_playing_sample_without_physical_claim(self):
        self.assertFalse(self.timeline.ready(100.))
        self.assertEqual(self.timeline.status(100.)['state'], 'pending')
        self.assertIsNone(self.timeline.status(100.)['sample_age_ms'])
        self.observe()
        self.assertFalse(self.timeline.ready(100.039))
        self.assertTrue(self.timeline.ready(100.04))
        self.assertTrue(self.timeline.ready(100.04 + self.timeline.ttl - 1e-6))
        self.assertFalse(self.timeline.ready(100.04 + self.timeline.ttl + 1e-6))
        self.assertFalse(self.timeline.status(100.04)['physical_alignment_verified'])
        for now in (float('nan'), float('inf'), float('-inf')):
            self.assertFalse(self.timeline.ready(now))

    def test_paused_buffering_and_ended_are_pending_even_with_fresh_position(self):
        for state in ('paused', 'buffering', 'ended'):
            with self.subTest(state=state):
                self.timeline = SongTimeline(recording())
                self.observe(state=state)
                self.assertFalse(self.timeline.ready(100.04))
                self.assertEqual(self.timeline.status(100.04)['state'], 'pending')
                self.timeline.observe(observation(position_seconds=1.4), 100.2, 100.24)
                self.assertTrue(self.timeline.ready(100.24))

    def test_uncertainty_at_half_shortest_interval_is_pending(self):
        self.timeline.observe(observation(), 0., .4)
        self.assertFalse(self.timeline.ready(.4))
        self.timeline.observe(observation(), 0., .399)
        self.assertTrue(self.timeline.ready(.399))

    def test_stalled_buffering_stays_pending_until_fresh_resume_reanchors_phase(self):
        self.observe()
        old_due = self.timeline.due(1)
        for sent in (100.2, 100.5):
            self.timeline.observe(observation(state='buffering', position_seconds=1.3), sent, sent + .04)
            self.assertFalse(self.timeline.ready(sent + .04))
        self.timeline.observe(observation(position_seconds=1.3), 100.7, 100.74)
        self.assertFalse(self.timeline.ready(100.74))
        self.timeline.observe(observation(position_seconds=1.5), 100.9, 100.94)
        self.assertTrue(self.timeline.ready(100.94))
        self.assertAlmostEqual(self.timeline.due(2), 101.52)
        self.assertGreater(self.timeline.due(2), old_due)
        self.assertEqual(self.timeline.next_cycle(100.94, .5), 2)
        # This is clock invalidation evidence, not a promise that every count is a seek.
        self.assertGreater(self.timeline.status(100.74)['discontinuities'], 0)

    def test_normal_playback_retains_phase_but_seek_reanchors_future_edges(self):
        self.observe()
        first_due = self.timeline.due(3)
        self.timeline.observe(observation(position_seconds=1.4), 100.2, 100.24)
        self.assertEqual(self.timeline.discontinuity, 0)
        self.assertAlmostEqual(self.timeline.due(3), first_due)
        self.timeline.observe(observation(position_seconds=2.5), 100.3, 100.34)
        self.assertEqual(self.timeline.discontinuity, 1)
        self.assertEqual(self.timeline.revision, 3)
        self.assertFalse(self.timeline.ready(100.34))
        self.assertAlmostEqual(self.timeline.due(3), 100.42)
        self.timeline.observe(observation(position_seconds=2.7), 100.5, 100.54)
        self.assertTrue(self.timeline.ready(100.54))
        self.assertAlmostEqual(self.timeline.due(4), 101.32)
        self.timeline.observe(observation(position_seconds=.5), 100.6, 100.64)
        self.assertEqual(self.timeline.discontinuity, 2)
        self.assertFalse(self.timeline.ready(100.64))
        self.timeline.observe(observation(position_seconds=.7), 100.8, 100.84)
        self.assertTrue(self.timeline.ready(100.84))
        self.assertAlmostEqual(self.timeline.due(0), 101.12)

    def test_frozen_playhead_invalidates_once_and_never_becomes_ready_from_fresh_receipts(self):
        self.observe(position_seconds=2.)
        for sent in (100.2, 100.4, 100.6, 100.8):
            self.timeline.observe(observation(position_seconds=2.), sent, sent + .04)
            self.assertFalse(self.timeline.ready(sent + .04))
            self.assertFalse(self.timeline.status(sent + .04)['playhead_advancing'])
            self.assertEqual(self.timeline.discontinuity, 1)
        self.assertEqual(self.timeline.revision, 5)
        self.timeline.observe(observation(position_seconds=2.2), 101., 101.04)
        self.assertTrue(self.timeline.ready(101.04))
        self.assertAlmostEqual(self.timeline.due(3), 101.42)

    def test_tiny_positive_progress_cannot_reset_allowance_on_each_fast_poll(self):
        self.observe(position_seconds=2.)
        for index in range(1, 31):
            sent = 100. + index * .05
            self.timeline.observe(observation(position_seconds=2. + index * .0001), sent, sent + .04)
            with self.subTest(index=index):
                self.assertEqual(self.timeline.ready(sent + .04), index < 3)
        self.assertEqual(self.timeline.discontinuity, 1)
        self.assertFalse(self.timeline.status(101.54)['playhead_advancing'])

    def test_bounded_normal_jitter_remains_coherent_across_many_observations(self):
        self.observe()
        for index, jitter in enumerate((.03, -.02, .01, -.04, .02), start=1):
            sent = 100. + index * .1
            position = 1.2 + index * .1 + jitter
            self.timeline.observe(observation(position_seconds=position), sent, sent + .04)
            self.assertTrue(self.timeline.ready(sent + .04))
        self.assertEqual(self.timeline.discontinuity, 0)

    def test_small_observation_jitter_within_bracket_does_not_count_as_seek(self):
        self.observe()
        self.timeline.observe(observation(position_seconds=1.51), 100.2, 100.24)
        self.assertEqual(self.timeline.discontinuity, 0)

    def test_invalid_observations_never_replace_last_confirmed_recording(self):
        self.observe()
        old_sample = deepcopy(self.timeline.sample)
        changes = [
            {'song_id': 'another-recording'}, {'sha256': 'b' * 64},
            {'position_seconds': -.11}, {'position_seconds': 8.11},
            {'position_seconds': float('nan')}, {'position_seconds': float('inf')},
            {'position_seconds': True}, {'position_seconds': '1.2'},
            {'rate': 0}, {'rate': 1.01}, {'rate': float('nan')}, {'rate': True},
            {'state': 'unknown'}, {'state': None}]
        for change in changes:
            with self.subTest(change=change):
                self.timeline = SongTimeline(recording())
                self.observe()
                with self.assertRaises(ValueError):
                    self.timeline.observe(observation(**change), 100.1, 100.14)
                self.assertEqual(self.timeline.sample, old_sample)
                self.assertEqual(self.timeline.revision, 1)

    def test_invalid_brackets_are_rejected_without_readiness(self):
        for sent, received in ((2, 1), (float('nan'), 1), (0, float('inf')), (True, 2), (0, '2')):
            with self.subTest(sent=sent, received=received):
                with self.assertRaises(ValueError):
                    self.timeline.observe(observation(), sent, received)
                self.assertIsNone(self.timeline.sample)

    def test_invalid_recording_maps_are_rejected_before_clock_creation(self):
        changes = [
            {'song_id': ''}, {'song_id': '../other'}, {'song_id': 'x' * 81},
            {'sha256': 'not-a-checksum'}, {'sha256': 'A' * 64},
            {'artist': 'Another artist'}, {'title': ''}, {'title': ' '},
            {'duration_seconds': 0}, {'duration_seconds': float('nan')},
            {'duration_seconds': True}, {'beat_seconds': [1., 2.]},
            {'beat_seconds': [1., 1., 2.]}, {'beat_seconds': [2., 1., 3.]},
            {'beat_seconds': [-.1, 1., 2.]}, {'beat_seconds': [1., 2., 8.]},
            {'beat_seconds': [1., 2., float('inf')]},
            {'beat_seconds': [True, 2., 3.]}, {'beat_seconds': '1,2,3'}]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(SongError):
                    SongTimeline(recording(**change))


if __name__ == '__main__':
    unittest.main()
