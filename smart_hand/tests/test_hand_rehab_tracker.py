import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from hand_rehab_tracker import (  # noqa: E402
    RepetitionTracker,
    classify_openness,
    hand_openness,
)


def synthetic_hand(bent=False):
    points = [(0.0, 0.0) for _ in range(21)]
    for base, x in ((5, 1.0), (9, 2.0), (13, 3.0), (17, 4.0)):
        points[base] = (x, 0.0)
        points[base + 1] = (x, 1.0)
        points[base + 2] = ((x + 0.8), 1.0) if bent else (x, 2.0)
        points[base + 3] = ((x + 0.8), 0.2) if bent else (x, 3.0)
    return points


class HandRehabTrackerTests(unittest.TestCase):
    def test_straight_and_bent_hands_separate(self):
        open_score = hand_openness(synthetic_hand(False))
        closed_score = hand_openness(synthetic_hand(True))
        self.assertEqual(classify_openness(open_score), "OPEN")
        self.assertEqual(classify_openness(closed_score), "CLOSED")
        self.assertGreater(open_score, closed_score)

    def test_xyz_flat_input_matches_xy_points(self):
        points = synthetic_hand(False)
        flat = [value for x, y in points for value in (x, y, 0.0)]
        self.assertAlmostEqual(hand_openness(points), hand_openness(flat))

    def test_one_stable_open_close_open_cycle_counts_once(self):
        tracker = RepetitionTracker(stable_frames=2)
        events = []
        for posture in ("OPEN", "OPEN", "CLOSED", "CLOSED", "OPEN", "OPEN"):
            events.append(tracker.observe(posture))
        self.assertEqual(tracker.repetitions, 1)
        self.assertEqual(events.count(True), 1)

    def test_mid_or_missing_frames_cannot_complete_cycle(self):
        tracker = RepetitionTracker(stable_frames=2)
        for posture in ("OPEN", "MID", "OPEN", None, "CLOSED", "MID", "OPEN"):
            self.assertFalse(tracker.observe(posture))
        self.assertEqual(tracker.repetitions, 0)

    def test_invalid_landmarks_fail_closed(self):
        with self.assertRaises(ValueError):
            hand_openness([])
        with self.assertRaises(ValueError):
            hand_openness([(0, 0)] * 21)


if __name__ == "__main__":
    unittest.main()
