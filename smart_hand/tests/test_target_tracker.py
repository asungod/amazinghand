import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from target_tracker import TargetTracker, VisionScheduler, payload_iou  # noqa: E402


def elapsed_ms(now_ms, previous_ms):
    return now_ms - previous_ms


class TargetTrackerTests(unittest.TestCase):
    TARGET = (41, 100, 100, 40, 60, 90)

    def test_requires_consecutive_stable_frames(self):
        tracker = TargetTracker(3, 750, 0.2)
        self.assertIsNone(tracker.observe(self.TARGET, 0, elapsed_ms))
        self.assertIsNone(tracker.observe(self.TARGET, 10, elapsed_ms))
        self.assertEqual(tracker.observe(self.TARGET, 20, elapsed_ms), self.TARGET)
        self.assertEqual(tracker.acquired, 1)

    def test_matching_active_target_updates_immediately(self):
        tracker = TargetTracker(1, 750, 0.2)
        tracker.observe(self.TARGET, 0, elapsed_ms)
        moved = (41, 105, 102, 40, 60, 95)
        self.assertEqual(tracker.observe(moved, 10, elapsed_ms), moved)
        self.assertEqual(tracker.updated, 1)

    def test_different_target_switches_only_after_stability(self):
        tracker = TargetTracker(2, 750, 0.2)
        tracker.observe(self.TARGET, 0, elapsed_ms)
        tracker.observe(self.TARGET, 10, elapsed_ms)
        other = (47, 300, 300, 50, 50, 92)
        self.assertEqual(tracker.observe(other, 20, elapsed_ms), self.TARGET)
        self.assertEqual(tracker.observe(other, 30, elapsed_ms), other)
        self.assertEqual(tracker.switches, 1)

    def test_short_dropout_is_tolerated_then_target_expires(self):
        tracker = TargetTracker(1, 750, 0.2)
        tracker.observe(self.TARGET, 100, elapsed_ms)
        self.assertEqual(tracker.observe(None, 800, elapsed_ms), self.TARGET)
        self.assertIsNone(tracker.current(851, elapsed_ms))
        self.assertEqual(tracker.lost, 1)

    def test_invalid_observation_does_not_become_active(self):
        tracker = TargetTracker(1, 750, 0.2)
        invalid_payloads = (
            (1, 2, 3),
            (41, "100", 100, 40, 60, 90),
            (41, -1, 100, 40, 60, 90),
            (65536, 100, 100, 40, 60, 90),
            (41, 100, 100, 40, 60, 101),
        )
        for now_ms, payload in enumerate(invalid_payloads):
            self.assertIsNone(tracker.observe(payload, now_ms, elapsed_ms))
        self.assertEqual(tracker.invalid_observations, len(invalid_payloads))

    def test_iou_requires_same_class(self):
        self.assertGreater(payload_iou(self.TARGET, self.TARGET), 0.99)
        other_class = (47, 100, 100, 40, 60, 90)
        self.assertEqual(payload_iou(self.TARGET, other_class), 0.0)

    def test_zero_iou_threshold_still_requires_same_class(self):
        tracker = TargetTracker(1, 750, 0.0)
        tracker.observe(self.TARGET, 0, elapsed_ms)
        other_class = (47, 100, 100, 40, 60, 90)
        self.assertEqual(tracker.observe(other_class, 1, elapsed_ms), other_class)
        self.assertEqual(tracker.switches, 1)
        self.assertEqual(tracker.updated, 0)


class VisionSchedulerTests(unittest.TestCase):
    TARGET = (41, 100, 100, 40, 60, 90)

    def setUp(self):
        self.tracker = TargetTracker(3, 750, 0.2)
        self.scheduler = VisionScheduler(self.tracker, 0, 500)

    def test_stable_target_waits_for_send_boundary(self):
        for now_ms in (0, 10, 20):
            self.assertTrue(self.scheduler.process_due(now_ms, elapsed_ms))
            self.scheduler.observe(self.TARGET, now_ms, elapsed_ms)
            payload = self.scheduler.take_send_payload(now_ms, elapsed_ms)

        self.assertIsNone(payload)
        self.assertEqual(
            self.scheduler.take_send_payload(500, elapsed_ms), self.TARGET
        )

    def test_dropout_is_retained_then_expires_before_later_send(self):
        for now_ms in (0, 10, 20):
            self.scheduler.observe(self.TARGET, now_ms, elapsed_ms)
        self.scheduler.take_send_payload(0, elapsed_ms)
        self.scheduler.observe(self.TARGET, 500, elapsed_ms)
        self.assertEqual(
            self.scheduler.take_send_payload(500, elapsed_ms), self.TARGET
        )

        self.scheduler.observe(None, 1000, elapsed_ms)
        self.assertEqual(
            self.scheduler.take_send_payload(1000, elapsed_ms), self.TARGET
        )
        self.scheduler.observe(None, 1251, elapsed_ms)
        self.assertIsNone(self.scheduler.take_send_payload(1500, elapsed_ms))
        self.assertEqual(self.tracker.lost, 1)

    def test_processing_interval_is_independent_from_send_interval(self):
        scheduler = VisionScheduler(self.tracker, 100, 500)
        self.assertTrue(scheduler.process_due(0, elapsed_ms))
        scheduler.observe(None, 0, elapsed_ms)
        self.assertFalse(scheduler.process_due(99, elapsed_ms))
        self.assertTrue(scheduler.process_due(100, elapsed_ms))
        self.assertIsNone(scheduler.take_send_payload(0, elapsed_ms))
        self.assertIsNone(scheduler.take_send_payload(499, elapsed_ms))
        self.assertEqual(scheduler.last_send_ms, 0)
        self.assertIsNone(scheduler.take_send_payload(500, elapsed_ms))
        self.assertEqual(scheduler.last_send_ms, 500)

    def test_elapsed_callback_handles_tick_wraparound(self):
        def wrapped_elapsed(now_ms, previous_ms):
            return (now_ms - previous_ms) % 1000

        scheduler = VisionScheduler(self.tracker, 100, 500)
        scheduler.observe(None, 950, wrapped_elapsed)
        self.assertFalse(scheduler.process_due(49, wrapped_elapsed))
        self.assertTrue(scheduler.process_due(50, wrapped_elapsed))
        scheduler.take_send_payload(800, wrapped_elapsed)
        self.assertIsNone(scheduler.take_send_payload(299, wrapped_elapsed))
        self.assertEqual(scheduler.last_send_ms, 800)
        self.assertIsNone(scheduler.take_send_payload(300, wrapped_elapsed))
        self.assertEqual(scheduler.last_send_ms, 300)


if __name__ == "__main__":
    unittest.main()
