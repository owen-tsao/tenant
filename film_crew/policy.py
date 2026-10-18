"""Offline, one-shot cut proposals. This module never controls a switcher.

Thresholds are provisional: real positive/negative replay must pass before the
caller sets ``validation_ready``. Capture times identify local snapshot
acquisition on the same monotonic clock as ``now``; they do not prove that a
camera source is advancing. The separate ``sources_fresh`` caller interlock
must cover both views. A pixel-change watchdog is conservative and can reject
a genuinely static source; it cannot establish sensor-frame authenticity.
"""

from collections.abc import Mapping
import math
from numbers import Real


def _finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _field(evidence: object, name: str) -> object:
    if isinstance(evidence, Mapping):
        return evidence.get(name)
    return getattr(evidence, name, None)


class OneShotPolicy:
    """Require an explicit arm and sustained semantic evidence for one DETAIL.

    Manual override, disconnect, a non-WIDE scene, or the external ``armed``
    or ``sources_fresh`` interlock going false disarms. Clearing those
    conditions never rearms.
    A returned proposal consumes the arm even if the caller cannot execute it;
    retry requires a deliberate new arm. WIDE is the caller's initial scene,
    not a scene this policy forces back after human intervention.
    """

    MIN_DEMONSTRATING = 0.75
    MIN_DETAIL_USEFULNESS = 0.75
    MIN_CONFIDENCE = 0.8
    MAX_UNCERTAINTY = 0.2
    MIN_DWELL = 0.75
    MIN_OBSERVATIONS = 3
    MAX_AGE = 0.5
    MAX_GAP = 0.6
    ARM_DELAY = 0.25

    def __init__(
        self,
        *,
        validation_ready: bool = False,
        max_age: float = 0.5,
        max_gap: float = 0.6,
        min_dwell: float = 0.75,
        min_observations: int = 3,
        arm_delay: float = 0.25,
    ):
        """Set bounded timing budgets after measuring the complete caller path.

        Age/gap must be in (0, 10] seconds, dwell in [.75, 30] seconds,
        observation count an integer in [3, 100], and delay in [0, 10] seconds.
        """
        for name, value, minimum, maximum in (
            ("max_age", max_age, 0, 10),
            ("max_gap", max_gap, 0, 10),
            ("min_dwell", min_dwell, self.MIN_DWELL, 30),
            ("arm_delay", arm_delay, 0, 10),
        ):
            if (not _finite_number(value) or not minimum <= value <= maximum
                    or (name in ("max_age", "max_gap") and value == 0)):
                raise ValueError(f"Invalid {name} timing budget")
        if (not isinstance(min_observations, int) or isinstance(min_observations, bool)
                or not self.MIN_OBSERVATIONS <= min_observations <= 100):
            raise ValueError("min_observations must be an integer in [3, 100]")
        self._max_age = max_age
        self._max_gap = max_gap
        self._min_dwell = min_dwell
        self._min_observations = min_observations
        self._arm_delay = arm_delay
        self.validation_ready = validation_ready
        self._active = False
        self._armed_at = None
        self._last_now = None
        self._last_capture = None
        self._clear_dwell()

    def _clear_dwell(self) -> None:
        self._positive_since = None
        self._observations = 0

    def reset_observations(self) -> None:
        """Interrupt semantic dwell without rearming or consuming the current arm."""
        self._clear_dwell()

    def disarm(self) -> None:
        self._active = False
        self._armed_at = None
        self._last_capture = None
        self._clear_dwell()

    def _advance_clock(self, now: object) -> bool:
        if not _finite_number(now) or (self._last_now is not None and now < self._last_now):
            self.disarm()
            return False
        self._last_now = now
        return True

    def arm(self, *, now: float, current_scene: str = "WIDE") -> bool:
        """Start a fresh observation window; return whether arming succeeded."""
        self.disarm()
        if not self._advance_clock(now):
            return False
        if self.validation_ready is not True or current_scene != "WIDE":
            return False
        self._active = True
        self._armed_at = now
        return True

    def propose(
        self,
        evidence: object,
        *,
        now: float,
        captured_at: float,
        armed: bool,
        manual_override: bool,
        connected: bool = True,
        sources_fresh: bool = False,
        current_scene: str = "WIDE",
    ) -> str | None:
        """Propose DETAIL once, or return None; scores are not actuator commands."""
        if not self._advance_clock(now):
            return None
        if (self.validation_ready is not True or armed is not True
                or manual_override is not False or connected is not True
                or sources_fresh is not True
                or current_scene != "WIDE"):
            self.disarm()
            return None
        if not self._active:
            return None
        if (not _finite_number(captured_at) or captured_at > now
                or captured_at < self._armed_at or now - captured_at > self._max_age
                or (self._last_capture is not None and captured_at < self._last_capture)):
            self._clear_dwell()
            return None
        if captured_at - self._armed_at < self._arm_delay:
            self._clear_dwell()
            return None

        duplicate = captured_at == self._last_capture
        if self._last_capture is not None and captured_at - self._last_capture > self._max_gap:
            self._clear_dwell()
        self._last_capture = captured_at

        scores = {name: _field(evidence, name) for name in (
            "demonstrating", "detail_usefulness", "confidence", "uncertainty")}
        similarity = _field(evidence, "pair_similarity")
        if (_field(evidence, "valid") is not True
                or any(not _finite_number(value) or not 0 <= value <= 1
                       for value in scores.values())
                or (similarity is not None and
                    (not _finite_number(similarity) or not -1 <= similarity <= 1))):
            self._clear_dwell()
            return None
        if (scores["demonstrating"] < self.MIN_DEMONSTRATING
                or scores["detail_usefulness"] < self.MIN_DETAIL_USEFULNESS
                or scores["confidence"] < self.MIN_CONFIDENCE
                or scores["uncertainty"] > self.MAX_UNCERTAINTY):
            self._clear_dwell()
            return None
        if duplicate:
            return None
        if self._positive_since is None:
            self._positive_since = captured_at
        self._observations += 1
        if (self._observations >= self._min_observations
                and captured_at - self._positive_since >= self._min_dwell):
            self.disarm()
            return "DETAIL"
        return None
