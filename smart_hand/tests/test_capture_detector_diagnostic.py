"""Host-only tests for the isolated kit's threshold probes, not accuracy."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "smart_hand" / "capture_kit"
sys.path.insert(0, str(ROOT / "smart_hand" / "maixcam2"))
spec = importlib.util.spec_from_file_location("capture_detector_kit", KIT / "sign_landmark_capture.py")
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)  # Import must not start the camera.


class Detector:
    def __init__(self, accepted):
        self.accepted = accepted
        self.calls = []

    def detect(self, frame, **kwargs):
        self.calls.append((frame, kwargs))
        return [types.SimpleNamespace(w=20, h=20)] if (
            kwargs["conf_th"], kwargs["conf_th2"]
        ) == self.accepted else []


class CaptureDetectorDiagnosticTests(unittest.TestCase):
    def test_each_profile_uses_same_frame_and_reports_exact_thresholds(self):
        for accepted, name, count in (
            ((0.7, 0.8), "baseline", 1),
            ((0.5, 0.8), "detector_relaxed", 2),
            ((0.7, 0.5), "second_check_relaxed", 3),
            ((0.5, 0.5), "both_relaxed", 4),
        ):
            with self.subTest(name=name):
                detector, frame = Detector(accepted), object()
                hand, selected, attempts = capture.detect_capture_hand(detector, frame, True)
                self.assertIsNotNone(hand)
                self.assertEqual(selected["name"], name)
                self.assertEqual((selected["conf_th"], selected["conf_th2"]), accepted)
                self.assertEqual(len(attempts), count)
                self.assertEqual(len(detector.calls), count)
                self.assertTrue(all(f is frame for f, _ in detector.calls))
                self.assertTrue(all(k["iou_th"] == 0.45 for _, k in detector.calls))
                self.assertTrue(all(not p["usable_hand_found"] for p in attempts[:-1]))

    def test_no_hand_is_not_fabricated_by_fallback(self):
        detector = Detector(None)
        hand, selected, attempts = capture.detect_capture_hand(detector, object(), True)
        self.assertIsNone(hand)
        self.assertIsNone(selected)
        self.assertEqual(len(attempts), 4)
        self.assertFalse(any(p["usable_hand_found"] for p in attempts))

    def test_disabled_diagnostic_never_relaxes_thresholds(self):
        detector = Detector((0.5, 0.5))
        hand, selected, attempts = capture.detect_capture_hand(detector, object(), False)
        self.assertIsNone(hand)
        self.assertIsNone(selected)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(detector.calls), 1)

    def test_sdk_errors_are_not_swallowed_or_mislabeled_as_no_hand(self):
        class Broken:
            def detect(self, *_args, **_kwargs):
                raise RuntimeError("SDK error")
        with self.assertRaisesRegex(RuntimeError, "SDK error"):
            capture.detect_capture_hand(Broken(), object(), True)

    def test_real_capture_records_effective_params_and_stops_without_false_samples(self):
        for accepted in ((0.5, 0.5), None):
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as directory:
                state = {"index": -1, "closed": False}
                class Frame:
                    def width(self):
                        return 320
                    def height(self):
                        return 224
                    def crop(self, *_rect):
                        return Frame()
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
                        super().__init__(accepted)
                    def input_format(self):
                        return "fake"
                    def detect(self, frame, **kwargs):
                        result = super().detect(frame, **kwargs)
                        if result:
                            result[0].points = [float(v) for i in range(21) for v in (i, i + 1, 0)]
                        return result
                output = Path(directory) / "samples.jsonl"
                written = capture.run_capture(
                    capture.CaptureConfig(consent=True, countdown_seconds=0,
                                          target_samples=2, max_capture_ms=1200,
                                          output_path=str(output)),
                    app_module=types.SimpleNamespace(need_exit=lambda: False),
                    camera_module=types.SimpleNamespace(Camera=Camera),
                    display_module=None, image_module=None,
                    nn_module=types.SimpleNamespace(HandLandmarks=NN),
                    time_module=types.SimpleNamespace(ticks_ms=lambda: state["index"] * 600,
                                                      ticks_diff=lambda a, b: b - a,
                                                      sleep_ms=lambda _ms: None),
                )
                self.assertTrue(state["closed"])
                if accepted is None:
                    self.assertEqual(written, 0)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(written, 2)
                    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
                    for row in rows:
                        self.assertTrue(row["capture_diagnostic_only"])
                        self.assertEqual(row["detector_profile"], "both_relaxed")
                        params = row["runtime_version"]["landmark_detector"]
                        self.assertEqual((params["conf_th"], params["conf_th2"]), (0.5, 0.5))
                        self.assertEqual(len(row["detector_attempts_this_frame"]), 4)

    def test_kit_defaults_and_production_template_remains_isolated(self):
        import sign_landmark_capture as template
        self.assertFalse(template.CONSENT)
        self.assertFalse(getattr(template, "DETECTION_DIAGNOSTIC", False))
        self.assertEqual((template.DETECT_CONFIDENCE, template.LANDMARK_CONFIDENCE), (0.7, 0.8))
        self.assertTrue(capture.DETECTION_DIAGNOSTIC)
        self.assertEqual(capture.SESSION_ID, "S01-L-IMAGE01")
        self.assertEqual(capture.GESTURE_ID, "L_SHAPE")
        self.assertEqual(capture.HAND_SIDE, "right")
        self.assertTrue(capture.ROI_RETRY)


if __name__ == "__main__":
    unittest.main()
