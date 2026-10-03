import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = PROJECT_ROOT / "host" / "smart_hand_dashboard.html"


class DashboardAssetTests(unittest.TestCase):
    def test_dashboard_contains_safety_disclosures_and_controls(self):
        content = DASHBOARD.read_text(encoding="utf-8")
        for required in (
            "模拟 / 回放模式",
            "RULE/STATE-MACHINE MVP",
            "第二级 NPU",
            "尚未部署",
            "不驱动舵机",
            'id="armToggle"',
            'id="executeButton"',
            'data-scenario="offline"',
            'data-scenario="jam"',
            'data-scenario="release"',
        ):
            self.assertIn(required, content)

    def test_three_demo_objects_and_intents_are_fixed(self):
        content = DASHBOARD.read_text(encoding="utf-8")
        for required in (
            "id:39",
            "id:41",
            "id:65",
            "CYLINDRICAL_GRASP",
            "POWER_GRASP",
            "PRECISION_GRASP",
        ):
            self.assertIn(required, content)


if __name__ == "__main__":
    unittest.main()
