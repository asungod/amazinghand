"""Fail-closed host reference model for a calibrated two-servo finger.

This module deliberately contains no serial-port or vendor-SDK code.  It defines
the checks that must pass before the future Titan driver may emit a bus write.
All positions, steps, voltage and temperature values remain raw registers.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


EXPECTED_SERVO_COUNT = 2


@dataclass(frozen=True)
class ServoCalibration:
    role: str
    servo_id: int
    direction_sign: int
    center_raw: int
    soft_min_raw: int
    soft_max_raw: int
    max_step_raw: int
    speed_limit_raw: int

    def __post_init__(self) -> None:
        if not self.role:
            raise ValueError("servo role must not be empty")
        if not 1 <= self.servo_id <= 253:
            raise ValueError("servo_id must be 1..253")
        if self.direction_sign not in (-1, 1):
            raise ValueError("direction_sign must be -1 or 1")
        if not 0 <= self.soft_min_raw < self.soft_max_raw <= 1023:
            raise ValueError("soft limits must satisfy 0 <= min < max <= 1023")
        if not self.soft_min_raw <= self.center_raw <= self.soft_max_raw:
            raise ValueError("center_raw must be inside the soft limits")
        if self.max_step_raw <= 0:
            raise ValueError("max_step_raw must be positive")
        if self.speed_limit_raw <= 0:
            raise ValueError("speed_limit_raw must be positive")


@dataclass(frozen=True)
class ServoObservation:
    position_raw: int
    voltage_raw: int
    temperature_raw: int
    read_ok: bool
    age_ms: int


def _required_int(row: Mapping[str, str], name: str, line_number: int) -> int:
    value = (row.get(name) or "").strip()
    if not value:
        raise ValueError(f"line {line_number}: required field {name} is empty")
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"line {line_number}: {name} must be an integer") from exc


def load_calibrations(path: str | Path) -> dict[int, ServoCalibration]:
    """Load exactly two complete, unique calibrations from a CSV file."""

    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != EXPECTED_SERVO_COUNT:
        raise ValueError(f"calibration must contain exactly {EXPECTED_SERVO_COUNT} rows")

    calibrations: dict[int, ServoCalibration] = {}
    roles: set[str] = set()
    versions: set[str] = set()
    for line_number, row in enumerate(rows, start=2):
        version = (row.get("calibration_version") or "").strip()
        if not version:
            raise ValueError(f"line {line_number}: calibration_version is empty")
        versions.add(version)
        role = (row.get("servo_role") or "").strip()
        calibration = ServoCalibration(
            role=role,
            servo_id=_required_int(row, "servo_id", line_number),
            direction_sign=_required_int(row, "direction_sign", line_number),
            center_raw=_required_int(row, "center_raw", line_number),
            soft_min_raw=_required_int(row, "soft_min_raw", line_number),
            soft_max_raw=_required_int(row, "soft_max_raw", line_number),
            max_step_raw=_required_int(row, "max_step_raw", line_number),
            speed_limit_raw=_required_int(row, "speed_limit_raw", line_number),
        )
        if calibration.servo_id in calibrations:
            raise ValueError(f"duplicate servo_id {calibration.servo_id}")
        if calibration.role in roles:
            raise ValueError(f"duplicate servo_role {calibration.role}")
        calibrations[calibration.servo_id] = calibration
        roles.add(calibration.role)
    if len(versions) != 1:
        raise ValueError("both servo rows must use one calibration_version")
    return calibrations


class ServoCommandGate:
    """Authorize bounded raw-position commands and latch runtime faults."""

    def __init__(
        self,
        calibrations: Mapping[int, ServoCalibration],
        *,
        max_feedback_age_ms: int = 100,
        voltage_min_raw: int = 50,
        voltage_max_raw: int = 70,
        temperature_max_raw: int = 50,
    ) -> None:
        if len(calibrations) != EXPECTED_SERVO_COUNT:
            raise ValueError("exactly two servo calibrations are required")
        if max_feedback_age_ms <= 0:
            raise ValueError("max_feedback_age_ms must be positive")
        self.calibrations = dict(calibrations)
        self.max_feedback_age_ms = max_feedback_age_ms
        self.voltage_min_raw = voltage_min_raw
        self.voltage_max_raw = voltage_max_raw
        self.temperature_max_raw = temperature_max_raw
        self.armed = False
        self.fault_latched = False
        self.last_block_reason = "disarmed"

    def _validate_observations(
        self, observations: Mapping[int, ServoObservation]
    ) -> bool:
        if set(observations) != set(self.calibrations):
            self.last_block_reason = "feedback_id_mismatch"
            return False
        for servo_id, observation in observations.items():
            calibration = self.calibrations[servo_id]
            if not observation.read_ok:
                self.last_block_reason = f"feedback_failed_id_{servo_id}"
                return False
            if observation.age_ms < 0 or observation.age_ms > self.max_feedback_age_ms:
                self.last_block_reason = f"feedback_stale_id_{servo_id}"
                return False
            if not calibration.soft_min_raw <= observation.position_raw <= calibration.soft_max_raw:
                self.last_block_reason = f"position_outside_soft_limit_id_{servo_id}"
                return False
            if not self.voltage_min_raw <= observation.voltage_raw <= self.voltage_max_raw:
                self.last_block_reason = f"voltage_unsafe_id_{servo_id}"
                return False
            if observation.temperature_raw >= self.temperature_max_raw:
                self.last_block_reason = f"temperature_unsafe_id_{servo_id}"
                return False
        return True

    def arm(self, observations: Mapping[int, ServoObservation]) -> bool:
        if self.fault_latched:
            self.last_block_reason = "fault_latched"
            return False
        if not self._validate_observations(observations):
            return False
        self.armed = True
        self.last_block_reason = "none"
        return True

    def disarm(self) -> None:
        self.armed = False
        self.last_block_reason = "disarmed"

    def plan(
        self,
        targets_raw: Mapping[int, int],
        observations: Mapping[int, ServoObservation],
    ) -> dict[int, int] | None:
        """Return an authorized copy of targets, or None without a bus command."""

        if self.fault_latched:
            self.last_block_reason = "fault_latched"
            return None
        if not self.armed:
            self.last_block_reason = "disarmed"
            return None
        if set(targets_raw) != set(self.calibrations):
            self.last_block_reason = "target_id_mismatch"
            return None
        if not self._validate_observations(observations):
            self.armed = False
            return None
        authorized: dict[int, int] = {}
        for servo_id, target in targets_raw.items():
            if type(target) is not int:
                self.last_block_reason = f"target_not_integer_id_{servo_id}"
                return None
            calibration = self.calibrations[servo_id]
            if not calibration.soft_min_raw <= target <= calibration.soft_max_raw:
                self.last_block_reason = f"target_outside_soft_limit_id_{servo_id}"
                return None
            if abs(target - observations[servo_id].position_raw) > calibration.max_step_raw:
                self.last_block_reason = f"target_step_too_large_id_{servo_id}"
                return None
            authorized[servo_id] = target
        self.last_block_reason = "none"
        return authorized

    def plan_logical_offsets(
        self,
        offsets_from_center: Mapping[int, int],
        observations: Mapping[int, ServoObservation],
    ) -> dict[int, int] | None:
        """Map direction-independent offsets to raw goals, then apply all gates.

        A positive logical offset has the same mechanism meaning for both joints;
        each calibrated ``direction_sign`` decides whether its raw register rises
        or falls.  This keeps AI/grip-policy code independent of servo mounting.
        """

        if set(offsets_from_center) != set(self.calibrations):
            self.last_block_reason = "logical_target_id_mismatch"
            return None
        raw_targets: dict[int, int] = {}
        for servo_id, offset in offsets_from_center.items():
            if type(offset) is not int:
                self.last_block_reason = f"logical_offset_not_integer_id_{servo_id}"
                return None
            calibration = self.calibrations[servo_id]
            raw_targets[servo_id] = (
                calibration.center_raw + calibration.direction_sign * offset
            )
        return self.plan(raw_targets, observations)

    def note_bus_write(self, success: bool) -> None:
        if type(success) is not bool:
            raise ValueError("success must be a boolean")
        if success:
            return
        self.fault_latched = True
        self.armed = False
        self.last_block_reason = "bus_write_failed"

    def clear_fault(self) -> bool:
        if self.armed:
            return False
        self.fault_latched = False
        self.last_block_reason = "disarmed"
        return True
