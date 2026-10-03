"""Participant-held-out evaluation for the OpenSignHand shape classifier.

This is an offline evaluator, not a training pipeline.  Each participant is
held out as a complete test fold, so samples from one person can never appear
in both that fold's train context and test context.  The current deterministic
classifier does not fit parameters, but the same fold contract is retained so
future learned classifiers can be inserted without weakening the evaluation.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


HOST_ROOT = Path(__file__).resolve().parent
MAIX_ROOT = HOST_ROOT.parent / "maixcam2"
if str(HOST_ROOT) not in sys.path:
    sys.path.insert(0, str(HOST_ROOT))
if str(MAIX_ROOT) not in sys.path:
    sys.path.insert(0, str(MAIX_ROOT))

from gesture_classifier import classify_gesture  # noqa: E402
from sign_landmark_dataset import (  # noqa: E402
    DatasetError,
    SCHEMA,
    SUPPORTED_GESTURES,
    load_samples,
    validate_sample,
)


class EvaluationError(DatasetError):
    """Raised when a meaningful participant-held-out score is impossible."""


def predict_sample(sample):
    """Run the existing explainable classifier on one validated sample."""
    result = classify_gesture(sample["landmarks"])
    return result["gesture_id"]


def _prediction_label(prediction):
    if isinstance(prediction, str):
        label = prediction
    elif isinstance(prediction, dict):
        label = prediction.get("gesture_id")
    else:
        label = getattr(prediction, "gesture_id", None)
    if label not in SUPPORTED_GESTURES:
        raise EvaluationError(
            "predictor returned unsupported gesture_id {!r}".format(label)
        )
    return label


def _empty_matrix():
    return dict(
        (actual, dict((predicted, 0) for predicted in SUPPORTED_GESTURES))
        for actual in SUPPORTED_GESTURES
    )


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


def evaluate_leave_one_participant_out(samples, predictor=None):
    """Evaluate validated samples with complete participant-held-out folds.

    ``predictor`` is optional and receives one sample mapping.  It may return
    a supported label or a classifier result mapping/object with a
    ``gesture_id`` field.  A predictor is never given test samples as training
    data by this function.
    """
    if not samples:
        raise EvaluationError("no data: at least two participants are required")
    validated = [validate_sample(sample) for sample in samples]
    participants = sorted(set(sample["participant_id"] for sample in validated))
    if len(participants) < 2:
        raise EvaluationError(
            "at least two participants are required for leave-one-participant-out evaluation"
        )
    predict = predictor or predict_sample
    matrix = _empty_matrix()
    participant_counts = Counter()
    actual_counts = Counter()
    predicted_counts = Counter()
    folds = []
    total_predictions = 0

    for held_out in participants:
        test_samples = [
            sample for sample in validated if sample["participant_id"] == held_out
        ]
        train_samples = [
            sample for sample in validated if sample["participant_id"] != held_out
        ]
        train_participants = sorted(
            set(sample["participant_id"] for sample in train_samples)
        )
        overlap = sorted(set(train_participants).intersection((held_out,)))
        if overlap:
            raise EvaluationError(
                "participant leakage detected in held-out fold {}".format(held_out)
            )
        if not test_samples or not train_samples:
            raise EvaluationError("empty train/test fold for participant {}".format(held_out))

        fold_predictions = 0
        for sample in test_samples:
            actual = sample["gesture_id"]
            predicted = _prediction_label(predict(sample))
            matrix[actual][predicted] += 1
            actual_counts[actual] += 1
            predicted_counts[predicted] += 1
            participant_counts[held_out] += 1
            fold_predictions += 1
            total_predictions += 1
        folds.append(
            {
                "held_out_participant": held_out,
                "train_sample_count": len(train_samples),
                "test_sample_count": len(test_samples),
                "train_participants": train_participants,
                "test_participants": [held_out],
                "participant_overlap": overlap,
                "predictions": fold_predictions,
            }
        )

    per_class = {}
    for label in SUPPORTED_GESTURES:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in SUPPORTED_GESTURES if actual != label)
        fn = sum(matrix[label][predicted] for predicted in SUPPORTED_GESTURES if predicted != label)
        per_class[label] = _metric(tp, fp, fn)
    macro_f1 = sum(item["f1"] for item in per_class.values()) / float(
        len(SUPPORTED_GESTURES)
    )
    unknown_total = actual_counts.get("UNKNOWN", 0)
    unknown_false_accepts = sum(
        matrix["UNKNOWN"][predicted]
        for predicted in SUPPORTED_GESTURES
        if predicted != "UNKNOWN"
    )
    unknown_far = (
        round(unknown_false_accepts / float(unknown_total), 6)
        if unknown_total
        else None
    )

    return {
        "schema": SCHEMA,
        "evaluation": "leave_one_participant_out",
        "sample_count": total_predictions,
        "participant_count": len(participants),
        "participants": participants,
        "sample_counts": {
            "actual": {
                label: actual_counts.get(label, 0) for label in SUPPORTED_GESTURES
            },
            "predicted": {
                label: predicted_counts.get(label, 0) for label in SUPPORTED_GESTURES
            },
            "by_participant": dict(sorted(participant_counts.items())),
        },
        "confusion_matrix": matrix,
        "per_class": per_class,
        "macro_f1": round(macro_f1, 6),
        "unknown_false_accept_rate": unknown_far,
        "unknown_false_accepts": unknown_false_accepts,
        "unknown_samples": unknown_total,
        "folds": folds,
        "leakage_check": {
            "passed": all(not fold["participant_overlap"] for fold in folds),
            "train_test_participant_overlap": [],
        },
    }


def evaluate_jsonl(path, predictor=None):
    """Load a valid JSONL file and evaluate it, failing on no/one-person data."""
    return evaluate_leave_one_participant_out(load_samples(path), predictor=predictor)


def _parser():
    parser = argparse.ArgumentParser(
        description="Evaluate OpenSignHand shape prototypes by participant-held-out folds."
    )
    parser.add_argument("dataset", type=Path)
    parser.add_argument(
        "--pretty", action="store_true", help="indent the JSON evaluation report"
    )
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        result = evaluate_jsonl(args.dataset)
    except (DatasetError, OSError, TypeError, ValueError) as exc:
        print("Sign classifier evaluation failed: {}".format(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

