"""Standalone MaixCAM2 collector for anonymous OpenSignHand landmarks.

This file is intentionally independent from ``main.py``.  It opens only the
camera, hand-landmark model, and optional display/touchscreen objects.  It
does not import or configure any communication, Titan, or servo code.

The validation and JSONL helpers at the top of the file use only the Python
standard library so they can be tested on a host without a Maix runtime.  The
Maix imports stay inside :func:`main`, which also makes a missing model or a
cancelled run fail closed before any record is written.
"""

import json
import math
import os
import re


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

MODEL_PATH = "/root/models/hand_landmarks.mud"
OUTPUT_PATH = "/root/opensignhand_landmarks.jsonl"
DEFAULT_MODEL_PATH = MODEL_PATH
DEFAULT_OUTPUT_PATH = OUTPUT_PATH
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 224
DETECT_CONFIDENCE = 0.7
IOU_THRESHOLD = 0.45
LANDMARK_CONFIDENCE = 0.8
# Capture-only threshold probes, never used by the control application.
DETECTION_DIAGNOSTIC = True
ROI_RETRY = True  # Fresh current-frame center crop, never cached predictions.
SAVE_HAND_EVIDENCE = True  # Local same-frame hand crops; no network upload.
MAX_EVIDENCE_BYTES = 256 * 1024

# Right-hand L after stable right-hand V verification (2026-10-03).
# Exported reusable kit: opt in explicitly before collecting new human data.
# No prior participant consent is transferred by this code snapshot.
PARTICIPANT_ID = "P01"
SESSION_ID = "S01-L-IMAGE01"
GESTURE_ID = "L_SHAPE"
CONSENT = False
TARGET_SAMPLES = 7  # 0, 500, ... 3000 ms: roughly one three-second pose.
CAPTURE_INTERVAL_MS = 500
COUNTDOWN_SECONDS = 3
MAX_CAPTURE_MS = 5000  # Bound a missing-hand run; never wait indefinitely.
HAND_SIDE = "right"  # This run only; earlier left-hand records remain unchanged.
VIEW = "front"  # "front" or "slight_side"; not measured angles.
SOURCE = "maixcam2_local_capture"
# Human-derived landmark data is not software.  Keep new local captures
# non-redistributable until the participant has separately agreed to a clear
# public-data licence; Apache-2.0 remains the licence for project source code.
LICENSE = "internal-research-only; no redistribution"

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


class CaptureError(ValueError):
    """Raised for invalid collection configuration or landmark records."""


class CaptureConfig:
    """Small dependency-free configuration object for one collection run."""

    def __init__(
        self,
        participant_id=PARTICIPANT_ID,
        session_id=SESSION_ID,
        gesture_id=GESTURE_ID,
        consent=CONSENT,
        target_samples=TARGET_SAMPLES,
        capture_interval_ms=CAPTURE_INTERVAL_MS,
        countdown_seconds=COUNTDOWN_SECONDS,
        output_path=OUTPUT_PATH,
        model_path=MODEL_PATH,
        source=SOURCE,
        license_name=LICENSE,
        max_capture_ms=MAX_CAPTURE_MS,
        hand_side=HAND_SIDE,
        view=VIEW,
    ):
        self.participant_id = participant_id
        self.session_id = session_id
        self.gesture_id = gesture_id
        self.consent = consent
        self.target_samples = target_samples
        self.capture_interval_ms = capture_interval_ms
        self.countdown_seconds = countdown_seconds
        self.output_path = output_path
        self.model_path = model_path
        self.source = source
        self.license = license_name
        self.max_capture_ms = max_capture_ms
        self.hand_side = hand_side
        self.view = view

    def as_dict(self):
        return {
            "participant_id": self.participant_id,
            "session_id": self.session_id,
            "gesture_id": self.gesture_id,
            "consent": self.consent,
            "target_samples": self.target_samples,
            "capture_interval_ms": self.capture_interval_ms,
            "countdown_seconds": self.countdown_seconds,
            "output_path": self.output_path,
            "model_path": self.model_path,
            "source": self.source,
            "license": self.license,
            "max_capture_ms": self.max_capture_ms,
            "hand_side": self.hand_side,
            "view": self.view,
        }


def _config_value(config, name, default=None):
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def _safe_identifier(value, field_name):
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise CaptureError(
            "{} must be an anonymous code matching {}".format(
                field_name, _SAFE_ID.pattern
            )
        )
    if "@" in value or any(character.isspace() for character in value):
        raise CaptureError("{} must not contain contact information".format(field_name))
    if re.match(r"^1[3-9][0-9]{9}$", value):
        raise CaptureError("{} must be an anonymous code, not a phone number".format(field_name))
    return value


def _required_text(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise CaptureError("{} must be a non-empty string".format(field_name))
    return value.strip()


def _finite_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CaptureError("{} must be a finite number".format(field_name))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise CaptureError("{} must be a finite number".format(field_name))
    if math.isnan(number) or math.isinf(number):
        raise CaptureError("{} must be a finite number".format(field_name))
    return number


def normalize_landmarks(raw_landmarks):
    """Validate and return one JSON-safe 21-point landmark representation.

    The detector supplies 63 flat x/y/z values.  Offline fixtures may use the
    host schema's 21 nested x/y pairs; both forms are preserved so the output
    remains directly consumable by ``host/sign_landmark_dataset.py``.
    """

    if not isinstance(raw_landmarks, (list, tuple)):
        raise CaptureError("landmarks must be a list or tuple")
    if len(raw_landmarks) == LANDMARK_POINT_COUNT:
        points = []
        for index, point in enumerate(raw_landmarks):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise CaptureError("landmarks[{}] must contain exactly x,y".format(index))
            points.append(
                [
                    _finite_number(point[0], "landmarks[{}].x".format(index)),
                    _finite_number(point[1], "landmarks[{}].y".format(index)),
                ]
            )
        return points
    if len(raw_landmarks) == LANDMARK_FLAT_COUNT:
        return [
            _finite_number(value, "landmarks[{}]".format(index))
            for index, value in enumerate(raw_landmarks)
        ]
    raise CaptureError(
        "landmarks must be 21x2 pairs or 63 flat xyz values (got {})".format(
            len(raw_landmarks)
        )
    )


def extract_hand_landmarks(hand):
    """Extract the detector's standard 21-point slice from one hand object."""

    points = getattr(hand, "points", hand)
    if not isinstance(points, (list, tuple)):
        raise CaptureError("hand points must be a list or tuple")
    if len(points) >= 8 + LANDMARK_FLAT_COUNT:
        points = points[8 : 8 + LANDMARK_FLAT_COUNT]
    return normalize_landmarks(points)


# Friendly aliases make this small script convenient for offline tests and
# keep the detector-specific naming out of data construction code.
coerce_landmarks = normalize_landmarks
extract_landmarks = extract_hand_landmarks


def validate_config(config):
    """Validate and return a normalized :class:`CaptureConfig`.

    Consent is intentionally stricter than the host reader: only the JSON/
    Python boolean ``True`` authorizes a real camera run.  Strings such as
    ``"true"`` or ``"recorded_with_consent"`` are rejected here.
    """

    if config is None:
        config = CaptureConfig()
    participant_id = _safe_identifier(
        _config_value(config, "participant_id"), "participant_id"
    )
    session_id = _safe_identifier(_config_value(config, "session_id"), "session_id")
    gesture_id = _config_value(config, "gesture_id")
    if gesture_id not in SUPPORTED_GESTURES:
        raise CaptureError(
            "gesture_id must be one of {}".format(", ".join(SUPPORTED_GESTURES))
        )
    if _config_value(config, "consent") is not True:
        raise CaptureError("consent must be the boolean True before capture can run")

    target_samples = _config_value(config, "target_samples")
    if isinstance(target_samples, bool) or not isinstance(target_samples, int):
        raise CaptureError("target_samples must be a positive integer")
    if target_samples <= 0:
        raise CaptureError("target_samples must be a positive integer")

    capture_interval_ms = _config_value(config, "capture_interval_ms")
    if isinstance(capture_interval_ms, bool) or not isinstance(capture_interval_ms, int):
        raise CaptureError("capture_interval_ms must be a positive integer")
    if capture_interval_ms <= 0:
        raise CaptureError("capture_interval_ms must be a positive integer")

    countdown_seconds = _config_value(config, "countdown_seconds")
    if isinstance(countdown_seconds, bool) or not isinstance(countdown_seconds, int):
        raise CaptureError("countdown_seconds must be a non-negative integer")
    if countdown_seconds < 0:
        raise CaptureError("countdown_seconds must be a non-negative integer")

    max_capture_ms = _config_value(config, "max_capture_ms", MAX_CAPTURE_MS)
    if (isinstance(max_capture_ms, bool) or not isinstance(max_capture_ms, int)
            or max_capture_ms <= 0):
        raise CaptureError("max_capture_ms must be a positive integer")
    hand_side = _config_value(config, "hand_side", HAND_SIDE)
    if hand_side not in ("left", "right", "unknown"):
        raise CaptureError("hand_side must be left, right or unknown")
    view = _config_value(config, "view", VIEW)
    if view not in ("front", "slight_side", "unspecified"):
        raise CaptureError("view must be front, slight_side or unspecified")

    output_value = _config_value(config, "output_path")
    try:
        output_value = os.fspath(output_value)
    except (AttributeError, TypeError):
        pass
    output_path = _required_text(output_value, "output_path")
    model_path = _required_text(_config_value(config, "model_path"), "model_path")
    source = _required_text(_config_value(config, "source"), "source")
    license_name = _required_text(_config_value(config, "license"), "license")
    return CaptureConfig(
        participant_id=participant_id,
        session_id=session_id,
        gesture_id=gesture_id,
        consent=True,
        target_samples=target_samples,
        capture_interval_ms=capture_interval_ms,
        countdown_seconds=countdown_seconds,
        output_path=output_path,
        model_path=model_path,
        source=source,
        license_name=license_name,
        max_capture_ms=max_capture_ms,
        hand_side=hand_side,
        view=view,
    )


validate_capture_config = validate_config


def _forbidden_top_level_fields(sample):
    for key in sample:
        if not isinstance(key, str):
            raise CaptureError("all field names must be strings")
        normalized = key.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in _FORBIDDEN_FIELDS or key in _FORBIDDEN_FIELDS:
            raise CaptureError("personal field {} is not allowed".format(key))


def validate_sample(sample):
    """Validate and return one record using the host dataset schema."""

    if not isinstance(sample, dict):
        raise CaptureError("sample must be a JSON object")
    _forbidden_top_level_fields(sample)
    missing = [field for field in REQUIRED_FIELDS if field not in sample]
    if missing:
        raise CaptureError("missing required fields: {}".format(", ".join(missing)))
    if sample.get("schema") != SCHEMA:
        raise CaptureError("schema must be {}".format(SCHEMA))
    participant_id = _safe_identifier(sample["participant_id"], "participant_id")
    session_id = _safe_identifier(sample["session_id"], "session_id")
    if sample["gesture_id"] not in SUPPORTED_GESTURES:
        raise CaptureError(
            "gesture_id must be one of {}".format(", ".join(SUPPORTED_GESTURES))
        )
    timestamp_ms = sample["timestamp_ms"]
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise CaptureError("timestamp_ms must be a non-negative integer")
    if timestamp_ms < 0:
        raise CaptureError("timestamp_ms must be a non-negative integer")
    landmarks = normalize_landmarks(sample["landmarks"])
    source = _required_text(sample["source"], "source")
    license_name = _required_text(sample["license"], "license")
    if sample["consent"] is not True:
        raise CaptureError("consent must be the boolean True")

    normalized = dict(sample)
    normalized.update(
        {
            "schema": SCHEMA,
            "participant_id": participant_id,
            "session_id": session_id,
            "gesture_id": sample["gesture_id"],
            "timestamp_ms": timestamp_ms,
            "landmarks": landmarks,
            "source": source,
            "license": license_name,
            "consent": True,
        }
    )
    return normalized


parse_sample = validate_sample
validate_record = validate_sample


def build_sample(
    participant_id,
    session_id,
    gesture_id,
    landmarks,
    timestamp_ms=0,
    consent=False,
    source=SOURCE,
    license_name=LICENSE,
):
    """Build and validate one schema-compatible, anonymous JSONL record."""

    sample = {
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
    return validate_sample(sample)


make_sample = build_sample
build_record = build_sample


def _source_fingerprint(module):
    """Hash the locally imported source, never a presumed deployment version."""
    return _file_fingerprint(getattr(module, "__file__", None))


def _file_fingerprint(path):
    result = {"path": path, "sha256": None, "status": "unavailable"}
    if not path:
        return result
    try:
        import hashlib

        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            while True:
                block = stream.read(8192)
                if not block:
                    break
                digest.update(block)
        result.update(sha256=digest.hexdigest(), status="source_file_hashed")
    except (ImportError, AttributeError, OSError):
        # Missing hashing support is not permission to invent a version.
        pass
    return result


class CaptureDiagnostics:
    """Local rule prediction per camera frame, independent of the live app.

    This is not main.py's running prediction, a learned-model prediction,
    or evidence that the device's main application has been upgraded.
    """

    def __init__(self):
        try:
            import gesture_classifier as classifier_module
            import gesture_features as features_module
        except ImportError:
            from . import gesture_classifier as classifier_module
            from . import gesture_features as features_module
        self.classifier = classifier_module.GestureClassifier()
        self.extract_features = features_module.extract_gesture_features
        # Compute once, not in the camera loop. Files must not be edited
        # during this run; hashes describe on-disk sources at startup.
        self.runtime_version = {
            "kind": "source_files_at_capture_start",
            "classifier": _source_fingerprint(classifier_module),
            "features": _source_fingerprint(features_module),
            "collector": _file_fingerprint(globals().get("__file__")),
            "confidence_threshold": self.classifier.confidence_threshold,
            "stable_hold_ms": self.classifier.stable_hold_ms,
        }

    def observe(self, landmarks, elapsed_ms):
        """Evaluate exactly this frame, including every missing-hand frame."""
        result = self.classifier.observe(
            landmarks, now_ms=elapsed_ms, hand_present=landmarks is not None
        )
        features = None
        feature_error = None
        if landmarks is not None:
            try:
                features = self.extract_features(landmarks)
            except (TypeError, ValueError, OverflowError) as exc:
                feature_error = str(exc)
        return {
            "predicted_gesture_id": result.gesture_id,
            "prediction_origin": "standalone_rule_capture",
            "confidence": result.confidence,
            "error_code": result.error_code,
            "valid": result.valid,
            "stable_ms": result.stable_ms,
            "stable": result.get("stable", False),
            "classifier_elapsed_ms": elapsed_ms,
            "top_candidate": result.get("top_candidate"),
            "finger_extension": features.get("finger_extension") if features else None,
            "rule_finger_extension": result.get("finger_extension"),
            "joint_angles_deg": features.get("joint_angles_deg") if features else None,
            "thumb_angle_deg": features.get("thumb_angle_deg") if features else None,
            "thumb_tip_distance": features.get("thumb_tip_distance") if features else None,
            "thumb_extension": result.get("thumb_extension"),
            "tip_gap": result.get("tip_gap"),
            "thumb_index_gap": result.get("thumb_index_gap"),
            "feature_error": feature_error,
        }


def build_diagnostic_sample(config, landmarks, now_ms, diagnostic,
                            runtime_version, sequence_id, frame_index):
    """Join an already evaluated frame with its own raw landmark slice."""
    sample = build_sample(
        config.participant_id, config.session_id, config.gesture_id, landmarks,
        timestamp_ms=max(0, now_ms), consent=config.consent,
        source=config.source, license_name=config.license,
    )
    sample.update(diagnostic)
    sample.update({
        "capture_diagnostics_schema": "opensignhand.capture_diagnostics.v1",
        "sample_id": "{}-{:06d}".format(sequence_id, frame_index),
        "sequence_id": sequence_id,
        "frame_index": frame_index,
        "intended_gesture": config.gesture_id,
        "hand": config.hand_side,
        "view": config.view,
        "landmarks_format": "63_xyz" if len(landmarks) == 63 else "21_xy",
        "prediction_timestamp_ms": max(0, now_ms),
        "runtime_version": runtime_version,
    })
    return validate_sample(sample)


def _canonical_sample(sample):
    normalized = validate_sample(sample)
    ordered = {}
    for field in REQUIRED_FIELDS:
        ordered[field] = normalized[field]
    for field in sorted(normalized):
        if field not in ordered:
            ordered[field] = normalized[field]
    return ordered


def _path_string(path):
    try:
        return os.fspath(path)
    except AttributeError:
        return str(path)


def _validate_existing_jsonl(path):
    """Reject an existing malformed file before appending a new line."""

    with open(path, "r", encoding="utf-8-sig") as stream:
        line_number = 0
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                sample = json.loads(line)
            except (TypeError, ValueError) as exc:
                raise CaptureError(
                    "existing JSONL line {} is invalid: {}".format(line_number, exc)
                )
            try:
                validate_sample(sample)
            except CaptureError as exc:
                raise CaptureError(
                    "existing JSONL line {} is invalid: {}".format(line_number, exc)
                )


def append_sample(path, sample):
    """Validate then append exactly one JSONL line and flush it."""

    normalized = _canonical_sample(sample)
    path = _path_string(path)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        _validate_existing_jsonl(path)
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    encoded = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=False
    )
    # Keep the line and newline in one write: one successful interval produces
    # one and only one JSONL record.
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(encoded + "\n")
        stream.flush()
    return normalized


write_sample = append_sample
append_record = append_sample


def select_largest_hand(objects):
    """Return the largest detected hand, or ``None`` for no detection."""

    if not objects:
        return None
    best = None
    best_area = -1.0
    for hand in objects:
        try:
            area = float(getattr(hand, "w")) * float(getattr(hand, "h"))
        except (AttributeError, TypeError, ValueError):
            continue
        if area > best_area:
            best = hand
            best_area = area
    return best


def _optional_number(value):
    """Missing/non-finite SDK diagnostics become null, never guessed values."""
    try:
        return _finite_number(value, "sdk diagnostic")
    except CaptureError:
        return None


def describe_hand(hand, coordinate_frame="original_camera_pixels"):
    """Copy SDK identity/geometry, NOT gesture confidence or certified side."""
    if hand is None:
        return None
    class_id = getattr(hand, "class_id", None)
    if isinstance(class_id, bool) or not isinstance(class_id, int):
        class_id = None
    corners = None
    points = getattr(hand, "points", None)
    if isinstance(points, (list, tuple)) and len(points) >= 71:
        values = [_optional_number(v) for v in points[:8]]
        if all(v is not None for v in values):
            corners = [[values[i], values[i+1]] for i in range(0, 8, 2)]
    return {
        "sdk_class_id": class_id,
        "sdk_score": _optional_number(getattr(hand, "score", None)),
        "box_xywh": [_optional_number(getattr(hand, key, None))
                     for key in ("x", "y", "w", "h")],
        "box_corners_xy": corners,
        "coordinate_frame": coordinate_frame,
    }


def _select_with_identity(objects, coordinate_frame):
    # Keep existing largest-area selection. Neither the intended label nor
    # the user's annotated hand side participates in selection.
    candidates = list(objects) if objects else []
    hand = select_largest_hand(candidates)
    selected_index = (next((i for i, item in enumerate(candidates) if item is hand), None)
                      if hand is not None else None)
    return hand, {
        "candidate_count": len(candidates),
        "selected_candidate_index": selected_index,
        "selection_policy": "largest_area",
        # Bound diagnostic record size, but always save the selected object
        # separately even if its index is beyond this preview list.
        "candidates": [describe_hand(item, coordinate_frame) for item in candidates[:8]],
        "candidates_truncated": len(candidates) > 8,
        "selected": describe_hand(hand, coordinate_frame),
    }


def center_crop_rect(frame):
    """Largest centered square: retain full height for this 320x224 camera."""
    width = int(frame.width())
    height = int(frame.height())
    if width <= 0 or height <= 0:
        raise CaptureError("invalid camera image dimensions")
    side = min(width, height)
    return ((width - side) // 2, (height - side) // 2, side, side)


class _CameraFrameHand:
    """Owned copy of SDK crop result with XY translated to camera pixels."""

    def __init__(self, hand, crop_rect):
        left, top, width, height = crop_rect
        raw = list(hand.points)
        if len(raw) != 71:
            raise CaptureError("ROI detector must return box8 + xyz63")
        raw = [_finite_number(value, "roi point") for value in raw]
        landmarks = raw[8:71]
        # Fail closed when predicted fingertips fall outside the actual crop.
        if any(not (0 <= landmarks[i] < width and 0 <= landmarks[i+1] < height)
               for i in range(0, 63, 3)):
            raise CaptureError("ROI landmarks outside crop")
        self.roi_raw_landmarks = list(landmarks)
        self.points = list(raw)
        for i in range(0, 8, 2):
            self.points[i] += left
            self.points[i+1] += top
        for i in range(8, 71, 3):
            self.points[i] += left
            self.points[i+1] += top
        # Z is intentionally unchanged: crop translation is only an XY offset.
        self.w, self.h = float(hand.w), float(hand.h)
        # SDK x/y describe its pre-rotation square, not min(rotated corners).
        # Translate those fields directly so box_xywh retains SDK semantics.
        source_x = _optional_number(getattr(hand, "x", None))
        source_y = _optional_number(getattr(hand, "y", None))
        self.x = source_x + left if source_x is not None else None
        self.y = source_y + top if source_y is not None else None
        self.class_id = getattr(hand, "class_id", None)
        self.score = getattr(hand, "score", None)


def detect_capture_hand(detector, frame, diagnostic=False, roi_retry=False):
    """Probe one current frame, optionally a fresh crop; report provenance.

    Stop at the first usable hand. Relaxed detections are diagnostic evidence,
    not validated observations for the control application. The SDK exposes
    only its combined result, so these profiles do not reveal raw stage scores.
    """
    profiles = [("baseline", DETECT_CONFIDENCE, LANDMARK_CONFIDENCE)]
    if diagnostic:
        profiles.extend((("detector_relaxed", 0.5, LANDMARK_CONFIDENCE),
                         ("second_check_relaxed", DETECT_CONFIDENCE, 0.5),
                         ("both_relaxed", 0.5, 0.5)))
    attempts = []
    for name, conf, conf2 in profiles:
        objects = detector.detect(frame, conf_th=conf, iou_th=IOU_THRESHOLD,
                                  conf_th2=conf2)
        hand, identity = _select_with_identity(objects, "original_camera_pixels")
        profile = {"name": name, "conf_th": conf, "iou_th": IOU_THRESHOLD,
                   "conf_th2": conf2, "usable_hand_found": hand is not None,
                   "hand_identity": identity}
        attempts.append(profile)
        if hand is not None:
            return hand, profile, attempts
    if roi_retry:
        rect = center_crop_rect(frame)
        # The source frame has not been drawn on; the crop comes from THIS
        # camera read, not the previous hand box, image or predicted label.
        cropped = frame.crop(*rect)
        for name, conf in (("roi_baseline", DETECT_CONFIDENCE),
                           ("roi_detector_relaxed", 0.5)):
            objects = detector.detect(cropped, conf_th=conf, iou_th=IOU_THRESHOLD,
                                      conf_th2=LANDMARK_CONFIDENCE)
            hand, identity = _select_with_identity(objects, "crop_local_pixels")
            rejection = None
            if hand is not None:
                try:
                    hand = _CameraFrameHand(hand, rect)
                except (CaptureError, TypeError, AttributeError, OverflowError) as exc:
                    rejection = str(exc)
                    hand = None
            profile = {"name": name, "conf_th": conf, "iou_th": IOU_THRESHOLD,
                       "conf_th2": LANDMARK_CONFIDENCE, "crop_rect": list(rect),
                       "usable_hand_found": hand is not None, "rejection": rejection,
                       "hand_identity": identity}
            attempts.append(profile)
            if hand is not None:
                return hand, profile, attempts
    return None, None, attempts


def capture_due(now_ms, last_capture_ms, interval_ms):
    """Return whether one fixed-interval record may be written now."""

    if isinstance(now_ms, bool) or not isinstance(now_ms, int):
        raise CaptureError("now_ms must be an integer")
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int):
        raise CaptureError("interval_ms must be a positive integer")
    if interval_ms <= 0:
        raise CaptureError("interval_ms must be a positive integer")
    if last_capture_ms is None:
        return True
    if isinstance(last_capture_ms, bool) or not isinstance(last_capture_ms, int):
        raise CaptureError("last_capture_ms must be an integer or None")
    return now_ms - last_capture_ms >= interval_ms


def _even_crop_span(start, end, limit):
    """Expand an intersecting crop to an even size without removing pixels."""
    if not 0 <= start < end <= limit:
        raise CaptureError("hand crop does not intersect frame")
    if (end - start) % 2:
        if end < limit:
            end += 1
        elif start > 0:
            start -= 1
        else:
            # An odd-sized full frame cannot be expanded within its bounds.
            raise CaptureError("frame cannot contain an even hand crop")
    return start, end


def save_hand_evidence(frame, sample, output_path, enabled=True):
    """Pair a bounded, unannotated current-frame crop with its JSONL record.

    Images are local internal evidence, not a public dataset. A landmark
    bounding crop may still contain background; it is not person anonymization.
    Failures remain explicit metadata and never manufacture a successful pair.
    """
    result = {"status": "disabled", "path": None, "sha256": None,
              "sample_id": sample["sample_id"], "timestamp_ms": sample["timestamp_ms"],
              "crop_rect": None, "annotated": False, "byte_count": 0}
    if not enabled:
        return result
    try:
        raw = normalize_landmarks(sample["landmarks"])
        xy = raw if len(raw) == 21 else [raw[i:i+2] for i in range(0, 63, 3)]
        width, height = int(frame.width()), int(frame.height())
        left = max(0, int(math.floor(min(p[0] for p in xy))) - 12)
        top = max(0, int(math.floor(min(p[1] for p in xy))) - 12)
        right = min(width, int(math.ceil(max(p[0] for p in xy))) + 13)
        bottom = min(height, int(math.ceil(max(p[1] for p in xy))) + 13)
        if right <= left or bottom <= top:
            raise CaptureError("hand crop does not intersect frame")
        # Maix's JPEG conversion requires even width AND height. Expand the
        # crop, never shrink it or alter the recorded model coordinates.
        left, right = _even_crop_span(left, right, width)
        top, bottom = _even_crop_span(top, bottom, height)
        rect = [left, top, right-left, bottom-top]
        result["crop_rect"] = rect
        # Already used SDK calls: crop is independent of the source; JPEG
        # encoding follows live_sidecar's to_jpeg().to_bytes() path.
        encoded = frame.crop(*rect).to_jpeg().to_bytes()
        if not isinstance(encoded, (bytes, bytearray, memoryview)):
            raise CaptureError("JPEG encoder did not return bytes")
        encoded = bytes(encoded)
        if not encoded or len(encoded) > MAX_EVIDENCE_BYTES:
            raise CaptureError("hand JPEG empty or exceeds byte limit")
        _safe_identifier(sample["sequence_id"], "sequence_id")
        _safe_identifier(sample["sample_id"], "sample_id")
        directory = os.path.join(os.path.dirname(_path_string(output_path)),
                                 "opensignhand_frames", sample["sequence_id"])
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(directory, sample["sample_id"] + ".jpg")
        # Reboots/repeated filenames must not overwrite previous evidence.
        with open(path, "xb") as stream:
            stream.write(encoded)
            stream.flush()
        result.update(status="saved", path=path, byte_count=len(encoded))
        result["sha256"] = _file_fingerprint(path)["sha256"]
    except Exception as exc:
        result.update(status="failed", error="{}:{}".format(type(exc).__name__, exc))
    return result


class CancelButton:
    """Release-edge cancel state machine for optional Maix touchscreen input."""

    def __init__(self, rect=None):
        self.rect = tuple(rect) if rect is not None else None
        self._pressed_inside = False
        self._last_pressed = False

    def set_rect(self, rect):
        self.rect = tuple(rect) if rect is not None else None

    def reset(self):
        self._pressed_inside = False
        self._last_pressed = False

    def _inside(self, x, y):
        if self.rect is None:
            return False
        left, top, width, height = self.rect
        return left <= x < left + width and top <= y < top + height

    def update(self, x, y, pressed, enabled=True):
        """Return true only when an enabled inside press is released inside."""

        inside = self._inside(x, y)
        emit = False
        if pressed and not self._last_pressed:
            self._pressed_inside = bool(enabled and inside)
        elif not pressed and self._last_pressed:
            emit = bool(enabled and inside and self._pressed_inside)
            self._pressed_inside = False
        self._last_pressed = bool(pressed)
        return emit


def countdown_values(seconds):
    """Return the deterministic visible countdown values for offline tests."""

    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
        raise CaptureError("countdown seconds must be a non-negative integer")
    return tuple(range(seconds, 0, -1))


def run_countdown(seconds, is_cancelled, sleep_ms, announce=print):
    """Print a one-second startup countdown; return false if cancelled."""

    for remaining in countdown_values(seconds):
        if is_cancelled():
            return False
        announce("OPENSIGNHAND STARTING IN {}".format(remaining))
        sleep_ms(1000)
    if is_cancelled():
        return False
    announce("OPENSIGNHAND CAPTURE STARTED")
    return True


def _ticks_ms(time_module):
    ticks = getattr(time_module, "ticks_ms", None)
    if ticks is not None:
        return int(ticks())
    # This fallback is for simple host fakes only; MaixCAM2 supplies ticks_ms.
    import time as host_time

    return int(host_time.monotonic() * 1000.0)


def _sleep_ms(time_module, duration_ms):
    sleep = getattr(time_module, "sleep_ms", None)
    if sleep is not None:
        sleep(int(duration_ms))
        return
    import time as host_time

    host_time.sleep(float(duration_ms) / 1000.0)


def _ticks_diff(time_module, previous_ms, now_ms):
    ticks_diff = getattr(time_module, "ticks_diff", None)
    if ticks_diff is not None:
        return int(ticks_diff(previous_ms, now_ms))
    return int(now_ms - previous_ms)


def _screen_size(screen, default_width=CAMERA_WIDTH, default_height=CAMERA_HEIGHT):
    if screen is None:
        return default_width, default_height
    width = getattr(screen, "width", None)
    height = getattr(screen, "height", None)
    try:
        width = width() if callable(width) else width
        height = height() if callable(height) else height
        return int(width), int(height)
    except (TypeError, ValueError):
        return default_width, default_height


def _show_preview(frame, screen, image_module, text, cancel_rect):
    if screen is None:
        return
    try:
        frame.draw_string(4, 4, text, color=image_module.COLOR_RED)
        left, top, width, height = cancel_rect
        frame.draw_rect(left, top, width, height, image_module.COLOR_RED, 2)
        frame.draw_string(left + 6, top + 8, "CANCEL", color=image_module.COLOR_RED)
        screen.show(frame)
    except Exception as exc:
        # A display fault must not turn into a data or hardware side effect.
        print("preview unavailable: {}".format(exc))


def draw_hand_identity(frame, landmarks, selected_hand, image_module, candidate_count=None):
    """Draw fresh same-frame model indices; never alter coordinates/data."""
    color = getattr(image_module, "COLOR_WHITE", image_module.COLOR_RED)
    width, height = int(frame.width()), int(frame.height())
    corners = selected_hand.get("box_corners_xy") if selected_hand else None
    if corners:
        for i in range(4):
            a, b = corners[i], corners[(i+1) % 4]
            frame.draw_line(int(round(a[0])), int(round(a[1])),
                            int(round(b[0])), int(round(b[1])), color, 2)
    if landmarks is not None:
        xy = normalize_landmarks(landmarks)
        for index, tag in ((4, "T4"), (8, "I8"), (20, "P20")):
            x, y = xy[index] if len(xy) == 21 else xy[index*3:index*3+2]
            if not (0 <= x < width and 0 <= y < height):
                continue
            frame.draw_circle(int(round(x)), int(round(y)), 3, color, 1)
            # Only the label's drawing position is bounded. Saved points and
            # the classifier input are untouched, including out-of-frame XY.
            frame.draw_string(max(0, min(width-32, int(x)+3)),
                              max(0, min(height-16, int(y)-16)), tag, color=color)
    if selected_hand:
        score = selected_hand["sdk_score"]
        value = "null" if score is None else "{:.3f}".format(score)
        frame.draw_string(4, 22, "ID={} S={} N={}".format(
            selected_hand["sdk_class_id"], value, candidate_count), color=color)


def _close_capture_resources(camera, screen):
    for resource in (camera, screen):
        close = getattr(resource, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def run_capture(
    config,
    *,
    app_module,
    camera_module,
    display_module,
    image_module,
    nn_module,
    time_module,
    touchscreen_module=None
):
    """Run one injected Maix capture session and return written sample count."""

    config = validate_config(config)
    # Fail before opening the camera if local rule dependencies are missing.
    diagnostics = CaptureDiagnostics()
    detector = nn_module.HandLandmarks(model=config.model_path)
    camera = camera_module.Camera(
        CAMERA_WIDTH, CAMERA_HEIGHT, detector.input_format()
    )
    screen = None
    if display_module is not None:
        try:
            screen = display_module.Display()
        except Exception as exc:
            print("display unavailable; console-only capture: {}".format(exc))

    touch = None
    if touchscreen_module is not None:
        try:
            touch = touchscreen_module.TouchScreen()
        except Exception as exc:
            print("touch cancel unavailable; use app stop: {}".format(exc))

    screen_width, screen_height = _screen_size(screen)
    # The detector frame can be shorter than the physical display.  Keep the
    # visible cancel rectangle inside the frame so drawing it never fails on a
    # 320x224 camera paired with a 320x240 panel.
    screen_width = min(screen_width, CAMERA_WIDTH)
    screen_height = min(screen_height, CAMERA_HEIGHT)
    cancel_rect = (
        max(2, screen_width - 112),
        max(2, screen_height - 42),
        108,
        36,
    )
    cancel_button = CancelButton(cancel_rect)

    def cancelled():
        try:
            if app_module.need_exit():
                return True
        except Exception:
            # A failed exit probe is not permission to continue collecting.
            return True
        if touch is not None:
            try:
                x, y, pressed = touch.read()
                if cancel_button.update(x, y, pressed, True):
                    return True
            except Exception as exc:
                print("touch read failed; capture remains cancellable by app stop: {}".format(exc))
        return False

    if not run_countdown(
        config.countdown_seconds,
        cancelled,
        lambda duration: _sleep_ms(time_module, duration),
    ):
        print("OPENSIGNHAND CAPTURE CANCELLED before first sample")
        _close_capture_resources(camera, screen)
        return 0

    diagnostics.runtime_version["landmark_detector"] = {
        "model_path": config.model_path,
        "model_sha256": None,  # Do not presume a model version from its name.
        "camera_width": CAMERA_WIDTH,
        "camera_height": CAMERA_HEIGHT,
        "conf_th": DETECT_CONFIDENCE,
        "iou_th": IOU_THRESHOLD,
        "conf_th2": LANDMARK_CONFIDENCE,
    }
    print("OPENSIGNHAND CLASSIFIER SOURCE SHA256={}".format(
        diagnostics.runtime_version["classifier"]["sha256"] or "unavailable"
    ))
    print("OPENSIGNHAND DETECTION DIAGNOSTIC={} baseline=0.7/0.8 probes=0.5/0.8,0.7/0.5,0.5/0.5".format(
        DETECTION_DIAGNOSTIC
    ))
    print("OPENSIGNHAND ROI RETRY={} modes=roi_baseline,roi_detector_relaxed".format(ROI_RETRY))
    print("OPENSIGNHAND IDENTITY DIAGNOSTIC=True markers=T4,I8,P20 side=raw_sdk_class_id")
    print("OPENSIGNHAND HAND IMAGE EVIDENCE={} local_only=True".format(SAVE_HAND_EVIDENCE))

    written = 0
    last_capture_ms = None
    previous_tick = None
    elapsed_ms = 0
    frame_index = 0
    sequence_id = None
    no_hand_frames = 0
    invalid_landmark_frames = 0
    profile_counts = {name: 0 for name in (
        "baseline", "detector_relaxed", "second_check_relaxed", "both_relaxed",
        "roi_baseline", "roi_detector_relaxed", "none"
    )}
    try:
        while written < config.target_samples:
            if cancelled():
                print("OPENSIGNHAND CAPTURE CANCELLED samples={}".format(written))
                break

            frame = camera.read()
            hand, selected_profile, detector_attempts = detect_capture_hand(
                detector, frame, DETECTION_DIAGNOSTIC, roi_retry=ROI_RETRY
            )
            profile_name = selected_profile["name"] if selected_profile else "none"
            profile_counts[profile_name] += 1
            landmarks = None
            if hand is not None:
                try:
                    landmarks = extract_hand_landmarks(hand)
                except CaptureError as exc:
                    invalid_landmark_frames += 1
                    print("invalid hand landmarks; sample skipped: {}".format(exc))

            now_ms = _ticks_ms(time_module)
            if previous_tick is not None:
                delta = _ticks_diff(time_module, previous_tick, now_ms)
                if delta < 0:
                    raise CaptureError("capture clock moved backwards")
                elapsed_ms += delta
            previous_tick = now_ms
            frame_index += 1
            if sequence_id is None:
                sequence_id = "{}-{}".format(config.session_id, max(0, now_ms))
            if hand is None:
                no_hand_frames += 1
            # Must execute on EVERY frame, not only the 500-ms write cadence.
            # Missing/invalid landmarks reset the classifier's stable hold.
            diagnostic = diagnostics.observe(landmarks, elapsed_ms)
            if elapsed_ms >= config.max_capture_ms:
                print("OPENSIGNHAND CAPTURE TIME LIMIT samples={}".format(written))
                break
            if landmarks is not None and (
                last_capture_ms is None
                or _ticks_diff(time_module, last_capture_ms, now_ms)
                >= config.capture_interval_ms
            ):
                # Do not mislabel a relaxed result with baseline parameters.
                runtime = dict(diagnostics.runtime_version)
                runtime["landmark_detector"] = dict(runtime["landmark_detector"])
                runtime["landmark_detector"].update({
                    "conf_th": selected_profile["conf_th"],
                    "conf_th2": selected_profile["conf_th2"],
                    "profile": profile_name,
                    "diagnostic_only": DETECTION_DIAGNOSTIC or ROI_RETRY,
                    "roi_retry_enabled": ROI_RETRY,
                    "crop_rect": selected_profile.get("crop_rect"),
                })
                sample = build_diagnostic_sample(
                    config, landmarks, now_ms, diagnostic,
                    runtime, sequence_id, frame_index,
                )
                sample["detector_attempts_this_frame"] = detector_attempts
                sample["detector_profile"] = profile_name
                sample["capture_diagnostic_only"] = DETECTION_DIAGNOSTIC or ROI_RETRY
                sample["roi_raw_landmarks"] = getattr(hand, "roi_raw_landmarks", None)
                sample["landmark_xy_frame"] = "original_camera_pixels"
                sample["selected_hand"] = describe_hand(hand)
                sample["hand_identity_schema"] = "opensignhand.hand_identity.v1"
                sample["no_hand_frames_seen"] = no_hand_frames
                sample["invalid_landmark_frames_seen"] = invalid_landmark_frames
                # Before any preview drawing: exact same camera read as the
                # detector/landmarks, with a unique record identity.
                sample["hand_image_evidence"] = save_hand_evidence(
                    frame, sample, config.output_path, SAVE_HAND_EVIDENCE)
                append_sample(config.output_path, sample)
                written += 1
                last_capture_ms = now_ms
                print(
                    "OPENSIGNHAND SAMPLE {}/{} target={} predicted={} stable_ms={} timestamp_ms={}".format(
                        written,
                        config.target_samples,
                        config.gesture_id,
                        diagnostic["predicted_gesture_id"],
                        diagnostic["stable_ms"],
                        max(0, now_ms),
                    )
                )
                print("OPENSIGNHAND DETECTOR PROFILE={}".format(profile_name))
                print("OPENSIGNHAND HAND IMAGE {}".format(json.dumps(sample["hand_image_evidence"])))
                print("OPENSIGNHAND HAND IDENTITY {}".format(json.dumps({
                    "selected_hand": sample["selected_hand"],
                    "candidate_count": selected_profile["hand_identity"]["candidate_count"],
                    "selected_candidate_index": selected_profile["hand_identity"]["selected_candidate_index"],
                })))

            if hand is None:
                preview_text = "HAND NOT FOUND samples={}/{}".format(
                    written, config.target_samples
                )
            else:
                preview_text = "{} {} / {}".format(
                    diagnostic["predicted_gesture_id"], written, config.target_samples
                )
            if screen is not None:
                try:
                    if hand is not None:
                        detector.draw_hand(
                            frame,
                            hand.class_id,
                            [int(round(v)) for v in hand.points] if hasattr(hand, "roi_raw_landmarks") else hand.points,
                            4,
                            10,
                            box=True,
                        )
                except Exception as exc:
                    print("landmark preview unavailable: {}".format(exc))
                try:
                    if hand is not None:
                        draw_hand_identity(frame, landmarks, describe_hand(hand), image_module,
                                           selected_profile["hand_identity"]["candidate_count"])
                except Exception as exc:
                    print("identity preview unavailable: {}".format(exc))
                if ROI_RETRY:
                    try:
                        frame.draw_rect(*center_crop_rect(frame), image_module.COLOR_RED, 1)
                    except Exception as exc:
                        print("ROI guide unavailable: {}".format(exc))
                _show_preview(frame, screen, image_module, preview_text, cancel_rect)
            _sleep_ms(time_module, 10)
    except KeyboardInterrupt:
        print("OPENSIGNHAND CAPTURE CANCELLED by user")
    finally:
        _close_capture_resources(camera, screen)

    if written >= config.target_samples:
        print("OPENSIGNHAND CAPTURE COMPLETE samples={}".format(written))
    print("OPENSIGNHAND FRAME SUMMARY frames={} no_hand={} invalid_landmarks={}".format(
        frame_index, no_hand_frames, invalid_landmark_frames
    ))
    print("OPENSIGNHAND DETECTOR PROFILE SUMMARY {}".format(json.dumps(profile_counts)))
    return written


def main(config=None):
    """Validate consent, then load MaixCAM2 runtime and collect samples."""

    try:
        config = validate_config(config if config is not None else CaptureConfig())
    except CaptureError as exc:
        print("OPENSIGNHAND CAPTURE NOT STARTED: {}".format(exc))
        return 2

    # Keep all Maix imports inside the executable path so host validation and
    # tests never require the board runtime.
    try:
        from maix import app, camera, display, image, nn, time
    except Exception as exc:
        print("OPENSIGNHAND Maix runtime unavailable: {}".format(exc))
        return 1
    try:
        from maix import touchscreen
    except Exception:
        touchscreen = None

    try:
        run_capture(
            config,
            app_module=app,
            camera_module=camera,
            display_module=display,
            image_module=image,
            nn_module=nn,
            time_module=time,
            touchscreen_module=touchscreen,
        )
        # A sample count is not a process exit status (7 samples != failure 7).
        return 0
    except KeyboardInterrupt:
        print("OPENSIGNHAND CAPTURE CANCELLED by user")
        return 130
    except Exception as exc:
        print("OPENSIGNHAND CAPTURE STOPPED safely: {}".format(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
