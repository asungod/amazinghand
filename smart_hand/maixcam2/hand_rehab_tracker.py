"""Scale-independent hand open/close metric and repetition tracker.

No Maix imports and no hardware writes.  The metric uses the four non-thumb
finger polylines from the standard 21-point hand-landmark order.
"""

import math

HAND_POINT_COUNT = 21
OPEN_THRESHOLD = 0.88
CLOSED_THRESHOLD = 0.72


def _distance(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _coerce_points(raw_points):
    if not isinstance(raw_points, (list, tuple)):
        raise ValueError("landmarks must be a list or tuple")
    if len(raw_points) == HAND_POINT_COUNT:
        points = []
        for point in raw_points:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                raise ValueError("each landmark needs x and y")
            points.append((float(point[0]), float(point[1])))
        return points
    if len(raw_points) == HAND_POINT_COUNT * 3:
        return [
            (float(raw_points[index]), float(raw_points[index + 1]))
            for index in range(0, len(raw_points), 3)
        ]
    raise ValueError("expected 21 points or 63 xyz values")


def hand_openness(raw_points):
    """Return 0..1 finger straightness; 1 is geometrically straight."""
    points = _coerce_points(raw_points)
    scores = []
    for mcp, pip, dip, tip in (
        (5, 6, 7, 8),
        (9, 10, 11, 12),
        (13, 14, 15, 16),
        (17, 18, 19, 20),
    ):
        path = (
            _distance(points[mcp], points[pip])
            + _distance(points[pip], points[dip])
            + _distance(points[dip], points[tip])
        )
        if path <= 1e-6:
            raise ValueError("degenerate finger landmarks")
        chord = _distance(points[mcp], points[tip])
        scores.append(max(0.0, min(1.0, chord / path)))
    return sum(scores) / len(scores)


def classify_openness(score):
    if score >= OPEN_THRESHOLD:
        return "OPEN"
    if score <= CLOSED_THRESHOLD:
        return "CLOSED"
    return "MID"


class RepetitionTracker:
    """Count OPEN -> CLOSED -> OPEN cycles with stable-frame hysteresis."""

    def __init__(self, stable_frames=3):
        if stable_frames < 1:
            raise ValueError("stable_frames must be positive")
        self.stable_frames = int(stable_frames)
        self.phase = "WAIT_OPEN"
        self.repetitions = 0
        self._candidate = None
        self._candidate_frames = 0

    def observe(self, posture):
        if posture not in ("OPEN", "MID", "CLOSED", None):
            raise ValueError("unknown posture")
        if posture in (None, "MID"):
            self._candidate = None
            self._candidate_frames = 0
            return False
        if posture != self._candidate:
            self._candidate = posture
            self._candidate_frames = 1
        else:
            self._candidate_frames += 1
        if self._candidate_frames < self.stable_frames:
            return False

        completed = False
        if self.phase == "WAIT_OPEN" and posture == "OPEN":
            self.phase = "WAIT_CLOSE"
        elif self.phase == "WAIT_CLOSE" and posture == "CLOSED":
            self.phase = "WAIT_REOPEN"
        elif self.phase == "WAIT_REOPEN" and posture == "OPEN":
            self.repetitions += 1
            self.phase = "WAIT_CLOSE"
            completed = True
        self._candidate_frames = 0
        return completed
