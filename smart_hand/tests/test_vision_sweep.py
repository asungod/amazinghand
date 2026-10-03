import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from replay_vision import parse_observations  # noqa: E402
from sweep_vision_params import parse_number_list, sweep_observations  # noqa: E402


class VisionParameterSweepTests(unittest.TestCase):
    def test_sweep_reports_acquisition_latency_for_each_combination(self):
        example_path = PROJECT_ROOT / "host" / "vision_replay_example.csv"
        with example_path.open("r", encoding="utf-8", newline="") as stream:
            observations = parse_observations(stream)

        rows = sweep_observations(
            observations,
            stable_frames_values=(2, 3),
            stale_timeout_values=(750,),
            match_iou_values=(0.2,),
            send_interval_values=(500,),
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual([row["first_acquire_ms"] for row in rows], [100, 200])
        self.assertEqual([row["first_vision_ms"] for row in rows], [500, 500])
        self.assertEqual([row["switches"] for row in rows], [1, 1])

    def test_parameter_list_deduplicates_and_rejects_out_of_range(self):
        self.assertEqual(parse_number_list("2,3,2", int, "test", 1), [2, 3])
        with self.assertRaisesRegex(ValueError, "out-of-range"):
            parse_number_list("0,2", int, "test", 1)
        with self.assertRaisesRegex(ValueError, "out-of-range"):
            parse_number_list("0.2,1.1", float, "test", 0.0, 1.0)


if __name__ == "__main__":
    unittest.main()
