"""Offline-only validation rules for the future eight-servo hand.

This module deliberately does not load the production calibration CSV, assign
hardware IDs, open a serial port, or emit a servo command.  It validates only
the structural conditions that must be true before a future four-finger
configuration could be considered executable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping


EXPECTED_FOUR_FINGER_ROLES = (
    "F1_PROXIMAL",
    "F1_DISTAL",
    "F2_PROXIMAL",
    "F2_DISTAL",
    "F3_PROXIMAL",
    "F3_DISTAL",
    "F4_PROXIMAL",
    "F4_DISTAL",
)

EXPECTED_GRIP_POSES = (
    "CYLINDRICAL_GRASP",
    "POWER_GRASP",
    "PRECISION_GRASP",
)


def validate_role_set(entries: Iterable[Mapping[str, object]]) -> list[str]:
    """Return structural errors for an eight-role fixture configuration.

    ``servo_id`` and ``calibrated`` are intentionally fixture metadata.  Real
    values must still be collected and approved at the hardware gate.
    """

    rows = list(entries)
    errors: list[str] = []
    roles = [str(row.get("role", "")).strip() for row in rows]
    if len(rows) != len(EXPECTED_FOUR_FINGER_ROLES):
        errors.append("exactly 8 logical servo roles are required")
    if len(set(roles)) != len(roles):
        errors.append("duplicate logical servo role")
    if set(roles) != set(EXPECTED_FOUR_FINGER_ROLES):
        errors.append("role set must match F1..F4 proximal/distal roles")

    ids = [row.get("servo_id") for row in rows]
    present_ids = [value for value in ids if value not in (None, "")]
    if len(present_ids) != len(EXPECTED_FOUR_FINGER_ROLES):
        errors.append("every role must have a fixture servo_id")
    if len(present_ids) != len(set(present_ids)):
        errors.append("duplicate fixture servo_id")
    for value in present_ids:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 253:
            errors.append("fixture servo_id must be an integer in 1..253")
            break

    if any(row.get("calibrated") is not True for row in rows):
        errors.append("every role must be explicitly calibrated before execution")
    return errors


def validate_pose_coverage(
    pose_targets: Mapping[str, Mapping[str, object]],
) -> list[str]:
    """Return errors when each pose does not cover all eight logical roles."""

    errors: list[str] = []
    expected = set(EXPECTED_FOUR_FINGER_ROLES)
    expected_poses = set(EXPECTED_GRIP_POSES)
    if set(pose_targets) != expected_poses:
        errors.append("pose set must match the 3 supported grip poses")
    for pose_name in EXPECTED_GRIP_POSES:
        targets = pose_targets.get(pose_name)
        if targets is None:
            continue
        if set(targets) != expected:
            errors.append(f"pose {pose_name!r} must cover all 8 logical roles")
    return errors


def validate_four_finger_fixture(
    entries: Iterable[Mapping[str, object]],
    pose_targets: Mapping[str, Mapping[str, object]],
) -> tuple[bool, list[str]]:
    """Validate a complete offline fixture; never authorizes hardware motion."""

    errors = validate_role_set(entries)
    errors.extend(validate_pose_coverage(pose_targets))
    return not errors, errors
