import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "host"


def source(name):
    return (HOST / name).read_text(encoding="utf-8")


def load_host_module(name):
    path = HOST / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TwoServoReadinessContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nudge = load_host_module("nudge_scs0009")
        cls.sync_nudge = load_host_module("sync_nudge_scs0009_pair")
        cls.finger_smoke = load_host_module("finger_smoke_scs0009")

    def test_all_motion_tools_stop_at_50_c(self):
        names = (
            "nudge_scs0009.py",
            "sync_nudge_scs0009_pair.py",
            "center_hold_scs0009_pair.py",
            "finger_smoke_scs0009.py",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIn("MAX_TEMPERATURE_C = 50", source(name))

    def test_finger_smoke_requires_both_mechanical_references(self):
        tree = ast.parse(source("finger_smoke_scs0009.py"))
        required = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument":
                if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in ("--center1", "--center2"):
                    kwargs = {kw.arg: kw.value for kw in node.keywords}
                    if isinstance(kwargs.get("required"), ast.Constant) and kwargs["required"].value is True:
                        required.add(node.args[0].value)
                    self.assertNotIn("default", kwargs)
        self.assertEqual(required, {"--center1", "--center2"})

    def test_finger_smoke_tolerance_is_strictly_smaller_than_delta(self):
        for delta in range(2, 21):
            with self.subTest(delta=delta):
                tolerance = self.finger_smoke.compute_position_tolerance(delta)
                self.assertGreaterEqual(tolerance, 0)
                self.assertLess(tolerance, delta)
        with self.assertRaises(ValueError):
            self.finger_smoke.compute_position_tolerance(1)

    def test_finger_smoke_rejects_one_servo_not_moving(self):
        goals = {1: 514, 2: 506}
        actual = {1: 508, 2: 506}
        with self.assertRaisesRegex(RuntimeError, "ID=1"):
            self.finger_smoke.require_positions_at_goals(actual, goals, 2)

    def test_finger_smoke_rejects_partial_second_servo_motion(self):
        goals = {1: 506, 2: 514}
        actual = {1: 506, 2: 510}
        with self.assertRaisesRegex(RuntimeError, "ID=2"):
            self.finger_smoke.require_positions_at_goals(actual, goals, 2)

    def test_finger_smoke_accepts_only_when_both_reach_strict_tolerance(self):
        goals = {1: 514, 2: 506}
        self.finger_smoke.require_positions_at_goals(
            {1: 512, 2: 508}, goals, 2
        )
        with self.assertRaises(RuntimeError):
            self.finger_smoke.require_positions_at_goals(
                {1: 511, 2: 508}, goals, 2
            )

    def test_center_hold_calls_511_an_electrical_midpoint(self):
        text = source("center_hold_scs0009_pair.py")
        self.assertIn("RAW_ELECTRICAL_MIDPOINT = 511", text)
        self.assertNotIn("RAW_CENTER", text)

    def test_single_servo_tool_refuses_uncalibrated_endpoint_starts(self):
        for start in (0, 21, 29, 994, 1023):
            with self.subTest(start=start):
                with self.assertRaisesRegex(RuntimeError, "endpoint"):
                    self.nudge.compute_safe_target(start, 8)

    def test_pair_tool_refuses_uncalibrated_endpoint_starts(self):
        for start in (0, 21, 29, 994, 1023):
            with self.subTest(start=start):
                with self.assertRaisesRegex(RuntimeError, "endpoint"):
                    self.sync_nudge.compute_safe_target(start, 8)

    def test_safe_target_moves_inward_without_calling_511_mechanical_center(self):
        cases = ((45, 8, 53), (500, 8, 508), (700, 8, 692))
        for start, delta, expected in cases:
            with self.subTest(start=start):
                self.assertEqual(
                    self.nudge.compute_safe_target(start, delta), expected
                )
                self.assertEqual(
                    self.sync_nudge.compute_safe_target(start, delta), expected
                )

    def test_limit_recovery_moves_only_inward_from_configured_limit(self):
        self.assertEqual(
            self.nudge.compute_limit_recovery_target(21, 16, 20, 1003), 37
        )
        self.assertEqual(
            self.nudge.compute_limit_recovery_target(1002, 16, 20, 1003), 986
        )
        for start in (30, 500, 990):
            with self.subTest(start=start):
                with self.assertRaisesRegex(RuntimeError, "not close enough"):
                    self.nudge.compute_limit_recovery_target(start, 16, 20, 1003)

    def test_limit_recovery_is_explicit_and_does_not_return_to_limit(self):
        text = source("nudge_scs0009.py")
        self.assertIn("--limit-recovery-confirmed", text)
        recovery_branch = text.split("if args.limit_recovery_confirmed:", 2)[-1]
        self.assertIn("one-way inward limit recovery verified", recovery_branch)
        self.assertIn("return 0", recovery_branch)

    def test_single_servo_arrival_requires_repeated_stable_samples(self):
        text = source("nudge_scs0009.py")
        self.assertIn("STABLE_SAMPLE_COUNT = 3", text)
        self.assertIn("abs(position - expected) <= POSITION_TOLERANCE", text)
        self.assertNotIn("if moving == 0:\n            return", text)

    def test_decision_document_contains_all_three_rulings(self):
        text = (ROOT / "docs" / "TWO_SERVO_POWER_AND_THERMAL_DECISION_2026-08-15.md").read_text(encoding="utf-8")
        for phrase in ("6.0V", "1.0A", "2.0A", "只能二选一", "Type-C只连接电脑", "50°C", "511只是电气中点参考", "ServoCommandGate"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
