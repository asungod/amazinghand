"""Fail-closed record validation for future four-finger hardware bring-up.

This module is deliberately offline-only. It does not enumerate serial ports,
load production calibration data, switch power, or emit servo packets. Passing
these rules means only that a Gate 5 -> Gate 6 record is structurally complete;
it never authorizes power or motion.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from host.four_finger_config_rules import EXPECTED_FOUR_FINGER_ROLES

ENUM_PENDING = "PENDING"
ENUM_VERIFIED = "READ_ONLY_VERIFIED"
CAL_PENDING = "PENDING"
CAL_VERIFIED = "VERIFIED"

STOP_REASONS = (
    "NONE",
    "ABNORMAL_HEAT",
    "ODOR",
    "STALL",
    "OVERCURRENT",
    "LINK_LOSS",
    "DIRECTION_UNKNOWN",
    "READBACK_FAILURE",
    "MANUAL_STOP",
)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_positive_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_gate_record(record: Mapping[str, object]) -> list[str]:
    """Validate that a requested Gate transition is explicit and sequential."""
    errors: list[str] = []
    current_gate = record.get("current_gate")
    requested_gate = record.get("requested_gate")
    if not _is_int(current_gate) or not 0 <= current_gate <= 7:
        errors.append("current_gate must be an integer in 0..7")
    if requested_gate is not None and (
        not _is_int(requested_gate) or not 0 <= requested_gate <= 7
    ):
        errors.append("requested_gate must be null or an integer in 0..7")
    if _is_int(current_gate) and _is_int(requested_gate):
        if requested_gate not in (current_gate, current_gate + 1):
            errors.append("requested_gate must not skip or reverse a Gate")
    return errors


def validate_role_records(entries: Sequence[Mapping[str, object]]) -> list[str]:
    """Validate eight read-only enumeration and calibration records."""
    rows = list(entries)
    errors: list[str] = []
    roles = [str(row.get("role", "")).strip() for row in rows]
    if len(rows) != len(EXPECTED_FOUR_FINGER_ROLES):
        errors.append("exactly 8 role records are required")
    if len(set(roles)) != len(roles):
        errors.append("duplicate role record")
    if set(roles) != set(EXPECTED_FOUR_FINGER_ROLES):
        errors.append("role records must match F1..F4 proximal/distal roles")

    verified_ids: list[int] = []
    for row in rows:
        role = str(row.get("role", "")).strip() or "<empty>"
        enum_status = row.get("enumeration_status")
        calibration_status = row.get("calibration_status")
        if enum_status not in (ENUM_PENDING, ENUM_VERIFIED):
            errors.append(f"{role}: invalid enumeration_status")
        if calibration_status not in (CAL_PENDING, CAL_VERIFIED):
            errors.append(f"{role}: invalid calibration_status")

        servo_id = row.get("servo_id")
        if enum_status == ENUM_VERIFIED:
            if not _is_int(servo_id) or not 1 <= servo_id <= 253:
                errors.append(f"{role}: verified servo_id must be an integer in 1..253")
            else:
                verified_ids.append(servo_id)
            if row.get("readback_ok") is not True:
                errors.append(f"{role}: verified enumeration requires readback_ok=true")
            if not _has_text(row.get("enumeration_evidence")):
                errors.append(f"{role}: verified enumeration requires evidence")

        if calibration_status == CAL_VERIFIED:
            if enum_status != ENUM_VERIFIED:
                errors.append(f"{role}: calibration requires verified enumeration")
            direction = row.get("direction_sign")
            soft_min = row.get("soft_min_raw")
            center = row.get("center_raw")
            soft_max = row.get("soft_max_raw")
            if direction not in (-1, 1) or isinstance(direction, bool):
                errors.append(f"{role}: direction_sign must be -1 or 1")
            if not all(_is_int(value) for value in (soft_min, center, soft_max)):
                errors.append(f"{role}: calibration raw values must be integers")
            elif not 0 <= soft_min <= center <= soft_max <= 1023 or soft_min == soft_max:
                errors.append(
                    f"{role}: calibration must satisfy 0 <= min <= center <= max <= 1023"
                )
            if not _has_text(row.get("calibration_evidence")):
                errors.append(f"{role}: verified calibration requires evidence")

    if len(verified_ids) != len(set(verified_ids)):
        errors.append("verified servo_id values must be unique")
    return errors


def validate_power_record(power: Mapping[str, object]) -> list[str]:
    """Validate an explicit power profile without choosing its real values."""
    errors: list[str] = []
    external_enabled = power.get("external_6v_enabled")
    profile_approved = power.get("profile_approved")
    if not isinstance(external_enabled, bool):
        errors.append("external_6v_enabled must be boolean")
    if not isinstance(profile_approved, bool):
        errors.append("profile_approved must be boolean")

    if profile_approved is True:
        if not _is_positive_number(power.get("voltage_v")):
            errors.append("approved power profile requires positive voltage_v")
        if not _is_positive_number(power.get("current_limit_a")):
            errors.append("approved power profile requires positive current_limit_a")
        if not _has_text(power.get("approval_evidence")):
            errors.append("approved power profile requires approval evidence")

    if external_enabled is True:
        if profile_approved is not True:
            errors.append("external 6V requires an approved power profile")
        if power.get("operator_present") is not True:
            errors.append("external 6V requires operator_present=true")
        if power.get("emergency_disconnect_ready") is not True:
            errors.append("external 6V requires emergency_disconnect_ready=true")
    return errors


def validate_stop_record(stop: Mapping[str, object], power: Mapping[str, object]) -> list[str]:
    """Validate that every abnormal condition is latched and de-energized."""
    errors: list[str] = []
    reason = stop.get("reason")
    if reason not in STOP_REASONS:
        errors.append("stop reason is not recognized")
        return errors

    latched = stop.get("stop_latched")
    if not isinstance(latched, bool):
        errors.append("stop_latched must be boolean")
    if reason == "NONE":
        if latched is not False:
            errors.append("reason NONE requires stop_latched=false")
        return errors

    if latched is not True:
        errors.append("abnormal stop reason requires stop_latched=true")
    if power.get("external_6v_enabled") is not False:
        errors.append("latched stop requires external 6V off")
    if stop.get("motion_authorized") is not False:
        errors.append("latched stop requires motion_authorized=false")
    if stop.get("next_gate_authorized") is not False:
        errors.append("latched stop requires next_gate_authorized=false")
    if not _has_text(stop.get("evidence")):
        errors.append("latched stop requires evidence")
    return errors


def validate_bringup_record(record: Mapping[str, object]) -> list[str]:
    """Validate a pending or completed record; do not infer readiness."""
    errors = validate_gate_record(record)
    roles = record.get("roles")
    power = record.get("power")
    stop = record.get("stop")
    if not isinstance(roles, list):
        errors.append("roles must be a list")
    else:
        errors.extend(validate_role_records(roles))
    if not isinstance(power, Mapping):
        errors.append("power must be a mapping")
        power = {}
    else:
        errors.extend(validate_power_record(power))
    if not isinstance(stop, Mapping):
        errors.append("stop must be a mapping")
    else:
        errors.extend(validate_stop_record(stop, power))

    mechanical_complete = record.get("mechanical_complete")
    if not isinstance(mechanical_complete, bool):
        errors.append("mechanical_complete must be boolean")
    if mechanical_complete is True and not _has_text(record.get("mechanical_evidence")):
        errors.append("mechanical completion requires evidence")
    if not isinstance(record.get("hardware_accessed"), bool):
        errors.append("hardware_accessed must be boolean")
    return errors


def validate_gate6_readiness(record: Mapping[str, object]) -> tuple[bool, list[str]]:
    """Check evidence completeness for Gate 5 -> 6; never authorize motion."""
    errors = validate_bringup_record(record)
    if record.get("current_gate") != 5 or record.get("requested_gate") != 6:
        errors.append("Gate 6 review requires an explicit 5 -> 6 request")
    if record.get("hardware_accessed") is not True:
        errors.append("Gate 6 review requires a real hardware session record")
    if record.get("mechanical_complete") is not True:
        errors.append("Gate 6 review requires completed mechanical evidence")

    roles = record.get("roles")
    if isinstance(roles, list):
        if any(row.get("enumeration_status") != ENUM_VERIFIED for row in roles):
            errors.append("Gate 6 review requires all 8 read-only enumerations")
        if any(row.get("calibration_status") != CAL_VERIFIED for row in roles):
            errors.append("Gate 6 review requires all 8 verified calibrations")

    power = record.get("power")
    if isinstance(power, Mapping):
        if power.get("profile_approved") is not True:
            errors.append("Gate 6 review requires an approved power profile")
        if power.get("external_6v_enabled") is not False:
            errors.append("Gate 6 preflight record must keep external 6V off")

    stop = record.get("stop")
    if isinstance(stop, Mapping) and (
        stop.get("reason") != "NONE" or stop.get("stop_latched") is not False
    ):
        errors.append("Gate 6 review is blocked by a latched stop")
    return not errors, errors
