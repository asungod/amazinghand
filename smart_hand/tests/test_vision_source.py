import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from vision_source import (  # noqa: E402
    MockVisionSource,
    Yolo11VisionSource,
    format_replay_row,
    select_target,
)


class VisionPolicyTests(unittest.TestCase):
    def test_highest_confidence_detection_is_selected(self):
        detections = [
            {"class_id": 39, "x": 10, "y": 20, "w": 40, "h": 60, "score": 0.70},
            {"class_id": 47, "x": 100, "y": 80, "w": 20, "h": 30, "score": 0.91},
        ]
        self.assertEqual(
            select_target(detections, 640, 480),
            (47, 110, 95, 20, 30, 91),
        )

    def test_larger_box_breaks_equal_confidence_tie(self):
        detections = [
            {"class_id": 1, "x": 0, "y": 0, "w": 10, "h": 10, "score": 0.8},
            {"class_id": 2, "x": 20, "y": 20, "w": 30, "h": 20, "score": 0.8},
        ]
        self.assertEqual(select_target(detections, 100, 100)[0], 2)

    def test_center_breaks_equal_confidence_tie_before_area(self):
        detections = [
            {"class_id": 1, "x": 0, "y": 0, "w": 50, "h": 50, "score": 0.8},
            {"class_id": 2, "x": 45, "y": 45, "w": 10, "h": 10, "score": 0.8},
        ]
        self.assertEqual(select_target(detections, 100, 100)[0], 2)

    def test_allowed_class_filter_is_applied(self):
        detections = [
            {"class_id": 0, "x": 0, "y": 0, "w": 50, "h": 50, "score": 0.99},
            {"class_id": 41, "x": 20, "y": 20, "w": 20, "h": 20, "score": 0.75},
        ]
        payload = select_target(detections, 100, 100, allowed_class_ids=(41,))
        self.assertEqual(payload[0], 41)

    def test_box_is_clipped_to_frame(self):
        detections = [
            {"class_id": 47, "x": -10, "y": 470, "w": 30, "h": 30, "score": 0.9}
        ]
        self.assertEqual(
            select_target(detections, 640, 480),
            (47, 10, 475, 20, 10, 90),
        )

    def test_invalid_or_outside_boxes_are_ignored(self):
        detections = [
            {"class_id": -1, "x": 0, "y": 0, "w": 10, "h": 10, "score": 0.9},
            {"class_id": 1, "x": 700, "y": 0, "w": 10, "h": 10, "score": 0.9},
            {"class_id": 1, "x": 0, "y": 0, "w": 0, "h": 10, "score": 0.9},
        ]
        self.assertIsNone(select_target(detections, 640, 480))

    def test_minimum_score_is_enforced(self):
        detections = [
            {"class_id": 39, "x": 0, "y": 0, "w": 10, "h": 10, "score": 0.49}
        ]
        self.assertIsNone(select_target(detections, 100, 100, minimum_score=0.5))

    def test_mock_source_is_deterministic(self):
        source = MockVisionSource()
        self.assertEqual(source.read(), (3, 320, 240, 80, 120, 96))
        self.assertEqual(source.read(), (3, 320, 240, 80, 120, 96))
        self.assertIn("frames=2", source.summary())

    def test_replay_rows_format_target_and_no_target(self):
        self.assertEqual(
            format_replay_row(125, (41, 100, 120, 40, 60, 91)),
            "REPLAY,125,41,100,120,40,60,91",
        )
        self.assertEqual(format_replay_row(250, None), "REPLAY,250,NONE,,,,,")

    def test_yolo_source_uses_documented_maix_api_shape(self):
        calls = {}

        class FakeObject:
            class_id = 41
            x = 10
            y = 20
            w = 40
            h = 60
            score = 0.88

        class FakeDetector:
            def __init__(self, model, dual_buff):
                calls["detector_init"] = (model, dual_buff)

            @staticmethod
            def input_width():
                return 640

            @staticmethod
            def input_height():
                return 480

            @staticmethod
            def input_format():
                return "rgb"

            @staticmethod
            def detect(frame, conf_th, iou_th):
                calls["detect"] = (frame, conf_th, iou_th)
                return [FakeObject()]

        class FakeCamera:
            def __init__(self, width, height, image_format):
                calls["camera_init"] = (width, height, image_format)

            @staticmethod
            def read():
                return "frame"

        fake_maix = types.ModuleType("maix")
        fake_maix.nn = types.SimpleNamespace(YOLO11=FakeDetector)
        fake_maix.camera = types.SimpleNamespace(Camera=FakeCamera)
        fake_maix.time = types.SimpleNamespace(
            ticks_ms=unittest.mock.Mock(side_effect=[100, 112]),
            ticks_diff=lambda previous, now: now - previous,
        )

        with patch.dict(sys.modules, {"maix": fake_maix}):
            source = Yolo11VisionSource("/root/models/yolo11n.mud")
            payload = source.read()

        self.assertEqual(calls["detector_init"], ("/root/models/yolo11n.mud", True))
        self.assertEqual(calls["camera_init"], (640, 480, "rgb"))
        self.assertEqual(calls["detect"], ("frame", 0.5, 0.45))
        self.assertEqual(payload, (41, 30, 50, 40, 60, 88))
        self.assertEqual(source.last_inference_ms, 12)
        self.assertEqual(source.inference_fps(), 83)


if __name__ == "__main__":
    unittest.main()
