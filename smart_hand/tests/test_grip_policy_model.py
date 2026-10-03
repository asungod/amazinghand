import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from grip_policy_model import (  # noqa: E402
    NO_ACTION,
    allowed_class_ids,
    decide_grip,
)


class GripPolicyTests(unittest.TestCase):
    def test_three_demo_classes_map_to_distinct_intents(self):
        cases = {
            39: ("bottle", "CYLINDRICAL_GRASP"),
            41: ("cup", "POWER_GRASP"),
            65: ("remote", "PRECISION_GRASP"),
        }
        for class_id, (object_name, action) in cases.items():
            with self.subTest(class_id=class_id):
                result = decide_grip((class_id, 320, 240, 80, 120, 90))
                self.assertEqual(result["object"], object_name)
                self.assertEqual(result["action"], action)
                self.assertEqual(result["reason"], "accepted")

    def test_confidence_boundary_is_explicit(self):
        self.assertEqual(
            decide_grip((39, 320, 240, 80, 120, 69))["reason"],
            "low_confidence",
        )
        self.assertEqual(
            decide_grip((39, 320, 240, 80, 120, 70))["action"],
            "CYLINDRICAL_GRASP",
        )

    def test_unsupported_class_never_creates_an_action(self):
        result = decide_grip((47, 320, 240, 80, 120, 99))
        self.assertEqual(result["action"], NO_ACTION)
        self.assertEqual(result["reason"], "unsupported_class")

    def test_invalid_payloads_fail_closed(self):
        invalid_payloads = (
            None,
            (39, 1, 2, 3, 4),
            (39, 1, 2, 0, 4, 90),
            (39, -1, 2, 3, 4, 90),
            (39, 1, 2, 3, 4, 101),
            (39, 1, 2, 3, 4, 90.0),
            (39, 65536, 2, 3, 4, 90),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                result = decide_grip(payload)
                self.assertEqual(result["action"], NO_ACTION)
                self.assertEqual(result["reason"], "invalid_payload")

    def test_minimum_confidence_configuration_is_checked(self):
        for invalid in (-1, 101, 70.0, "70"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    decide_grip((39, 1, 2, 3, 4, 90), invalid)

    def test_allowed_class_ids_are_stable_for_maix_configuration(self):
        self.assertEqual(allowed_class_ids(), (39, 41, 65))


if __name__ == "__main__":
    unittest.main()

