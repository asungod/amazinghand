import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from action_safety_model import MotionSafetyGate  # noqa: E402


def elapsed_ms(now_ms, previous_ms):
    return now_ms - previous_ms


class MotionSafetyGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = MotionSafetyGate(target_timeout_ms=750)

    def arm_with_fresh_target(self, sequence=1, now_ms=0):
        self.gate.set_link(True)
        self.assertTrue(self.gate.arm())
        self.assertTrue(self.gate.note_target(sequence, now_ms))

    def test_startup_blocks_until_link_arm_and_fresh_target(self):
        self.assertFalse(self.gate.can_start_motion(0, elapsed_ms))
        self.assertEqual(self.gate.last_block_reason, "link_offline")
        self.gate.set_link(True)
        self.assertFalse(self.gate.can_start_motion(0, elapsed_ms))
        self.assertEqual(self.gate.last_block_reason, "disarmed")
        self.assertTrue(self.gate.arm())
        self.assertFalse(self.gate.can_start_motion(0, elapsed_ms))
        self.assertEqual(self.gate.last_block_reason, "target_missing")
        self.assertTrue(self.gate.note_target(1, 100))
        self.assertTrue(self.gate.start_motion(800, elapsed_ms))

    def test_stale_target_requests_safe_stop(self):
        self.arm_with_fresh_target(now_ms=0)
        self.assertTrue(self.gate.start_motion(0, elapsed_ms))
        self.assertIsNone(self.gate.tick(750, elapsed_ms))
        self.assertEqual(self.gate.tick(751, elapsed_ms), "safe_stop_required")
        self.assertFalse(self.gate.motion_active)
        self.assertEqual(self.gate.safe_stop_requests, 1)
        self.assertEqual(self.gate.last_block_reason, "target_stale")

    def test_link_loss_disarms_clears_target_and_requests_safe_stop(self):
        self.arm_with_fresh_target()
        self.assertTrue(self.gate.start_motion(0, elapsed_ms))

        self.assertEqual(self.gate.set_link(False), "safe_stop_required")

        self.assertFalse(self.gate.armed)
        self.assertIsNone(self.gate.target_sequence)
        self.assertFalse(self.gate.motion_active)
        self.assertEqual(self.gate.last_block_reason, "link_offline")

    def test_duplicate_old_sequence_and_rollover_are_handled(self):
        self.gate.set_link(True)
        self.assertTrue(self.gate.note_target(65535, 0))
        self.assertFalse(self.gate.note_target(65535, 100))
        self.assertFalse(self.gate.note_target(65534, 200))
        self.assertEqual(self.gate.target_seen_ms, 0)
        self.assertTrue(self.gate.note_target(0, 300))
        self.assertEqual(self.gate.target_seen_ms, 300)

    def test_fault_is_latched_and_requires_new_arm_and_target(self):
        self.arm_with_fresh_target()
        self.assertTrue(self.gate.start_motion(0, elapsed_ms))
        self.assertEqual(self.gate.latch_fault(), "safe_stop_required")
        self.assertFalse(self.gate.arm())
        self.assertTrue(self.gate.clear_fault())
        self.assertTrue(self.gate.arm())
        self.assertFalse(self.gate.can_start_motion(0, elapsed_ms))
        self.assertEqual(self.gate.last_block_reason, "target_missing")


if __name__ == "__main__":
    unittest.main()
