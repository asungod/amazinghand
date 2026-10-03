import unittest

from host.four_finger_config_rules import (
    EXPECTED_GRIP_POSES,
    EXPECTED_FOUR_FINGER_ROLES,
    validate_four_finger_fixture,
    validate_pose_coverage,
    validate_role_set,
)


FIXTURE_CLASS_TO_POSE = {
    39: "CYLINDRICAL_GRASP",
    41: "POWER_GRASP",
    65: "PRECISION_GRASP",
}


def role_fixture(*, calibrated=True):
    return [
        {"role": role, "servo_id": index, "calibrated": calibrated}
        for index, role in enumerate(EXPECTED_FOUR_FINGER_ROLES, start=101)
    ]


def pose_fixture():
    return {
        pose_name: {role: 511 for role in EXPECTED_FOUR_FINGER_ROLES}
        for pose_name in FIXTURE_CLASS_TO_POSE.values()
    }


class FourFingerConfigRuleTests(unittest.TestCase):
    def test_fixture_has_exactly_eight_unique_logical_roles(self):
        roles = [row["role"] for row in role_fixture()]
        self.assertEqual(len(roles), 8)
        self.assertEqual(len(set(roles)), 8)
        self.assertEqual(set(roles), set(EXPECTED_FOUR_FINGER_ROLES))

    def test_complete_fixture_is_structurally_valid(self):
        ok, errors = validate_four_finger_fixture(role_fixture(), pose_fixture())
        self.assertTrue(ok)
        self.assertEqual(errors, [])

    def test_each_supported_class_pose_covers_all_eight_roles(self):
        poses = pose_fixture()
        self.assertEqual(set(FIXTURE_CLASS_TO_POSE), {39, 41, 65})
        for class_id, pose_name in FIXTURE_CLASS_TO_POSE.items():
            with self.subTest(class_id=class_id, pose_name=pose_name):
                self.assertEqual(
                    set(poses[pose_name]), set(EXPECTED_FOUR_FINGER_ROLES)
                )
        self.assertEqual(validate_pose_coverage(poses), [])

    def test_missing_role_fails_closed(self):
        rows = role_fixture()[:-1]
        errors = validate_role_set(rows)
        self.assertIn("exactly 8 logical servo roles are required", errors)
        self.assertIn("role set must match F1..F4 proximal/distal roles", errors)

    def test_duplicate_role_fails_closed(self):
        rows = role_fixture()
        rows[1]["role"] = rows[0]["role"]
        errors = validate_role_set(rows)
        self.assertIn("duplicate logical servo role", errors)
        self.assertIn("role set must match F1..F4 proximal/distal roles", errors)

    def test_duplicate_id_fails_closed(self):
        rows = role_fixture()
        rows[1]["servo_id"] = rows[0]["servo_id"]
        self.assertIn("duplicate fixture servo_id", validate_role_set(rows))

    def test_missing_ids_fail_closed(self):
        rows = role_fixture()
        rows[0]["servo_id"] = None
        self.assertIn("every role must have a fixture servo_id", validate_role_set(rows))
        for row in rows:
            row["servo_id"] = ""
        self.assertIn("every role must have a fixture servo_id", validate_role_set(rows))

    def test_illegal_ids_fail_closed(self):
        for value in (True, 0, 254):
            rows = role_fixture()
            rows[0]["servo_id"] = value
            self.assertIn(
                "fixture servo_id must be an integer in 1..253",
                validate_role_set(rows),
            )

    def test_uncalibrated_role_fails_closed(self):
        self.assertIn(
            "every role must be explicitly calibrated before execution",
            validate_role_set(role_fixture(calibrated=False)),
        )

    def test_pose_missing_role_fails_closed(self):
        poses = pose_fixture()
        poses["POWER_GRASP"].pop("F4_DISTAL")
        errors = validate_pose_coverage(poses)
        self.assertEqual(errors, ["pose 'POWER_GRASP' must cover all 8 logical roles"])

    def test_missing_empty_and_unknown_pose_sets_fail_closed(self):
        self.assertEqual(
            validate_pose_coverage({}),
            ["pose set must match the 3 supported grip poses"],
        )
        poses = pose_fixture()
        poses.pop("POWER_GRASP")
        self.assertIn("pose set must match the 3 supported grip poses", validate_pose_coverage(poses))
        poses = pose_fixture()
        poses["UNKNOWN_GRASP"] = {role: 511 for role in EXPECTED_FOUR_FINGER_ROLES}
        self.assertIn("pose set must match the 3 supported grip poses", validate_pose_coverage(poses))

    def test_fixture_pose_names_remain_frozen(self):
        self.assertEqual(
            EXPECTED_GRIP_POSES,
            ("CYLINDRICAL_GRASP", "POWER_GRASP", "PRECISION_GRASP"),
        )


if __name__ == "__main__":
    unittest.main()
