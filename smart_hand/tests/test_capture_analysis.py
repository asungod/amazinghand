"""Synthetic contract tests for local, read-only capture analysis."""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "smart_hand/host/analyze_capture.py"
spec = importlib.util.spec_from_file_location("capture_analysis", SCRIPT)
analyzer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analyzer)

from sign_landmark_capture import CaptureConfig, CaptureDiagnostics, build_diagnostic_sample


def sample(points=None):
    if points is None:
        points = [[0.0, 0.0] for _ in range(21)]
        for base, x in ((5, 1), (9, 2), (13, 3), (17, 4)):
            for offset in range(4):
                points[base + offset] = [120.0 + x * 10, 50.0 + offset * 20]
    engine = CaptureDiagnostics()
    engine.runtime_version["landmark_detector"] = {"camera_width": 320, "camera_height": 224}
    return build_diagnostic_sample(
        CaptureConfig(consent=True, gesture_id="V_SIGN"), points, 10,
        engine.observe(points, 0), engine.runtime_version, "synthetic-sequence", 1,
    )


class CaptureAnalysisTests(unittest.TestCase):
    def test_same_frame_replay_with_user_target_different_from_prediction(self):
        report = analyzer.analyze_rows([sample()])
        self.assertEqual(report["single_frame_replay_match_count"], 1)
        self.assertEqual(report["sequence_count"], 1)
        row = report["rows"][0]
        self.assertEqual(row["target_annotation"], "V_SIGN")
        self.assertEqual(row["device_prediction"], "OPEN_PALM")
        self.assertTrue(all(row["source_hash_matches"].values()))
        self.assertTrue(report["not_an_accuracy_estimate"])
        self.assertTrue(report["target_is_user_annotation_not_verified_ground_truth"])

    def test_wrong_geometry_or_timestamp_is_not_accepted_as_same_frame(self):
        for field in ("prediction_timestamp_ms", "finger_extension", "joint_angles_deg", "predicted_gesture_id"):
            record = sample()
            record[field] = None
            with self.subTest(field=field):
                row = analyzer.analyze_rows([record])["rows"][0]
                self.assertFalse(row["single_frame_replay_matches"])
                self.assertIn(field, row["mismatched_fields"])

    def test_version_mismatch_does_not_get_confused_with_replay_equality(self):
        record = sample()
        record["runtime_version"]["classifier"]["sha256"] = "0" * 64
        row = analyzer.analyze_rows([record])["rows"][0]
        self.assertTrue(row["single_frame_replay_matches"])
        self.assertFalse(row["source_hash_matches"]["classifier"])

    def test_optional_rule_extension_is_checked_without_rejecting_old_records(self):
        record = sample()
        self.assertIn("rule_finger_extension", record)
        record["rule_finger_extension"] = [0.0] * 4
        self.assertIn("rule_finger_extension", analyzer.analyze_rows([record])["rows"][0]["mismatched_fields"])
        del record["rule_finger_extension"]
        self.assertTrue(analyzer.analyze_rows([record])["rows"][0]["single_frame_replay_matches"])

    def test_sparse_frames_are_never_used_to_rebuild_stable_time(self):
        record = sample()
        record["stable_ms"] = 50000
        report = analyzer.analyze_rows([record])
        self.assertFalse(report["temporal_replay_performed"])
        self.assertEqual(report["rows"][0]["recorded_stable_ms"], 50000)
        self.assertEqual(report["single_frame_replay_match_count"], 1)

    def test_correlated_frames_remain_one_sequence(self):
        record = sample()
        other = copy.deepcopy(record)
        other["sample_id"] = "synthetic-sequence-2"
        report = analyzer.analyze_rows([record, other])
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["sequence_count"], 1)

    def test_geometry_degeneracy_is_reported_not_fabricated(self):
        row = analyzer.analyze_rows([sample([[0, 0]] * 21)])["rows"][0]
        self.assertTrue(row["single_frame_replay_matches"])
        self.assertIsNone(row["joint_angles_deg"])
        self.assertEqual(row["host_prediction"], "UNKNOWN")

    def test_image_bounds_are_metadata_based_not_a_new_classifier_gate(self):
        record = sample()
        self.assertEqual(analyzer.analyze_rows([record])["rows"][0]["outside_image_xy_count"], 0)
        record["runtime_version"]["landmark_detector"]["camera_width"] = 100
        row = analyzer.analyze_rows([record])["rows"][0]
        self.assertGreater(row["outside_image_xy_count"], 0)
        self.assertLess(row["min_image_edge_distance_px"], 0)
        self.assertEqual(row["host_prediction"], "OPEN_PALM")

    def test_cli_refuses_to_overwrite_input_or_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.jsonl"
            path.write_text(json.dumps(sample()) + "\n", encoding="utf-8")
            original = path.read_bytes()
            result = subprocess.run(
                [sys.executable, "-X", "utf8", str(SCRIPT), str(path), "--output", str(path)],
                capture_output=True, text=True, encoding="utf-8", timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
