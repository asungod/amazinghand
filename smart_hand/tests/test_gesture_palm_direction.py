"""Synthetic regressions: straight-looking chains can point into the palm.

No private device coordinates are embedded in this public-capable test file.
"""
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "maixcam2"))
from gesture_classifier import classify_gesture, _palm_directed_extension
from gesture_features import extract_gesture_features, feature_vector
from sign_landmark_capture import CaptureDiagnostics


def palm_shape(folded=(False, False, True, True)):
    points = [(0.0, 0.0)] * 21
    for base, x, y, back in zip((5, 9, 13, 17), (-0.4, 0.0, 0.4, 0.7),
                               (1.0, 1.0, 1.0, 0.8), folded):
        points[base] = (x, y)
        sign = -1 if back else 1
        for step, distance in enumerate((0.3, 0.5, 0.7), 1):
            points[base + step] = (x, y + sign * distance)
    return points


class PalmDirectionTests(unittest.TestCase):
    def test_collinear_inward_pair_is_v_not_open(self):
        points = palm_shape()
        features = extract_gesture_features(points)
        self.assertTrue(all(x > 0.99 for x in features["finger_extension"]))
        self.assertTrue(all(x > 179.9 for x in features["joint_angles_deg"]))
        result = classify_gesture(points)
        self.assertEqual(result.gesture_id, "V_SIGN")
        self.assertEqual(result.finger_extension[2:], [0.0, 0.0])
        self.assertTrue(all(x > 0.99 for x in result.finger_straightness))

    def test_outward_open_control_is_not_rejected(self):
        self.assertEqual(classify_gesture(palm_shape((False,) * 4)).gesture_id, "OPEN_PALM")

    def test_all_inward_and_one_outward_remain_distinct(self):
        self.assertEqual(classify_gesture(palm_shape((True,) * 4)).gesture_id, "FIST")
        self.assertEqual(classify_gesture(palm_shape((False, True, True, True))).gesture_id, "POINT")

    def test_rotation_mirror_translation_and_scale_invariance(self):
        for folded, expected in (((False, False, True, True), "V_SIGN"), ((False,) * 4, "OPEN_PALM")):
            for angle in (0, 0.7, 2.2, math.pi):
                for mirror in (-1, 1):
                    for scale in (0.2, 7.0):
                        c, s = math.cos(angle), math.sin(angle)
                        transformed = [(100 + scale * (mirror*x*c - y*s),
                                        55 + scale * (mirror*x*s + y*c)) for x, y in palm_shape(folded)]
                        self.assertEqual(classify_gesture(transformed).gesture_id, expected)

    def test_backward_direction_alone_does_not_force_a_fold(self):
        # Tip points backward but is farther from wrist: conservative no-op.
        points = [(0.0, 0.0)] * 21
        for base, tip in ((5, 8), (9, 12), (13, 16), (17, 20)):
            points[base] = (0.0, 1.0)
            points[tip] = (4.0, 0.5)
        self.assertEqual(_palm_directed_extension([0.95] * 4, points), [0.95] * 4)

    def test_equal_radius_boundary_does_not_force_a_fold(self):
        # Equal/boundary positions do not satisfy the strict geometric guard.
        points = [(0.0, 0.0)] * 21
        for base, tip in ((5, 8), (9, 12), (13, 16), (17, 20)):
            points[base] = points[tip] = (0.0, 1.0)
        self.assertEqual(_palm_directed_extension([0.95] * 4, points), [0.95] * 4)

    def test_feature_vector_contract_is_unchanged_and_input_not_mutated(self):
        features = extract_gesture_features(palm_shape())
        before = feature_vector(features)
        original = list(features["finger_extension"])
        _palm_directed_extension(original, features["normalized_landmarks"])
        self.assertEqual(original, features["finger_extension"])
        self.assertEqual(before, feature_vector(extract_gesture_features(palm_shape())))
        self.assertEqual(len(before), 18)

    def test_capture_records_raw_straightness_separately_from_rule_extension(self):
        capture = CaptureDiagnostics()
        row = capture.observe(palm_shape(), 0)
        self.assertEqual(row["predicted_gesture_id"], "V_SIGN")
        self.assertTrue(all(x > 0.99 for x in row["finger_extension"]))
        self.assertEqual(row["rule_finger_extension"][2:], [0.0, 0.0])
        capture.observe(None, 200)
        self.assertEqual(capture.observe(palm_shape(), 500)["stable_ms"], 0)


if __name__ == "__main__":
    unittest.main()
