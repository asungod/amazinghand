"""Train and audit the optional OpenSignHand centroid classifier.

The trainer is deliberately small and dependency-free.  It fits one
standardized centroid per known prototype (OPEN_PALM/FIST/V_SIGN), evaluates
with complete participant-held-out folds, and emits an auditable JSON model.
It never creates or modifies the source JSONL dataset.
"""

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path


HOST_ROOT = Path(__file__).resolve().parent
MAIX_ROOT = HOST_ROOT.parent / "maixcam2"
if str(HOST_ROOT) not in sys.path:
    sys.path.insert(0, str(HOST_ROOT))
if str(MAIX_ROOT) not in sys.path:
    sys.path.insert(0, str(MAIX_ROOT))

from gesture_classifier import (  # noqa: E402
    DEFAULT_MODEL_PATH,
    MODEL_FEATURE_NAME,
    MODEL_LABELS,
    MODEL_SCHEMA,
    MODEL_SCHEMA_VERSION,
    MODEL_TYPE,
    validate_model_payload,
)
from gesture_features import extract_gesture_features, feature_vector  # noqa: E402
from sign_landmark_dataset import (  # noqa: E402
    DatasetError,
    SUPPORTED_GESTURES,
    load_samples,
    validate_sample,
)


EVALUATION_LABELS = tuple(SUPPORTED_GESTURES)


class TrainingError(DatasetError):
    """Raised when a meaningful, leakage-free model cannot be trained."""


def _finite(value, name):
    if isinstance(value, bool):
        raise TrainingError("{} must be numeric".format(name))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise TrainingError("{} must be numeric".format(name))
    if math.isnan(number) or math.isinf(number):
        raise TrainingError("{} must be finite".format(name))
    return number


def _vectors(samples):
    """Validate samples and return deterministic (sample, vector) pairs."""
    pairs = []
    for index, raw_sample in enumerate(samples, start=1):
        sample = validate_sample(raw_sample, index)
        try:
            vector = feature_vector(extract_gesture_features(sample["landmarks"]))
        except (TypeError, ValueError, OverflowError, ArithmeticError) as exc:
            raise TrainingError(
                "sample {} has invalid feature geometry: {}".format(index, exc)
            )
        if not vector:
            raise TrainingError("sample {} produced an empty feature vector".format(index))
        if any(
            math.isnan(float(value)) or math.isinf(float(value))
            for value in vector
        ):
            raise TrainingError("sample {} produced NaN/Inf features".format(index))
        pairs.append((sample, [float(value) for value in vector]))
    if not pairs:
        raise TrainingError("dataset contains no samples")
    dimension = len(pairs[0][1])
    if any(len(vector) != dimension for _sample, vector in pairs):
        raise TrainingError("feature vector dimensions are inconsistent")
    if dimension != 18:
        raise TrainingError("feature vector dimension must be 18")
    return pairs


def _require_training_shape(pairs):
    participants = sorted(set(sample["participant_id"] for sample, _ in pairs))
    if len(participants) < 2:
        raise TrainingError("at least two participants are required")
    counts = Counter(sample["gesture_id"] for sample, _ in pairs)
    missing = [label for label in MODEL_LABELS if counts.get(label, 0) == 0]
    if missing:
        raise TrainingError(
            "missing required gesture classes: {}".format(", ".join(missing))
        )
    return participants, counts


def _fit_parameters(pairs):
    """Fit mean/std and standardized centroids from known samples only."""
    known = [(sample, vector) for sample, vector in pairs
             if sample["gesture_id"] in MODEL_LABELS]
    if not known:
        raise TrainingError("no known gesture samples available for fitting")
    dimension = len(known[0][1])
    for label in MODEL_LABELS:
        if not any(sample["gesture_id"] == label for sample, _ in known):
            raise TrainingError(
                "training fold is missing required class {}".format(label)
            )
    count = float(len(known))
    mean = [
        sum(vector[index] for _sample, vector in known) / count
        for index in range(dimension)
    ]
    std = []
    for index in range(dimension):
        variance = sum(
            (vector[index] - mean[index]) ** 2 for _sample, vector in known
        ) / count
        # A constant feature carries no discriminative scale but must remain
        # numerically usable on-device.
        std.append(max(math.sqrt(variance), 1e-6))
    standardized = []
    for sample, vector in known:
        standardized.append(
            (
                sample,
                [
                    (value - mean[index]) / std[index]
                    for index, value in enumerate(vector)
                ],
            )
        )
    centroids = {}
    for label in MODEL_LABELS:
        vectors = [vector for sample, vector in standardized
                   if sample["gesture_id"] == label]
        centroids[label] = [
            sum(vector[index] for vector in vectors) / float(len(vectors))
            for index in range(dimension)
        ]

    distances = []
    for sample, vector in standardized:
        centroid = centroids[sample["gesture_id"]]
        distance = math.sqrt(
            sum((value - center) ** 2 for value, center in zip(vector, centroid))
            / float(dimension)
        )
        distances.append(distance)
    max_within = max(distances) if distances else 0.0
    # A small floor avoids rejecting an exact prototype, while the cap keeps a
    # noisy dataset from disabling UNKNOWN rejection altogether.
    reject_distance = max(0.35, min(3.5, max_within * 2.5 + 0.05))
    # The margin gate is intentionally modest; distance remains the primary
    # rejection signal and close class boundaries are reported as UNKNOWN.
    reject_margin = 0.05
    return {
        "feature_dim": dimension,
        "feature_mean": mean,
        "feature_std": std,
        "centroids": centroids,
        "reject_distance": reject_distance,
        "reject_margin": reject_margin,
        "confidence_threshold": 0.64,
    }


def _predict(vector, parameters):
    standardized = [
        (value - mean) / scale
        for value, mean, scale in zip(
            vector, parameters["feature_mean"], parameters["feature_std"]
        )
    ]
    distances = []
    for label in MODEL_LABELS:
        centroid = parameters["centroids"][label]
        distance = math.sqrt(
            sum((value - center) ** 2 for value, center in zip(standardized, centroid))
            / float(parameters["feature_dim"])
        )
        distances.append((label, distance))
    distances.sort(key=lambda item: (item[1], item[0]))
    label, nearest = distances[0]
    margin = distances[1][1] - nearest
    if (
        nearest > parameters["reject_distance"]
        or margin < parameters["reject_margin"]
    ):
        return "UNKNOWN"
    return label


def _empty_matrix():
    return {
        actual: {predicted: 0 for predicted in EVALUATION_LABELS}
        for actual in EVALUATION_LABELS
    }


def _metric(tp, fp, fn):
    precision = tp / float(tp + fp) if tp + fp else 0.0
    recall = tp / float(tp + fn) if tp + fn else 0.0
    f1 = (
        2.0 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "support": tp + fn,
    }


def evaluate_participant_folds(pairs):
    """Fit each fold only on other participants and return audit metrics."""
    participants, _counts = _require_training_shape(pairs)
    matrix = _empty_matrix()
    actual_counts = Counter()
    predicted_counts = Counter()
    folds = []
    total = 0
    for held_out in participants:
        train = [pair for pair in pairs if pair[0]["participant_id"] != held_out]
        test = [pair for pair in pairs if pair[0]["participant_id"] == held_out]
        if not train or not test:
            raise TrainingError("empty train/test fold for {}".format(held_out))
        train_participants = sorted(set(sample["participant_id"] for sample, _ in train))
        if held_out in train_participants:
            raise TrainingError("participant leakage detected for {}".format(held_out))
        parameters = _fit_parameters(train)
        fold_predictions = 0
        for sample, vector in test:
            actual = sample["gesture_id"]
            predicted = _predict(vector, parameters)
            matrix[actual][predicted] += 1
            actual_counts[actual] += 1
            predicted_counts[predicted] += 1
            total += 1
            fold_predictions += 1
        folds.append(
            {
                "held_out_participant": held_out,
                "train_sample_count": len(train),
                "test_sample_count": len(test),
                "train_participants": train_participants,
                "test_participants": [held_out],
                "participant_overlap": [],
                "predictions": fold_predictions,
            }
        )
    per_class = {}
    for label in EVALUATION_LABELS:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in EVALUATION_LABELS if actual != label)
        fn = sum(matrix[label][predicted] for predicted in EVALUATION_LABELS if predicted != label)
        per_class[label] = _metric(tp, fp, fn)
    macro_f1 = sum(item["f1"] for item in per_class.values()) / float(
        len(EVALUATION_LABELS)
    )
    unknown_total = actual_counts.get("UNKNOWN", 0)
    unknown_false_accepts = sum(
        matrix["UNKNOWN"][predicted]
        for predicted in MODEL_LABELS
    )
    return {
        "schema": MODEL_SCHEMA,
        "evaluation": "leave_one_participant_out",
        "sample_count": total,
        "participant_count": len(participants),
        "participants": participants,
        "sample_counts": {
            "actual": {
                label: actual_counts.get(label, 0) for label in EVALUATION_LABELS
            },
            "predicted": {
                label: predicted_counts.get(label, 0) for label in EVALUATION_LABELS
            },
        },
        "class_counts": {
            label: sum(1 for sample, _ in pairs if sample["gesture_id"] == label)
            for label in EVALUATION_LABELS
        },
        "confusion_matrix": matrix,
        "per_class": per_class,
        "macro_f1": round(macro_f1, 6),
        "unknown_false_accept_rate": (
            round(unknown_false_accepts / float(unknown_total), 6)
            if unknown_total else None
        ),
        "unknown_false_accepts": unknown_false_accepts,
        "unknown_samples": unknown_total,
        "folds": folds,
        "leakage_check": {
            "passed": True,
            "train_test_participant_overlap": [],
        },
    }


def build_model(samples):
    """Validate, evaluate, fit final parameters, and return model/report."""
    pairs = _vectors(samples)
    participants, counts = _require_training_shape(pairs)
    report = evaluate_participant_folds(pairs)
    parameters = _fit_parameters(pairs)
    model = {
        "schema": MODEL_SCHEMA,
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "feature_name": MODEL_FEATURE_NAME,
        "feature_dim": parameters["feature_dim"],
        "labels": list(MODEL_LABELS),
        "feature_mean": parameters["feature_mean"],
        "feature_std": parameters["feature_std"],
        "centroids": parameters["centroids"],
        "reject_distance": parameters["reject_distance"],
        "reject_margin": parameters["reject_margin"],
        "confidence_threshold": parameters["confidence_threshold"],
        "training": {
            "sample_count": len(pairs),
            "known_sample_count": sum(counts.get(label, 0) for label in MODEL_LABELS),
            "participant_count": len(participants),
            "participants": participants,
            "class_counts": {
                label: counts.get(label, 0) for label in EVALUATION_LABELS
            },
            "evaluation": "leave_one_participant_out",
        },
    }
    # Validate the exact object that will be written, before touching disk.
    validate_model_payload(model)
    return model, report


def train_jsonl(dataset_path, output_path, report_path=None):
    samples = load_samples(dataset_path)
    model, report = build_model(samples)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(model, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    if report_path is not None:
        report_path = Path(report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
    return model, report


def _parser():
    parser = argparse.ArgumentParser(
        description="Train an auditable OpenSignHand centroid model offline."
    )
    parser.add_argument("dataset", type=Path, help="validated landmark JSONL")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        default=Path(DEFAULT_MODEL_PATH),
        help="JSON model output path (default: %(default)s)",
    )
    parser.add_argument("--report", type=Path, help="optional JSON evaluation report")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        _model, report = train_jsonl(args.dataset, args.output, args.report)
    except (DatasetError, OSError, TypeError, ValueError, TrainingError) as exc:
        print("Sign classifier training failed: {}".format(exc), file=sys.stderr)
        return 1
    public = {
        "ok": True,
        "model_path": str(args.output),
        "sample_count": report["sample_count"],
        "participant_count": report["participant_count"],
        "participants": report["participants"],
        "class_counts": report["class_counts"],
        "macro_f1": report["macro_f1"],
        "unknown_false_accept_rate": report["unknown_false_accept_rate"],
        "confusion_matrix": report["confusion_matrix"],
        "folds": report["folds"],
    }
    print(json.dumps(public, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
