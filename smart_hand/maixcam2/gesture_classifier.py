"""Deterministic bounded hand-shape classifier for the OpenSignHand MVP.

The labels in this file are deliberately *shape* labels, not formal Chinese
sign-language labels.  A small rule classifier is used instead of a heavy
runtime model so it is explainable, replayable, and safe to run on MaixPy.
"""

import json
import math
import os
import time

try:
    from gesture_features import extract_gesture_features, feature_vector
except ImportError:  # Package-style host import.
    from .gesture_features import extract_gesture_features, feature_vector


OPEN_PALM = "OPEN_PALM"
FIST = "FIST"
V_SIGN = "V_SIGN"
POINT = "POINT"
THUMBS_UP = "THUMBS_UP"
L_SHAPE = "L_SHAPE"
OK_PINCH = "OK_PINCH"
UNKNOWN = "UNKNOWN"

ERROR_OK = "OK"
ERROR_NO_HAND = "NO_HAND"
ERROR_INVALID_LANDMARKS = "INVALID_LANDMARKS"
ERROR_LOW_CONFIDENCE = "LOW_CONFIDENCE"
ERROR_LINK_OFFLINE = "LINK_OFFLINE"
ERROR_VISION_STALE = "VISION_STALE"

# Optional learned-model contract.  The rule classifier below remains the
# default whenever this contract cannot be loaded or validated.
MODEL_SCHEMA = "opensignhand.gesture_centroid"
MODEL_SCHEMA_VERSION = 1
MODEL_TYPE = "standardized_centroid"
MODEL_FEATURE_NAME = "gesture_features.feature_vector"
MODEL_LABELS = (OPEN_PALM, FIST, V_SIGN)
DEFAULT_MODEL_PATH = "/root/models/opensignhand_gesture_model.json"


def _now_ms():
    ticks_ms = getattr(time, "ticks_ms", None)
    if ticks_ms is not None:
        return int(ticks_ms())
    return int(time.monotonic() * 1000.0)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


class GestureResult(dict):
    """Mapping result with attribute access for small UI/firmware callers."""

    def __init__(self, gesture_id, confidence, stable_ms, valid, error_code, **extra):
        values = {
            "gesture_id": gesture_id,
            "confidence": float(confidence),
            "stable_ms": int(max(0, stable_ms)),
            "valid": bool(valid),
            "error_code": error_code,
        }
        values.update(extra)
        dict.__init__(self, values)
        self.__dict__.update(values)

    def as_dict(self):
        return dict(self)

    to_dict = as_dict


def _mean(values):
    return sum(values) / float(len(values)) if values else 0.0


def _palm_directed_extension(straightness, normalized):
    """Reject straight-looking chains whose tips have returned to the wrist.

    Chord/path measures collinearity, not extension away from the palm. A
    folded chain can project as a straight line pointing back into the palm.
    Require BOTH a backward MCP-to-tip direction and a tip closer to the
    wrist than its MCP before treating that finger as folded. Dot products
    and squared distances keep this invariant under rotation/mirroring/scale.
    This rule-only correction leaves the learned model's feature vector alone.
    It cannot recover depth-ambiguous folds whose projected tips point outward.
    """
    extension = list(straightness)
    if len(normalized) != 21:
        return extension
    wrist = normalized[0]
    for offset, (mcp, tip) in enumerate(((5, 8), (9, 12), (13, 16), (17, 20))):
        base = (normalized[mcp][0] - wrist[0], normalized[mcp][1] - wrist[1])
        end = (normalized[tip][0] - wrist[0], normalized[tip][1] - wrist[1])
        backward = (end[0] - base[0]) * base[0] + (end[1] - base[1]) * base[1]
        base_radius_sq = base[0] ** 2 + base[1] ** 2
        tip_radius_sq = end[0] ** 2 + end[1] ** 2
        if backward < 0.0 and tip_radius_sq < base_radius_sq:
            extension[offset] = 0.0
    return extension


def _classify_features(features):
    extension = list(features.get("finger_extension", ()))
    if len(extension) != 4:
        return UNKNOWN, 0.0, {"reason": "missing_finger_features"}

    straightness = list(extension)
    normalized = features.get("normalized_landmarks", ())
    extension = _palm_directed_extension(extension, normalized)
    index, middle, ring, pinky = extension
    average = _mean(extension)
    minimum = min(extension)
    maximum = max(extension)
    tip_gap = 0.0
    thumb_index_gap = 99.0
    if len(normalized) >= 13:
        a = normalized[8]
        b = normalized[12]
        tip_gap = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
    if len(normalized) >= 9:
        thumb_tip = normalized[4]
        index_tip = normalized[8]
        thumb_index_gap = (
            (thumb_tip[0] - index_tip[0]) ** 2
            + (thumb_tip[1] - index_tip[1]) ** 2
        ) ** 0.5

    thumb_angle = float(features.get("thumb_angle_deg", 0.0))
    thumb_distance = float(features.get("thumb_tip_distance", 0.0))
    thumb_straight = _clamp((thumb_angle - 115.0) / 55.0)
    thumb_far = _clamp((thumb_distance - 0.65) / 0.70)
    thumb_extension = 0.65 * thumb_straight + 0.35 * thumb_far

    # The shape score is intentionally transparent: straight fingers score
    # high, folded fingers score low.  The V prototype also requires visible
    # separation between the index and middle fingertips.
    open_score = 0.55 * average + 0.45 * minimum
    fist_score = (
        0.55 * (1.0 - average) + 0.45 * (1.0 - maximum)
    ) * (1.0 - 0.35 * thumb_extension)
    v_pattern = _mean((index, middle, 1.0 - ring, 1.0 - pinky))
    gap_quality = _clamp((tip_gap - 0.18) / 0.45)
    v_score = 0.75 * v_pattern + 0.25 * gap_quality
    # A partly occluded folded pair can appear 70-80% straight in 2-D.
    # Do not let that V-like contrast turn into a confident open palm.
    v_like = (
        index >= 0.72 and middle >= 0.72 and tip_gap >= 0.22
        and min(index, middle) - max(ring, pinky) >= 0.14
    )
    point_score = _mean(
        (index, 1.0 - middle, 1.0 - ring, 1.0 - pinky, 1.0 - thumb_extension)
    )
    thumbs_up_score = (
        0.70 * _mean((1.0 - index, 1.0 - middle, 1.0 - ring, 1.0 - pinky))
        + 0.30 * thumb_extension
    )
    l_shape_score = _mean(
        (index, 1.0 - middle, 1.0 - ring, 1.0 - pinky, thumb_extension)
    )
    ok_contact = _clamp((0.42 - thumb_index_gap) / 0.28)
    ok_pinch_score = (
        0.70 * _mean((1.0 - index, middle, ring, pinky))
        + 0.30 * ok_contact
    )

    candidates = (
        (OPEN_PALM, open_score),
        (FIST, fist_score),
        (V_SIGN, v_score),
        (POINT, point_score),
        (THUMBS_UP, thumbs_up_score),
        (L_SHAPE, l_shape_score),
        (OK_PINCH, ok_pinch_score),
    )
    candidates = sorted(candidates, key=lambda item: item[1], reverse=True)
    label, score = candidates[0]
    l_shape_accepted = (
        index >= 0.72
        and middle <= 0.62
        and ring <= 0.62
        and pinky <= 0.62
        and thumb_extension >= 0.55
        and l_shape_score >= 0.70
    )
    if v_like and ring <= 0.75 and pinky <= 0.75 and v_score >= 0.64:
        label, score = V_SIGN, v_score
    elif label == V_SIGN and l_shape_accepted:
        # A folded middle finger can still earn V's fingertip-gap bonus.
        # It cannot satisfy the V gate, but must not suppress a fully
        # qualified L.  Do not fall back to arbitrary runner-up shapes or
        # relax the thumb gate for ambiguous 2-D projections.
        label, score = L_SHAPE, l_shape_score
    details = {
        "top_candidate": label,
        "open_score": _clamp(open_score),
        "fist_score": _clamp(fist_score),
        "v_score": _clamp(v_score),
        "point_score": _clamp(point_score),
        "thumbs_up_score": _clamp(thumbs_up_score),
        "l_shape_score": _clamp(l_shape_score),
        "ok_pinch_score": _clamp(ok_pinch_score),
        "thumb_extension": _clamp(thumb_extension),
        "thumb_index_gap": thumb_index_gap,
        "tip_gap": tip_gap,
        "v_like": v_like,
        "finger_extension": extension,
        "finger_straightness": straightness,
    }

    # Pattern gates avoid accepting a high average when one decisive finger
    # contradicts the prototype.  They also leave ambiguous poses UNKNOWN.
    if label == OPEN_PALM:
        accepted = minimum >= 0.68 and score >= 0.70 and not v_like
    elif label == FIST:
        # Folded fingers are inherently less uniform than a straight palm;
        # retain a lower score gate while still requiring every finger to be
        # clearly below the extension range.
        accepted = maximum <= 0.62 and score >= 0.62
    elif label == V_SIGN:
        accepted = (
            index >= 0.72
            and middle >= 0.72
            and ring <= 0.75
            and pinky <= 0.75
            and tip_gap >= 0.22
            and score >= 0.64
        )
    elif label == POINT:
        accepted = (
            index >= 0.72
            and middle <= 0.62
            and ring <= 0.62
            and pinky <= 0.62
            and thumb_extension <= 0.52
            and score >= 0.70
        )
    elif label == THUMBS_UP:
        accepted = (
            maximum <= 0.62
            and thumb_extension >= 0.55
            and score >= 0.68
        )
    elif label == L_SHAPE:
        accepted = l_shape_accepted
    else:
        accepted = (
            index <= 0.68
            and middle >= 0.68
            and ring >= 0.68
            and pinky >= 0.68
            and thumb_index_gap <= 0.42
            and score >= 0.68
        )
    if not accepted:
        return UNKNOWN, _clamp(score), details
    return label, _clamp(score), details


def classify_gesture(raw_points):
    """Classify one frame without a temporal stability filter.

    The return object always has the five common result fields.  For a valid
    recognized frame, ``stable_ms`` is zero because no temporal history was
    supplied; use :class:`GestureClassifier` for the training loop.
    """
    try:
        features = extract_gesture_features(raw_points)
    except (TypeError, ValueError, OverflowError):
        return GestureResult(
            UNKNOWN, 0.0, 0, False, ERROR_INVALID_LANDMARKS
        )
    label, confidence, details = _classify_features(features)
    if label == UNKNOWN:
        return GestureResult(
            label, confidence, 0, False, ERROR_LOW_CONFIDENCE, **details
        )
    return GestureResult(label, confidence, 0, True, ERROR_OK, **details)


class GestureClassifier:
    """Stateful frame classifier with monotonic stable-duration reporting."""

    def __init__(self, confidence_threshold=0.64, stable_hold_ms=300):
        if confidence_threshold < 0.0 or confidence_threshold > 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if stable_hold_ms < 0:
            raise ValueError("stable_hold_ms must be non-negative")
        self.confidence_threshold = float(confidence_threshold)
        self.stable_hold_ms = int(stable_hold_ms)
        self._candidate = None
        self._candidate_since_ms = None
        self._last_now_ms = None
        self._last_result = None

    def reset(self):
        self._candidate = None
        self._candidate_since_ms = None
        self._last_now_ms = None
        self._last_result = None

    def _clock(self, now_ms):
        if now_ms is None:
            now_ms = _now_ms()
        now_ms = int(now_ms)
        if self._last_now_ms is not None and now_ms < self._last_now_ms:
            raise ValueError("now_ms must be monotonic")
        self._last_now_ms = now_ms
        return now_ms

    def _error(self, gesture_id, error_code, now_ms, confidence=0.0, **extra):
        self._candidate = None
        self._candidate_since_ms = None
        result = GestureResult(
            gesture_id, confidence, 0, False, error_code, **extra
        )
        self._last_result = result
        return result

    def _classify_frame(self, raw_points):
        """Classify one frame; subclasses may replace only this method."""
        return classify_gesture(raw_points)

    def observe(
        self,
        raw_points,
        now_ms=None,
        hand_present=True,
        link_online=True,
        vision_stale=False,
    ):
        """Consume one frame and return the common recognition result.

        ``valid`` means that this frame is a recognized, above-threshold
        prototype.  ``stable_ms`` is temporal evidence for the same label;
        callers should require their lesson's hold duration before completing
        a lesson.  Link and freshness checks fail closed before geometry is
        evaluated.
        """
        now_ms = self._clock(now_ms)
        if not link_online:
            return self._error(UNKNOWN, ERROR_LINK_OFFLINE, now_ms)
        if vision_stale:
            return self._error(UNKNOWN, ERROR_VISION_STALE, now_ms)
        if not hand_present or raw_points is None:
            return self._error(UNKNOWN, ERROR_NO_HAND, now_ms)
        result = self._classify_frame(raw_points)
        if not result.valid:
            self._candidate = None
            self._candidate_since_ms = None
            result["stable_ms"] = 0
            result.stable_ms = 0
            self._last_result = result
            return result
        if result.confidence < self.confidence_threshold:
            return self._error(
                UNKNOWN,
                ERROR_LOW_CONFIDENCE,
                now_ms,
                result.confidence,
                raw_gesture_id=result.gesture_id,
            )

        if result.gesture_id != self._candidate:
            self._candidate = result.gesture_id
            self._candidate_since_ms = now_ms
        stable_ms = now_ms - self._candidate_since_ms
        result["stable_ms"] = stable_ms
        result.stable_ms = stable_ms
        result["stable"] = stable_ms >= self.stable_hold_ms
        result.stable = result["stable"]
        self._last_result = result
        return result

    def classify(self, *args, **kwargs):
        """Alias used by simple frame-loop callers."""
        return self.observe(*args, **kwargs)

    update = observe

    @property
    def last_result(self):
        return self._last_result


def _finite_float(value, name):
    if isinstance(value, bool):
        raise ValueError("{} must be numeric".format(name))
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("{} must be numeric".format(name))
    if math.isnan(number) or math.isinf(number):
        raise ValueError("{} must be finite".format(name))
    return number


def _finite_vector(value, name, expected_length):
    if not isinstance(value, (list, tuple)) or len(value) != expected_length:
        raise ValueError(
            "{} must contain exactly {} values".format(name, expected_length)
        )
    return [_finite_float(item, "{}[{}]".format(name, index))
            for index, item in enumerate(value)]


def validate_model_payload(payload):
    """Validate and normalize a learned-model JSON object.

    This function is deliberately strict: a malformed model must not be
    allowed to influence an edge-device decision.  It returns a fresh mapping
    with finite Python floats and the fixed feature/label contract.
    """
    if not isinstance(payload, dict):
        raise ValueError("model must be a JSON object")
    if payload.get("schema") != MODEL_SCHEMA:
        raise ValueError("unsupported model schema")
    if payload.get("schema_version") != MODEL_SCHEMA_VERSION:
        raise ValueError("unsupported model schema_version")
    if payload.get("model_type") != MODEL_TYPE:
        raise ValueError("unsupported model type")
    labels = payload.get("labels")
    if labels != list(MODEL_LABELS):
        raise ValueError("model labels must be {}".format(list(MODEL_LABELS)))
    if payload.get("feature_name") != MODEL_FEATURE_NAME:
        raise ValueError("unsupported model feature definition")
    feature_dim = payload.get("feature_dim")
    if isinstance(feature_dim, bool) or not isinstance(feature_dim, int):
        raise ValueError("feature_dim must be an integer")
    # feature_vector currently has 18 fixed values.  Refuse accidental model
    #/runtime drift instead of silently truncating or padding coordinates.
    if feature_dim != 18:
        raise ValueError("feature_dim must be 18")
    mean = _finite_vector(payload.get("feature_mean"), "feature_mean", feature_dim)
    scale = _finite_vector(payload.get("feature_std"), "feature_std", feature_dim)
    if any(item <= 0.0 for item in scale):
        raise ValueError("feature_std values must be positive")
    centroids = payload.get("centroids")
    if not isinstance(centroids, dict):
        raise ValueError("centroids must be an object")
    normalized_centroids = {}
    for label in MODEL_LABELS:
        normalized_centroids[label] = _finite_vector(
            centroids.get(label), "centroids.{}".format(label), feature_dim
        )
    reject_distance = _finite_float(
        payload.get("reject_distance"), "reject_distance"
    )
    reject_margin = _finite_float(payload.get("reject_margin"), "reject_margin")
    confidence_threshold = _finite_float(
        payload.get("confidence_threshold", 0.64), "confidence_threshold"
    )
    if reject_distance <= 0.0:
        raise ValueError("reject_distance must be positive")
    if reject_margin < 0.0:
        raise ValueError("reject_margin must be non-negative")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")
    return {
        "schema": MODEL_SCHEMA,
        "schema_version": MODEL_SCHEMA_VERSION,
        "model_type": MODEL_TYPE,
        "feature_name": MODEL_FEATURE_NAME,
        "feature_dim": feature_dim,
        "labels": list(MODEL_LABELS),
        "feature_mean": mean,
        "feature_std": scale,
        "centroids": normalized_centroids,
        "reject_distance": reject_distance,
        "reject_margin": reject_margin,
        "confidence_threshold": confidence_threshold,
    }


class LearnedGestureClassifier(GestureClassifier):
    """Small standardized-centroid classifier for optional edge deployment."""

    def __init__(self, model, stable_hold_ms=300):
        normalized = validate_model_payload(model)
        GestureClassifier.__init__(
            self,
            confidence_threshold=normalized["confidence_threshold"],
            stable_hold_ms=stable_hold_ms,
        )
        self.model = normalized

    def _classify_frame(self, raw_points):
        try:
            features = extract_gesture_features(raw_points)
            vector = feature_vector(features)
            if len(vector) != self.model["feature_dim"]:
                raise ValueError("feature vector dimension mismatch")
            standardized = [
                (float(value) - mean) / scale
                for value, mean, scale in zip(
                    vector,
                    self.model["feature_mean"],
                    self.model["feature_std"],
                )
            ]
            distances = []
            for label in self.model["labels"]:
                centroid = self.model["centroids"][label]
                squared = sum(
                    (value - center) ** 2
                    for value, center in zip(standardized, centroid)
                )
                distances.append(
                    (label, math.sqrt(squared / self.model["feature_dim"]))
                )
            distances.sort(key=lambda item: (item[1], item[0]))
            label, nearest = distances[0]
            second = distances[1][1]
            margin = second - nearest
            reject_distance = self.model["reject_distance"]
            reject_margin = self.model["reject_margin"]
            distance_confidence = _clamp(1.0 - nearest / reject_distance)
            if reject_margin > 0.0:
                margin_confidence = _clamp(margin / reject_margin)
            else:
                margin_confidence = 1.0
            confidence = _clamp(
                0.5 * distance_confidence + 0.5 * margin_confidence
            )
            details = {
                "nearest_distance": nearest,
                "second_distance": second,
                "distance_margin": margin,
                "model_type": MODEL_TYPE,
            }
            if nearest > reject_distance or margin < reject_margin:
                return GestureResult(
                    UNKNOWN,
                    confidence,
                    0,
                    False,
                    ERROR_LOW_CONFIDENCE,
                    **details
                )
            return GestureResult(label, confidence, 0, True, ERROR_OK, **details)
        except (TypeError, ValueError, OverflowError, ArithmeticError):
            return GestureResult(
                UNKNOWN, 0.0, 0, False, ERROR_INVALID_LANDMARKS
            )


def load_model(model_path=DEFAULT_MODEL_PATH):
    """Load and validate one JSON model; raise on any unsafe input."""
    with open(model_path, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return validate_model_payload(payload)


def create_classifier(
    model_path=DEFAULT_MODEL_PATH, stable_hold_ms=300, confidence_threshold=None
):
    """Create the learned classifier when safe, otherwise return rule mode.

    The fallback is intentionally silent and deterministic for MaixCAM2 boot:
    missing files, malformed JSON, incompatible schemas, and bad dimensions all
    preserve the bounded rule classifier.  Runtime sign mode instantiates that
    rule classifier directly because legacy learned JSON files contain only the
    original three classes.
    """
    if model_path is None:
        model_path = DEFAULT_MODEL_PATH
    try:
        if not os.path.isfile(model_path):
            raise OSError("model file is missing")
        model = load_model(model_path)
        if confidence_threshold is not None:
            model["confidence_threshold"] = _finite_float(
                confidence_threshold, "confidence_threshold"
            )
        return LearnedGestureClassifier(model, stable_hold_ms=stable_hold_ms)
    except Exception:
        fallback_threshold = 0.64
        if confidence_threshold is not None:
            try:
                candidate = _finite_float(
                    confidence_threshold, "confidence_threshold"
                )
                if 0.0 <= candidate <= 1.0:
                    fallback_threshold = candidate
            except (TypeError, ValueError, OverflowError):
                pass
        return GestureClassifier(
            confidence_threshold=fallback_threshold, stable_hold_ms=stable_hold_ms
        )


# Compatibility-friendly names for host scripts without adding another model.
BasicGestureClassifier = GestureClassifier
classify = classify_gesture
classify_landmarks = classify_gesture
