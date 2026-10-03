"""Recorded outputs for the reported V-as-open and L-miss failures.

The original suite locked the pre-fix failures.  After the narrow L-gate
fix, three affected tests below assert the corrected L result/stability;
the other eight still document unchanged behavior and unresolved failures.
Passing this suite is NOT evidence that every reported bug is fixed or
that device accuracy improved.  The original suite and classifier remain
in outputs/Grok_Gesture_Review_2026-10-01/pre_l_gate_fix; cases.json and
reproduce.py retain the original baseline without rewriting observations.

Run from the smart_hand directory:

    python -m unittest tests.test_gesture_misclassification_evidence -v
"""

import math
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from gesture_classifier import (  # noqa: E402
    ERROR_LOW_CONFIDENCE,
    ERROR_OK,
    L_SHAPE,
    OPEN_PALM,
    POINT,
    UNKNOWN,
    V_SIGN,
    GestureClassifier,
    _classify_features,
    classify_gesture,
)
from gesture_features import extract_gesture_features  # noqa: E402
from hand_rehab_tracker import classify_openness, hand_openness  # noqa: E402


PALM_NORMAL = (0.0, 0.0, 1.0)
MCPS = {
    5: (-0.028, 0.078, 0.0),
    9: (-0.006, 0.084, 0.0),
    13: (0.014, 0.078, 0.0),
    17: (0.032, 0.066, 0.0),
}
ALONG = {
    5: (-0.16, 1.0, 0.0),
    9: (0.0, 1.0, 0.0),
    13: (0.12, 1.0, 0.0),
    17: (0.28, 1.0, 0.0),
}
LENGTHS = {
    5: (0.039, 0.024, 0.018),
    9: (0.043, 0.027, 0.019),
    13: (0.037, 0.024, 0.017),
    17: (0.030, 0.018, 0.014),
}
LOOSE_V_FLEX_DEG = {
    "index": (10.0, 6.0),
    "middle": (10.0, 6.0),
    "ring": (78.0, 25.0),
    "pinky": (74.0, 20.0),
}
TUCKED_L_FLEX_DEG = {
    "index": (8.0, 4.0),
    "middle": (105.0, 80.0),
    "ring": (100.0, 75.0),
    "pinky": (95.0, 70.0),
}

# Rounded orthographic projections previously measured for the two poses.
LOOSE_V_FRONTAL_XY = (
    (0.0, 0.0),
    (-0.016, 0.02),
    (-0.032, 0.03),
    (-0.0601, 0.0403),
    (-0.0802, 0.0477),
    (-0.028, 0.078),
    (-0.0342, 0.1165),
    (-0.0379, 0.1398),
    (-0.0406, 0.1569),
    (-0.006, 0.084),
    (-0.006, 0.127),
    (-0.006, 0.1536),
    (-0.006, 0.1719),
    (0.014, 0.078),
    (0.0184, 0.1147),
    (0.019, 0.1197),
    (0.0185, 0.1159),
    (0.032, 0.066),
    (0.0401, 0.0949),
    (0.0414, 0.0997),
    (0.0412, 0.0987),
)
TUCKED_L_YAW65_XY = (
    (0.0, 0.0),
    (-0.0013, 0.02),
    (-0.0045, 0.03),
    (-0.0142, 0.0403),
    (-0.0226, 0.0493),
    (-0.0118, 0.078),
    (-0.0144, 0.1165),
    (-0.013, 0.14),
    (-0.0108, 0.1574),
    (-0.0025, 0.084),
    (-0.0025, 0.127),
    (0.0211, 0.12),
    (0.0196, 0.1011),
    (0.0059, 0.078),
    (0.0078, 0.1147),
    (0.029, 0.1106),
    (0.0295, 0.0938),
    (0.0135, 0.066),
    (0.0169, 0.0949),
    (0.033, 0.0934),
    (0.0348, 0.0804),
)


def _normalize(vector):
    length = math.sqrt(sum(component * component for component in vector))
    return tuple(component / length for component in vector)


def _add(origin, direction, scale):
    return tuple(origin[index] + direction[index] * scale for index in range(3))


def _cross(left, right):
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _rodrigues(vector, axis, theta):
    axis = _normalize(axis)
    cosine, sine = math.cos(theta), math.sin(theta)
    crossed = _cross(axis, vector)
    dot = sum(axis[index] * vector[index] for index in range(3))
    return tuple(
        vector[index] * cosine
        + crossed[index] * sine
        + axis[index] * dot * (1.0 - cosine)
        for index in range(3)
    )


def _rot_x(point, angle):
    cosine, sine = math.cos(angle), math.sin(angle)
    return (
        point[0],
        point[1] * cosine - point[2] * sine,
        point[1] * sine + point[2] * cosine,
    )


def _rot_y(point, angle):
    cosine, sine = math.cos(angle), math.sin(angle)
    return (
        point[0] * cosine + point[2] * sine,
        point[1],
        -point[0] * sine + point[2] * cosine,
    )


def _finger_chain(mcp, along, lengths, flex_pip, flex_dip):
    """Flex a finger toward +Z, the camera, when the palm faces the camera."""
    axis = _cross(along, PALM_NORMAL)
    pip = _add(mcp, along, lengths[0])
    middle = _rodrigues(along, axis, flex_pip)
    dip = _add(pip, middle, lengths[1])
    tip_direction = _rodrigues(middle, axis, flex_dip)
    tip = _add(dip, tip_direction, lengths[2])
    return pip, dip, tip


def build_hand(flex_deg, thumb_ip_deg):
    """Return 21 unprojected (x, y, z) landmarks for one fixed right-hand model."""
    points = [(0.0, 0.0, 0.0)] * 21
    points[0] = (0.0, 0.0, 0.0)
    points[1] = (-0.016, 0.020, 0.006)
    points[2] = (-0.032, 0.030, 0.010)
    thumb_along = _normalize((-0.95, 0.35, 0.08))
    thumb_axis = _cross(thumb_along, PALM_NORMAL)
    points[3] = _add(points[2], thumb_along, 0.030)
    tip_direction = _rodrigues(
        thumb_along, thumb_axis, math.radians(180.0 - thumb_ip_deg)
    )
    points[4] = _add(points[3], tip_direction, 0.026)
    for base, name in ((5, "index"), (9, "middle"), (13, "ring"), (17, "pinky")):
        flex_pip, flex_dip = flex_deg[name]
        pip, dip, tip = _finger_chain(
            MCPS[base],
            _normalize(ALONG[base]),
            LENGTHS[base],
            math.radians(flex_pip),
            math.radians(flex_dip),
        )
        points[base] = MCPS[base]
        points[base + 1] = pip
        points[base + 2] = dip
        points[base + 3] = tip
    return points


def project_xy(points, yaw_deg=0.0, pitch_deg=0.0):
    """Orthographic view: yaw around Y, then pitch around X, then drop Z."""
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    projected = []
    for point in points:
        point = _rot_y(point, yaw)
        point = _rot_x(point, pitch)
        projected.append((point[0], point[1]))
    return projected


def loose_v_frontal():
    return project_xy(build_hand(LOOSE_V_FLEX_DEG, thumb_ip_deg=150.0))


def tucked_l(yaw_deg, thumb_ip_deg):
    return project_xy(
        build_hand(TUCKED_L_FLEX_DEG, thumb_ip_deg=thumb_ip_deg),
        yaw_deg=yaw_deg,
    )


def rule_features(extension, tip_gap, thumb_angle, thumb_distance):
    points = [(0.0, 0.0) for _ in range(21)]
    points[4] = (0.2, 0.2)
    points[8] = (0.0, 0.0)
    points[12] = (float(tip_gap), 0.0)
    return {
        "finger_extension": tuple(extension),
        "normalized_landmarks": points,
        "thumb_angle_deg": float(thumb_angle),
        "thumb_tip_distance": float(thumb_distance),
    }


def _polyline_ratio(points, indexes, dimensions):
    def distance(start, end):
        return math.sqrt(
            sum((start[axis] - end[axis]) ** 2 for axis in range(dimensions))
        )

    joints = [points[index] for index in indexes]
    segments = [
        distance(joints[index], joints[index + 1]) for index in range(3)
    ]
    path = sum(segments)
    return distance(joints[0], joints[3]) / path, segments


def _round_xy(points):
    return tuple((round(point[0], 4), round(point[1], 4)) for point in points)


def _easy_shape(pattern):
    """The straight-or-fully-folded fixture used by test_sign_core."""
    points = [(0.0, 0.0) for _ in range(21)]
    for (base, x_position), folded in zip(
        ((5, 1.0), (9, 2.0), (13, 3.0), (17, 4.0)), pattern
    ):
        points[base] = (x_position, 0.0)
        points[base + 1] = (x_position, 1.0)
        points[base + 2] = ((x_position + 0.8), 1.0) if folded else (x_position, 2.0)
        points[base + 3] = ((x_position + 0.8), 0.2) if folded else (x_position, 3.0)
    return points


class GestureMisclassificationEvidenceTests(unittest.TestCase):
    def test_narrow_tip_gap_lets_partial_v_become_open_palm(self):
        narrow = rule_features((0.95, 0.93, 0.74, 0.70), 0.20, 100.0, 0.4)
        wide_enough = rule_features((0.95, 0.93, 0.74, 0.70), 0.22, 100.0, 0.4)
        narrow_label, narrow_score, narrow_details = _classify_features(narrow)
        blocked_label, blocked_score, blocked_details = _classify_features(wide_enough)

        self.assertEqual(narrow_label, OPEN_PALM)
        self.assertAlmostEqual(narrow_score, 0.772, places=3)
        self.assertFalse(narrow_details["v_like"])
        self.assertAlmostEqual(narrow_details["tip_gap"], 0.20, places=2)

        self.assertEqual(blocked_label, UNKNOWN)
        self.assertAlmostEqual(blocked_score, 0.772, places=3)
        self.assertTrue(blocked_details["v_like"])
        self.assertAlmostEqual(blocked_details["tip_gap"], 0.22, places=2)

    def test_extension_just_past_existing_guard_is_open_palm(self):
        guarded = rule_features((0.96, 0.94, 0.79, 0.78), 0.50, 100.0, 0.4)
        accepted = rule_features((0.96, 0.94, 0.82, 0.80), 0.50, 100.0, 0.4)
        guarded_label, guarded_score, guarded_details = _classify_features(guarded)
        accepted_label, accepted_score, accepted_details = _classify_features(accepted)

        self.assertEqual(guarded_label, UNKNOWN)
        self.assertNotEqual(guarded_label, OPEN_PALM)
        self.assertAlmostEqual(guarded_score, 0.828, places=3)
        self.assertTrue(guarded_details["v_like"])

        self.assertEqual(accepted_label, OPEN_PALM)
        self.assertAlmostEqual(accepted_score, 0.844, places=3)
        self.assertFalse(accepted_details["v_like"])

    def test_loose_v_projection_matches_frozen_points_and_open_palm(self):
        points = loose_v_frontal()
        self.assertEqual(_round_xy(points), LOOSE_V_FRONTAL_XY)
        result = classify_gesture(points)
        features = extract_gesture_features(points)

        self.assertEqual(result.gesture_id, OPEN_PALM)
        self.assertTrue(result.valid)
        self.assertEqual(result.error_code, ERROR_OK)
        self.assertAlmostEqual(result.confidence, 0.894, places=3)
        self.assertFalse(result["v_like"])
        self.assertAlmostEqual(result["open_score"], 0.894, places=3)
        self.assertAlmostEqual(result["v_score"], 0.579, places=3)
        self.assertAlmostEqual(result["tip_gap"], 0.472, places=3)
        self.assertEqual(
            tuple(round(value, 3) for value in features["finger_extension"]),
            (1.0, 1.0, 0.833, 0.946),
        )
        # joint_angles_deg order is pip, dip for index, middle, ring, pinky.
        self.assertAlmostEqual(features["joint_angles_deg"][5], 0.0, places=1)
        self.assertAlmostEqual(features["joint_angles_deg"][7], 0.0, places=1)

        openness = hand_openness(points)
        self.assertAlmostEqual(openness, 0.945, places=3)
        self.assertEqual(classify_openness(openness), "OPEN")

    def test_same_loose_v_loses_its_bend_when_z_is_dropped(self):
        raw = build_hand(LOOSE_V_FLEX_DEG, thumb_ip_deg=150.0)
        ratio_3d, segments_3d = _polyline_ratio(raw, (13, 14, 15, 16), 3)
        ratio_2d, segments_2d = _polyline_ratio(raw, (13, 14, 15, 16), 2)

        self.assertAlmostEqual(ratio_3d, 0.709, places=3)
        self.assertAlmostEqual(ratio_2d, 0.833, places=3)
        self.assertEqual(
            [round(value, 4) for value in segments_3d],
            [0.037, 0.024, 0.017],
        )
        self.assertEqual(
            [round(value, 4) for value in segments_2d],
            [0.037, 0.005, 0.0038],
        )

        flat_without_depth = []
        flat_with_depth = []
        for x_position, y_position in loose_v_frontal():
            flat_without_depth.extend((x_position, y_position, 0.0))
            flat_with_depth.extend((x_position, y_position, 5.0))
        self.assertEqual(
            extract_gesture_features(flat_without_depth)["finger_extension"],
            extract_gesture_features(flat_with_depth)["finger_extension"],
        )
        self.assertEqual(
            classify_gesture(flat_with_depth).gesture_id,
            OPEN_PALM,
        )

    def test_loose_v_hold_becomes_stable_open_palm(self):
        classifier = GestureClassifier(stable_hold_ms=300)
        points = loose_v_frontal()
        first = classifier.observe(points, now_ms=0)
        middle = classifier.observe(points, now_ms=200)
        held = classifier.observe(points, now_ms=300)

        self.assertEqual(first.gesture_id, OPEN_PALM)
        self.assertEqual(first.stable_ms, 0)
        self.assertEqual(middle.stable_ms, 200)
        self.assertFalse(middle.stable)
        self.assertEqual(held.gesture_id, OPEN_PALM)
        self.assertAlmostEqual(held.confidence, 0.894, places=3)
        self.assertEqual(held.stable_ms, 300)
        self.assertTrue(held.stable)
        self.assertTrue(held.valid)

    def test_yawed_loose_v_with_gap_under_0_22_is_open_palm(self):
        points = project_xy(
            build_hand(LOOSE_V_FLEX_DEG, thumb_ip_deg=150.0),
            yaw_deg=70.0,
            pitch_deg=-30.0,
        )
        result = classify_gesture(points)
        extension = result["finger_extension"]
        contrast = min(extension[0], extension[1]) - max(extension[2], extension[3])

        self.assertEqual(result.gesture_id, OPEN_PALM)
        self.assertAlmostEqual(result.confidence, 0.851, places=3)
        self.assertFalse(result["v_like"])
        self.assertAlmostEqual(result["tip_gap"], 0.199, places=3)
        self.assertGreaterEqual(contrast, 0.14)
        self.assertEqual(
            tuple(round(value, 3) for value in extension),
            (0.993, 0.993, 0.788, 0.835),
        )

    def test_easy_folded_fixture_is_still_v_sign(self):
        result = classify_gesture(_easy_shape((False, False, True, True)))
        features = extract_gesture_features(
            _easy_shape((False, False, True, True))
        )
        self.assertEqual(result.gesture_id, V_SIGN)
        self.assertEqual(
            tuple(round(value, 3) for value in features["finger_extension"]),
            (1.0, 1.0, 0.317, 0.317),
        )
        self.assertAlmostEqual(result["tip_gap"], 0.400, places=3)

    def test_tucked_l_yaw_65_passes_despite_ineligible_v_score(self):
        frontal = classify_gesture(tucked_l(0.0, 180.0))
        yawed_points = tucked_l(65.0, 180.0)
        self.assertEqual(_round_xy(yawed_points), TUCKED_L_YAW65_XY)
        yawed = classify_gesture(yawed_points)

        self.assertEqual(frontal.gesture_id, L_SHAPE)
        self.assertAlmostEqual(frontal.confidence, 0.817, places=3)
        self.assertTrue(frontal.valid)

        self.assertEqual(yawed.gesture_id, L_SHAPE)
        self.assertTrue(yawed.valid)
        self.assertEqual(yawed.error_code, ERROR_OK)
        self.assertEqual(yawed["top_candidate"], L_SHAPE)
        self.assertAlmostEqual(yawed.confidence, 0.707, places=3)
        self.assertAlmostEqual(yawed["v_score"], 0.719, places=3)
        self.assertAlmostEqual(yawed["l_shape_score"], 0.707, places=3)
        self.assertGreater(yawed["v_score"], yawed["l_shape_score"])
        self.assertFalse(yawed["v_like"])
        self.assertAlmostEqual(yawed["tip_gap"], 0.829, places=3)
        self.assertAlmostEqual(yawed["thumb_extension"], 0.677, places=3)
        self.assertGreaterEqual(yawed["thumb_extension"], 0.55)
        self.assertEqual(
            tuple(round(value, 3) for value in yawed["finger_extension"]),
            (0.997, 0.323, 0.377, 0.439),
        )

    def test_qualified_yawed_l_does_not_reset_stable_hold(self):
        classifier = GestureClassifier(stable_hold_ms=300)
        frontal = tucked_l(0.0, 180.0)
        yawed = tucked_l(65.0, 180.0)
        started = classifier.observe(frontal, now_ms=0)
        held = classifier.observe(frontal, now_ms=250)
        self.assertEqual(started.gesture_id, L_SHAPE)
        self.assertEqual(started.stable_ms, 0)
        rotated = classifier.observe(yawed, now_ms=320)
        continued = classifier.observe(frontal, now_ms=600)

        self.assertEqual(held.gesture_id, L_SHAPE)
        self.assertEqual(held.stable_ms, 250)
        self.assertEqual(rotated.gesture_id, L_SHAPE)
        self.assertEqual(rotated.stable_ms, 320)
        self.assertTrue(rotated.valid)
        self.assertTrue(rotated.stable)
        self.assertEqual(continued.gesture_id, L_SHAPE)
        self.assertEqual(continued.stable_ms, 600)
        self.assertTrue(continued.stable)

    def test_yawed_hooked_thumb_l_is_classified_as_point(self):
        result = classify_gesture(tucked_l(40.0, 130.0))
        self.assertEqual(result.gesture_id, POINT)
        self.assertTrue(result.valid)
        self.assertEqual(result.error_code, ERROR_OK)
        self.assertAlmostEqual(result.confidence, 0.783, places=3)
        self.assertAlmostEqual(result["point_score"], 0.783, places=3)
        self.assertAlmostEqual(result["l_shape_score"], 0.599, places=3)
        self.assertAlmostEqual(result["v_score"], 0.725, places=3)
        self.assertAlmostEqual(result["thumb_extension"], 0.042, places=3)
        self.assertEqual(
            tuple(round(value, 3) for value in result["finger_extension"]),
            (0.998, 0.29, 0.342, 0.412),
        )

    def test_visible_thumb_ip_of_120_degrees_cannot_reach_l_gate(self):
        folded = (0.96, 0.30, 0.28, 0.26)
        at_150 = _classify_features(rule_features(folded, 0.80, 150.0, 1.40))
        at_140 = _classify_features(rule_features(folded, 0.80, 140.0, 1.40))
        at_120 = _classify_features(rule_features(folded, 0.80, 120.0, 1.80))

        self.assertEqual(at_150[0], L_SHAPE)
        self.assertAlmostEqual(at_150[2]["thumb_extension"], 0.764, places=3)

        self.assertEqual(at_140[0], L_SHAPE)
        self.assertAlmostEqual(at_140[1], at_140[2]["l_shape_score"], places=9)
        self.assertAlmostEqual(at_140[2]["thumb_extension"], 0.645, places=3)
        self.assertGreaterEqual(at_140[2]["thumb_extension"], 0.55)
        self.assertGreater(at_140[2]["v_score"], at_140[2]["l_shape_score"])

        self.assertEqual(at_120[0], UNKNOWN)
        self.assertAlmostEqual(at_120[2]["thumb_extension"], 0.409, places=3)
        self.assertLess(at_120[2]["thumb_extension"], 0.55)

    def test_l_recovery_keeps_every_existing_pattern_gate(self):
        eligible = rule_features((0.96, 0.30, 0.28, 0.26), 0.80, 140.0, 1.40)
        self.assertEqual(_classify_features(eligible)[0], L_SHAPE)
        for extension in (
            (0.71, 0.30, 0.28, 0.26),  # index not extended
            (0.96, 0.63, 0.28, 0.26),  # middle not folded
            (0.96, 0.30, 0.63, 0.26),  # ring not folded
            (0.96, 0.30, 0.28, 0.63),  # pinky not folded
            (0.72, 0.62, 0.62, 0.62),  # pattern fits, score insufficient
        ):
            with self.subTest(extension=extension):
                invalid = dict(eligible, finger_extension=extension)
                self.assertNotEqual(_classify_features(invalid)[0], L_SHAPE)
        # Deliberately between POINT's <= .52 and L's >= .55 gates.
        uncertain = rule_features((0.96, 0.30, 0.28, 0.26), 0.80, 130.5, 1.40)
        result = _classify_features(uncertain)
        self.assertGreater(result[2]["thumb_extension"], 0.52)
        self.assertLess(result[2]["thumb_extension"], 0.55)
        self.assertEqual(result[0], UNKNOWN)

    def test_recovered_l_mirror_and_transform_preserve_label(self):
        points = tucked_l(65.0, 180.0)
        for mirrored in (False, True):
            transformed = [
                ((-x if mirrored else x) * 2.0 + 0.3, y * 2.0 - 0.4)
                for x, y in points
            ]
            with self.subTest(mirrored=mirrored):
                result = classify_gesture(transformed)
                self.assertEqual(result.gesture_id, L_SHAPE)
                self.assertTrue(result.valid)
                self.assertAlmostEqual(result.confidence, 0.707, places=3)

    def test_genuinely_unknown_frame_still_resets_l_stability(self):
        classifier = GestureClassifier(stable_hold_ms=300)
        frontal = tucked_l(0.0, 180.0)
        classifier.observe(frontal, now_ms=0)
        classifier.observe(frontal, now_ms=250)
        unknown = classifier.observe(
            _easy_shape((False, True, False, True)), now_ms=320
        )
        self.assertEqual(unknown.gesture_id, UNKNOWN)
        self.assertFalse(unknown.valid)
        self.assertEqual(unknown.stable_ms, 0)
        restarted = classifier.observe(frontal, now_ms=600)
        self.assertEqual(restarted.gesture_id, L_SHAPE)
        self.assertEqual(restarted.stable_ms, 0)
        self.assertFalse(restarted.stable)


if __name__ == "__main__":
    unittest.main()
