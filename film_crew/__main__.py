"""Host-operated rehearsal controls; not a public guest authorization service."""

import argparse
import hashlib
import json
from pathlib import Path
import time

from .cameras import DEFAULT_RUNTIME_DIR, load_manifest, prepare_manifest
from .config import load_obs_config
from .controller import Frame, OneCutDirector
from .policy import OneShotPolicy


def replay_accepted(path, *, supervised_trial=False):
    """Check a real manual-proof receipt for these exact model rules.

    This is a rehearsal interlock, not a signature/authentication boundary. The
    Normal use also needs held-out replay acceptance. Explicit supervised trial
    use permits one experiment without asserting that replay passed. Software
    tests/model timing benchmarks cannot fill in the physical proof fields.
    """
    try:
        source = Path(path)
        if source.stat().st_size > 16384:
            return False
        value = json.loads(source.read_text())
        here = Path(__file__).parent
        permitted = (value.get('supervised_trial_approved') is True if supervised_trial
                     else value.get('held_out_replay_passed') is True)
        return (value.get('manual_two_feed_switching_passed') is True and permitted
                and all(value.get(name + '_sha256') == hashlib.sha256(
                    (here / (name + '.py')).read_bytes()).hexdigest()
                        for name in ('vision', 'policy')))
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def run_watch(control, classifier, *, seconds, validation_ready, arm,
              clock=time.monotonic, sleep=time.sleep, emit=print):
    """Keep the model/socket resident for a bounded rehearsal and at most one cut."""
    director = OneCutDirector(OneShotPolicy(validation_ready=validation_ready), window_seconds=seconds)
    deadline = clock() + seconds

    def state():
        result = control.observe_program()
        scene = 'WIDE' if result['scene'] == 'WIDE' else 'DETAIL' if result['scene'] == 'OBJECT' else 'OTHER'
        # The adapter latches every unexpected program/collection event,
        # including a round trip that returns to the original scene.
        revision = 1 if result['override_detected'] else 0
        return scene, revision

    if arm:
        scene, revision = state()
        if revision or not director.arm(now=clock(), current_scene=scene, revision=revision):
            raise ValueError('Automatic choice needs its rehearsal receipt and an unchanged WIDE scene.')
    try:
        while clock() < deadline:
            scene, revision = state()
            if arm and not director.check_state(now=clock(), current_scene=scene, revision=revision):
                break
            shots = [control.snapshot(role, width=640, height=360) for role in ('wide', 'detail')]
            frames = [Frame(role, shot.png, shot.request_started_monotonic)
                      for role, shot in zip(('wide', 'detail'), shots)]
            evidence = classifier.classify(shots[0].png, shots[1].png)
            emit(json.dumps({'kind': 'semantic_evidence', 'observed_monotonic': clock(),
                             'pair_sampled_monotonic': {frame.role: frame.sampled_at for frame in frames},
                             **evidence.as_dict()}, separators=(',', ':')))
            scene, revision = state()
            if arm:
                proposal = director.consider(frames, evidence, now=clock(), current_scene=scene, revision=revision)
                if proposal:
                    scene, revision = state()
                    if director.take_proposal(now=clock(), current_scene=scene, revision=revision):
                        requested_at = clock()
                        control.switch('detail', not_after=min(frame.sampled_at for frame in frames)
                                       + director.max_evidence_age)
                        emit(json.dumps({'kind': 'cut_requested', 'view': 'OBJECT',
                                         'request_started_monotonic': requested_at,
                                         'readback_received_monotonic': clock(),
                                         'physical_result': 'requires_visible_observation'}))
                    break
                if not director.active:
                    break
            sleep(min(.1, max(0, deadline - clock())))
    finally:
        director.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Tenant two-phone OBS rehearsal on this Mac.')
    parser.add_argument('--runtime', type=Path, default=DEFAULT_RUNTIME_DIR)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('prepare', help='Prepare/reuse two private camera QR codes; no connection.')
    commands.add_parser('status', help='Read OBS state without preparing or switching scenes.')
    setup = commands.add_parser('setup', help='Prepare dedicated warm OBS camera scenes.')
    adoption = setup.add_mutually_exclusive_group()
    adoption.add_argument('--adopt-empty-owned', action='store_true')
    adoption.add_argument('--adopt-verified-owned', action='store_true')
    cut = commands.add_parser('cut'); cut.add_argument('view', choices=('wide', 'detail'))
    watch = commands.add_parser('watch', help='Keep local model warm and observe; no cuts unless armed.')
    watch.add_argument('--model-dir', type=Path, required=True)
    watch.add_argument('--device', choices=('cpu', 'mps'), default='mps')
    watch.add_argument('--seconds', type=float, default=120)
    watch.add_argument('--arm', action='store_true')
    watch.add_argument('--trial', action='store_true', help='One supervised experiment; requires a manual-proof trial receipt.')
    watch.add_argument('--validation', type=Path, default=DEFAULT_RUNTIME_DIR / 'validation.json')
    args = parser.parse_args(argv)
    if args.command == 'prepare':
        prepare_manifest(args.runtime)
        print('Two private camera invitations prepared. No camera or OBS connection opened.')
        return 0
    accepted = False
    if args.command == 'watch':
        if not 0 < args.seconds <= 600:
            parser.error('Use a finite rehearsal window up to 600 seconds.')
        if args.trial and not args.arm:
            parser.error('--trial is used with --arm for the single supervised choice.')
        accepted = replay_accepted(args.validation, supervised_trial=args.trial)
        if args.arm and not accepted:
            parser.error('These model rules need a real manual-proof receipt and replay acceptance or supervised trial release.')
        # Load and warm before starting the armed observation window.
        from .vision import VisionClassifier
        classifier = VisionClassifier(args.model_dir, device=args.device)
    from .obs_control import ObsControl
    deadline = time.monotonic() + (args.seconds if args.command == 'watch' else 60)
    with_control = ObsControl(load_obs_config(args.runtime / 'obs.json'),
                              authorize=lambda: time.monotonic() < deadline)
    try:
        with_control.connect()
        if args.command == 'status':
            print(json.dumps(with_control.discover()))
            return 0
        adoption_options = {}
        if args.command == 'setup':
            adoption_options = dict(adopt_empty_owned=args.adopt_empty_owned,
                                    adopt_verified_owned=args.adopt_verified_owned)
        with_control.configure(load_manifest(args.runtime / 'cameras.json'), **adoption_options)
        if args.command == 'setup':
            print('Dedicated warm camera scenes prepared; physical feeds still need verification.')
        elif args.command == 'cut':
            result = with_control.switch(args.view)
            print(json.dumps({'scene': result['scene'], 'physical_result': 'requires_visible_observation'}))
        else:
            run_watch(with_control, classifier, seconds=args.seconds, validation_ready=accepted, arm=args.arm)
    finally:
        with_control.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit('Film crew observation stopped; current scene retained.')
