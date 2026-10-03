import unittest

from host.eight_servo_plan_model import (
    ServoFeedback,
    StructuralPlanResult,
    validate_structural_plan,
)
from host.four_finger_config_rules import EXPECTED_FOUR_FINGER_ROLES


IDS = {role: index + 1 for index, role in enumerate(EXPECTED_FOUR_FINGER_ROLES)}
LIMITS = {role: (100, 900) for role in EXPECTED_FOUR_FINGER_ROLES}
TARGETS = {role: 500 for role in EXPECTED_FOUR_FINGER_ROLES}
FEEDBACK = {
    servo_id: ServoFeedback(servo_id=servo_id, position_raw=500, age_ms=20)
    for servo_id in IDS.values()
}


def valid_result():
    return validate_structural_plan(IDS, TARGETS, LIMITS, FEEDBACK)


class EightServoPlanModelTests(unittest.TestCase):
    def test_complete_snapshot_is_structurally_valid_only(self):
        result = valid_result()
        self.assertIsInstance(result, StructuralPlanResult)
        self.assertTrue(result.structural_plan_valid)
        self.assertEqual(result.errors, ())
        self.assertFalse(hasattr(result, "packets"))
        self.assertFalse(hasattr(result, "targets_by_id"))

    def test_missing_role_id_fails_closed(self):
        ids = dict(IDS)
        ids.pop(EXPECTED_FOUR_FINGER_ROLES[-1])
        result = validate_structural_plan(ids, TARGETS, LIMITS, FEEDBACK)
        self.assertFalse(result.valid)
        self.assertTrue(any("missing roles" in error for error in result.errors))

    def test_duplicate_role_id_fails_closed(self):
        ids = dict(IDS)
        ids[EXPECTED_FOUR_FINGER_ROLES[1]] = ids[EXPECTED_FOUR_FINGER_ROLES[0]]
        result = validate_structural_plan(ids, TARGETS, LIMITS, FEEDBACK)
        self.assertFalse(result.valid)
        self.assertIn("role_to_servo_id contains duplicate servo IDs", result.errors)

    def test_missing_feedback_id_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback.pop(8)
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertTrue(any("feedback missing IDs" in error for error in result.errors))

    def test_extra_feedback_id_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback[99] = ServoFeedback(servo_id=99, position_raw=500, age_ms=0)
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn("feedback has unknown IDs: 99", result.errors)

    def test_stale_feedback_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback[3] = ServoFeedback(servo_id=3, position_raw=500, age_ms=151)
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn("F2_PROXIMAL: feedback is stale", result.errors)

    def test_failed_feedback_item_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback[4] = ServoFeedback(
            servo_id=4, position_raw=500, age_ms=20, item_ok=False
        )
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn("F2_DISTAL: per-item feedback failure", result.errors)

    def test_read_failure_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback[5] = ServoFeedback(
            servo_id=5, position_raw=500, age_ms=20, read_ok=False
        )
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn("F3_PROXIMAL: feedback read failed", result.errors)

    def test_target_out_of_range_fails_closed(self):
        targets = dict(TARGETS)
        targets[EXPECTED_FOUR_FINGER_ROLES[0]] = 901
        result = validate_structural_plan(IDS, targets, LIMITS, FEEDBACK)
        self.assertFalse(result.valid)
        self.assertIn(
            "F1_PROXIMAL: target is outside offline soft limits", result.errors
        )

    def test_feedback_position_out_of_range_fails_closed(self):
        feedback = dict(FEEDBACK)
        feedback[6] = ServoFeedback(servo_id=6, position_raw=99, age_ms=20)
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn(
            "F3_DISTAL: feedback position is outside offline soft limits",
            result.errors,
        )

    def test_feedback_key_and_payload_id_must_match(self):
        feedback = dict(FEEDBACK)
        feedback[7] = ServoFeedback(servo_id=8, position_raw=500, age_ms=20)
        result = validate_structural_plan(IDS, TARGETS, LIMITS, feedback)
        self.assertFalse(result.valid)
        self.assertIn("F4_PROXIMAL: feedback servo_id does not match map key", result.errors)

    def test_unknown_role_and_malformed_limits_fail_closed(self):
        targets = dict(TARGETS)
        targets["UNKNOWN"] = 500
        limits = dict(LIMITS)
        limits[EXPECTED_FOUR_FINGER_ROLES[2]] = (900, 100)
        result = validate_structural_plan(IDS, targets, limits, FEEDBACK)
        self.assertFalse(result.valid)
        self.assertTrue(any("unknown roles" in error for error in result.errors))
        self.assertIn(
            "F2_PROXIMAL: limits must be integer min/max within 0..1023",
            result.errors,
        )

    def test_boolean_id_and_target_are_not_accepted_as_integers(self):
        ids = dict(IDS)
        ids[EXPECTED_FOUR_FINGER_ROLES[0]] = True
        targets = dict(TARGETS)
        targets[EXPECTED_FOUR_FINGER_ROLES[1]] = False
        result = validate_structural_plan(ids, targets, LIMITS, FEEDBACK)
        self.assertFalse(result.valid)
        self.assertIn("every servo ID must be an integer in 1..253", result.errors)
        self.assertIn("F1_DISTAL: target must be an integer", result.errors)


if __name__ == "__main__":
    unittest.main()

