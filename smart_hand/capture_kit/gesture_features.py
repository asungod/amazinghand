"""Small, explainable geometry features for 21-point hand landmarks.

The MaixCAM2 hand-landmark model returns a flat sequence of 63 values in
``x, y, z`` order (the first eight values in ``hand.points`` are the detector
box).  Offline tests and host tools often use 21 ``(x, y)`` pairs instead, so
this module deliberately accepts both forms.

There is no dependency on Maix, NumPy, or a training runtime here.  The
classifier consumes the resulting ratios and angles, which keeps the MVP
deterministic and practical to run on a small edge device.  The classes are
*basic hand-shape prototypes*; this module does not assign a formal sign
language meaning to any shape.
"""

import math


HAND_POINT_COUNT = 21
FLAT_POINT_COUNT = HAND_POINT_COUNT * 3

# Standard MediaPipe/Maix 21-point order.
WRIST = 0
THUMB_CMC = 1
THUMB_MCP = 2
THUMB_IP = 3
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_PIP = 6
INDEX_DIP = 7
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_PIP = 10
MIDDLE_DIP = 11
MIDDLE_TIP = 12
RING_MCP = 13
RING_PIP = 14
RING_DIP = 15
RING_TIP = 16
PINKY_MCP = 17
PINKY_PIP = 18
PINKY_DIP = 19
PINKY_TIP = 20

FINGER_NAMES = ("index", "middle", "ring", "pinky")
FINGER_CHAINS = (
    (INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP),
    (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP),
    (RING_MCP, RING_PIP, RING_DIP, RING_TIP),
    (PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP),
)


def _distance(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _coerce_number(value, name):
    # bool is technically an int in Python, but is never a useful coordinate.
    if isinstance(value, bool):
        raise ValueError("{} must be numeric".format(name))
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be numeric".format(name))
    if math.isnan(number) or math.isinf(number):
        raise ValueError("{} must be finite".format(name))
    return number


def coerce_landmarks(raw_points):
    """Return 21 ``(x, y)`` pairs from Maix or host-test input.

    Accepted input forms are a sequence of 21 point-like values, where each
    value has at least two coordinates, or a flat sequence of 63 ``x, y, z``
    values.  The z coordinate is intentionally ignored because all features
    are 2-D and scale-normalized.
    """
    if not isinstance(raw_points, (list, tuple)):
        raise ValueError("landmarks must be a list or tuple")
    if len(raw_points) == HAND_POINT_COUNT:
        points = []
        for index, point in enumerate(raw_points):
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise ValueError("landmark {} needs x and y".format(index))
            points.append(
                (
                    _coerce_number(point[0], "landmark x"),
                    _coerce_number(point[1], "landmark y"),
                )
            )
        return points
    if len(raw_points) == FLAT_POINT_COUNT:
        points = []
        for index in range(0, FLAT_POINT_COUNT, 3):
            points.append(
                (
                    _coerce_number(raw_points[index], "landmark x"),
                    _coerce_number(raw_points[index + 1], "landmark y"),
                )
            )
        return points
    raise ValueError("expected 21 points or 63 xyz values")


def _rotate(point, angle):
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        point[0] * cosine - point[1] * sine,
        point[0] * sine + point[1] * cosine,
    )


def _normalize_with_metadata(raw_points):
    """Return normalized points plus the original scale and orientation.

    The wrist becomes the origin.  The wrist-to-middle-MCP vector is rotated
    to the positive y axis, making the feature frame insensitive to in-plane
    camera rotation.  Scale is the average wrist-to-index/middle/ring/pinky
    MCP distance, with a conservative fallback for a partially visible hand.
    """
    points = coerce_landmarks(raw_points)
    wrist = points[WRIST]
    translated = [(point[0] - wrist[0], point[1] - wrist[1]) for point in points]

    palm_vector = translated[MIDDLE_MCP]
    palm_length = _distance((0.0, 0.0), palm_vector)
    if palm_length <= 1e-6:
        raise ValueError("degenerate palm landmarks")
    # atan2(palm) + correction rotates the palm vector to +y.
    orientation = math.atan2(palm_vector[1], palm_vector[0])
    rotation = (math.pi / 2.0) - orientation
    rotated = [_rotate(point, rotation) for point in translated]
    scale_values = [
        _distance(rotated[WRIST], rotated[index])
        for index in (INDEX_MCP, MIDDLE_MCP, RING_MCP, PINKY_MCP)
    ]
    scale_values = [value for value in scale_values if value > 1e-6]
    if not scale_values:
        raise ValueError("degenerate palm scale")
    scale = sum(scale_values) / float(len(scale_values))
    normalized = [(point[0] / scale, point[1] / scale) for point in rotated]
    return normalized, scale, orientation


def normalize_landmarks(raw_points):
    """Translate, scale, and orient landmarks into a stable palm frame.

    The wrist becomes the origin.  The wrist-to-middle-MCP vector is rotated
    to the positive y axis, making the feature frame insensitive to in-plane
    camera rotation.  Scale is the average wrist-to-index/middle/ring/pinky
    MCP distance, with a conservative fallback for a partially visible hand.
    """
    normalized, unused_scale, unused_orientation = _normalize_with_metadata(
        raw_points
    )
    return normalized


def _angle(a, b, c):
    """Angle ABC in degrees, returning 0 for a degenerate joint."""
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    length = math.sqrt(ba[0] ** 2 + ba[1] ** 2) * math.sqrt(
        bc[0] ** 2 + bc[1] ** 2
    )
    if length <= 1e-9:
        return 0.0
    cosine = (ba[0] * bc[0] + ba[1] * bc[1]) / length
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def _finger_metrics(points, chain):
    mcp, pip, dip, tip = chain
    path = (
        _distance(points[mcp], points[pip])
        + _distance(points[pip], points[dip])
        + _distance(points[dip], points[tip])
    )
    if path <= 1e-9:
        raise ValueError("degenerate finger landmarks")
    chord = _distance(points[mcp], points[tip])
    straightness = _clamp(chord / path)
    return {
        "straightness": straightness,
        "tip_distance": _distance(points[WRIST], points[tip]),
        "pip_angle_deg": _angle(points[mcp], points[pip], points[dip]),
        "dip_angle_deg": _angle(points[pip], points[dip], points[tip]),
        "path": path,
        "chord": chord,
    }


def extract_gesture_features(raw_points):
    """Extract named, JSON-friendly geometry features.

    The returned mapping intentionally includes normalized landmarks so a
    recorder can inspect the geometry without changing the classifier API.
    ``finger_extension`` is an interpretable 0..1 score for index/middle/ring/
    pinky; it is the primary signal for the three prototype classes.
    """
    normalized, palm_scale, palm_orientation = _normalize_with_metadata(raw_points)
    metrics = {}
    extensions = []
    tips = []
    angles = []
    for name, chain in zip(FINGER_NAMES, FINGER_CHAINS):
        values = _finger_metrics(normalized, chain)
        metrics[name] = values
        extensions.append(values["straightness"])
        tips.append(values["tip_distance"])
        angles.extend((values["pip_angle_deg"], values["dip_angle_deg"]))

    thumb_angle = _angle(
        normalized[THUMB_MCP], normalized[THUMB_IP], normalized[THUMB_TIP]
    )
    thumb_tip_distance = _distance(normalized[WRIST], normalized[THUMB_TIP])
    return {
        "normalized_landmarks": normalized,
        "finger_extension": extensions,
        "fingertip_distance": tips,
        "joint_angles_deg": angles,
        "thumb_angle_deg": thumb_angle,
        "thumb_tip_distance": thumb_tip_distance,
        "finger_metrics": metrics,
        "palm_scale": palm_scale,
        "palm_orientation_rad": palm_orientation,
    }


def feature_vector(features):
    """Return a compact deterministic vector for optional linear models.

    No model in this MVP requires the vector, but exposing it makes future
    collection/replay scripts able to use the same feature definition.
    """
    if not isinstance(features, dict):
        features = extract_gesture_features(features)
    vector = []
    vector.extend(features.get("finger_extension", ()))
    vector.extend(features.get("fingertip_distance", ()))
    vector.extend(features.get("joint_angles_deg", ()))
    vector.append(features.get("thumb_angle_deg", 0.0) / 180.0)
    vector.append(features.get("thumb_tip_distance", 0.0))
    return [float(value) for value in vector]


# Friendly aliases for simple host scripts and future callers.
extract_features = extract_gesture_features
normalize = normalize_landmarks
