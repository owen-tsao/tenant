from io import BytesIO
import unittest

from PIL import Image, PngImagePlugin

from film_crew.controller import Frame, OneCutDirector, PixelWatchdog
from film_crew.policy import OneShotPolicy


def png(color, metadata=''):
    stream = BytesIO()
    info = PngImagePlugin.PngInfo(); info.add_text('note', metadata)
    Image.new('RGB', (32, 32), color).save(stream, format='PNG', pnginfo=info)
    return stream.getvalue()


GOOD = dict(valid=True, demonstrating=.95, detail_usefulness=.95,
            confidence=.95, uncertainty=.05)


class PixelWatchdogTests(unittest.TestCase):
    def test_new_responses_and_png_metadata_do_not_prove_pixel_change(self):
        watch = PixelWatchdog()
        for role in ('wide', 'detail'):
            self.assertTrue(watch.observe(Frame(role, png('red', 'first'), 10), now=10))
            self.assertTrue(watch.observe(Frame(role, png('red', 'second'), 11), now=11))
        self.assertFalse(watch.fresh(now=11))
        for role in ('wide', 'detail'):
            watch.observe(Frame(role, png('blue'), 11.1), now=11.1)
        self.assertTrue(watch.fresh(now=11.1))
        self.assertFalse(watch.fresh(now=14))

    def test_one_live_view_cannot_cover_for_a_frozen_view(self):
        watch = PixelWatchdog()
        for role in ('wide', 'detail'):
            watch.observe(Frame(role, png('red'), 10), now=10)
        watch.observe(Frame('wide', png('blue'), 11), now=11)
        self.assertFalse(watch.fresh(now=11))

    def test_malformed_future_duplicate_or_out_of_order_snapshot_clears_pair(self):
        for frame in (Frame('wide', b'invalid', 11), Frame('wide', png('blue'), 12),
                      Frame('wide', png('blue'), 10), Frame('wide', png('blue'), 9)):
            with self.subTest(frame=frame):
                watch = PixelWatchdog()
                for role in ('wide', 'detail'):
                    watch.observe(Frame(role, png('red'), 10), now=10)
                    watch.observe(Frame(role, png('blue'), 10.5), now=10.5)
                self.assertFalse(watch.observe(frame, now=11))
                self.assertFalse(watch.fresh(now=11))


class OneCutDirectorTests(unittest.TestCase):
    def setUp(self):
        self.director = OneCutDirector(OneShotPolicy(validation_ready=True), window_seconds=10)
        self.assertTrue(self.director.arm(now=100, current_scene='WIDE', revision=7))

    def pair(self, at, color):
        return [Frame(role, png(color), at) for role in ('wide', 'detail')]

    def observe(self, at, color, **changes):
        state = dict(now=at, current_scene='WIDE', revision=7)
        state.update(changes)
        return self.director.consider(self.pair(at, color), GOOD, **state)

    def test_one_cut_requires_both_changing_views_and_semantic_dwell(self):
        self.assertIsNone(self.observe(100.25, 'red'))
        self.assertIsNone(self.observe(100.65, 'blue'))
        self.assertIsNone(self.observe(101.05, 'green'))
        self.assertEqual(self.observe(101.45, 'yellow'), 'DETAIL')
        self.assertFalse(self.director.active)
        self.assertIsNone(self.observe(101.85, 'purple'))

    def test_manual_change_during_model_inference_cancels_pending_cut(self):
        self.observe(100.25, 'red'); self.observe(100.65, 'blue'); self.observe(101.05, 'green')
        self.assertIsNone(self.observe(101.45, 'yellow', revision=8))
        self.assertEqual(self.director.reason, 'manual_or_external_scene_change')
        self.assertIsNone(self.observe(101.85, 'purple'))

    def test_external_scene_change_cancels_even_if_revision_is_unavailable(self):
        self.assertIsNone(self.observe(100.25, 'red', current_scene='DETAIL'))
        self.assertFalse(self.director.active)

    def test_deadline_expires_during_inference_without_late_cut(self):
        self.observe(100.25, 'red'); self.observe(100.65, 'blue'); self.observe(101.05, 'green')
        self.assertIsNone(self.director.consider(self.pair(109.9, 'yellow'), GOOD,
                                               now=110.1, current_scene='WIDE', revision=7))
        self.assertEqual(self.director.reason, 'observation_window_ended')

    def test_frozen_pixels_cannot_seed_first_cut(self):
        for at in (100.25, 100.65, 101.05, 102, 103):
            self.assertIsNone(self.observe(at, 'red'))

    def test_repeated_pixels_after_one_change_do_not_accumulate_dwell(self):
        self.observe(100.25, 'red'); self.observe(100.65, 'blue')
        self.assertIsNone(self.observe(101.05, 'blue'))
        self.assertIsNone(self.observe(101.45, 'blue'))

    def test_incomplete_pair_with_negative_evidence_interrupts_prior_dwell(self):
        self.observe(100., 'red'); self.observe(100.25, 'blue'); self.observe(100.65, 'green')
        negative = dict(GOOD, demonstrating=.01, confidence=.01)
        pair = [Frame('wide', png('black'), 100.8), Frame('detail', png('green'), 100.8)]
        self.assertIsNone(self.director.consider(pair, negative, now=100.8,
                                                current_scene='WIDE', revision=7))
        self.assertIsNone(self.observe(101.05, 'yellow'))

    def ready_proposal(self):
        self.observe(100.25, 'red'); self.observe(100.65, 'blue'); self.observe(101.05, 'green')
        self.assertEqual(self.observe(101.45, 'yellow'), 'DETAIL')

    def test_proposal_is_consumed_once_without_automatic_retry(self):
        self.ready_proposal()
        self.assertEqual(self.director.take_proposal(now=101.5, current_scene='WIDE', revision=7), 'DETAIL')
        self.assertIsNone(self.director.take_proposal(now=101.6, current_scene='WIDE', revision=7))

    def test_pending_proposal_rejects_old_evidence_and_clock_regression(self):
        for at in (109.9, 101.4):
            with self.subTest(at=at):
                self.setUp(); self.ready_proposal()
                self.assertIsNone(self.director.take_proposal(now=at, current_scene='WIDE', revision=7))
                self.assertEqual(self.director.reason, 'stale_pending_evidence')

    def test_post_inference_cancellation_deadline_or_roundtrip_scene_change_prevents_dispatch(self):
        for change in ('stop', 'deadline', 'roundtrip_scene'):
            with self.subTest(change=change):
                self.setUp(); self.ready_proposal()
                args = dict(now=101.5, current_scene='WIDE', revision=7)
                if change == 'stop':
                    self.director.stop()
                elif change == 'deadline':
                    args['now'] = 110
                else:
                    # WIDE -> DETAIL -> WIDE: final name is unchanged, revision is not.
                    args['revision'] = 9
                self.assertIsNone(self.director.take_proposal(**args))
                self.assertIsNone(self.director.take_proposal(now=101.6, current_scene='WIDE', revision=7))

    def test_lost_pixel_changes_disarm_after_observation_started(self):
        self.observe(100.25, 'red'); self.observe(100.65, 'blue')
        self.assertIsNone(self.observe(103, 'blue'))
        self.assertEqual(self.director.reason, 'no_recent_pixel_changes')

    def test_unvalidated_classifier_cannot_arm(self):
        director = OneCutDirector(OneShotPolicy())
        self.assertFalse(director.arm(now=100, current_scene='WIDE', revision=7))

    def test_stale_snapshot_or_one_role_twice_stops_instead_of_cutting(self):
        for frames in ([Frame('wide', png('red'), 90), Frame('detail', png('red'), 100)],
                       [Frame('wide', png('red'), 100)] * 2):
            with self.subTest(frames=frames):
                self.setUp()
                self.assertIsNone(self.director.consider(frames, GOOD, now=100,
                                                        current_scene='WIDE', revision=7))
                self.assertFalse(self.director.active)

    def test_malformed_acquisition_disarms_without_preserving_prior_dwell(self):
        for frames in (None, [None, None], [{}, {}], 'bad',
                       [Frame([], png('red'), 100), Frame('detail', png('red'), 100)]):
            with self.subTest(frames=frames):
                self.setUp()
                self.observe(100.25, 'red'); self.observe(100.65, 'blue'); self.observe(101.05, 'green')
                self.assertIsNone(self.director.consider(frames, GOOD, now=101.45,
                                                        current_scene='WIDE', revision=7))
                self.assertFalse(self.director.active)
                self.assertEqual(self.director.reason, 'invalid_frame_pair')
                self.assertIsNone(self.observe(101.85, 'yellow'))
