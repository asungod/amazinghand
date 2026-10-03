import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "maixcam2"))

from rehab_imitation import ImitationSessionController
from rehab_quality import RhythmQualityTracker
from rehab_session_log import SessionCsvLogger


class RhythmQualityTests(unittest.TestCase):
    def feed(self, tracker, frames):
        events = [tracker.observe(posture, now) for posture, now in frames]
        return events

    def tracker(self):
        return RhythmQualityTracker(
            target_interval_ms=1000, tolerance_ms=100, min_hold_ms=100
        )

    def test_normal_pace_and_hold(self):
        tracker = self.tracker()
        events = self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("OPEN", 250),
                                     ("CLOSED", 1100), ("OPEN", 1250),
                                     ("CLOSED", 2100), ("OPEN", 2250)])
        self.assertEqual(sum(events), 3)
        self.assertEqual(tracker.rhythm_status, "NORMAL")
        self.assertEqual(tracker.hold_status, "OK")
        self.assertEqual(tracker.quality_status, "OK")
        self.assertEqual(tracker.pace_avg_ms, 1000)

    def test_fast_slow_and_mixed(self):
        tracker = self.tracker()
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 10), ("OPEN", 120),
                            ("CLOSED", 510), ("OPEN", 620),
                            ("CLOSED", 2020), ("OPEN", 2130)])
        self.assertEqual(tracker.rhythm_status, "MIXED")
        self.assertEqual(tracker.fast_count, 1)
        self.assertEqual(tracker.slow_count, 1)

        fast = self.tracker()
        self.feed(fast, [("OPEN", 0), ("CLOSED", 10), ("OPEN", 120),
                         ("CLOSED", 500), ("OPEN", 620)])
        self.assertEqual(fast.rhythm_status, "TOO_FAST")

        slow = self.tracker()
        self.feed(slow, [("OPEN", 0), ("CLOSED", 10), ("OPEN", 120),
                         ("CLOSED", 1500), ("OPEN", 1620)])
        self.assertEqual(slow.rhythm_status, "TOO_SLOW")

    def test_short_mid_and_none_do_not_break_hold(self):
        tracker = RhythmQualityTracker(
            target_interval_ms=1000, tolerance_ms=100, min_hold_ms=300
        )
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("MID", 180),
                            (None, 220), ("CLOSED", 300), ("OPEN", 500)])
        self.assertEqual(tracker.hold_durations_ms, [400])
        self.assertEqual(tracker.hold_status, "OK")

    def test_hold_break_beyond_grace_finishes_hold(self):
        tracker = RhythmQualityTracker(
            target_interval_ms=1000, tolerance_ms=100, min_hold_ms=100,
            hold_grace_ms=100
        )
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("MID", 150),
                            ("OPEN", 251)])
        self.assertEqual(tracker.hold_durations_ms, [50])
        self.assertEqual(tracker.hold_status, "INSUFFICIENT")

    def test_default_hold_grace_is_backward_compatible(self):
        tracker = self.tracker()
        self.assertEqual(tracker.hold_grace_ms, 250)
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("MID", 200),
                            ("CLOSED", 300), ("OPEN", 500)])
        self.assertEqual(tracker.hold_durations_ms, [400])

    def test_short_hold_and_timeout(self):
        tracker = self.tracker()
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("OPEN", 150),
                            ("CLOSED", 1100)])
        tracker.expire(1150)
        self.assertEqual(tracker.hold_status, "INSUFFICIENT")
        self.assertEqual(tracker.short_hold_count, 2)

    def test_no_second_completion_leaves_pace_unknown(self):
        tracker = self.tracker()
        self.feed(tracker, [("OPEN", 0), ("CLOSED", 100), ("OPEN", 250)])
        self.assertEqual(tracker.repetition_completed, 1)
        self.assertEqual(tracker.rhythm_status, "UNKNOWN")
        self.assertIsNone(tracker.pace_avg_ms)

    def test_controller_exposes_tracker_and_reset(self):
        controller = ImitationSessionController(goal_repetitions=1, stable_frames=1)
        self.assertIs(controller.quality_tracker, controller.quality_tracker)
        controller.start(0)
        controller.observe("OPEN", 1, lambda a, b: a - b)
        controller.observe("CLOSED", 100, lambda a, b: a - b)
        controller.observe("OPEN", 250, lambda a, b: a - b)
        self.assertEqual(controller.quality_tracker.repetition_completed, 1)
        controller.reset()
        self.assertEqual(controller.quality_tracker.repetition_completed, 0)

    def test_quality_sidecar_is_optional_and_separate(self):
        controller = ImitationSessionController(goal_repetitions=1, stable_frames=1)
        controller.start(0)
        elapsed = lambda a, b: a - b
        for posture, now in (("OPEN", 1), ("CLOSED", 100), ("OPEN", 250)):
            controller.observe(posture, now, elapsed)
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "sessions.csv"
            quality = Path(directory) / "quality.csv"
            logger = SessionCsvLogger(str(base))
            self.assertEqual(logger.append(controller, 250, elapsed), 1)
            self.assertEqual(logger.append_quality(controller, session_number=1, now_ms=250, path=str(quality)), 1)
            self.assertEqual(logger.append_quality(controller, session_number=1, path=str(quality)), 1)
            self.assertEqual(len(base.read_text().splitlines()[0].split(",")), 9)
            self.assertEqual(len(quality.read_text().splitlines()[0].split(",")), 12)
            self.assertEqual(len(quality.read_text().splitlines()), 2)
            self.assertEqual(quality.read_text().splitlines()[1].split(",")[1], "1")


if __name__ == "__main__":
    unittest.main()