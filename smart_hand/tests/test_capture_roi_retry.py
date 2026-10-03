"""Synthetic current-frame ROI tests; no participant images/coordinates."""
import json
from pathlib import Path
import tempfile
import types
import unittest

from smart_hand.tests.test_capture_detector_diagnostic import capture


class Frame:
    def __init__(self, tag="original", width=320, height=224):
        self.tag, self._width, self._height = tag, width, height
        self.crops = []
    def width(self):
        return self._width
    def height(self):
        return self._height
    def crop(self, x, y, w, h):
        self.crops.append((x, y, w, h))
        return Frame("roi", w, h)


def hand():
    xy = [(100, 200), (95, 190), (110, 185), (130, 185), (150, 185)]
    for x, extended in ((80, True), (100, False), (120, False), (140, False)):
        xy.extend([(x, 120), (x, 105 if extended else 140),
                   (x, 90 if extended else 160), (x, 75 if extended else 180)])
    raw = [value for i, (x, y) in enumerate(xy) for value in (x, y, i * 10)]
    return types.SimpleNamespace(points=[60, 60, 190, 60, 190, 210, 60, 210] + raw,
                                 w=130, h=150, class_id=1)


class Detector:
    def __init__(self, threshold=0.7, value=None):
        self.threshold, self.value, self.calls = threshold, value, []
    def detect(self, frame, **kwargs):
        self.calls.append((frame, kwargs))
        return [self.value or hand()] if frame.tag == "roi" and kwargs["conf_th"] == self.threshold else []


class CaptureRoiTests(unittest.TestCase):
    def test_roi_baseline_translates_box_xy_and_all_xyz_without_mutating_sdk_output(self):
        original = hand()
        before = list(original.points)
        frame, detector = Frame(), Detector(value=original)
        result, profile, attempts = capture.detect_capture_hand(detector, frame, True, True)
        self.assertEqual(frame.crops, [(48, 0, 224, 224)])
        self.assertEqual(profile["name"], "roi_baseline")
        self.assertEqual(len(attempts), 5)
        self.assertEqual(result.points[0:2], [108, 60])
        for i in range(8, 71, 3):
            self.assertEqual(result.points[i], before[i] + 48)
            self.assertEqual(result.points[i+1:i+3], before[i+1:i+3])
        self.assertEqual(result.roi_raw_landmarks, before[8:])
        self.assertEqual(original.points, before)
        self.assertEqual((result.w, result.h, result.class_id), (130, 150, 1))

    def test_roi_relaxed_is_bounded_and_second_check_remains_strict(self):
        detector = Detector(threshold=0.5)
        result, profile, attempts = capture.detect_capture_hand(detector, Frame(), True, True)
        self.assertIsNotNone(result)
        self.assertEqual(profile["name"], "roi_detector_relaxed")
        self.assertEqual(len(detector.calls), 6)
        self.assertEqual(len(attempts), 6)
        self.assertTrue(all(k["conf_th2"] == 0.8 for f, k in detector.calls if f.tag == "roi"))

    def test_original_detection_skips_crop_entirely(self):
        class Original(Detector):
            def detect(self, frame, **kwargs):
                return [hand()]
        frame = Frame()
        _, profile, attempts = capture.detect_capture_hand(Original(), frame, True, True)
        self.assertEqual(profile["name"], "baseline")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(frame.crops, [])

    def test_current_frame_failure_never_reuses_previous_roi_hand(self):
        detector = Detector()
        first = capture.detect_capture_hand(detector, Frame(), True, True)[0]
        detector.threshold = None
        second, profile, attempts = capture.detect_capture_hand(detector, Frame(), True, True)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIsNone(profile)
        self.assertEqual(len(attempts), 6)

    def test_disabled_roi_does_not_crop(self):
        frame = Frame()
        result, _, attempts = capture.detect_capture_hand(Detector(), frame, True, False)
        self.assertIsNone(result)
        self.assertEqual(len(attempts), 4)
        self.assertEqual(frame.crops, [])

    def test_bad_landmarks_are_rejected_not_clamped_into_roi(self):
        for modification in ("outside", "nan", "short"):
            value = hand()
            if modification == "outside":
                value.points[8] = 224
            elif modification == "nan":
                value.points[10] = float("nan")
            else:
                value.points = value.points[:-1]
            result, profile, attempts = capture.detect_capture_hand(Detector(value=value), Frame(), True, True)
            self.assertIsNone(result)
            self.assertIsNone(profile)
            self.assertTrue(attempts[-2]["rejection"])
            self.assertFalse(any(p["usable_hand_found"] for p in attempts))

    def test_crop_error_is_not_hidden_as_no_hand(self):
        class Broken(Frame):
            def crop(self, *_args):
                raise RuntimeError("crop failed")
        with self.assertRaisesRegex(RuntimeError, "crop failed"):
            capture.detect_capture_hand(Detector(), Broken(), True, True)

    def test_portrait_and_invalid_dimensions_are_bounded(self):
        self.assertEqual(capture.center_crop_rect(Frame(width=224, height=320)), (0, 48, 224, 224))
        with self.assertRaises(capture.CaptureError):
            capture.center_crop_rect(Frame(width=0))

    def test_real_capture_writes_roi_provenance_and_missing_frame_resets_stability(self):
        state = {"index": -1, "closed": False}
        class Camera:
            def __init__(self, *_args):
                pass
            def read(self):
                state["index"] += 1
                return Frame()
            def close(self):
                state["closed"] = True
        class NN(Detector):
            def __init__(self, **_kwargs):
                super().__init__()
            def input_format(self):
                return "fake"
            def detect(self, frame, **kwargs):
                return [] if state["index"] == 1 else super().detect(frame, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "roi.jsonl"
            count = capture.run_capture(
                capture.CaptureConfig(consent=True, countdown_seconds=0, target_samples=2,
                                      max_capture_ms=1200, output_path=str(path)),
                app_module=types.SimpleNamespace(need_exit=lambda: False),
                camera_module=types.SimpleNamespace(Camera=Camera),
                display_module=None, image_module=None,
                nn_module=types.SimpleNamespace(HandLandmarks=NN),
                time_module=types.SimpleNamespace(ticks_ms=lambda: state["index"] * 200,
                                                  ticks_diff=lambda a, b: b-a,
                                                  sleep_ms=lambda _ms: None))
            rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(count, 2)
            self.assertTrue(state["closed"])
            self.assertEqual(rows[1]["stable_ms"], 200)  # Not 600 across the loss.
            for row in rows:
                self.assertEqual(row["predicted_gesture_id"], "L_SHAPE")
                self.assertEqual(row["detector_profile"], "roi_baseline")
                self.assertEqual(row["runtime_version"]["landmark_detector"]["crop_rect"], [48, 0, 224, 224])
                self.assertEqual(row["landmark_xy_frame"], "original_camera_pixels")
                self.assertEqual(row["landmarks"][0], row["roi_raw_landmarks"][0] + 48)
                self.assertTrue(row["capture_diagnostic_only"])
            from smart_hand.tests.test_capture_analysis import analyzer
            replay = analyzer.analyze_rows(rows)
            self.assertEqual(replay["single_frame_replay_match_count"], 2)
            self.assertTrue(all(r["roi_to_camera_transform_validated"] for r in replay["rows"]))
            rows[0]["roi_raw_landmarks"][0] += 1
            self.assertIn("roi_to_camera_transform", analyzer.analyze_rows(rows)["rows"][0]["mismatched_fields"])


if __name__ == "__main__":
    unittest.main()
