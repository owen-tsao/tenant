"""Decision-safety scenarios, using semantic evidence without cameras or ML."""

from dataclasses import dataclass
import unittest

from film_crew.policy import OneShotPolicy


def evidence(**changes):
    result = dict(valid=True, demonstrating=.9, detail_usefulness=.9,
                  confidence=.9, uncertainty=.1)
    result.update(changes)
    return result


class OneShotPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = OneShotPolicy(validation_ready=True)
        self.assertTrue(self.policy.arm(now=100.))

    def observe(self, when, values=None, **changes):
        args = dict(now=when, captured_at=when, armed=True, manual_override=False,
                    sources_fresh=True)
        args.update(changes)
        return self.policy.propose(evidence() if values is None else values, **args)

    def sustained(self, start=100.25):
        return [self.observe(start + offset) for offset in (0, .4, .8)]

    def test_unvalidated_model_cannot_arm_or_propose(self):
        self.policy = OneShotPolicy()
        self.assertFalse(self.policy.arm(now=100.))
        self.assertEqual(self.sustained(), [None] * 3)

    def test_external_armed_flag_does_not_implicitly_arm(self):
        self.policy = OneShotPolicy(validation_ready=True)
        self.assertEqual(self.sustained(), [None] * 3)

    def test_sustained_demonstration_proposes_one_detail(self):
        self.assertEqual(self.sustained(), [None, None, "DETAIL"])
        self.assertEqual(self.sustained(102.), [None] * 3)

    def test_explicit_rearm_allows_a_second_deliberate_cut(self):
        self.assertEqual(self.sustained()[-1], "DETAIL")
        self.assertTrue(self.policy.arm(now=102.))
        self.assertEqual(self.sustained(102.25)[-1], "DETAIL")

    def test_disarm_clears_pending_observations(self):
        self.observe(100.25)
        self.observe(100.65)
        self.policy.disarm()
        self.assertIsNone(self.observe(101.05))

    def test_incomplete_pair_resets_dwell_preserves_arm_and_never_rearms_consumed_cut(self):
        self.assertIsNone(self.observe(100.25))
        self.assertIsNone(self.observe(100.65))
        self.policy.reset_observations()  # Controller skipped incomplete pixel novelty.
        self.assertIsNone(self.observe(101.05))  # Prior positives cannot finish this dwell.
        self.assertIsNone(self.observe(101.45))
        self.assertEqual(self.observe(101.85), "DETAIL")  # Original arm remains usable.
        self.policy.reset_observations()
        self.assertEqual(self.sustained(102.25), [None] * 3)  # Consumed arm stays consumed.

    def test_arm_requires_wide_scene(self):
        self.assertFalse(self.policy.arm(now=100., current_scene="DETAIL"))
        self.assertEqual(self.sustained(), [None] * 3)

    def test_dwell_requires_time_not_only_observation_count(self):
        self.assertEqual([self.observe(t) for t in (100.25, 100.3, 100.4)], [None] * 3)
        self.assertIsNone(self.observe(100.8))
        self.assertEqual(self.observe(101.05), "DETAIL")

    def test_long_dwell_requires_three_distinct_frames(self):
        self.assertIsNone(self.observe(100.25))
        self.assertIsNone(self.observe(100.8))
        self.assertEqual(self.observe(101.05), "DETAIL")

    def test_duplicate_frame_never_completes_dwell(self):
        self.assertIsNone(self.observe(100.25))
        self.assertIsNone(self.observe(100.65))
        self.assertIsNone(self.observe(101.05, captured_at=100.65))
        self.assertEqual(self.observe(101.05), "DETAIL")

    def test_frames_before_arm_delay_do_not_seed_dwell(self):
        self.assertIsNone(self.observe(100.))
        self.assertIsNone(self.observe(100.2))
        self.assertEqual(self.sustained(), [None, None, "DETAIL"])

    def test_manual_override_latches_disarm_until_explicit_rearm(self):
        self.observe(100.25)
        self.assertIsNone(self.observe(100.65, manual_override=True))
        self.assertEqual(self.sustained(101.), [None] * 3)
        self.assertTrue(self.policy.arm(now=102.))
        self.assertEqual(self.sustained(102.25)[-1], "DETAIL")

    def test_external_disarm_interlock_requires_explicit_rearm(self):
        self.observe(100.25)
        self.observe(100.65, armed=False)
        self.assertEqual(self.sustained(101.), [None] * 3)

    def test_disconnect_cannot_resume_pending_cut(self):
        self.observe(100.25)
        self.observe(100.65, connected=False)
        self.assertEqual(self.sustained(101.), [None] * 3)

    def test_missing_source_freshness_denies_even_recent_snapshot_acquisitions(self):
        for when in (100.25, 100.65, 101.05):
            self.assertIsNone(self.policy.propose(
                evidence(), now=when, captured_at=when, armed=True, manual_override=False))
        self.assertEqual(self.sustained(102.), [None] * 3)

    def test_source_freshness_loss_latches_disarm_until_explicit_rearm(self):
        self.observe(100.25)
        self.observe(100.65)
        self.assertIsNone(self.observe(101.05, sources_fresh=False))
        self.assertEqual(self.sustained(102.), [None] * 3)
        self.assertTrue(self.policy.arm(now=103.))
        self.assertEqual(self.sustained(103.25)[-1], "DETAIL")

    def test_truthy_nonboolean_source_freshness_is_not_authority(self):
        for bad in (1, "yes", None):
            with self.subTest(bad=bad):
                self.setUp()
                self.assertIsNone(self.observe(100.25, sources_fresh=bad))
                self.assertEqual(self.sustained(101.), [None] * 3)

    def test_measured_custom_timing_budgets_are_applied(self):
        self.policy = OneShotPolicy(validation_ready=True, max_age=1., max_gap=1.,
                                    min_dwell=1.5, min_observations=4, arm_delay=.5)
        self.assertTrue(self.policy.arm(now=100.))
        self.assertIsNone(self.observe(100.3))
        results = [self.observe(capture + .8, captured_at=capture)
                   for capture in (100.5, 101.2, 101.9, 102.6)]
        self.assertEqual(results, [None, None, None, "DETAIL"])

    def test_invalid_timing_options_fail_at_construction(self):
        for name, values in {
            "max_age": (0, -1, 10.1, True, None, float("nan"), float("inf")),
            "max_gap": (0, -1, 10.1, True, "1", float("nan")),
            "min_dwell": (0, .74, 30.1, True, float("inf")),
            "min_observations": (0, 2, 3., 101, True, None),
            "arm_delay": (-.1, 10.1, True, None, float("nan")),
        }.items():
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    OneShotPolicy(**{name: value})

    def test_manual_scene_change_does_not_get_forced_back(self):
        self.observe(100.25)
        self.observe(100.65, current_scene="DETAIL")
        self.assertEqual(self.sustained(101.), [None] * 3)

    def test_unknown_scene_disarms(self):
        self.observe(100.25, current_scene="UNAVAILABLE")
        self.assertEqual(self.sustained(101.), [None] * 3)

    def test_validation_revocation_disarms(self):
        self.observe(100.25)
        self.policy.validation_ready = False
        self.observe(100.65)
        self.policy.validation_ready = True
        self.assertEqual(self.sustained(101.), [None] * 3)

    def test_bad_semantics_interrupt_dwell_for_each_guard(self):
        for bad in (dict(demonstrating=.2), dict(detail_usefulness=.2),
                    dict(confidence=.3), dict(uncertainty=.8), dict(valid=False)):
            with self.subTest(bad=bad):
                self.setUp()
                self.observe(100.25)
                self.observe(100.65, evidence(**bad))
                self.assertEqual(self.sustained(101.05), [None, None, "DETAIL"])

    def test_stale_frame_clears_dwell(self):
        self.observe(100.25)
        self.observe(100.65)
        self.assertIsNone(self.observe(101.3, captured_at=100.65))
        self.assertEqual(self.sustained(101.4), [None, None, "DETAIL"])

    def test_future_frame_clears_dwell(self):
        self.observe(100.25)
        self.assertIsNone(self.observe(100.65, captured_at=101.))
        self.assertEqual(self.sustained(100.75), [None, None, "DETAIL"])

    def test_prearm_frames_are_rejected(self):
        self.assertIsNone(self.observe(100.25, captured_at=99.9))
        self.assertEqual(self.sustained(100.65), [None, None, "DETAIL"])

    def test_reordered_capture_clears_dwell(self):
        self.observe(100.25)
        self.observe(100.65)
        self.assertIsNone(self.observe(100.7, captured_at=100.5))
        self.assertEqual(self.sustained(100.75), [None, None, "DETAIL"])

    def test_stream_gap_requires_new_sustained_evidence(self):
        self.observe(100.25)
        self.observe(100.65)
        self.assertEqual(self.sustained(101.5), [None, None, "DETAIL"])

    def test_clock_regression_disarms_instead_of_finishing_cut(self):
        self.observe(100.25)
        self.observe(100.65)
        self.assertIsNone(self.observe(100.5))
        self.assertEqual(self.sustained(101.), [None] * 3)
        self.assertFalse(self.policy.arm(now=100.))

    def test_nonfinite_clock_disarms(self):
        for bad in (float("nan"), float("inf"), -float("inf"), None, True, "101"):
            with self.subTest(bad=bad):
                self.setUp()
                self.assertIsNone(self.observe(bad))
                self.assertEqual(self.sustained(101.), [None] * 3)

    def test_malformed_capture_time_clears_pending_evidence(self):
        for bad in (float("nan"), float("inf"), None, True, "100.65"):
            with self.subTest(bad=bad):
                self.setUp()
                self.observe(100.25)
                self.assertIsNone(self.observe(100.65, captured_at=bad))
                self.assertEqual(self.sustained(100.75), [None, None, "DETAIL"])

    def test_malformed_scores_and_missing_valid_never_cut(self):
        for bad in (None, {}, evidence(valid=1), evidence(confidence=True),
                    evidence(demonstrating=float("nan")), evidence(uncertainty=-.1),
                    evidence(detail_usefulness=1.1), evidence(confidence=".99"),
                    evidence(pair_similarity=float("inf")), evidence(pair_similarity=1.1)):
            with self.subTest(bad=bad):
                self.setUp()
                self.assertEqual([self.observe(t, bad) if bad is not None else
                                  self.policy.propose(None, now=t, captured_at=t,
                                                      armed=True, manual_override=False,
                                                      sources_fresh=True)
                                  for t in (100.25, 100.65, 101.05)], [None] * 3)

    def test_dataclass_evidence_is_accepted(self):
        @dataclass
        class Evidence:
            valid: bool = True
            demonstrating: float = .9
            detail_usefulness: float = .9
            confidence: float = .9
            uncertainty: float = .1

        self.assertEqual([self.observe(t, Evidence()) for t in
                          (100.25, 100.65, 101.05)], [None, None, "DETAIL"])

    def test_uncertainty_on_duplicate_can_cancel_dwell(self):
        self.observe(100.25)
        self.observe(100.65)
        self.observe(100.7, evidence(uncertainty=.8), captured_at=100.65)
        self.assertEqual(self.sustained(100.75), [None, None, "DETAIL"])

    def test_positive_evidence_is_not_mutated(self):
        values = evidence(pair_similarity=.5)
        original = dict(values)
        self.observe(100.25, values)
        self.assertEqual(values, original)


class VisionBoundaryTests(unittest.TestCase):
    """Parser/failure paths never need a model, camera, network, or torch."""
    @staticmethod
    def png(size=(32, 24), *, animated=False):
        from io import BytesIO
        from PIL import Image
        output = BytesIO()
        image = Image.new('RGB', size, 'gray')
        if animated:
            image.save(output, 'PNG', save_all=True,
                       append_images=[Image.new('RGB', size, 'white')], duration=100)
        else:
            image.save(output, 'PNG')
        return output.getvalue()

    def test_png_rejects_nonbytes_wrong_format_truncation_and_small_dimensions(self):
        from film_crew.vision import _png
        for payload in (None, 'url', b'JPEG', b'', self.png()[:40], self.png((8, 8))):
            with self.subTest(kind=type(payload).__name__):
                with self.assertRaises(Exception):
                    _png(payload)

    def test_png_rejects_animated_frame_sequence(self):
        from film_crew.vision import _png
        with self.assertRaises(ValueError):
            _png(self.png(animated=True))

    def test_png_rejects_encoded_size_bound_and_decoded_pixel_bomb_before_load(self):
        import struct
        import zlib
        from film_crew.vision import _png, MAX_PNG_BYTES
        with self.assertRaises(ValueError):
            _png(b'\x89PNG\r\n\x1a\n' + b'x' * MAX_PNG_BYTES)
        # Valid header/chunk CRC, enormous declared dimensions; no large image allocation.
        def chunk(name, body):
            return struct.pack('>I', len(body)) + name + body + struct.pack('>I', zlib.crc32(name + body))
        payload = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 5000, 5000, 8, 2, 0, 0, 0))
        payload += chunk(b'IDAT', zlib.compress(b'\0')) + chunk(b'IEND', b'')
        with self.assertRaises(ValueError):
            _png(payload)

    def test_png_valid_frame_decodes_to_detached_rgb(self):
        from film_crew.vision import _png
        image = _png(self.png())
        self.assertEqual((image.mode, image.size), ('RGB', (32, 24)))
        image.close()

    def test_busy_and_parser_failure_return_uncertainty_and_release_lock(self):
        import threading
        from film_crew.vision import VisionClassifier
        classifier = VisionClassifier.__new__(VisionClassifier)
        classifier._lock = threading.Lock()
        classifier._lock.acquire()
        result = classifier.classify(b'bad', b'bad')
        self.assertFalse(result.valid)
        self.assertEqual((result.confidence, result.uncertainty, result.reason), (0., 1., 'classifier_busy'))
        classifier._lock.release()
        for _ in range(2):
            result = classifier.classify(b'bad', b'bad')
            self.assertFalse(result.valid)
            self.assertEqual((result.confidence, result.uncertainty), (0., 1.))
            self.assertTrue(classifier._lock.acquire(blocking=False))
            classifier._lock.release()

    def test_inference_failure_closes_images_without_exposing_exception_details(self):
        import threading
        from unittest.mock import patch
        from film_crew.vision import VisionClassifier
        class Image:
            closed = False
            def close(self): self.closed = True
        images = [Image(), Image()]
        classifier = VisionClassifier.__new__(VisionClassifier)
        classifier._lock = threading.Lock()
        classifier._torch = None  # Deliberate inference failure after successful decode.
        with patch('film_crew.vision._png', side_effect=images):
            result = classifier.classify(b'private frame', b'private frame')
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, 'invalid_snapshot_or_inference')
        self.assertTrue(all(image.closed for image in images))
        self.assertNotIn('private', str(result.as_dict()))
        self.assertTrue(classifier._lock.acquire(blocking=False))
        classifier._lock.release()

    def test_unreviewed_or_missing_local_artifacts_fail_before_model_loading(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from film_crew.vision import VisionClassifier
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                VisionClassifier(directory)
            Path(directory, 'open_clip_model.safetensors').write_bytes(b'not pretrained weights')
            with self.assertRaises(ValueError):
                VisionClassifier(directory)
            for options in ({'threads': True}, {'threads': 0}, {'device': 'network'}):
                with self.subTest(options=options):
                    with self.assertRaises(ValueError):
                        VisionClassifier(directory, **options)


if __name__ == "__main__":
    unittest.main()
