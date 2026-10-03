import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from rehab_goal import RepetitionGoalController  # noqa: E402


class RepetitionGoalTests(unittest.TestCase):
    def test_release_inside_cycles_five_ten_fifteen(self):
        controller = RepetitionGoalController()
        controller.set_display_rect((10, 20, 100, 40))
        for expected in (10, 15, 5):
            self.assertFalse(controller.update_touch(20, 30, True, True))
            self.assertTrue(controller.update_touch(20, 30, False, True))
            self.assertEqual(controller.goal, expected)

    def test_disabled_drag_and_outside_release_do_not_change_goal(self):
        controller = RepetitionGoalController()
        controller.set_display_rect((10, 20, 100, 40))
        controller.update_touch(20, 30, True, False)
        self.assertFalse(controller.update_touch(20, 30, False, False))
        controller.update_touch(20, 30, True, True)
        self.assertFalse(controller.update_touch(200, 30, False, True))
        self.assertEqual(controller.goal, 5)

    def test_invalid_options_fail_closed(self):
        for options in ((), (0, 5), (5, 5), (True, 5)):
            with self.assertRaises(ValueError):
                RepetitionGoalController(options=options, initial=5)


if __name__ == "__main__":
    unittest.main()
