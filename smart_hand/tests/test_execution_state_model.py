import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from execution_state_model import (  # noqa: E402
    CLOSING,
    DISARMED,
    FAULT,
    HOLDING,
    READY,
    RELEASING,
    ExecutionStateMachine,
)


def elapsed_ms(now_ms, previous_ms):
    return now_ms - previous_ms


class ExecutionStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.machine = ExecutionStateMachine(
            target_timeout_ms=750,
            closing_timeout_ms=3000,
            releasing_timeout_ms=2000,
        )

    def prepare_target(self, now_ms=100, sequence=1):
        self.machine.set_link(True, 0)
        self.assertTrue(self.machine.arm(10))
        self.assertTrue(self.machine.note_target(sequence, "POWER_GRASP", now_ms))

    def test_normal_grasp_hold_and_release_path(self):
        self.prepare_target()
        self.assertEqual(self.machine.state, READY)
        self.assertTrue(self.machine.request_grasp(200, elapsed_ms))
        self.assertEqual(self.machine.state, CLOSING)
        self.assertTrue(self.machine.note_contact_stable(300))
        self.assertEqual(self.machine.state, HOLDING)
        self.assertTrue(self.machine.request_release(400))
        self.assertEqual(self.machine.state, RELEASING)
        self.assertTrue(self.machine.complete_release(500))
        self.assertEqual(self.machine.state, READY)
        self.assertIsNone(self.machine.target_sequence)

    def test_startup_is_fail_closed(self):
        self.assertEqual(self.machine.state, DISARMED)
        self.assertFalse(self.machine.arm())
        self.machine.set_link(True)
        self.assertTrue(self.machine.arm())
        self.assertFalse(self.machine.request_grasp(0, elapsed_ms))

    def test_target_must_be_new_supported_and_fresh(self):
        self.machine.set_link(True)
        self.machine.arm()
        self.assertFalse(self.machine.note_target(1, "NO_ACTION", 0))
        self.assertTrue(self.machine.note_target(65535, "POWER_GRASP", 0))
        self.assertFalse(self.machine.note_target(65535, "POWER_GRASP", 20))
        self.assertTrue(self.machine.note_target(0, "POWER_GRASP", 30))
        self.assertFalse(self.machine.request_grasp(781, elapsed_ms))

    def test_link_loss_during_motion_latches_fault_and_stop(self):
        self.prepare_target(now_ms=0)
        self.assertTrue(self.machine.request_grasp(0, elapsed_ms))
        self.assertEqual(self.machine.set_link(False, 10), "safe_stop_required")
        self.assertEqual(self.machine.state, FAULT)
        self.assertEqual(self.machine.fault_reason, "link_offline")
        self.assertTrue(self.machine.safe_stop_required)

    def test_stale_target_during_hold_latches_fault(self):
        self.prepare_target(now_ms=0)
        self.machine.request_grasp(0, elapsed_ms)
        self.machine.note_contact_stable(100)
        self.assertEqual(self.machine.tick(751, elapsed_ms), "safe_stop_required")
        self.assertEqual(self.machine.state, FAULT)
        self.assertEqual(self.machine.fault_reason, "target_stale")

    def test_motion_timeout_and_explicit_recovery(self):
        self.prepare_target(now_ms=3000)
        self.machine.request_grasp(3000, elapsed_ms)
        self.assertEqual(self.machine.tick(6001, elapsed_ms), "safe_stop_required")
        self.assertEqual(self.machine.state, FAULT)
        self.assertTrue(self.machine.clear_fault(6100))
        self.assertEqual(self.machine.state, DISARMED)
        self.assertFalse(self.machine.armed)
        self.assertIsNone(self.machine.target_sequence)
        self.assertTrue(self.machine.arm(6200))
        self.assertFalse(self.machine.request_grasp(6200, elapsed_ms))

    def test_disarm_during_motion_requests_stop_without_fault(self):
        self.prepare_target(now_ms=0)
        self.machine.request_grasp(0, elapsed_ms)
        self.assertEqual(self.machine.disarm(10), "safe_stop_required")
        self.assertEqual(self.machine.state, DISARMED)
        self.assertIsNone(self.machine.fault_reason)


if __name__ == "__main__":
    unittest.main()

