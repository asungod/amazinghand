import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from protocol import encode_frame  # noqa: E402
from sign_motion import (  # noqa: E402
    ACTION_CANCEL,
    ACTION_START,
    ERROR_ACK_TIMEOUT,
    ERROR_MALFORMED_SIGNSTAT,
    ERROR_STATUS_TIMEOUT,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_QUEUED,
    ERROR_UNSUPPORTED_SEQUENCE,
    SignMotionController,
)


class SignMotionControllerTests(unittest.TestCase):
    def test_start_ack_status_completion(self):
        motion = SignMotionController(status_timeout_ms=30000)
        self.assertTrue(motion.begin_request(ACTION_START, 12, 0, 1))
        self.assertTrue(motion.note_sent(12, ACTION_START, 0, 1))
        self.assertTrue(motion.note_ack(12, 0, 10))
        self.assertTrue(motion.note_status(
            {"type": "SIGNSTAT", "seq": 0, "args": [1, 12, 1, 1, 0, 0, 1]}, 20
        ))
        self.assertEqual(motion.state, STATE_QUEUED)
        self.assertTrue(motion.note_status(
            {"type": "SIGNSTAT", "seq": 1, "args": [1, 12, 1, 5, 1, 1, 1]}, 18000
        ))
        self.assertEqual(motion.state, STATE_COMPLETED)
        self.assertIsNone(motion.active_request_seq)

    def test_malformed_and_wrong_request_statuses_do_not_mutate(self):
        motion = SignMotionController()
        self.assertTrue(motion.begin_request(ACTION_START, 8, 0, 1))
        self.assertTrue(motion.note_sent(8, ACTION_START, 0, 1))
        before = motion.status()
        self.assertFalse(motion.note_status(
            {"type": "SIGNSTAT", "seq": 0, "args": [1, 8, 2, 1, 0, 0, 1]}, 2
        ))
        self.assertEqual(motion.state, before["state"])
        self.assertEqual(motion.last_error, ERROR_MALFORMED_SIGNSTAT)
        self.assertFalse(motion.note_status(
            {"type": "SIGNSTAT", "seq": 0, "args": [1, 9, 1, 1, 0, 0, 1]}, 2
        ))
        self.assertEqual(motion.last_error, "UNEXPECTED_REQUEST")

    def test_ack_and_status_timeouts_fail_closed(self):
        motion = SignMotionController(ack_timeout_ms=1000, status_timeout_ms=30000)
        self.assertTrue(motion.begin_request(ACTION_START, 4, 0, 1))
        self.assertTrue(motion.note_sent(4, ACTION_START, 0, 1))
        motion.tick(1000)
        self.assertEqual(motion.state, STATE_FAILED)
        self.assertEqual(motion.last_error, ERROR_ACK_TIMEOUT)

        motion = SignMotionController(ack_timeout_ms=1000, status_timeout_ms=30000)
        self.assertTrue(motion.begin_request(ACTION_START, 4, 0, 1))
        self.assertTrue(motion.note_sent(4, ACTION_START, 0, 1))
        self.assertTrue(motion.note_ack(4, 0, 1))
        motion.tick(30001)
        self.assertEqual(motion.state, STATE_FAILED)
        self.assertEqual(motion.last_error, ERROR_STATUS_TIMEOUT)

    def test_cancel_requires_matching_cancel_status_action(self):
        motion = SignMotionController()
        self.assertTrue(motion.begin_request(ACTION_START, 1, 0, 1))
        self.assertTrue(motion.note_sent(1, ACTION_START, 0, 1))
        self.assertTrue(motion.note_ack(1, 0, 1))
        self.assertTrue(motion.note_status(
            {"type": "SIGNSTAT", "seq": 0, "args": [1, 1, 1, 2, 0, 0, 1]}, 2
        ))
        self.assertTrue(motion.begin_request(ACTION_CANCEL, 2, 3, 1))
        self.assertTrue(motion.note_sent(2, ACTION_CANCEL, 3, 1))
        self.assertTrue(motion.note_ack(2, 0, 4))
        self.assertFalse(motion.note_status(
            {"type": "SIGNSTAT", "seq": 1, "args": [1, 2, 1, 3, 0, 0, 1]}, 5
        ))
        self.assertTrue(motion.note_status(
            {"type": "SIGNSTAT", "seq": 1, "args": [1, 2, 1, 3, 0, 0, 2]}, 5
        ))

    def test_each_fixed_sequence_is_supported_but_unknown_id_is_rejected(self):
        for sequence_id in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13):
            motion = SignMotionController()
            self.assertTrue(
                motion.begin_request(ACTION_START, sequence_id, 0, sequence_id)
            )
            self.assertEqual(motion.sequence_id, sequence_id)
        motion = SignMotionController()
        self.assertFalse(motion.begin_request(ACTION_START, 14, 0, 14))
        self.assertEqual(motion.last_error, ERROR_UNSUPPORTED_SEQUENCE)


if __name__ == "__main__":
    unittest.main()
