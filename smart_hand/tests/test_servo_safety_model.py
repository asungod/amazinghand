import csv
import tempfile
import unittest
from pathlib import Path

from host.servo_safety_model import (
    ServoCalibration,
    ServoCommandGate,
    ServoObservation,
    load_calibrations,
)


def calibrations():
    return {
        1: ServoCalibration("joint1", 1, 1, 511, 300, 700, 20, 60),
        2: ServoCalibration("joint2", 2, -1, 511, 280, 720, 20, 60),
    }


def observations(position1=511, position2=511, age_ms=5):
    return {
        1: ServoObservation(position1, 60, 25, True, age_ms),
        2: ServoObservation(position2, 60, 25, True, age_ms),
    }


class ServoCommandGateTests(unittest.TestCase):
    def test_normal_arm_and_bounded_pair_command(self):
        gate = ServoCommandGate(calibrations())
        status = observations()
        self.assertTrue(gate.arm(status))
        self.assertEqual(gate.plan({1: 523, 2: 499}, status), {1: 523, 2: 499})
        self.assertEqual(gate.last_block_reason, "none")

    def test_logical_offsets_apply_each_calibrated_direction(self):
        gate = ServoCommandGate(calibrations())
        status = observations()
        self.assertTrue(gate.arm(status))
        self.assertEqual(
            gate.plan_logical_offsets({1: 12, 2: 12}, status),
            {1: 523, 2: 499},
        )

    def test_missing_feedback_and_stale_feedback_fail_closed(self):
        gate = ServoCommandGate(calibrations())
        self.assertFalse(gate.arm({1: observations()[1]}))
        self.assertEqual(gate.last_block_reason, "feedback_id_mismatch")
        self.assertFalse(gate.arm(observations(age_ms=101)))
        self.assertEqual(gate.last_block_reason, "feedback_stale_id_1")

    def test_limit_and_step_violations_emit_no_plan(self):
        gate = ServoCommandGate(calibrations())
        status = observations()
        self.assertTrue(gate.arm(status))
        self.assertIsNone(gate.plan({1: 701, 2: 511}, status))
        self.assertEqual(gate.last_block_reason, "target_outside_soft_limit_id_1")
        self.assertIsNone(gate.plan({1: 532, 2: 511}, status))
        self.assertEqual(gate.last_block_reason, "target_step_too_large_id_1")

    def test_runtime_feedback_failure_disarms(self):
        gate = ServoCommandGate(calibrations())
        self.assertTrue(gate.arm(observations()))
        failed = dict(observations())
        failed[2] = ServoObservation(511, 60, 25, False, 5)
        self.assertIsNone(gate.plan({1: 511, 2: 511}, failed))
        self.assertFalse(gate.armed)
        self.assertEqual(gate.last_block_reason, "feedback_failed_id_2")

    def test_bus_failure_latches_fault_until_explicit_clear(self):
        gate = ServoCommandGate(calibrations())
        self.assertTrue(gate.arm(observations()))
        gate.note_bus_write(False)
        self.assertTrue(gate.fault_latched)
        self.assertFalse(gate.arm(observations()))
        self.assertTrue(gate.clear_fault())
        self.assertTrue(gate.arm(observations()))


class CalibrationCsvTests(unittest.TestCase):
    FIELDNAMES = [
        "calibration_version", "servo_role", "servo_id", "direction_sign",
        "center_raw", "soft_min_raw", "soft_max_raw", "max_step_raw",
        "speed_limit_raw",
    ]

    def _write(self, rows):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "calibration.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return directory, path

    def test_complete_two_row_calibration_loads(self):
        rows = [
            dict(calibration_version="v1", servo_role="joint1", servo_id=1,
                 direction_sign=1, center_raw=511, soft_min_raw=300,
                 soft_max_raw=700, max_step_raw=20, speed_limit_raw=60),
            dict(calibration_version="v1", servo_role="joint2", servo_id=2,
                 direction_sign=-1, center_raw=511, soft_min_raw=280,
                 soft_max_raw=720, max_step_raw=20, speed_limit_raw=60),
        ]
        directory, path = self._write(rows)
        try:
            loaded = load_calibrations(path)
        finally:
            directory.cleanup()
        self.assertEqual(set(loaded), {1, 2})
        self.assertEqual(loaded[2].direction_sign, -1)

    def test_blank_limit_is_rejected(self):
        rows = [
            dict(calibration_version="v1", servo_role="joint1", servo_id=1,
                 direction_sign=1, center_raw=511, soft_min_raw="",
                 soft_max_raw=700, max_step_raw=20, speed_limit_raw=60),
            dict(calibration_version="v1", servo_role="joint2", servo_id=2,
                 direction_sign=-1, center_raw=511, soft_min_raw=280,
                 soft_max_raw=720, max_step_raw=20, speed_limit_raw=60),
        ]
        directory, path = self._write(rows)
        try:
            with self.assertRaisesRegex(ValueError, "soft_min_raw is empty"):
                load_calibrations(path)
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
