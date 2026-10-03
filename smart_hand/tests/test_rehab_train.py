import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from rehab_train import TrainButtonController, authority_allows_training  # noqa: E402


def elapsed(now_ms, previous_ms):
    return now_ms - previous_ms


def ready_snapshot():
    return {
        "ver": 1,
        "link_online": True,
        "have_vision": True,
        "vision_stale": False,
        "have_actionable": True,
        "pose": 0,
        "gate_present": True,
        "gate_fault": False,
    }


class RehabTrainTests(unittest.TestCase):
    def test_authority_gate_fails_closed_for_each_missing_condition(self):
        self.assertTrue(authority_allows_training(ready_snapshot()))
        for key, blocked_value in (
            ("link_online", False),
            ("have_vision", False),
            ("vision_stale", True),
            ("have_actionable", False),
            ("pose", 2),
            ("gate_present", False),
            ("gate_fault", True),
        ):
            snapshot = ready_snapshot()
            snapshot[key] = blocked_value
            with self.subTest(key=key):
                self.assertFalse(authority_allows_training(snapshot))

    def test_only_release_inside_enabled_button_emits(self):
        controller = TrainButtonController()
        controller.set_display_rect((10, 20, 100, 50))
        self.assertFalse(controller.update_touch(20, 30, True, True))
        self.assertTrue(controller.update_touch(20, 30, False, True))
        self.assertFalse(controller.update_touch(20, 30, True, False))
        self.assertFalse(controller.update_touch(20, 30, False, False))
        self.assertFalse(controller.update_touch(5, 5, True, True))
        self.assertFalse(controller.update_touch(20, 30, False, True))

    def test_authoritative_status_completes_and_counts(self):
        controller = TrainButtonController(1000, 30000, 2000)
        snapshot = ready_snapshot()
        self.assertTrue(controller.enabled(snapshot, 0, elapsed))
        controller.note_sent(7, 10)
        self.assertFalse(controller.enabled(snapshot, 20, elapsed))
        self.assertFalse(controller.note_ack(8, 0, 30))
        self.assertTrue(controller.note_ack(7, 0, 30))
        self.assertEqual(controller.state, "QUEUED")
        self.assertTrue(controller.note_train_status(
            {"type": "TRAINSTAT", "seq": 1, "args": [1, 7, 2, 0, 0]},
            100,
            elapsed,
        ))
        self.assertEqual(controller.state, "RUNNING")
        self.assertTrue(controller.note_train_status(
            {"type": "TRAINSTAT", "seq": 2, "args": [1, 7, 3, 1, 4]},
            5030,
            elapsed,
        ))
        self.assertEqual(controller.state, "COMPLETED")
        self.assertEqual(controller.titan_completed_count, 4)
        self.assertEqual(controller.session_completed_count, 1)
        self.assertEqual(controller.last_duration_ms, 5000)
        self.assertEqual(
            controller.status_line(False), "TRAIN COMPLETE REP=1 5.0s"
        )
        self.assertFalse(controller.enabled(snapshot, 7029, elapsed))
        self.assertTrue(controller.enabled(snapshot, 7030, elapsed))

    def test_pending_request_times_out_fail_closed(self):
        controller = TrainButtonController(1000)
        controller.note_sent(9, 100)
        self.assertFalse(controller.expire(1099, elapsed))
        self.assertTrue(controller.expire(1100, elapsed))
        self.assertEqual(controller.state, "ACK_TIMEOUT")

    def test_run_status_timeout_fails_closed(self):
        controller = TrainButtonController(1000, 30000, 2000)
        controller.note_sent(9, 100)
        self.assertTrue(controller.note_ack(9, 0, 110))
        self.assertFalse(controller.expire(30109, elapsed))
        self.assertTrue(controller.expire(30110, elapsed))
        self.assertEqual(controller.state, "STATUS_TIMEOUT")
        self.assertFalse(controller.enabled(ready_snapshot(), 30111, elapsed))

    def test_malformed_or_wrong_request_status_is_ignored(self):
        controller = TrainButtonController()
        controller.note_sent(7, 10)
        controller.note_ack(7, 0, 20)
        self.assertFalse(controller.note_train_status(
            {"type": "TRAINSTAT", "seq": 1, "args": [1, 8, 3, 1, 1]},
            30,
            elapsed,
        ))
        self.assertFalse(controller.note_train_status(
            {"type": "TRAINSTAT", "seq": 1, "args": [1, 7, 99, 1, 1]},
            30,
            elapsed,
        ))
        self.assertEqual(controller.state, "QUEUED")

    def test_session_count_starts_at_one_when_titan_total_is_not_zero(self):
        controller = TrainButtonController()
        controller.note_sent(7, 10)
        controller.note_ack(7, 0, 20)
        controller.note_train_status(
            {"type": "TRAINSTAT", "seq": 1, "args": [1, 7, 3, 1, 9]},
            1020,
            elapsed,
        )
        self.assertEqual(controller.titan_completed_count, 9)
        self.assertEqual(controller.session_completed_count, 1)


if __name__ == "__main__":
    unittest.main()
