import unittest

from host.eight_servo_group_stop_model import (
    EXPECTED_SERVO_COUNT,
    simulate_group_stop,
)


IDS = tuple(range(1, EXPECTED_SERVO_COUNT + 1))


class EightServoGroupStopTests(unittest.TestCase):
    def test_normal_stop_attempts_all_ids(self):
        result = simulate_group_stop(IDS)
        self.assertTrue(result.valid_request)
        self.assertEqual(result.attempted_ids, IDS)
        self.assertEqual(result.torque_off_ok_ids, IDS)
        self.assertTrue(result.all_torque_off_confirmed)
        self.assertFalse(result.fault_latched)
        self.assertTrue(result.external_power_cut_required)

    def test_first_failure_does_not_skip_remaining_ids(self):
        result = simulate_group_stop(IDS, torque_off_fail_ids={1})
        self.assertEqual(result.attempted_ids, IDS)
        self.assertEqual(result.torque_off_failed_ids, (1,))
        self.assertEqual(result.torque_off_ok_ids, IDS[1:])
        self.assertTrue(result.fault_latched)
        self.assertFalse(result.all_torque_off_confirmed)

    def test_middle_and_last_failures_are_both_reported(self):
        result = simulate_group_stop(IDS, torque_off_fail_ids={4, 8})
        self.assertEqual(result.torque_off_failed_ids, (4, 8))
        self.assertEqual(result.attempted_ids, IDS)
        self.assertTrue(result.fault_latched)

    def test_interruption_is_incomplete_and_requires_external_cut(self):
        result = simulate_group_stop(IDS, interrupt_after_attempts=3)
        self.assertEqual(result.attempted_ids, (1, 2, 3))
        self.assertTrue(result.interrupted)
        self.assertFalse(result.all_attempts_completed)
        self.assertTrue(result.fault_latched)
        self.assertTrue(result.external_power_cut_required)

    def test_invalid_count_duplicate_and_range_fail_before_attempts(self):
        for ids in ((1, 2), (1, 1, 3, 4, 5, 6, 7, 8), (1, 2, 3, 4, 5, 6, 7, 254)):
            with self.subTest(ids=ids):
                result = simulate_group_stop(ids)
                self.assertFalse(result.valid_request)
                self.assertEqual(result.attempted_ids, ())
                self.assertTrue(result.fault_latched)
                self.assertTrue(result.external_power_cut_required)

    def test_boolean_id_and_failure_id_are_rejected(self):
        ids = list(IDS)
        ids[0] = True
        result = simulate_group_stop(ids)
        self.assertFalse(result.valid_request)
        self.assertTrue(result.errors)
        result = simulate_group_stop(IDS, torque_off_fail_ids={True})
        self.assertFalse(result.valid_request)

    def test_negative_interruption_is_rejected(self):
        result = simulate_group_stop(IDS, interrupt_after_attempts=-1)
        self.assertFalse(result.valid_request)
        self.assertEqual(result.attempted_ids, ())


if __name__ == "__main__":
    unittest.main()
