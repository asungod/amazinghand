import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from rehab_imitation import (  # noqa: E402
    ImitationSessionController,
    TERMINATION_REASON_USER_CANCELLED,
)


def elapsed(now_ms, previous_ms):
    return now_ms - previous_ms


def stable(controller, posture, now_ms):
    result = False
    for offset in range(controller.stable_frames):
        result = controller.observe(posture, now_ms + offset, elapsed)
    return result


class ImitationSessionTests(unittest.TestCase):
    def test_active_cancel_enters_terminal_state_with_reason_and_result(self):
        controller = ImitationSessionController(goal_repetitions=3)
        controller.start(100)
        stable(controller, "OPEN", 110)
        self.assertTrue(controller.cancel(250))
        self.assertEqual(controller.state, "TIMEOUT")
        self.assertEqual(controller.completed_ms, 250)
        self.assertEqual(
            controller.termination_reason, TERMINATION_REASON_USER_CANCELLED
        )
        self.assertEqual(
            controller.result_lines(250, elapsed)[0],
            "RESULT INCOMPLETE 0/3 0%",
        )
        self.assertIn("termination_reason=user_cancelled", controller.result_log_line(250, elapsed))
        self.assertEqual(controller.coaching_line(), "USER CANCELLED")

    def test_cancel_is_ignored_when_not_active(self):
        controller = ImitationSessionController(goal_repetitions=1)
        self.assertFalse(controller.cancel(100))
        self.assertEqual(controller.state, "IDLE")
        controller.start(0)
        stable(controller, "OPEN", 10)
        stable(controller, "CLOSED", 20)
        stable(controller, "OPEN", 30)
        self.assertEqual(controller.state, "COMPLETE")
        self.assertFalse(controller.cancel(40))
        self.assertEqual(controller.state, "COMPLETE")

    def test_cancel_does_not_emit_or_accept_late_observations(self):
        controller = ImitationSessionController(goal_repetitions=1)
        controller.start(0)
        stable(controller, "OPEN", 10)
        self.assertTrue(controller.cancel(20))
        for posture in ("CLOSED", "OPEN", "CLOSED", "OPEN"):
            self.assertFalse(controller.observe(posture, 30, elapsed))
        self.assertEqual(controller.repetitions, 0)
        self.assertEqual(controller.state, "TIMEOUT")

    def test_cancel_terminal_hold_restores_to_idle(self):
        controller = ImitationSessionController(
            goal_repetitions=1, terminal_hold_ms=100
        )
        controller.start(0)
        self.assertTrue(controller.cancel(10))
        self.assertFalse(controller.terminal_expired(109, elapsed))
        self.assertTrue(controller.terminal_expired(110, elapsed))
        controller.reset()
        self.assertEqual(controller.state, "IDLE")

    def test_five_explicit_open_close_open_cycles_complete(self):
        controller = ImitationSessionController(goal_repetitions=5)
        controller.start(0)
        stable(controller, "OPEN", 10)
        for repetition in range(5):
            stable(controller, "CLOSED", 100 + repetition * 100)
            stable(controller, "OPEN", 150 + repetition * 100)
        self.assertEqual(controller.state, "COMPLETE")
        self.assertEqual(controller.repetitions, 5)
        self.assertIn("USER COMPLETE 5/5", controller.status_line(1000, elapsed))
        self.assertEqual(controller.completion_percent(), 100)
        self.assertEqual(
            controller.result_lines(1000, elapsed)[0], "RESULT PASS 5/5 100%"
        )
        self.assertEqual(
            controller.result_lines(1000, elapsed)[2],
            "QUALITY DEGRADED rhythm=TOO_FAST hold=INSUFFICIENT",
        )
        self.assertIn("outcome=COMPLETE", controller.result_log_line(1000, elapsed))
        self.assertIn("completion_pct=100", controller.result_log_line(1000, elapsed))

    def test_visual_observations_before_start_cannot_count(self):
        controller = ImitationSessionController(goal_repetitions=1)
        stable(controller, "OPEN", 0)
        stable(controller, "CLOSED", 10)
        stable(controller, "OPEN", 20)
        self.assertEqual(controller.state, "IDLE")
        self.assertEqual(controller.repetitions, 0)

    def test_missing_and_mid_frames_do_not_complete_cycle(self):
        controller = ImitationSessionController(goal_repetitions=1)
        controller.start(0)
        stable(controller, "OPEN", 10)
        for posture in (None, "MID", None, "MID"):
            controller.observe(posture, 20, elapsed)
        stable(controller, "OPEN", 30)
        self.assertEqual(controller.repetitions, 0)
        self.assertEqual(controller.state, "ACTIVE")

    def test_observe_timeout_expires_quality_hold(self):
        controller = ImitationSessionController(goal_repetitions=1, timeout_ms=1000, stable_frames=1)
        controller.start(0)
        controller.observe("OPEN", 1, elapsed)
        controller.observe("CLOSED", 100, elapsed)
        self.assertFalse(controller.observe("CLOSED", 1000, elapsed))
        self.assertEqual(controller.state, "TIMEOUT")
        self.assertEqual(controller.quality_tracker.hold_durations_ms, [900])

    def test_timeout_fails_closed_and_late_frames_cannot_count(self):
        controller = ImitationSessionController(
            goal_repetitions=1, timeout_ms=1000
        )
        controller.start(100)
        self.assertFalse(controller.expire(1099, elapsed))
        self.assertTrue(controller.expire(1100, elapsed))
        stable(controller, "OPEN", 1200)
        stable(controller, "CLOSED", 1210)
        stable(controller, "OPEN", 1220)
        self.assertEqual(controller.state, "TIMEOUT")
        self.assertEqual(controller.repetitions, 0)
        self.assertEqual(
            controller.result_lines(1100, elapsed),
            (
                "RESULT INCOMPLETE 0/1 0%",
                "TIME 1.0s AVG -- REASON imitation_timeout",
                "QUALITY UNKNOWN rhythm=UNKNOWN hold=UNKNOWN",
            ),
        )
        self.assertIn("avg_rep_ms=-1", controller.result_log_line(1100, elapsed))
        self.assertFalse(controller.terminal_expired(4099, elapsed))
        self.assertTrue(controller.terminal_expired(4100, elapsed))

    def test_partial_timeout_result_reports_rate_and_average(self):
        controller = ImitationSessionController(
            goal_repetitions=4, timeout_ms=1000
        )
        controller.start(0)
        stable(controller, "OPEN", 10)
        stable(controller, "CLOSED", 100)
        stable(controller, "OPEN", 200)
        stable(controller, "CLOSED", 300)
        stable(controller, "OPEN", 400)
        self.assertTrue(controller.expire(1000, elapsed))
        self.assertEqual(controller.repetitions, 2)
        self.assertEqual(controller.completion_percent(), 50)
        self.assertEqual(controller.average_repetition_ms(1000, elapsed), 500)
        self.assertEqual(
            controller.result_lines(1000, elapsed),
            (
                "RESULT INCOMPLETE 2/4 50%",
                "TIME 1.0s AVG 0.5s REASON imitation_timeout",
                "QUALITY DEGRADED rhythm=TOO_FAST hold=INSUFFICIENT",
            ),
        )

    def test_hand_vision_failure_reason_is_displayed_and_logged(self):
        controller = ImitationSessionController(goal_repetitions=1)
        controller.start(0)
        self.assertTrue(controller.mark_timeout(100, "hand_vision_init_failed"))
        self.assertEqual(controller.termination_reason, "hand_vision_init_failed")
        self.assertIn("REASON hand_vision_init_failed", controller.result_lines(100, elapsed)[1])
        self.assertIn("termination_reason=hand_vision_init_failed", controller.result_log_line(100, elapsed))

    def test_result_quality_line_fails_closed_on_summary_error(self):
        class BrokenQuality:
            def reset(self):
                pass

            def summary(self):
                raise RuntimeError("quality unavailable")

        controller = ImitationSessionController(quality_tracker=BrokenQuality())
        controller.state = "COMPLETE"
        self.assertEqual(
            controller.result_quality_line(),
            "QUALITY UNKNOWN rhythm=UNKNOWN hold=UNKNOWN",
        )

    def test_active_runtime_quality_status_is_explicit_and_matches_result(self):
        controller = ImitationSessionController(goal_repetitions=2, stable_frames=1)
        controller.start(0)
        stable(controller, "OPEN", 10)
        stable(controller, "CLOSED", 100)
        stable(controller, "OPEN", 200)

        self.assertEqual(
            controller.quality_status_line(),
            "QUALITY UNKNOWN rhythm=UNKNOWN hold=INSUFFICIENT",
        )
        self.assertEqual(
            controller.result_quality_line(), controller.quality_status_line()
        )

    def test_quality_feedback_maps_existing_statuses_without_changing_quality_summary(self):
        controller = ImitationSessionController(goal_repetitions=2, stable_frames=1)
        controller.start(0)
        stable(controller, "OPEN", 10)
        stable(controller, "CLOSED", 100)
        stable(controller, "OPEN", 200)

        self.assertEqual(controller.quality_feedback_line(), "FEEDBACK HOLD TOO SHORT")
        self.assertEqual(controller.quality_tracker.summary()["rhythm_status"], "UNKNOWN")

    def test_quality_feedback_is_unknown_before_any_quality_data(self):
        controller = ImitationSessionController(goal_repetitions=1)
        controller.start(0)
        self.assertEqual(controller.quality_feedback_line(), "FEEDBACK UNKNOWN")

    def test_reset_clears_previous_session(self):
        controller = ImitationSessionController(goal_repetitions=1)
        controller.start(0)
        stable(controller, "OPEN", 10)
        stable(controller, "CLOSED", 20)
        stable(controller, "OPEN", 30)
        self.assertEqual(controller.state, "COMPLETE")
        controller.reset()
        self.assertEqual(controller.state, "IDLE")
        self.assertEqual(controller.repetitions, 0)


if __name__ == "__main__":
    unittest.main()
