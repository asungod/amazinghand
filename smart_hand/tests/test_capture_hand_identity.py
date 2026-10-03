"""Synthetic SDK identity/overlay checks; never assert hardware accuracy."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest

from smart_hand.tests.test_capture_detector_diagnostic import capture
from smart_hand.tests.test_capture_roi_retry import Frame, hand


class DrawingFrame(Frame):
    def __init__(self):
        super().__init__()
        self.drawing = []
    def draw_line(self, *args):
        self.drawing.append(("line", args))
    def draw_circle(self, *args):
        self.drawing.append(("circle", args))
    def draw_string(self, *args, **kwargs):
        self.drawing.append(("string", args))
    def draw_rect(self, *args):
        self.drawing.append(("rect", args))


COLORS = types.SimpleNamespace(COLOR_RED="red", COLOR_WHITE="white")


class HandIdentityTests(unittest.TestCase):
    def test_identity_is_owned_and_does_not_confuse_model_score_with_gesture_score(self):
        value = hand()
        value.x, value.y, value.score = 60, 60, 0.875
        result = capture.describe_hand(value)
        self.assertEqual(result["sdk_score"], 0.875)
        self.assertEqual(result["sdk_class_id"], 1)
        self.assertEqual(result["box_xywh"], [60, 60, 130, 150])
        self.assertEqual(result["box_corners_xy"][0], [60, 60])
        self.assertNotIn("confidence", result)
        self.assertNotIn("hand_side", result)
        value.points[0] = 999
        self.assertEqual(result["box_corners_xy"][0], [60, 60])

    def test_missing_and_invalid_fields_are_null_and_json_safe(self):
        self.assertIsNone(capture.describe_hand(None))
        for score in (None, True, float("nan"), float("inf"), "0.9"):
            for side in (None, True, "right", 1.5):
                result = capture.describe_hand(types.SimpleNamespace(score=score, class_id=side))
                self.assertIsNone(result["sdk_score"])
                self.assertIsNone(result["sdk_class_id"])
                self.assertEqual(result["box_xywh"], [None]*4)
                self.assertIsNone(result["box_corners_xy"])
                json.dumps(result, allow_nan=False)

    def test_multi_hand_selection_remains_largest_area_not_side_score_or_target(self):
        smaller, larger = hand(), hand()
        smaller.score, smaller.class_id = 0.999, 1
        larger.w, larger.score, larger.class_id = 160, 0.810, 0
        class NN:
            def detect(self, *_args, **_kwargs):
                return [smaller, larger]
        selected, profile, attempts = capture.detect_capture_hand(NN(), Frame(), True, True)
        self.assertIs(selected, larger)
        identity = profile["hand_identity"]
        self.assertEqual(identity["candidate_count"], 2)
        self.assertEqual(identity["selected_candidate_index"], 1)
        self.assertEqual(identity["selected"]["sdk_class_id"], 0)
        self.assertEqual(identity["selected"]["sdk_score"], 0.810)
        self.assertEqual(identity["selection_policy"], "largest_area")
        self.assertEqual(len(attempts), 1)

    def test_bounded_list_still_preserves_selected_candidate_beyond_eight(self):
        candidates = [hand() for _ in range(10)]
        for i, value in enumerate(candidates):
            value.w, value.score = i+1, 0.8+i/100
        selected, identity = capture._select_with_identity(candidates, "original_camera_pixels")
        self.assertIs(selected, candidates[9])
        self.assertEqual(identity["candidate_count"], 10)
        self.assertEqual(len(identity["candidates"]), 8)
        self.assertTrue(identity["candidates_truncated"])
        self.assertEqual(identity["selected_candidate_index"], 9)
        self.assertEqual(identity["selected"]["sdk_score"], 0.89)

    def test_empty_and_tie_selection_are_not_guessed(self):
        selected, identity = capture._select_with_identity([], "original_camera_pixels")
        self.assertIsNone(selected)
        self.assertEqual(identity["candidate_count"], 0)
        self.assertIsNone(identity["selected_candidate_index"])
        first, second = hand(), hand()
        selected, identity = capture._select_with_identity([first, second], "original_camera_pixels")
        self.assertIs(selected, first)
        self.assertEqual(identity["selected_candidate_index"], 0)

    def test_roi_identity_preserves_score_side_and_distinguishes_coordinate_frames(self):
        value = hand()
        value.score = 0.9123
        value.x, value.y = 10, 20  # Deliberately not min(rotated corner XY).
        class NN:
            def detect(self, frame, **_kwargs):
                return [value] if frame.tag == "roi" else []
        selected, profile, attempts = capture.detect_capture_hand(NN(), Frame(), True, True)
        local = profile["hand_identity"]["selected"]
        camera = capture.describe_hand(selected)
        self.assertEqual(local["coordinate_frame"], "crop_local_pixels")
        self.assertEqual(camera["coordinate_frame"], "original_camera_pixels")
        self.assertEqual(local["box_corners_xy"][0], [60, 60])
        self.assertEqual(camera["box_corners_xy"][0], [108, 60])
        self.assertEqual(camera["box_xywh"], [58, 20, 130, 150])
        self.assertEqual(local["box_xywh"], [10, 20, 130, 150])
        self.assertEqual(camera["sdk_score"], 0.9123)
        self.assertEqual(camera["sdk_class_id"], 1)
        self.assertTrue(all(p["hand_identity"]["candidate_count"] == 0 for p in attempts[:-1]))

    def test_roi_missing_sdk_origin_stays_null_not_invented_from_corners(self):
        wrapped = capture._CameraFrameHand(hand(), (48, 0, 224, 224))
        summary = capture.describe_hand(wrapped)
        self.assertEqual(summary["box_xywh"], [None, None, 130, 150])
        self.assertEqual(summary["box_corners_xy"][0], [108, 60])

    def test_overlay_uses_exact_model_tip_indices_without_changing_points(self):
        value, frame = hand(), DrawingFrame()
        raw = value.points[8:]
        before = list(raw)
        capture.draw_hand_identity(frame, raw, capture.describe_hand(value), COLORS, 2)
        self.assertEqual(raw, before)
        self.assertEqual(len([d for d in frame.drawing if d[0] == "line"]), 4)
        circles = [d[1][:2] for d in frame.drawing if d[0] == "circle"]
        self.assertEqual(circles, [tuple(raw[i*3:i*3+2]) for i in (4, 8, 20)])
        tags = [d[1][2] for d in frame.drawing if d[0] == "string"]
        self.assertEqual(tags[:3], ["T4", "I8", "P20"])
        self.assertEqual(tags[3], "ID=1 S=null N=2")

    def test_outside_tip_not_drawn_and_frame_without_hand_not_annotated(self):
        value, frame = hand(), DrawingFrame()
        raw = value.points[8:]
        raw[8*3] = 320
        capture.draw_hand_identity(frame, raw, None, COLORS)
        self.assertEqual([d[1][2] for d in frame.drawing if d[0] == "string"], ["T4", "P20"])
        empty = DrawingFrame()
        capture.draw_hand_identity(empty, None, None, COLORS)
        self.assertEqual(empty.drawing, [])

    def test_real_capture_logs_and_saves_identity_even_if_sdk_overlay_fails(self):
        state = {"index": -1, "closed": False, "frames": []}
        value = hand()
        value.x, value.y, value.score = 60, 60, 0.923
        class Camera:
            def __init__(self, *_args):
                pass
            def read(self):
                state["index"] += 1
                frame = DrawingFrame()
                state["frames"].append(frame)
                return frame
            def close(self):
                state["closed"] = True
        class NN:
            def __init__(self, **_kwargs):
                pass
            def input_format(self):
                return "fake"
            def detect(self, *_args, **_kwargs):
                return [] if state["index"] == 1 else [value]
            def draw_hand(self, *_args, **_kwargs):
                raise RuntimeError("unsupported draw_hand")
        screen = types.SimpleNamespace(width=lambda:320, height=lambda:224, show=lambda _f:None)
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()) as log:
            path = Path(directory) / "identity.jsonl"
            count = capture.run_capture(
                capture.CaptureConfig(consent=True, countdown_seconds=0, target_samples=2,
                                      max_capture_ms=1200, output_path=str(path)),
                app_module=types.SimpleNamespace(need_exit=lambda: False),
                camera_module=types.SimpleNamespace(Camera=Camera),
                display_module=types.SimpleNamespace(Display=lambda:screen), image_module=COLORS,
                nn_module=types.SimpleNamespace(HandLandmarks=NN),
                time_module=types.SimpleNamespace(ticks_ms=lambda:state["index"]*200,
                                                  ticks_diff=lambda a,b:b-a, sleep_ms=lambda _ms:None))
            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(count, 2)
        self.assertTrue(state["closed"])
        self.assertEqual(rows[1]["stable_ms"], 200)
        self.assertIn("IDENTITY DIAGNOSTIC=True", log.getvalue())
        self.assertIn("OPENSIGNHAND HAND IDENTITY", log.getvalue())
        for row in rows:
            self.assertEqual(row["hand_identity_schema"], "opensignhand.hand_identity.v1")
            self.assertEqual(row["selected_hand"]["sdk_score"], 0.923)
            self.assertEqual(row["selected_hand"]["sdk_class_id"], 1)
            self.assertNotEqual(row["confidence"], row["selected_hand"]["sdk_score"])
            self.assertEqual(row["detector_attempts_this_frame"][0]["hand_identity"]["candidate_count"], 1)
        missing_tags = [d[1][2] for d in state["frames"][1].drawing if d[0] == "string"]
        self.assertFalse(any(tag in missing_tags for tag in ("T4", "I8", "P20")))
        self.assertTrue(any(d[0] == "string" and d[1][2] == "I8" for d in state["frames"][0].drawing))


if __name__ == "__main__":
    unittest.main()
