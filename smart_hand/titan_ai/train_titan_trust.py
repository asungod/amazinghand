"""Train and export the advisory TitanTrust-Tiny MLP.

The initial corpus is synthetic by design. It exists to validate the software
pipeline and fail-closed integration before collecting independent hardware
sessions. Never present its score as clinical or field accuracy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.metrics import accuracy_score, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPClassifier


FEATURE_NAMES = (
    "confidence_pct",
    "bbox_motion_pct",
    "bbox_scale_change_pct",
    "arrival_interval_ms",
    "arrival_jitter_ms",
    "sequence_gap_delta",
    "invalid_frame_delta",
    "duplicate_old_delta",
    "vision_age_ms",
    "valid_frame_ratio_pct",
)

CLASS_NAMES = ("TRUSTED", "UNCERTAIN", "ANOMALOUS")

# Fixed engineering ranges keep host and MCU preprocessing identical.
FEATURE_MIN = np.array([0, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float64)
FEATURE_MAX = np.array(
    [100, 100, 100, 2000, 1000, 20, 20, 20, 2000, 100],
    dtype=np.float64,
)


def _bounded_normal(
    rng: np.random.Generator,
    count: int,
    mean: list[float],
    std: list[float],
) -> np.ndarray:
    values = rng.normal(np.asarray(mean), np.asarray(std), size=(count, 10))
    return np.clip(values, FEATURE_MIN, FEATURE_MAX)


def build_synthetic_corpus(seed: int, samples_per_class: int) -> tuple[np.ndarray, np.ndarray]:
    """Build overlapping normal, uncertain and injected-fault examples."""

    rng = np.random.default_rng(seed)
    trusted = _bounded_normal(
        rng,
        samples_per_class,
        [88, 5, 4, 500, 25, 0, 0, 0, 120, 96],
        [7, 4, 3, 70, 22, 0.25, 0.15, 0.18, 90, 4],
    )
    uncertain = _bounded_normal(
        rng,
        samples_per_class,
        [69, 20, 17, 650, 130, 1, 0.5, 0.8, 520, 72],
        [12, 11, 10, 190, 90, 0.9, 0.7, 0.9, 180, 13],
    )
    anomalous = _bounded_normal(
        rng,
        samples_per_class,
        [45, 48, 42, 1150, 420, 5, 4, 5, 1100, 38],
        [21, 23, 22, 380, 230, 3.5, 3.2, 3.4, 390, 20],
    )

    # Make every anomalous sample contain at least one explicit fail-closed sign.
    selectors = rng.integers(0, 5, size=samples_per_class)
    for row, selector in enumerate(selectors):
        if selector == 0:
            anomalous[row, 8] = rng.uniform(760, 2000)  # stale vision
        elif selector == 1:
            anomalous[row, 6] = rng.uniform(1, 20)  # invalid frames
        elif selector == 2:
            anomalous[row, 5] = rng.uniform(3, 20)  # forward gaps
        elif selector == 3:
            anomalous[row, 9] = rng.uniform(0, 45)  # poor valid ratio
        else:
            anomalous[row, 3] = rng.uniform(1200, 2000)  # arrival timeout trend

    features = np.vstack((trusted, uncertain, anomalous))
    labels = np.concatenate(
        (
            np.zeros(samples_per_class, dtype=np.int64),
            np.ones(samples_per_class, dtype=np.int64),
            np.full(samples_per_class, 2, dtype=np.int64),
        )
    )
    return features, labels


def normalize_features(features: np.ndarray) -> np.ndarray:
    clipped = np.clip(features, FEATURE_MIN, FEATURE_MAX)
    return ((clipped - FEATURE_MIN) / (FEATURE_MAX - FEATURE_MIN)) * 2.0 - 1.0


def train_model(seed: int = 20260827, samples_per_class: int = 3000):
    features, labels = build_synthetic_corpus(seed, samples_per_class)
    train_x, test_x, train_y, test_y = train_test_split(
        normalize_features(features),
        labels,
        test_size=0.25,
        random_state=seed,
        stratify=labels,
    )
    model = MLPClassifier(
        hidden_layer_sizes=(12,),
        activation="relu",
        solver="lbfgs",
        alpha=0.002,
        max_iter=1000,
        random_state=seed,
    )
    model.fit(train_x, train_y)
    predicted = model.predict(test_x)
    metrics = {
        "schema": "amazinghand.titantrust.training",
        "schema_version": 1,
        "seed": seed,
        "corpus": "deterministic_synthetic_fault_injection",
        "samples_total": int(len(features)),
        "samples_test": int(len(test_y)),
        "accuracy_synthetic_holdout": float(accuracy_score(test_y, predicted)),
        "confusion_matrix": confusion_matrix(test_y, predicted).tolist(),
        "classes": list(CLASS_NAMES),
        "features": list(FEATURE_NAMES),
        "field_accuracy_validated": False,
        "hardware_inference_validated": False,
        "controls_servo": False,
    }
    return model, metrics


def _c_float(value: float) -> str:
    rendered = f"{float(value):.9g}"
    if "." not in rendered and "e" not in rendered.lower():
        rendered += ".0"
    return rendered + "f"


def _c_array_1d(name: str, values: np.ndarray) -> str:
    body = ", ".join(_c_float(value) for value in values)
    return f"static const float {name}[{values.size}] = {{{body}}};\n"


def _c_array_2d(name: str, values: np.ndarray) -> str:
    rows = []
    for row in values:
        rows.append("    {" + ", ".join(_c_float(value) for value in row) + "}")
    return (
        f"static const float {name}[{values.shape[0]}][{values.shape[1]}] = {{\n"
        + ",\n".join(rows)
        + "\n};\n"
    )


def export_c(model: MLPClassifier, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    hidden_weights = np.asarray(model.coefs_[0], dtype=np.float64)
    output_weights = np.asarray(model.coefs_[1], dtype=np.float64)
    hidden_bias = np.asarray(model.intercepts_[0], dtype=np.float64)
    output_bias = np.asarray(model.intercepts_[1], dtype=np.float64)

    header = """#ifndef TITAN_TRUST_MODEL_H
#define TITAN_TRUST_MODEL_H

#include <stdint.h>

#ifdef __cplusplus
extern \"C\" {
#endif

#define TITAN_TRUST_FEATURE_COUNT 10
#define TITAN_TRUST_CLASS_COUNT 3

typedef enum
{
    TITAN_TRUST_TRUSTED = 0,
    TITAN_TRUST_UNCERTAIN = 1,
    TITAN_TRUST_ANOMALOUS = 2
} titan_trust_class_t;

/*
 * Advisory inference only. It never authorizes motion.
 * Invalid/non-finite input fails closed to TITAN_TRUST_ANOMALOUS.
 */
titan_trust_class_t titan_trust_predict(
    const float features[TITAN_TRUST_FEATURE_COUNT],
    float logits[TITAN_TRUST_CLASS_COUNT]);

const char *titan_trust_class_name(titan_trust_class_t value);

#ifdef __cplusplus
}
#endif

#endif
"""

    source = """#include \"titan_trust_model.h\"

#include <math.h>
#include <stddef.h>

#define TITAN_TRUST_HIDDEN_COUNT 12

"""
    source += _c_array_1d("g_feature_min", FEATURE_MIN)
    source += _c_array_1d("g_feature_max", FEATURE_MAX)
    source += _c_array_2d("g_hidden_weights", hidden_weights)
    source += _c_array_1d("g_hidden_bias", hidden_bias)
    source += _c_array_2d("g_output_weights", output_weights)
    source += _c_array_1d("g_output_bias", output_bias)
    source += """

static float clamp_value(float value, float minimum, float maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

titan_trust_class_t titan_trust_predict(
    const float features[TITAN_TRUST_FEATURE_COUNT],
    float logits[TITAN_TRUST_CLASS_COUNT])
{
    float normalized[TITAN_TRUST_FEATURE_COUNT];
    float hidden[TITAN_TRUST_HIDDEN_COUNT];
    float local_logits[TITAN_TRUST_CLASS_COUNT];
    size_t input_index;
    size_t hidden_index;
    size_t output_index;
    size_t best_index = TITAN_TRUST_ANOMALOUS;

    if (features == NULL)
    {
        return TITAN_TRUST_ANOMALOUS;
    }
    for (input_index = 0; input_index < TITAN_TRUST_FEATURE_COUNT; ++input_index)
    {
        float value = features[input_index];
        if (!isfinite(value))
        {
            return TITAN_TRUST_ANOMALOUS;
        }
        value = clamp_value(value, g_feature_min[input_index], g_feature_max[input_index]);
        normalized[input_index] =
            ((value - g_feature_min[input_index]) /
             (g_feature_max[input_index] - g_feature_min[input_index])) * 2.0f - 1.0f;
    }

    for (hidden_index = 0; hidden_index < TITAN_TRUST_HIDDEN_COUNT; ++hidden_index)
    {
        float value = g_hidden_bias[hidden_index];
        for (input_index = 0; input_index < TITAN_TRUST_FEATURE_COUNT; ++input_index)
        {
            value += normalized[input_index] * g_hidden_weights[input_index][hidden_index];
        }
        hidden[hidden_index] = value > 0.0f ? value : 0.0f;
    }

    for (output_index = 0; output_index < TITAN_TRUST_CLASS_COUNT; ++output_index)
    {
        float value = g_output_bias[output_index];
        for (hidden_index = 0; hidden_index < TITAN_TRUST_HIDDEN_COUNT; ++hidden_index)
        {
            value += hidden[hidden_index] * g_output_weights[hidden_index][output_index];
        }
        local_logits[output_index] = value;
        if (logits != NULL) logits[output_index] = value;
    }

    best_index = 0;
    for (output_index = 1; output_index < TITAN_TRUST_CLASS_COUNT; ++output_index)
    {
        if (local_logits[output_index] > local_logits[best_index])
        {
            best_index = output_index;
        }
    }
    return (titan_trust_class_t)best_index;
}

const char *titan_trust_class_name(titan_trust_class_t value)
{
    switch (value)
    {
    case TITAN_TRUST_TRUSTED: return \"TRUSTED\";
    case TITAN_TRUST_UNCERTAIN: return \"UNCERTAIN\";
    case TITAN_TRUST_ANOMALOUS: return \"ANOMALOUS\";
    default: return \"UNKNOWN\";
    }
}
"""
    (output_dir / "titan_trust_model.h").write_text(header, encoding="utf-8", newline="\n")
    (output_dir / "titan_trust_model.c").write_text(source, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260827)
    parser.add_argument("--samples-per-class", type=int, default=3000)
    args = parser.parse_args()

    model, metrics = train_model(args.seed, args.samples_per_class)
    export_c(model, args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "training_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
