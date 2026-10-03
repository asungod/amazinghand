"""User-imitation phase controller for a rehabilitation training session.

Pure Python: no Maix imports, UART access, or motion commands.  Mechanical
demonstration completion may start this controller, but visual observations can
only update the user's repetition count.
"""

from hand_rehab_tracker import RepetitionTracker
from rehab_quality import RhythmQualityTracker


TERMINATION_REASON_GOAL_REACHED = "goal_reached"
TERMINATION_REASON_IMITATION_TIMEOUT = "imitation_timeout"
TERMINATION_REASON_HAND_VISION_INIT_FAILED = "hand_vision_init_failed"
TERMINATION_REASON_USER_CANCELLED = "user_cancelled"


class ImitationSessionController:
    def __init__(
        self,
        goal_repetitions=5,
        timeout_ms=60000,
        stable_frames=3,
        terminal_hold_ms=3000,
        quality_tracker=None,
    ):
        if goal_repetitions < 1:
            raise ValueError("goal_repetitions must be positive")
        if timeout_ms < 1000:
            raise ValueError("timeout_ms must be at least 1000")
        self.goal_repetitions = int(goal_repetitions)
        self.timeout_ms = int(timeout_ms)
        self.stable_frames = int(stable_frames)
        self.terminal_hold_ms = int(terminal_hold_ms)
        self.state = "IDLE"
        self.started_ms = None
        self.completed_ms = None
        self.termination_reason = None
        self.tracker = RepetitionTracker(self.stable_frames)
        self.quality_tracker = quality_tracker or RhythmQualityTracker(stable_frames=self.stable_frames)

    @property
    def repetitions(self):
        return self.tracker.repetitions

    def start(self, now_ms):
        self.tracker = RepetitionTracker(self.stable_frames)
        self.quality_tracker.reset()
        self.started_ms = now_ms
        self.completed_ms = None
        self.termination_reason = None
        self.state = "ACTIVE"

    def reset(self):
        self.tracker = RepetitionTracker(self.stable_frames)
        self.quality_tracker.reset()
        self.started_ms = None
        self.completed_ms = None
        self.termination_reason = None
        self.state = "IDLE"

    def mark_timeout(self, now_ms, reason=TERMINATION_REASON_IMITATION_TIMEOUT):
        """Close an active session with a fixed, non-diagnostic reason code."""
        if self.state != "ACTIVE":
            return False
        self.state = "TIMEOUT"
        self.completed_ms = now_ms
        self.termination_reason = str(reason)
        self.quality_tracker.expire(now_ms)
        return True

    def cancel(self, now_ms):
        """Close only the active user-imitation session locally.

        Cancellation is deliberately a controller-only transition.  It does
        not emit a UART frame or request any Titan motion, and terminal result
        handling remains shared with timeout sessions.
        """
        return self.mark_timeout(now_ms, TERMINATION_REASON_USER_CANCELLED)

    def observe(self, posture, now_ms, elapsed_ms):
        if self.state != "ACTIVE":
            return False
        if elapsed_ms(now_ms, self.started_ms) >= self.timeout_ms:
            self.mark_timeout(now_ms)
            return False
        completed_rep = self.tracker.observe(posture)
        self.quality_tracker.observe(posture, now_ms)
        if completed_rep and self.repetitions >= self.goal_repetitions:
            self.completed_ms = now_ms
            self.state = "COMPLETE"
            self.termination_reason = TERMINATION_REASON_GOAL_REACHED
        return completed_rep

    def expire(self, now_ms, elapsed_ms):
        if self.state != "ACTIVE":
            return False
        if elapsed_ms(now_ms, self.started_ms) < self.timeout_ms:
            return False
        return self.mark_timeout(now_ms)

    def terminal_expired(self, now_ms, elapsed_ms):
        return bool(
            self.state in ("COMPLETE", "TIMEOUT")
            and self.completed_ms is not None
            and elapsed_ms(now_ms, self.completed_ms) >= self.terminal_hold_ms
        )

    def duration_ms(self, now_ms, elapsed_ms):
        if self.started_ms is None:
            return None
        end_ms = self.completed_ms if self.completed_ms is not None else now_ms
        return elapsed_ms(end_ms, self.started_ms)

    def completion_percent(self):
        return min(100, int(round(
            100.0 * self.repetitions / self.goal_repetitions
        )))

    def average_repetition_ms(self, now_ms, elapsed_ms):
        if self.repetitions < 1:
            return None
        return int(round(
            self.duration_ms(now_ms, elapsed_ms) / self.repetitions
        ))

    def result_lines(self, now_ms, elapsed_ms):
        """Return compact on-device result lines for a terminal session."""
        if self.state not in ("COMPLETE", "TIMEOUT"):
            return None
        duration = self.duration_ms(now_ms, elapsed_ms)
        average = self.average_repetition_ms(now_ms, elapsed_ms)
        outcome = "PASS" if self.state == "COMPLETE" else "INCOMPLETE"
        line_1 = "RESULT {} {}/{} {}%".format(
            outcome,
            self.repetitions,
            self.goal_repetitions,
            self.completion_percent(),
        )
        line_2 = "TIME {:.1f}s AVG {}".format(
            duration / 1000.0,
            "--" if average is None else "{:.1f}s".format(average / 1000.0),
        )
        return line_1, line_2, self.result_quality_line()

    def result_quality_line(self):
        """Return a compact quality summary for the on-device view."""
        return self.quality_status_line()

    def quality_feedback_line(self):
        """Return a display-only, actionable quality hint.

        The quality tracker remains the source of truth; this method only
        converts its existing statuses into short English keys which the
        MaixCAM2 overlay can translate when a Chinese font is available.
        English keys are intentionally retained as the firmware fallback.
        """
        try:
            summary = self.quality_tracker.summary()
            quality_status = summary.get("quality_status", "UNKNOWN")
            rhythm_status = summary.get("rhythm_status", "UNKNOWN")
            hold_status = summary.get("hold_status", "UNKNOWN")
            valid_frame_pct = summary.get("valid_frame_pct")
        except Exception:
            quality_status = rhythm_status = hold_status = "UNKNOWN"
            valid_frame_pct = None

        # Do not show a failure hint before the tracker has enough data to
        # evaluate a session.  Low coverage is a separate tracking hint.
        if valid_frame_pct is not None and valid_frame_pct < 50.0:
            return "TRACKING LOW"
        if hold_status == "INSUFFICIENT":
            return "FEEDBACK HOLD TOO SHORT"
        if rhythm_status == "TOO_SLOW":
            return "FEEDBACK TOO SLOW"
        if rhythm_status == "TOO_FAST":
            return "FEEDBACK TOO FAST"
        if quality_status == "UNKNOWN":
            return "FEEDBACK UNKNOWN"
        if quality_status == "OK":
            return "FEEDBACK OK"
        return "FEEDBACK UNKNOWN"

    def coaching_line(self):
        """Return one short, actionable coaching hint for a terminal view.

        This is presentation-only. It never changes training completion, UART
        commands, or the motion safety lock. When both rhythm and hold need
        attention, holding the closed hand is prioritized because it is a
        single observable action for the next repetition.
        """
        if self.termination_reason == TERMINATION_REASON_USER_CANCELLED:
            return "USER CANCELLED"
        try:
            summary = self.quality_tracker.summary()
            quality_status = summary.get("quality_status", "UNKNOWN")
            rhythm_status = summary.get("rhythm_status", "UNKNOWN")
            hold_status = summary.get("hold_status", "UNKNOWN")
        except Exception:
            quality_status = rhythm_status = hold_status = "UNKNOWN"

        if hold_status == "INSUFFICIENT":
            return "NEXT: HOLD CLOSED"
        if rhythm_status == "TOO_FAST":
            return "NEXT: SLOW DOWN"
        if rhythm_status == "TOO_SLOW":
            return "NEXT: MOVE STEADY"
        if rhythm_status == "MIXED":
            return "NEXT: KEEP RHYTHM"
        if quality_status == "OK":
            return "NEXT: GOOD JOB"
        return "NEXT: TRY AGAIN"
    def quality_status_line(self):
        """Return the current fail-closed quality status for runtime display."""
        quality = self.quality_tracker
        try:
            summary = quality.summary()
            quality_status = summary.get("quality_status", "UNKNOWN")
            rhythm_status = summary.get("rhythm_status", "UNKNOWN")
            hold_status = summary.get("hold_status", "UNKNOWN")
        except Exception:
            quality_status = rhythm_status = hold_status = "UNKNOWN"
        # Keep the on-device overlay short enough to remain on one line.  The
        # full status values are still preserved by the quality summary and
        # session CSV logger; this is display-only compression.
        rhythm_label = {
            "NORMAL": "OK",
            "TOO_FAST": "FAST",
            "TOO_SLOW": "SLOW",
            "MIXED": "MIX",
            "UNKNOWN": "?",
        }.get(rhythm_status, rhythm_status)
        hold_label = {
            "OK": "OK",
            "INSUFFICIENT": "SHORT",
            "UNKNOWN": "?",
        }.get(hold_status, hold_status)
        quality_label = {
            "OK": "OK",
            "DEGRADED": "WARN",
            "UNKNOWN": "?",
        }.get(quality_status, quality_status)
        return "Q:{} P:{} H:{}".format(
            quality_label, rhythm_label, hold_label
        )

    def result_log_line(self, now_ms, elapsed_ms):
        if self.state not in ("COMPLETE", "TIMEOUT"):
            return None
        average = self.average_repetition_ms(now_ms, elapsed_ms)
        return (
            "USER SESSION RESULT outcome={} reps={} goal={} duration_ms={} "
            "completion_pct={} avg_rep_ms={} termination_reason={}"
        ).format(
            self.state,
            self.repetitions,
            self.goal_repetitions,
            self.duration_ms(now_ms, elapsed_ms),
            self.completion_percent(),
            -1 if average is None else average,
            self.termination_reason or "unknown",
        )

    def status_line(self, now_ms, elapsed_ms):
        if self.state == "IDLE":
            return "USER WAIT_DEMO"
        duration = self.duration_ms(now_ms, elapsed_ms)
        seconds = duration / 1000.0 if duration is not None else 0.0
        if self.state == "COMPLETE":
            return "USER COMPLETE {}/{} {:.1f}s".format(
                self.repetitions, self.goal_repetitions, seconds
            )
        if self.state == "TIMEOUT":
            return "USER TIMEOUT {}/{}".format(
                self.repetitions, self.goal_repetitions
            )
        return "IMITATE {}/{} {:.1f}s".format(
            self.repetitions, self.goal_repetitions, seconds
        )

