import io
import json
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(PROJECT_ROOT / "host"))
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from evaluate_sign_classifier import (  # noqa: E402
    EvaluationError,
    evaluate_leave_one_participant_out,
    evaluate_jsonl,
)
from sign_landmark_dataset import (  # noqa: E402
    SCHEMA,
    SUPPORTED_GESTURES,
    append_sample,
    load_samples,
    main as dataset_main,
    summarize_samples,
    validate_jsonl,
    validate_sample,
)


def points(folded=False):
    values = [(0.0, 0.0) for _ in range(21)]
    values[9] = (2.0, 0.0)
    for base, x in ((5, 1.0), (9, 2.0), (13, 3.0), (17, 4.0)):
        values[base] = (x, 0.0)
        values[base + 1] = (x, 1.0)
        values[base + 2] = ((x + 0.8), 1.0) if folded else (x, 2.0)
        values[base + 3] = ((x + 0.8), 0.2) if folded else (x, 3.0)
    return values


def sample(participant, session, gesture, timestamp=0, prediction=None):
    record = {
        "schema": SCHEMA,
        "participant_id": participant,
        "session_id": session,
        "gesture_id": gesture,
        "timestamp_ms": timestamp,
        "landmarks": points(gesture == "FIST"),
        "source": "local_fixture",
        "license": "Apache-2.0-derived-fixture",
        "consent": True,
    }
    if prediction is not None:
        record["expected_prediction"] = prediction
    return record


class SignLandmarkDatasetTests(unittest.TestCase):
    def test_validate_accepts_nested_and_flat_landmarks(self):
        nested = validate_sample(sample("P01", "S01", "OPEN_PALM"))
        self.assertEqual(len(nested["landmarks"]), 21)
        flat = sample("P02", "S01", "FIST")
        flat["landmarks"] = [coordinate for point in points(True) for coordinate in (point[0], point[1], 0.0)]
        normalized = validate_sample(flat)
        self.assertEqual(len(normalized["landmarks"]), 63)

    def test_rejects_bad_schema_geometry_pii_and_consent(self):
        bad_schema = sample("P01", "S01", "OPEN_PALM")
        bad_schema["schema"] = "other.v1"
        with self.assertRaises(ValueError):
            validate_sample(bad_schema)

        bad_geometry = sample("P01", "S01", "OPEN_PALM")
        bad_geometry["landmarks"] = [[0, 0]] * 20
        with self.assertRaises(ValueError):
            validate_sample(bad_geometry)

        bad_identity = sample("P01", "S01", "OPEN_PALM")
        bad_identity["phone"] = "13800138000"
        with self.assertRaisesRegex(ValueError, "personal field"):
            validate_sample(bad_identity)

        bad_consent = sample("P01", "S01", "OPEN_PALM")
        bad_consent["consent"] = False
        with self.assertRaises(ValueError):
            validate_sample(bad_consent)

        ambiguous_consent = sample("P01", "S01", "OPEN_PALM")
        ambiguous_consent["consent"] = "recorded_with_consent"
        with self.assertRaisesRegex(ValueError, "JSON boolean true"):
            validate_sample(ambiguous_consent)

    def test_append_validate_summary_and_cli_are_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "samples.jsonl"
            path.touch()
            append_sample(path, sample("P01", "S01", "OPEN_PALM", 10))
            append_sample(path, sample("P02", "S01", "FIST", 20))
            report = validate_jsonl(path)
            self.assertTrue(report["ok"])
            self.assertEqual(report["sample_count"], 2)
            summary = summarize_samples(load_samples(path))
            self.assertEqual(summary["participant_count"], 2)
            self.assertEqual(summary["gestures"]["OPEN_PALM"], 1)
            self.assertEqual(dataset_main(["validate", str(path)]), 0)
            self.assertEqual(dataset_main(["summary", str(path)]), 0)

    def test_invalid_jsonl_is_reported_and_append_refuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text("{not json}\n", encoding="utf-8")
            report = validate_jsonl(path)
            self.assertFalse(report["ok"])
            self.assertEqual(report["errors"][0]["line"], 1)
            with self.assertRaises(ValueError):
                append_sample(path, sample("P01", "S01", "OPEN_PALM"))


class SignClassifierEvaluationTests(unittest.TestCase):
    def test_leave_one_participant_out_metrics_and_unknown_far(self):
        records = [
            sample("P01", "S01", "OPEN_PALM", 0, "OPEN_PALM"),
            sample("P01", "S01", "FIST", 1, "FIST"),
            sample("P01", "S01", "UNKNOWN", 2, "OPEN_PALM"),
            sample("P02", "S01", "OPEN_PALM", 0, "OPEN_PALM"),
            sample("P02", "S01", "FIST", 1, "V_SIGN"),
            sample("P02", "S01", "V_SIGN", 2, "V_SIGN"),
            sample("P02", "S01", "UNKNOWN", 3, "UNKNOWN"),
        ]
        result = evaluate_leave_one_participant_out(
            records, predictor=lambda record: record["expected_prediction"]
        )
        self.assertEqual(result["sample_count"], len(records))
        self.assertEqual(result["participant_count"], 2)
        self.assertEqual(result["confusion_matrix"]["UNKNOWN"]["OPEN_PALM"], 1)
        self.assertEqual(result["per_class"]["OPEN_PALM"]["support"], 2)
        self.assertEqual(result["unknown_samples"], 2)
        self.assertEqual(result["unknown_false_accepts"], 1)
        self.assertEqual(result["unknown_false_accept_rate"], 0.5)
        self.assertTrue(result["leakage_check"]["passed"])
        for fold in result["folds"]:
            self.assertEqual(fold["participant_overlap"], [])
            self.assertNotIn(fold["held_out_participant"], fold["train_participants"])

    def test_one_participant_and_empty_data_fail_without_fake_scores(self):
        with self.assertRaisesRegex(EvaluationError, "at least two participants"):
            evaluate_leave_one_participant_out([sample("P01", "S01", "OPEN_PALM")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                evaluate_jsonl(path)

    def test_supported_labels_are_shape_prototypes_only(self):
        self.assertEqual(
            SUPPORTED_GESTURES,
            (
                "OPEN_PALM", "FIST", "V_SIGN", "POINT", "THUMBS_UP",
                "L_SHAPE", "OK_PINCH", "UNKNOWN",
            ),
        )
        manifest = (
            PROJECT_ROOT / "data" / "opensignhand" / "manifest.example.csv"
        ).read_text(encoding="utf-8")
        self.assertIn("NationalCSL-DP", manifest)
        self.assertIn("10.6084/m9.figshare.27261843.v3", manifest)
        self.assertIn("CC BY 4.0", manifest)
        self.assertNotIn(".mp4", manifest.lower())


if __name__ == "__main__":
    unittest.main()
