"""One supervised attention shift; acquisition and OBS stay outside this module.

The watchdog measures decoded pixel changes, not camera authenticity. A live
sender can repeat old images; a still genuine view can be conservatively refused.
No code here grants a public Tenant guest access or changes a room lease.
"""

from dataclasses import dataclass, field
import hashlib
from io import BytesIO
import math
import warnings

from film_crew.policy import OneShotPolicy


@dataclass(frozen=True)
class Frame:
    role: str
    png: bytes = field(repr=False)
    sampled_at: float


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def pixel_digest(png: bytes) -> bytes:
    """Hash decoded RGB pixels; changing PNG metadata cannot fake new imagery."""
    from PIL import Image
    if not isinstance(png, bytes) or not 0 < len(png) <= 8 * 1024 * 1024:
        raise ValueError('Expected a bounded PNG.')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(png), formats=['PNG']) as image:
            if image.width < 16 or image.height < 16 or image.width * image.height > 4_000_000:
                raise ValueError('Unsupported snapshot dimensions.')
            image.load()
            rgb = image.convert('RGB')
            try:
                digest = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).digest()
            finally:
                rgb.close()
            return digest


class PixelWatchdog:
    """Require recent *changes* in both views, never just a recent API response."""

    def __init__(self, *, max_age=2.0):
        if not _number(max_age) or not 0 < max_age <= 10:
            raise ValueError('Invalid pixel freshness budget.')
        self.max_age = max_age
        self._views = {}

    def clear(self):
        self._views.clear()

    def observe(self, frame: Frame, *, now: float) -> bool:
        if (frame.role not in {'wide', 'detail'} or not _number(now)
                or not _number(frame.sampled_at) or frame.sampled_at > now
                or now - frame.sampled_at > self.max_age):
            self.clear()
            return False
        previous = self._views.get(frame.role)
        if previous and frame.sampled_at <= previous[1]:
            self.clear()
            return False
        try:
            fingerprint = pixel_digest(frame.png)
        except Exception:
            self.clear()
            return False
        changed_at = None if previous is None else previous[2]
        if previous and fingerprint != previous[0]:
            changed_at = frame.sampled_at
        self._views[frame.role] = (fingerprint, frame.sampled_at, changed_at)
        return True

    def fresh(self, *, now: float) -> bool:
        return (_number(now) and set(self._views) == {'wide', 'detail'}
                and all(changed is not None and 0 <= now - changed <= self.max_age
                        for _, _, changed in self._views.values()))

    def changed_in(self, frame: Frame) -> bool:
        """Whether this sample changed pixels, rather than just the last sample."""
        view = self._views.get(frame.role)
        return view is not None and view[2] == frame.sampled_at


class OneCutDirector:
    """Pure coordinator; returns one proposal, never invokes OBS itself.

    Call arm once per explicit operator request. Sample both views, run the model,
    and call consider with a fresh switcher state *after* inference. Recheck that
    state again immediately before executing the returned proposal. OBS has no
    atomic conditional switch; an in-flight human/remote switch remains a narrow
    race that this supervised experiment cannot eliminate.
    """

    def __init__(self, policy: OneShotPolicy, *, window_seconds=120, pixel_max_age=2.0,
                 max_evidence_age=.5):
        if not _number(window_seconds) or not 0 < window_seconds <= 600:
            raise ValueError('Invalid supervised observation window.')
        if not _number(max_evidence_age) or not 0 < max_evidence_age <= 10:
            raise ValueError('Invalid semantic evidence age.')
        self.policy = policy
        self.watchdog = PixelWatchdog(max_age=pixel_max_age)
        self.window_seconds = window_seconds
        self.max_evidence_age = max_evidence_age
        self.active = False
        self.reason = 'not_armed'
        self._revision = None
        self._deadline = None
        self._observing = False
        self._pending = False
        self._pending_sampled_at = None
        self._proposed_at = None

    def stop(self, reason='stopped'):
        self.active = False
        self.reason = reason
        self._pending = False
        self.policy.disarm()

    def arm(self, *, now, current_scene, revision):
        self.watchdog.clear()
        self._pending = False
        self._observing = False
        self.active = self.policy.arm(now=now, current_scene=current_scene)
        self.reason = 'waiting_for_pixel_changes' if self.active else 'validation_or_scene_gate'
        self._revision = revision
        self._deadline = now + self.window_seconds if self.active else None
        return self.active

    def check_state(self, *, now, current_scene, revision):
        if not self.active:
            return False
        if not _number(now) or now >= self._deadline:
            self.stop('observation_window_ended')
        elif current_scene != 'WIDE' or revision != self._revision:
            self.stop('manual_or_external_scene_change')
        return self.active

    def consider(self, frames, evidence, *, now, current_scene, revision):
        if not self.check_state(now=now, current_scene=current_scene, revision=revision):
            return None
        if (not isinstance(frames, (list, tuple)) or len(frames) != 2
                or any(not isinstance(frame, Frame) or not isinstance(frame.role, str) for frame in frames)
                or {frame.role for frame in frames} != {'wide', 'detail'}):
            self.stop('invalid_frame_pair')
            return None
        if not all(self.watchdog.observe(frame, now=now) for frame in frames):
            self.stop('invalid_or_stale_snapshot')
            return None
        fresh = self.watchdog.fresh(now=now)
        if not fresh:
            if self._observing:
                self.stop('no_recent_pixel_changes')
            return None
        self._observing = True
        if not all(self.watchdog.changed_in(frame) for frame in frames):
            self.policy.reset_observations()
            return None
        sampled_at = min(frame.sampled_at for frame in frames)
        proposal = self.policy.propose(
            evidence, now=now, captured_at=sampled_at,
            armed=True, manual_override=False, connected=True,
            current_scene=current_scene, sources_fresh=True)
        if proposal:
            self.stop('one_cut_proposed')
            self._pending = True
            self._pending_sampled_at = sampled_at
            self._proposed_at = now
        return proposal

    def take_proposal(self, *, now, current_scene, revision):
        """Consume once, after a final deadline/cancellation/switcher recheck.

        Never retry a failed or unknown switch result. A new operator arm is
        needed even if the underlying WebSocket failed before displaying a cut.
        """
        if not self._pending:
            return None
        if (not _number(now) or now >= self._deadline):
            self.stop('observation_window_ended')
            return None
        if (now < self._proposed_at or now - self._pending_sampled_at > self.max_evidence_age
                or not self.watchdog.fresh(now=now)):
            self.stop('stale_pending_evidence')
            return None
        if current_scene != 'WIDE' or revision != self._revision:
            self.stop('manual_or_external_scene_change')
            return None
        self._pending = False
        self.reason = 'cut_dispatch_issued'
        return 'DETAIL'
