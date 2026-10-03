import io
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from replay_vision import (  # noqa: E402
    parse_observations,
    parse_probe_log,
    replay_observations,
)


class VisionReplayTests(unittest.TestCase):
    def test_example_covers_acquire_switch_dropout_and_loss(self):
        example_path = PROJECT_ROOT / "host" / "vision_replay_example.csv"
        with example_path.open("r", encoding="utf-8", newline="") as stream:
            observations = parse_observations(stream)

        result = replay_observations(observations, output=None)

        self.assertEqual(result["tracker"].acquired, 1)
        self.assertEqual(result["tracker"].switches, 1)
        self.assertEqual(result["tracker"].lost, 1)
        self.assertEqual([item[0] for item in result["sends"]], [500, 1000, 1500, 2000])
        self.assertEqual([item[1][0] for item in result["sends"]], [41, 41, 47, 47])

    def test_rejects_decreasing_timestamps(self):
        stream = io.StringIO(
            "time_ms,class_id,center_x,center_y,width,height,confidence\n"
            "100,NONE,,,,,\n"
            "99,NONE,,,,,\n"
        )

        with self.assertRaisesRegex(ValueError, "timestamps must be nondecreasing"):
            parse_observations(stream)

    def test_extracts_replay_rows_from_mixed_probe_log(self):
        stream = io.StringIO(
            "YOLO11 probe started\n"
            "REPLAY,time_ms,class_id,center_x,center_y,width,height,confidence\n"
            "vision stats: frames=1\n"
            "[device] REPLAY,0,41,100,120,40,60,91\n"
            "target: NONE\n"
            "REPLAY,25,NONE,,,,,\n"
        )

        self.assertEqual(
            parse_probe_log(stream),
            [(0, (41, 100, 120, 40, 60, 91)), (25, None)],
        )


if __name__ == "__main__":
    unittest.main()
