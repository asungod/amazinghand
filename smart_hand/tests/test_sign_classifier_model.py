import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from gesture_classifier import (  # noqa: E402
    ERROR_LINK_OFFLINE,
    ERROR_NO_HAND,
    ERROR_VISION_STALE,
    FIST,
    GestureClassifier,
    LearnedGestureClassifier,
    OPEN_PALM,
    UNKNOWN,
    V_SIGN,
    create_classifier,
    validate_model_payload,
)
from train_sign_classifier import build_model, train_jsonl  # noqa: E402


def shape(pattern):
    points = [(0.0, 0.0) for _ in range(21)]
    points[9] = (2.0, 0.0)
    for (base, x), folded in zip(
        ((5, 1.0), (9, 2.0), (13, 3.0), (17, 4.0)), pattern
    ):
        points[base] = (x, 0.0)
        points[base + 1] = (x, 1.0)
        points[base + 2] = ((x + 0.8), 1.0) if folded else (x, 2.0)
        points[base + 3] = ((x + 0.8), 0.2) if folded else (x, 3.0)
    return points


OPEN = shape((False, False, False, False))
FIST_POINTS = shape((True, True, True, True))
V_POINTS = shape((False, False, True, True))


def dataset_samples():
    rows = []
    values = ((OPEN_PALM, OPEN), (FIST, FIST_POINTS), (V_SIGN, V_POINTS))
    timestamp = 0
    for participant in ("P01", "P02"):
        for gesture, landmarks in values:
            rows.append(
                {
                    "schema": "opensignhand.landmark.v1",
                    "participant_id": participant,
                    "session_id": "S01",
                    "gesture_id": gesture,
                    "timestamp_ms": timestamp,
                    "landmarks": landmarks,
                    "source": "unit_fixture",
                    "license": "unit-test-fixture; no redistribution",
                    "consent": True,
                }
            )
            timestamp += 1
    return rows


class LearnedClassifierTests(unittest.TestCase):
    def test_train_export_and_known_classes(self):
        model, report = build_model(dataset_samples())
        self.assertEqual(model["schema_version"], 1)
        self.assertEqual(model["feature_dim"], 18)
        self.assertEqual(report["participant_count"], 2)
        self.assertEqual(report["unknown_false_accept_rate"], None)
        validate_model_payload(model)
        classifier = LearnedGestureClassifier(model, stable_hold_ms=300)
        self.assertEqual(classifier.observe(OPEN, now_ms=0).gesture_id, OPEN_PALM)
        self.assertEqual(classifier.observe(FIST_POINTS, now_ms=1).gesture_id, FIST)
        self.assertEqual(classifier.observe(V_POINTS, now_ms=2).gesture_id, V_SIGN)

    def test_factory_falls_back_for_missing_or_invalid_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertIsInstance(create_classifier(path), GestureClassifier)
            model, _report = build_model(dataset_samples())
            path.write_text(json.dumps(model), encoding="utf-8")
            self.assertIsInstance(create_classifier(path), LearnedGestureClassifier)
            broken = dict(model)
            broken["feature_dim"] = 17
            path.write_text(json.dumps(broken), encoding="utf-8")
            fallback = create_classifier(path)
            self.assertIsInstance(fallback, GestureClassifier)
            self.assertNotIsInstance(fallback, LearnedGestureClassifier)

    def test_learning_keeps_safety_gates_and_monotonic_stability(self):
        model, _report = build_model(dataset_samples())
        classifier = LearnedGestureClassifier(model, stable_hold_ms=300)
        self.assertEqual(
            classifier.observe(OPEN, now_ms=0, link_online=False).error_code,
            ERROR_LINK_OFFLINE,
        )
        self.assertEqual(
            classifier.observe(OPEN, now_ms=1, vision_stale=True).error_code,
            ERROR_VISION_STALE,
        )
        self.assertEqual(
            classifier.observe(None, now_ms=2, hand_present=False).error_code,
            ERROR_NO_HAND,
        )
        first = classifier.observe(OPEN, now_ms=10)
        second = classifier.observe(OPEN, now_ms=310)
        self.assertEqual(first.stable_ms, 0)
        self.assertEqual(second.stable_ms, 300)
        self.assertTrue(second.stable)

    def test_train_jsonl_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "samples.jsonl"
            lines = [json.dumps(row, sort_keys=True) for row in dataset_samples()]
            dataset.write_text("\n".join(lines) + "\n", encoding="utf-8")
            first = root / "first.json"
            second = root / "second.json"
            train_jsonl(dataset, first)
            train_jsonl(dataset, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main()
