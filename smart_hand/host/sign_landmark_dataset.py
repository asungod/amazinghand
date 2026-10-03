"""Offline JSONL dataset tooling for OpenSignHand landmark samples.

The format stores anonymous participant/session codes and 2-D or flat 3-D
landmarks only.  This module never opens a camera and never imports Maix
runtime code, so collection scripts can validate/append records on a host
computer or in an offline CI job.

The four labels are deliberately basic hand-shape prototypes.  They are not
translations of formal Chinese sign-language words.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path


SCHEMA = "opensignhand.landmark.v1"
SCHEMA_VERSION = SCHEMA
SUPPORTED_GESTURES = (
    "OPEN_PALM", "FIST", "V_SIGN", "POINT", "THUMBS_UP",
    "L_SHAPE", "OK_PINCH", "UNKNOWN"
)
REQUIRED_FIELDS = (
    "schema",
    "participant_id",
    "session_id",
    "gesture_id",
    "timestamp_ms",
    "landmarks",
    "source",
    "license",
    "consent",
)
LANDMARK_POINT_COUNT = 21
LANDMARK_FLAT_COUNT = LANDMARK_POINT_COUNT * 3
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_FORBIDDEN_FIELDS = frozenset(
    (
        "name",
        "real_name",
        "fullname",
        "phone",
        "mobile",
        "telephone",
        "email",
        "id_card",
        "address",
        "姓名",
        "真实姓名",
        "手机号",
        "电话",
        "邮箱",
        "身份证",
        "住址",
    )
)
_FALSE_CONSENT = frozenset(("", "0", "false", "no", "none", "denied", "拒绝"))


class DatasetError(ValueError):
    """Raised for missing, malformed, or unsafe dataset input."""


class SampleValidationError(DatasetError):
    """Raised when one JSONL object does not meet the public schema."""


def _location(line_number):
    return "line {}: ".format(line_number) if line_number is not None else ""


def _fail(message, line_number=None):
    raise SampleValidationError(_location(line_number) + message)


def _is_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return not (math.isnan(float(value)) or math.isinf(float(value)))
    except (TypeError, ValueError, OverflowError):
        return False


def _safe_identifier(value, field_name, line_number=None):
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        _fail(
            "{} must be an anonymous code matching {}".format(
                field_name, _SAFE_ID.pattern
            ),
            line_number,
        )
    # Explicitly reject common direct identifiers even if a future regex is
    # relaxed.  The format intentionally carries no names, phones, or emails.
    if "@" in value or any(character.isspace() for character in value):
        _fail("{} must not contain contact information".format(field_name), line_number)
    return value


def _landmarks(value, line_number=None):
    if not isinstance(value, (list, tuple)):
        _fail("landmarks must be a list", line_number)
    if len(value) == LANDMARK_POINT_COUNT:
        points = []
        for index, point in enumerate(value):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                _fail("landmarks[{}] must contain exactly x,y".format(index), line_number)
            if not (_is_number(point[0]) and _is_number(point[1])):
                _fail("landmarks[{}] coordinates must be finite numbers".format(index), line_number)
            points.append([float(point[0]), float(point[1])])
        return points
    if len(value) == LANDMARK_FLAT_COUNT:
        flat = []
        for index, coordinate in enumerate(value):
            if not _is_number(coordinate):
                _fail("landmarks[{}] must be a finite number".format(index), line_number)
            flat.append(float(coordinate))
        return flat
    _fail(
        "landmarks must be 21x2 pairs or 63 flat xyz values (got {})".format(
            len(value)
        ),
        line_number,
    )


def _required_text(value, field_name, line_number=None):
    if not isinstance(value, str) or not value.strip():
        _fail("{} must be a non-empty string".format(field_name), line_number)
    return value.strip()


def _consent(value, line_number=None):
    # Keep this deliberately strict.  Free-form strings such as "recorded" or
    # "ok" are not auditable proof that a participant explicitly agreed.
    if value is not True:
        _fail("consent must be the JSON boolean true", line_number)
    return True


def _forbidden_top_level_fields(sample, line_number=None):
    for key in sample:
        if not isinstance(key, str):
            _fail("all field names must be strings", line_number)
        normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in _FORBIDDEN_FIELDS or key in _FORBIDDEN_FIELDS:
            _fail("personal field {} is not allowed".format(key), line_number)


def validate_sample(sample, line_number=None):
    """Validate and return a JSON-safe copy of one sample object.

    Extra fields are preserved for future annotations, except direct personal
    identifiers.  Required fields stay stable so old collectors remain
    readable by later tooling.
    """
    if not isinstance(sample, dict):
        _fail("sample must be a JSON object", line_number)
    _forbidden_top_level_fields(sample, line_number)
    missing = [field for field in REQUIRED_FIELDS if field not in sample]
    if missing:
        _fail("missing required fields: {}".format(", ".join(missing)), line_number)
    if sample.get("schema") != SCHEMA:
        _fail("schema must be {}".format(SCHEMA), line_number)

    participant_id = _safe_identifier(sample["participant_id"], "participant_id", line_number)
    session_id = _safe_identifier(sample["session_id"], "session_id", line_number)
    gesture_id = sample["gesture_id"]
    if gesture_id not in SUPPORTED_GESTURES:
        _fail(
            "gesture_id must be one of {}".format(", ".join(SUPPORTED_GESTURES)),
            line_number,
        )
    timestamp_ms = sample["timestamp_ms"]
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        _fail("timestamp_ms must be a non-negative integer", line_number)
    if timestamp_ms < 0:
        _fail("timestamp_ms must be a non-negative integer", line_number)

    landmarks = _landmarks(sample["landmarks"], line_number)
    source = _required_text(sample["source"], "source", line_number)
    license_name = _required_text(sample["license"], "license", line_number)
    consent = _consent(sample["consent"], line_number)

    normalized = dict(sample)
    normalized.update(
        {
            "schema": SCHEMA,
            "participant_id": participant_id,
            "session_id": session_id,
            "gesture_id": gesture_id,
            "timestamp_ms": timestamp_ms,
            "landmarks": landmarks,
            "source": source,
            "license": license_name,
            "consent": consent,
        }
    )
    return normalized


def _canonical_sample(sample):
    """Order required fields first for stable diffs and reproducible logs."""
    ordered = {}
    for field in REQUIRED_FIELDS:
        ordered[field] = sample[field]
    for field in sorted(sample):
        if field not in ordered:
            ordered[field] = sample[field]
    return ordered


def validate_jsonl(path):
    """Return a validation report without fabricating records or metrics."""
    path = Path(path)
    report = {"ok": False, "path": str(path), "sample_count": 0, "samples": [], "errors": []}
    if not path.is_file():
        report["errors"].append({"line": 0, "error": "file does not exist"})
        return report
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    sample = json.loads(line)
                    report["samples"].append(validate_sample(sample, line_number))
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    report["errors"].append({"line": line_number, "error": str(exc)})
    except (OSError, UnicodeError) as exc:
        report["errors"].append({"line": 0, "error": str(exc)})
        return report
    report["sample_count"] = len(report["samples"])
    report["ok"] = bool(report["sample_count"] > 0 and not report["errors"])
    if report["sample_count"] == 0 and not report["errors"]:
        report["errors"].append({"line": 0, "error": "dataset contains no samples"})
    return report


def load_samples(path):
    """Load a non-empty, fully valid JSONL dataset or raise clearly."""
    report = validate_jsonl(path)
    if not report["ok"]:
        details = "; ".join(
            "line {}: {}".format(item["line"], item["error"])
            for item in report["errors"][:3]
        )
        raise DatasetError("invalid sign landmark dataset: {}".format(details))
    return report["samples"]


def append_sample(path, sample):
    """Validate then append exactly one JSONL object; never touches cameras."""
    normalized = validate_sample(sample)
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        existing = validate_jsonl(path)
        if not existing["ok"]:
            raise DatasetError("refusing to append to invalid dataset")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(_canonical_sample(normalized), ensure_ascii=False, sort_keys=False))
        stream.write("\n")
    return normalized


def summarize_samples(samples):
    """Return deterministic counts for validated samples."""
    if not samples:
        raise DatasetError("cannot summarize an empty dataset")
    participants = Counter(sample["participant_id"] for sample in samples)
    sessions = Counter(
        (sample["participant_id"], sample["session_id"]) for sample in samples
    )
    gestures = Counter(sample["gesture_id"] for sample in samples)
    sources = Counter(sample["source"] for sample in samples)
    return {
        "schema": SCHEMA,
        "sample_count": len(samples),
        "participant_count": len(participants),
        "session_count": len(sessions),
        "participants": dict(sorted(participants.items())),
        "gestures": {
            gesture: gestures.get(gesture, 0) for gesture in SUPPORTED_GESTURES
        },
        "sources": dict(sorted(sources.items())),
        "timestamp_min_ms": min(sample["timestamp_ms"] for sample in samples),
        "timestamp_max_ms": max(sample["timestamp_ms"] for sample in samples),
    }


def summary_jsonl(path):
    return summarize_samples(load_samples(path))


def _read_sample_argument(args):
    if bool(args.sample_json) == bool(args.sample_file):
        raise DatasetError("choose exactly one of --sample-json or --sample-file")
    if args.sample_json:
        try:
            return json.loads(args.sample_json)
        except json.JSONDecodeError as exc:
            raise DatasetError("--sample-json is not valid JSON: {}".format(exc))
    try:
        with Path(args.sample_file).open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError("cannot read sample file: {}".format(exc))


def _parser():
    parser = argparse.ArgumentParser(
        description="Validate, append, and summarize OpenSignHand landmark JSONL offline."
    )
    subparsers = parser.add_subparsers(dest="command")

    validate_parser = subparsers.add_parser("validate", help="validate every JSONL sample")
    validate_parser.add_argument("dataset", type=Path)

    append_parser = subparsers.add_parser("append", help="validate and append one JSON object")
    append_parser.add_argument("dataset", type=Path)
    group = append_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sample-json")
    group.add_argument("--sample-file", type=Path)

    summary_parser = subparsers.add_parser("summary", help="summarize a valid dataset")
    summary_parser.add_argument("dataset", type=Path)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            report = validate_jsonl(args.dataset)
            public_report = {
                "ok": report["ok"],
                "path": report["path"],
                "sample_count": report["sample_count"],
                "errors": report["errors"],
            }
            print(json.dumps(public_report, ensure_ascii=False, sort_keys=True))
            return 0 if report["ok"] else 1
        if args.command == "append":
            sample = _read_sample_argument(args)
            append_sample(args.dataset, sample)
            print(json.dumps({"ok": True, "path": str(args.dataset)}, ensure_ascii=False))
            return 0
        if args.command == "summary":
            print(json.dumps(summary_jsonl(args.dataset), ensure_ascii=False, sort_keys=True))
            return 0
        _parser().print_help(sys.stderr)
        return 2
    except (DatasetError, OSError, TypeError, ValueError) as exc:
        print("Sign landmark dataset failed: {}".format(exc), file=sys.stderr)
        return 1


# Friendly names for host tests and small collection scripts.
parse_sample = validate_sample
validate_file = validate_jsonl
load_jsonl = load_samples


if __name__ == "__main__":
    raise SystemExit(main())
