import json
import runpy
import sys
import tempfile
import types
import unittest
from unittest import mock
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from sign_landmark_capture import (  # noqa: E402
    CaptureDiagnostics,
    CaptureConfig,
    CaptureError,
    CancelButton,
    append_sample,
    build_sample,
    build_diagnostic_sample,
    capture_due,
    countdown_values,
    extract_hand_landmarks,
    main,
    normalize_landmarks,
    run_capture,
    _source_fingerprint,
    validate_config,
)
from gesture_classifier import classify_gesture  # noqa: E402
from gesture_features import extract_gesture_features  # noqa: E402
from smart_hand.host.sign_landmark_dataset import validate_sample as host_validate_sample


def flat_points():
    return [float(value) for index in range(21) for value in (index, index + 1, 0.0)]


def shape_points(folded=(False, False, False, False)):
    points = [[0.0, 0.0] for _ in range(21)]
    for (base, x), bent in zip(((5, 1), (9, 2), (13, 3), (17, 4)), folded):
        points[base] = [x, 0.0]
        points[base + 1] = [x, 1.0]
        points[base + 2] = [x + 0.8, 1.0] if bent else [x, 2.0]
        points[base + 3] = [x + 0.8, 0.2] if bent else [x, 3.0]
    return points


class SignLandmarkCaptureTests(unittest.TestCase):
    def run_fake_capture(self, frames, ticks, **overrides):
        """Use real collector/classifier with injected camera, NN and clock."""
        state = {"index": -1, "closed": False, "detect_count": 0}

        class Camera:
            def __init__(self, *_args):
                pass

            def read(self):
                state["index"] += 1
                return state["index"]

            def close(self):
                state["closed"] = True

        class Detector:
            def __init__(self, **_kwargs):
                pass

            def input_format(self):
                return "host_fake"

            def detect(self, frame, **_kwargs):
                state["detect_count"] += 1
                raw = frames[frame]
                return [] if raw is None else [
                    types.SimpleNamespace(w=10, h=10, points=raw)
                ]

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            options = dict(
                consent=True, gesture_id="V_SIGN", session_id="S01-03",
                hand_side="right", view="front", target_samples=2,
                countdown_seconds=0, output_path=str(path),
            )
            options.update(overrides)
            written = run_capture(
                CaptureConfig(**options),
                app_module=types.SimpleNamespace(need_exit=lambda: False),
                camera_module=types.SimpleNamespace(Camera=Camera),
                display_module=None, image_module=None,
                nn_module=types.SimpleNamespace(HandLandmarks=Detector),
                time_module=types.SimpleNamespace(
                    ticks_ms=lambda: ticks[state["index"]],
                    sleep_ms=lambda _duration: None,
                    ticks_diff=lambda start, end: (end - start) % (1 << 16),
                ),
            )
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
        return written, records, state

    def test_module_main_is_consent_gated_before_maix_import(self):
        self.assertEqual(main(), 2)

    def test_config_requires_boolean_consent_and_supported_label(self):
        base = CaptureConfig(consent=True)
        self.assertEqual(validate_config(base).consent, True)
        with self.assertRaises(CaptureError):
            validate_config(CaptureConfig(consent="true"))
        with self.assertRaises(CaptureError):
            validate_config(CaptureConfig(consent=True, gesture_id="HELLO"))
        with self.assertRaises(CaptureError):
            validate_config(CaptureConfig(consent=True, participant_id="13800138000"))

    def test_build_and_append_match_host_jsonl_shape(self):
        sample = build_sample(
            "P01", "S01", "OPEN_PALM", flat_points(), timestamp_ms=17, consent=True
        )
        self.assertEqual(len(sample["landmarks"]), 63)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "landmarks.jsonl"
            append_sample(path, sample)
            append_sample(
                path,
                build_sample(
                    "P01", "S01", "UNKNOWN", flat_points(), timestamp_ms=27, consent=True
                ),
            )
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["consent"], True)

    def test_landmark_extraction_uses_detector_eight_value_prefix(self):
        hand = types.SimpleNamespace(points=[-1] * 8 + flat_points())
        self.assertEqual(extract_hand_landmarks(hand), flat_points())
        self.assertEqual(len(normalize_landmarks([[0, 0]] * 21)), 21)

    def test_fixed_interval_and_release_edge_cancel(self):
        self.assertTrue(capture_due(10, None, 500))
        self.assertFalse(capture_due(100, 0, 500))
        self.assertTrue(capture_due(500, 0, 500))
        cancel = CancelButton((10, 20, 30, 30))
        self.assertFalse(cancel.update(20, 30, True))
        self.assertTrue(cancel.update(20, 30, False))
        self.assertFalse(cancel.update(20, 30, True))

    def test_countdown_values_are_deterministic(self):
        self.assertEqual(countdown_values(3), (3, 2, 1))
        self.assertEqual(countdown_values(0), ())

    def test_diagnostics_match_real_classifier_and_features_on_same_points(self):
        landmarks = shape_points()
        engine = CaptureDiagnostics()
        diagnostic = engine.observe(landmarks, 0)
        config = validate_config(CaptureConfig(consent=True, gesture_id="V_SIGN"))
        sample = build_diagnostic_sample(
            config, landmarks, 17, diagnostic, engine.runtime_version, "S01-run1", 1
        )
        direct = classify_gesture(landmarks)
        features = extract_gesture_features(landmarks)
        self.assertEqual(sample["gesture_id"], "V_SIGN")
        self.assertEqual(sample["intended_gesture"], "V_SIGN")
        self.assertEqual(sample["predicted_gesture_id"], "OPEN_PALM")
        self.assertEqual(sample["predicted_gesture_id"], direct.gesture_id)
        self.assertEqual(sample["confidence"], direct.confidence)
        self.assertEqual(sample["joint_angles_deg"], features["joint_angles_deg"])
        self.assertEqual(sample["finger_extension"], features["finger_extension"])
        self.assertEqual(sample["timestamp_ms"], sample["prediction_timestamp_ms"])
        self.assertEqual(sample["landmarks"], landmarks)
        self.assertEqual(sample["landmarks_format"], "21_xy")
        self.assertEqual(host_validate_sample(sample), sample)
        # JSON round-trip must preserve full floats; no UI rounding or NaN.
        self.assertEqual(json.loads(json.dumps(sample, allow_nan=False)), sample)

    def test_capture_loop_updates_unwritten_frames_and_resets_on_missing_hand(self):
        opened = shape_points()
        written, records, state = self.run_fake_capture(
            [opened, None, opened, opened, opened], [0, 100, 200, 250, 600]
        )
        self.assertEqual(written, 2)
        self.assertTrue(state["closed"])
        self.assertEqual(state["detect_count"], 5)
        self.assertEqual(records[1]["stable_ms"], 400)
        self.assertEqual(records[1]["frame_index"], 5)
        self.assertEqual(records[1]["no_hand_frames_seen"], 1)
        self.assertEqual(records[0]["sequence_id"], records[1]["sequence_id"])
        self.assertNotEqual(records[0]["sample_id"], records[1]["sample_id"])

    def test_unknown_unwritten_frame_also_resets_stability(self):
        opened = shape_points()
        unknown = shape_points((False, True, False, True))
        _, records, _ = self.run_fake_capture(
            [opened, unknown, opened, opened], [0, 100, 200, 600]
        )
        self.assertEqual(records[1]["stable_ms"], 400)

    def test_each_written_prediction_matches_its_own_raw_frame_not_previous(self):
        opened = shape_points()
        v_sign = shape_points((False, False, True, True))
        _, records, _ = self.run_fake_capture([opened, v_sign], [0, 500])
        self.assertEqual(records[0]["predicted_gesture_id"], "OPEN_PALM")
        self.assertEqual(records[1]["predicted_gesture_id"], "V_SIGN")
        self.assertEqual(records[1]["landmarks"], v_sign)
        self.assertEqual(records[1]["stable_ms"], 0)
        self.assertEqual(records[1]["joint_angles_deg"], extract_gesture_features(v_sign)["joint_angles_deg"])

    def test_flat_xyz_detector_slice_is_preserved_with_full_diagnostics(self):
        xy = shape_points((False, False, True, True))
        xyz = [v for x, y in xy for v in (x, y, 0.123)]
        _, records, _ = self.run_fake_capture([[-1] * 8 + xyz], [10], target_samples=1)
        self.assertEqual(records[0]["landmarks"], xyz)
        self.assertEqual(records[0]["landmarks_format"], "63_xyz")
        self.assertEqual(records[0]["predicted_gesture_id"], "V_SIGN")
        self.assertEqual(len(records[0]["joint_angles_deg"]), 8)

    def test_invalid_landmark_frame_is_skipped_but_resets_hold(self):
        opened = shape_points()
        _, records, _ = self.run_fake_capture(
            [opened, [float("nan")] * 63, opened, opened], [0, 100, 200, 600]
        )
        self.assertEqual(records[1]["stable_ms"], 400)
        self.assertEqual(records[1]["invalid_landmark_frames_seen"], 1)

    def test_degenerate_geometry_keeps_raw_data_but_null_features(self):
        landmarks = [[0.0, 0.0]] * 21
        engine = CaptureDiagnostics()
        diagnostic = engine.observe(landmarks, 0)
        self.assertFalse(diagnostic["valid"])
        self.assertEqual(diagnostic["error_code"], "INVALID_LANDMARKS")
        self.assertIsNone(diagnostic["joint_angles_deg"])
        self.assertIsNone(diagnostic["thumb_extension"])
        self.assertIsNotNone(diagnostic["feature_error"])

    def test_source_hash_is_actual_file_and_failure_is_explicit_null(self):
        import hashlib
        import gesture_classifier

        engine = CaptureDiagnostics()
        actual = hashlib.sha256(Path(gesture_classifier.__file__).read_bytes()).hexdigest()
        self.assertEqual(engine.runtime_version["classifier"]["sha256"], actual)
        self.assertEqual(engine.runtime_version["confidence_threshold"], 0.64)
        self.assertEqual(engine.runtime_version["stable_hold_ms"], 300)
        failed = _source_fingerprint(types.SimpleNamespace(__file__="missing_capture_source.py"))
        self.assertIsNone(failed["sha256"])
        self.assertEqual(failed["status"], "unavailable")

    def test_no_hand_run_is_bounded_and_does_not_write_false_samples(self):
        written, records, state = self.run_fake_capture([None, None], [0, 5000])
        self.assertEqual(written, 0)
        self.assertEqual(records, [])
        self.assertTrue(state["closed"])

    def test_tick_wrap_keeps_elapsed_stability_and_write_interval(self):
        opened = shape_points()
        _, records, _ = self.run_fake_capture([opened, opened, opened], [65500, 64, 464])
        self.assertEqual(records[1]["stable_ms"], 500)
        self.assertEqual(records[1]["classifier_elapsed_ms"], 500)
        self.assertEqual(records[1]["timestamp_ms"], 464)

    def test_invalid_metadata_and_limit_fail_before_capture(self):
        for overrides in (dict(hand_side="both"), dict(view="65_degrees"), dict(max_capture_ms=0), dict(max_capture_ms=True)):
            with self.subTest(overrides=overrides):
                with self.assertRaises(CaptureError):
                    validate_config(CaptureConfig(consent=True, **overrides))

    def test_capture_requires_consent_before_loading_rules_or_camera(self):
        with mock.patch("sign_landmark_capture.CaptureDiagnostics") as engine:
            with self.assertRaises(CaptureError):
                run_capture(
                    CaptureConfig(consent=False), app_module=None, camera_module=None,
                    display_module=None, image_module=None, nn_module=None, time_module=None,
                )
            engine.assert_not_called()

    def test_cancel_before_first_sample_closes_camera(self):
        camera = mock.Mock()
        detector = mock.Mock()
        detector.input_format.return_value = "host_fake"
        with mock.patch("sign_landmark_capture.CaptureDiagnostics"):
            result = run_capture(
                CaptureConfig(consent=True),
                app_module=types.SimpleNamespace(need_exit=lambda: True),
                camera_module=types.SimpleNamespace(Camera=lambda *_args: camera),
                display_module=None, image_module=None,
                nn_module=types.SimpleNamespace(HandLandmarks=lambda **_kwargs: detector),
                time_module=None,
            )
        self.assertEqual(result, 0)
        camera.close.assert_called_once()
        camera.read.assert_not_called()

    def test_main_does_not_return_sample_count_as_error_exit(self):
        fake_maix = types.ModuleType("maix")
        for name in ("app", "camera", "display", "image", "nn", "time"):
            setattr(fake_maix, name, None)
        with mock.patch.dict(sys.modules, {"maix": fake_maix}):
            with mock.patch("sign_landmark_capture.run_capture", return_value=7):
                self.assertEqual(main(CaptureConfig(consent=True)), 0)

    def test_project_launcher_calls_capture_and_preserves_exit_status(self):
        entry = PROJECT_ROOT / "capture_kit/main.py"
        for status in (0, 2):
            with self.subTest(status=status):
                with mock.patch("sign_landmark_capture.main", return_value=status) as start:
                    with self.assertRaises(SystemExit) as stopped:
                        runpy.run_path(str(entry), run_name="__main__")
                    self.assertEqual(stopped.exception.code, status)
                    start.assert_called_once_with()

    def test_project_launcher_import_does_not_start_capture(self):
        entry = PROJECT_ROOT / "capture_kit/main.py"
        with mock.patch("sign_landmark_capture.main") as start:
            runpy.run_path(str(entry), run_name="capture_import_check")
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
