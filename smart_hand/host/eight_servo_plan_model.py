"""Offline all-or-none planning model for a future eight-servo hand.

This module is intentionally a *structural validator*, not an execution layer.
It does not open a serial port, talk to a servo bus, load production
calibration data, or encode packets. A valid result means only that one
complete eight-role target plan is internally consistent with a complete,
fresh feedback snapshot and the supplied offline limits.

The validator is fail-closed: any missing/extra/duplicate ID, stale or failed
feedback item, malformed role set, or out-of-range target invalidates the
whole plan. No partial plan is returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from host.four_finger_config_rules import EXPECTED_FOUR_FINGER_ROLES


MAX_SERVO_ID: Final[int] = 253


@dataclass(frozen=True)
class ServoFeedback:
    """One offline feedback sample associated with a physical servo ID."""

    servo_id: int
    position_raw: int
    age_ms: int
    read_ok: bool = True
    item_ok: bool = True


@dataclass(frozen=True)
class StructuralPlanResult:
    """Validation result with no command/packet payload."""

    valid: bool
    errors: tuple[str, ...]

    @property
    def structural_plan_valid(self) -> bool:
        """Explicit name for the only positive authorization this model gives."""

        return self.valid


def _is_int(value: object) -> bool:
    return type(value) is int


def _exact_roles(mapping: Mapping[str, object], label: str, errors: list[str]) -> None:
    expected = set(EXPECTED_FOUR_FINGER_ROLES)
    actual = set(mapping)
    missing = expected - actual
    extra = actual - expected
    if missing:
        errors.append(f"{label} missing roles: {','.join(sorted(missing))}")
    if extra:
        errors.append(f"{label} has unknown roles: {','.join(sorted(extra))}")


def _validate_role_to_id(
    role_to_servo_id: Mapping[str, object], errors: list[str]
) -> set[int]:
    _exact_roles(role_to_servo_id, "role_to_servo_id", errors)
    ids: list[object] = [
        role_to_servo_id.get(role) for role in EXPECTED_FOUR_FINGER_ROLES
    ]
    if any(value is None for value in ids):
        errors.append("role_to_servo_id must provide every role ID")
    if any(not _is_int(value) or not 1 <= value <= MAX_SERVO_ID for value in ids):
        errors.append("every servo ID must be an integer in 1..253")
    present = [value for value in ids if _is_int(value)]
    if len(present) != len(set(present)):
        errors.append("role_to_servo_id contains duplicate servo IDs")
    return set(present)


def _validate_limits(
    limits_by_role: Mapping[str, object], errors: list[str]
) -> None:
    _exact_roles(limits_by_role, "limits_by_role", errors)
    for role in EXPECTED_FOUR_FINGER_ROLES:
        bounds = limits_by_role.get(role)
        if (
            not isinstance(bounds, (tuple, list))
            or len(bounds) != 2
            or not _is_int(bounds[0])
            or not _is_int(bounds[1])
            or bounds[0] < 0
            or bounds[1] > 1023
            or bounds[0] > bounds[1]
        ):
            errors.append(f"{role}: limits must be integer min/max within 0..1023")


def validate_structural_plan(
    role_to_servo_id: Mapping[str, object],
    targets_by_role: Mapping[str, object],
    limits_by_role: Mapping[str, object],
    feedback_by_id: Mapping[object, object],
    *,
    max_feedback_age_ms: int = 150,
) -> StructuralPlanResult:
    """Validate one complete eight-servo plan without producing a bus command.

    The returned object contains only a boolean and diagnostic strings. Even
    on success it deliberately does not expose reordered targets or packet
    bytes, so callers cannot mistake this helper for an execution primitive.
    """

    errors: list[str] = []
    if not _is_int(max_feedback_age_ms) or max_feedback_age_ms < 0:
        errors.append("max_feedback_age_ms must be a non-negative integer")

    id_set = _validate_role_to_id(role_to_servo_id, errors)

    _exact_roles(targets_by_role, "targets_by_role", errors)
    _validate_limits(limits_by_role, errors)

    expected_ids = id_set
    actual_feedback_ids = set(feedback_by_id)
    if actual_feedback_ids != expected_ids:
        missing = expected_ids - actual_feedback_ids
        extra = actual_feedback_ids - expected_ids
        if missing:
            errors.append(f"feedback missing IDs: {','.join(map(str, sorted(missing)))}")
        if extra:
            errors.append(f"feedback has unknown IDs: {','.join(map(str, sorted(extra)))}")

    if len(feedback_by_id) != len(actual_feedback_ids):
        errors.append("feedback ID collection must not contain duplicate keys")

    for role in EXPECTED_FOUR_FINGER_ROLES:
        target = targets_by_role.get(role)
        bounds = limits_by_role.get(role)
        if not _is_int(target):
            errors.append(f"{role}: target must be an integer")
        elif (
            isinstance(bounds, (tuple, list))
            and len(bounds) == 2
            and _is_int(bounds[0])
            and _is_int(bounds[1])
            and not bounds[0] <= target <= bounds[1]
        ):
            errors.append(f"{role}: target is outside offline soft limits")

        servo_id = role_to_servo_id.get(role)
        if not _is_int(servo_id):
            continue
        sample = feedback_by_id.get(servo_id)
        if sample is None:
            continue
        if not isinstance(sample, ServoFeedback):
            errors.append(f"{role}: feedback item has invalid type")
            continue
        if sample.servo_id != servo_id:
            errors.append(f"{role}: feedback servo_id does not match map key")
        if not sample.read_ok:
            errors.append(f"{role}: feedback read failed")
        if not sample.item_ok:
            errors.append(f"{role}: per-item feedback failure")
        if not _is_int(sample.age_ms) or sample.age_ms < 0:
            errors.append(f"{role}: feedback age is invalid")
        elif _is_int(max_feedback_age_ms) and sample.age_ms > max_feedback_age_ms:
            errors.append(f"{role}: feedback is stale")
        if not _is_int(sample.position_raw) or not 0 <= sample.position_raw <= 1023:
            errors.append(f"{role}: feedback position is invalid")
        elif (
            isinstance(bounds, (tuple, list))
            and len(bounds) == 2
            and _is_int(bounds[0])
            and _is_int(bounds[1])
            and not bounds[0] <= sample.position_raw <= bounds[1]
        ):
            errors.append(f"{role}: feedback position is outside offline soft limits")

    # All-or-none: never return a partial target mapping or a command-like
    # object. ``errors`` is a tuple to keep the result immutable.
    return StructuralPlanResult(valid=not errors, errors=tuple(errors))


__all__ = [
    "ServoFeedback",
    "StructuralPlanResult",
    "validate_structural_plan",
]
