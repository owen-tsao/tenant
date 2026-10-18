import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from PIL import Image

from film_crew.__main__ import replay_accepted, run_watch


class Clock:
    def __init__(self):
        self.now = 100.

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeObs:
    def __init__(self, clock):
        self.clock = clock
        self.scene = 'WIDE'
        self.override = False
        self.samples = 0
        self.switches = []
        self.state_calls = 0
        self.change_on_state = None
        self.delay_on_state = None

    def observe_program(self):
        self.state_calls += 1
        if self.state_calls == self.delay_on_state:
            self.clock.now += 1  # Slow final OBS RPC; overall rehearsal has not expired.
        if self.state_calls == self.change_on_state:
            self.override = True  # Includes a manual round trip back to WIDE.
        return dict(scene=self.scene, override_detected=self.override)

    def snapshot(self, role, **options):
        if role == 'wide':
            self.samples += 1
        image = Image.new('RGB', (32, 32), (self.samples * 20 % 255, 10, 10))
        stream = BytesIO(); image.save(stream, format='PNG')
        return SimpleNamespace(png=stream.getvalue(), request_started_monotonic=self.clock())

    def switch(self, role, *, not_after=None):
        if not_after is not None and self.clock() >= not_after:
            raise ValueError('Expired evidence before the actual write.')
        self.switches.append(role)
        self.scene = 'OBJECT'


class FakeClassifier:
    def __init__(self, clock, on_inference=None):
        self.clock = clock
        self.on_inference = on_inference

    def classify(self, wide, detail):
        self.clock.now += .2
        if self.on_inference:
            self.on_inference()
        values = dict(valid=True, demonstrating=.95, detail_usefulness=.95,
                      confidence=.95, uncertainty=.05)
        return SimpleNamespace(**values, as_dict=lambda: values)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.obs = FakeObs(self.clock)
        self.messages = []

    def run_watch(self, **changes):
        options = dict(seconds=3, validation_ready=True, arm=True,
                       clock=self.clock, sleep=self.clock.sleep, emit=self.messages.append)
        options.update(changes)
        run_watch(self.obs, FakeClassifier(self.clock), **options)

    def test_warm_loop_requests_only_one_cut(self):
        self.run_watch()
        self.assertEqual(self.obs.switches, ['detail'])
        self.assertEqual(sum(json.loads(line)['kind'] == 'cut_requested' for line in self.messages), 1)

    def test_observe_only_and_unaccepted_replay_never_switch(self):
        self.run_watch(arm=False, validation_ready=False)
        self.assertEqual(self.obs.switches, [])
        with self.assertRaises(ValueError):
            self.run_watch(validation_ready=False)
        self.assertEqual(self.obs.switches, [])

    def test_manual_roundtrip_after_inference_before_dispatch_blocks_cut(self):
        # Five acquired pairs complete dwell; state12 is the final proposal check.
        self.obs.change_on_state = 12
        self.run_watch()
        self.assertEqual(self.obs.switches, [])

    def test_slow_final_state_read_cannot_dispatch_stale_evidence(self):
        self.obs.delay_on_state = 12
        self.run_watch()
        self.assertEqual(self.obs.switches, [])

    def test_expiry_during_inference_and_latched_manual_change_block_cut(self):
        for change in ('expiry', 'manual'):
            with self.subTest(change=change):
                self.setUp()
                def interrupt():
                    if change == 'expiry':
                        self.clock.now += 10
                    else:
                        self.obs.override = True
                run_watch(self.obs, FakeClassifier(self.clock, interrupt), seconds=3,
                          validation_ready=True, arm=True, clock=self.clock,
                          sleep=self.clock.sleep, emit=self.messages.append)
                self.assertEqual(self.obs.switches, [])

    def test_replay_receipt_requires_physical_and_replay_results_for_exact_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'validation.json'
            self.assertFalse(replay_accepted(path))
            here = Path(__file__).parents[1] / 'film_crew'
            value = {name + '_sha256': hashlib.sha256((here / (name + '.py')).read_bytes()).hexdigest()
                     for name in ('vision', 'policy')}
            value['manual_two_feed_switching_passed'] = True
            value['held_out_replay_passed'] = True
            path.write_text(json.dumps(value))
            self.assertTrue(replay_accepted(path))
            for key in ('manual_two_feed_switching_passed', 'held_out_replay_passed', 'vision_sha256'):
                changed = dict(value); changed[key] = False
                path.write_text(json.dumps(changed))
                self.assertFalse(replay_accepted(path))

    def test_explicit_trial_receipt_does_not_claim_replay_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'trial.json'
            here = Path(__file__).parents[1] / 'film_crew'
            value = {name + '_sha256': hashlib.sha256((here / (name + '.py')).read_bytes()).hexdigest()
                     for name in ('vision', 'policy')}
            value.update(manual_two_feed_switching_passed=True, supervised_trial_approved=True,
                         held_out_replay_passed=False)
            path.write_text(json.dumps(value))
            self.assertTrue(replay_accepted(path, supervised_trial=True))
            self.assertFalse(replay_accepted(path))
            value['manual_two_feed_switching_passed'] = False
            path.write_text(json.dumps(value))
            self.assertFalse(replay_accepted(path, supervised_trial=True))
