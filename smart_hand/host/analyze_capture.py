"""Read-only same-frame replay of local captures, NOT an accuracy evaluator.

No camera, communications, network or model API is opened. Records stay local.
Sparse saved frames cannot reproduce stability from the full camera stream.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "smart_hand/maixcam2"))
sys.path.insert(0, str(ROOT / "smart_hand/host"))

import gesture_classifier
import gesture_features
from sign_landmark_dataset import load_samples


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def same(actual, recorded):
    if isinstance(actual, (list, tuple)):
        return (isinstance(recorded, (list, tuple))
                and len(actual) == len(recorded)
                and all(same(a, b) for a, b in zip(actual, recorded)))
    if isinstance(actual, bool):
        return isinstance(recorded, bool) and actual == recorded
    if isinstance(actual, (float, int)):
        return (isinstance(recorded, (float, int)) and not isinstance(recorded, bool)
                and math.isclose(actual, recorded, rel_tol=0.0, abs_tol=1e-9))
    return actual == recorded


def analyze_rows(samples):
    rows = []
    hashes = {
        "classifier": digest(gesture_classifier.__file__),
        "features": digest(gesture_features.__file__),
    }
    for record in samples:
        raw = record["landmarks"]
        result = gesture_classifier.classify_gesture(raw)
        try:
            features = gesture_features.extract_gesture_features(raw)
        except (TypeError, ValueError, OverflowError):
            features = {}
        checks = {
            "predicted_gesture_id": result.gesture_id,
            "confidence": result.confidence,
            "valid": result.valid,
            "error_code": result.error_code,
            "finger_extension": features.get("finger_extension"),
            "joint_angles_deg": features.get("joint_angles_deg"),
            "thumb_angle_deg": features.get("thumb_angle_deg"),
            "thumb_tip_distance": features.get("thumb_tip_distance"),
            "thumb_extension": result.get("thumb_extension"),
            "tip_gap": result.get("tip_gap"),
            "thumb_index_gap": result.get("thumb_index_gap"),
        }
        # Only newer captures carry corrected rule extension; retain legacy
        # replay compatibility without silently ignoring a present field.
        if "rule_finger_extension" in record:
            checks["rule_finger_extension"] = result.get("finger_extension")
        mismatches = [key for key, value in checks.items()
                      if key not in record or not same(value, record[key])]
        if record.get("prediction_timestamp_ms") != record["timestamp_ms"]:
            mismatches.append("prediction_timestamp_ms")
        runtime = record.get("runtime_version") or {}
        source_matches = {
            name: (runtime.get(name) or {}).get("sha256") == value
            for name, value in hashes.items()
        }
        detector = runtime.get("landmark_detector") or {}
        roi_transform_validated = None
        local = record.get("roi_raw_landmarks")
        if local is not None:
            rect = detector.get("crop_rect")
            roi_transform_validated = False
            if (isinstance(local, (list, tuple)) and len(local) == 63
                    and isinstance(rect, (list, tuple)) and len(rect) == 4
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                            and math.isfinite(v) for v in rect)):
                expected = []
                for i in range(0, 63, 3):
                    try:
                        expected.extend((local[i] + rect[0], local[i+1] + rect[1], local[i+2]))
                    except TypeError:
                        break
                roi_transform_validated = len(expected) == 63 and same(expected, raw)
            if not roi_transform_validated:
                mismatches.append("roi_to_camera_transform")
        width, height = detector.get("camera_width"), detector.get("camera_height")
        xy = gesture_features.coerce_landmarks(raw)
        outside = None
        edge_distance = None
        if (isinstance(width, (float, int)) and not isinstance(width, bool)
                and isinstance(height, (float, int)) and not isinstance(height, bool)
                and width > 0 and height > 0):
            outside = sum(not (0 <= x < width and 0 <= y < height) for x, y in xy)
            edge_distance = min(min(x, y, width - 1 - x, height - 1 - y) for x, y in xy)
        rows.append({
            "sample_id": record.get("sample_id"),
            "frame_index": record.get("frame_index"),
            "sequence_id": record.get("sequence_id"),
            "target_annotation": record["gesture_id"],
            "device_prediction": record.get("predicted_gesture_id"),
            "host_prediction": result.gesture_id,
            "device_score": record.get("confidence"),
            "single_frame_replay_matches": not mismatches,
            "mismatched_fields": mismatches,
            "source_hash_matches": source_matches,
            "roi_to_camera_transform_validated": roi_transform_validated,
            "finger_extension": features.get("finger_extension"),
            "joint_angles_deg": features.get("joint_angles_deg"),
            "thumb_extension": result.get("thumb_extension"),
            "tip_gap": result.get("tip_gap"),
            "outside_image_xy_count": outside,
            "min_image_edge_distance_px": edge_distance,
            "recorded_stable_ms": record.get("stable_ms"),
            "temporal_replay_performed": False,
        })
    return {
        "schema": "opensignhand.capture_analysis.v1",
        "sample_count": len(rows),
        "sequence_count": len({row["sequence_id"] for row in rows}),
        "recorded_prediction_counts": dict(Counter(row["device_prediction"] for row in rows)),
        "single_frame_replay_match_count": sum(row["single_frame_replay_matches"] for row in rows),
        "current_source_sha256": hashes,
        "not_an_accuracy_estimate": True,
        "target_is_user_annotation_not_verified_ground_truth": True,
        "temporal_replay_performed": False,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze_rows(load_samples(args.input))
    report["input_sha256"] = digest(args.input)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        # Exclusive create: never silently overwrite evidence or the input.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
