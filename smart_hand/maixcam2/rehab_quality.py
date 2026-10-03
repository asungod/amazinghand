"""Pure-Python, best-effort training quality tracker.

This module is deliberately a side channel: it observes the same posture
labels as the repetition controller but has no authority over motion or the
existing session CSV format.
"""


class RhythmQualityTracker:
    """Measure repetition pace, closed-hand hold quality and frame coverage."""

    def __init__(
        self,
        target_interval_ms=2000,
        tolerance_ms=500,
        min_hold_ms=500,
        stable_frames=1,
        fast_threshold_ms=None,
        slow_threshold_ms=None,
        hold_grace_ms=250,
    ):
        if target_interval_ms <= 0:
            raise ValueError("target_interval_ms must be positive")
        if tolerance_ms < 0 or min_hold_ms < 0 or hold_grace_ms < 0:
            raise ValueError("quality thresholds must be non-negative")
        if stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        self.target_interval_ms = int(target_interval_ms)
        self.fast_threshold_ms = int(
            target_interval_ms - tolerance_ms
            if fast_threshold_ms is None else fast_threshold_ms
        )
        self.slow_threshold_ms = int(
            target_interval_ms + tolerance_ms
            if slow_threshold_ms is None else slow_threshold_ms
        )
        if self.fast_threshold_ms < 0 or self.slow_threshold_ms < self.fast_threshold_ms:
            raise ValueError("invalid rhythm thresholds")
        self.min_hold_ms = int(min_hold_ms)
        self.hold_grace_ms = int(hold_grace_ms)
        self.stable_frames = int(stable_frames)
        self.reset()

    def reset(self):
        self.repetition_completed = 0
        self.repetition_completed_ms = []
        self.hold_durations_ms = []
        self._phase = "WAIT_OPEN"
        self._candidate = None
        self._candidate_frames = 0
        self._closed_since_ms = None
        self._hold_break_since_ms = None
        self._observed_frames = 0
        self._valid_frames = 0
        self.last_now_ms = None

    def _stable_posture(self, posture):
        if posture not in ("OPEN", "MID", "CLOSED", None):
            raise ValueError("unknown posture")
        if posture in (None, "MID"):
            self._candidate = None
            self._candidate_frames = 0
            return None
        if posture != self._candidate:
            self._candidate = posture
            self._candidate_frames = 1
        else:
            self._candidate_frames += 1
        if self._candidate_frames < self.stable_frames:
            return None
        self._candidate_frames = 0
        return posture

    def observe(self, posture, now_ms):
        """Observe one frame and return True only on a completed repetition."""
        now_ms = int(now_ms)
        if self.last_now_ms is not None and now_ms < self.last_now_ms:
            raise ValueError("now_ms must be monotonic")
        self.last_now_ms = now_ms
        self._observed_frames += 1
        if posture in ("OPEN", "CLOSED"):
            self._valid_frames += 1
        if self._closed_since_ms is not None:
            if posture == "CLOSED":
                if (
                    self._hold_break_since_ms is not None
                    and now_ms - self._hold_break_since_ms > self.hold_grace_ms
                ):
                    self._finish_hold(self._hold_break_since_ms)
                else:
                    self._hold_break_since_ms = None
            elif self._hold_break_since_ms is None:
                self._hold_break_since_ms = now_ms
                if self.hold_grace_ms == 0:
                    self._finish_hold(now_ms)
            elif now_ms - self._hold_break_since_ms > self.hold_grace_ms:
                self._finish_hold(self._hold_break_since_ms)
        stable = self._stable_posture(posture)
        if stable is None:
            return False
        if stable == "CLOSED":
            if self._closed_since_ms is None:
                self._closed_since_ms = now_ms
            if self._phase == "WAIT_CLOSE":
                self._phase = "WAIT_REOPEN"
        elif stable == "OPEN":
            if self._closed_since_ms is not None:
                self._finish_hold(now_ms)
            if self._phase == "WAIT_OPEN":
                self._phase = "WAIT_CLOSE"
            elif self._phase == "WAIT_REOPEN":
                self.repetition_completed += 1
                self.repetition_completed_ms.append(now_ms)
                self._phase = "WAIT_CLOSE"
                return True
        return False

    def _finish_hold(self, now_ms):
        duration = max(0, int(now_ms) - self._closed_since_ms)
        self.hold_durations_ms.append(duration)
        self._closed_since_ms = None
        self._hold_break_since_ms = None

    def expire(self, now_ms):
        """Close an in-progress hold when the owning session times out."""
        if self._closed_since_ms is not None:
            self._finish_hold(int(now_ms))

    @property
    def hold_status(self):
        if not self.hold_durations_ms:
            return "UNKNOWN"
        return "OK" if all(x >= self.min_hold_ms for x in self.hold_durations_ms) else "INSUFFICIENT"

    @property
    def pace_intervals_ms(self):
        return [b - a for a, b in zip(self.repetition_completed_ms, self.repetition_completed_ms[1:])]

    @property
    def pace_avg_ms(self):
        values = self.pace_intervals_ms
        return None if not values else int(round(sum(values) / float(len(values))))

    @property
    def pace_min_ms(self):
        values = self.pace_intervals_ms
        return None if not values else min(values)

    @property
    def pace_max_ms(self):
        values = self.pace_intervals_ms
        return None if not values else max(values)

    @property
    def rhythm_status(self):
        values = self.pace_intervals_ms
        if not values:
            return "UNKNOWN"
        labels = []
        for value in values:
            if value < self.fast_threshold_ms:
                labels.append("TOO_FAST")
            elif value > self.slow_threshold_ms:
                labels.append("TOO_SLOW")
            else:
                labels.append("NORMAL")
        unique = set(labels)
        return labels[0] if len(unique) == 1 else "MIXED"

    @property
    def quality_status(self):
        if self.rhythm_status == "UNKNOWN" or self.hold_status == "UNKNOWN":
            return "UNKNOWN"
        return "OK" if self.rhythm_status == "NORMAL" and self.hold_status == "OK" else "DEGRADED"

    @property
    def valid_frame_pct(self):
        if not self._observed_frames:
            return None
        return round(100.0 * self._valid_frames / self._observed_frames, 1)

    # Friendly aliases for callers serializing a quality summary.
    @property
    def fast_count(self):
        return sum(x < self.fast_threshold_ms for x in self.pace_intervals_ms)

    @property
    def slow_count(self):
        return sum(x > self.slow_threshold_ms for x in self.pace_intervals_ms)

    @property
    def short_hold_count(self):
        return sum(x < self.min_hold_ms for x in self.hold_durations_ms)

    def summary(self):
        return {
            "quality_status": self.quality_status,
            "rhythm_status": self.rhythm_status,
            "hold_status": self.hold_status,
            "pace_avg_ms": self.pace_avg_ms,
            "pace_min_ms": self.pace_min_ms,
            "pace_max_ms": self.pace_max_ms,
            "fast_count": self.fast_count,
            "slow_count": self.slow_count,
            "short_hold_count": self.short_hold_count,
            "valid_frame_pct": self.valid_frame_pct,
            "repetitions": self.repetition_completed,
        }
