"""Offline all-or-none stop model for a future eight-servo hand.

This is a record/decision model only.  It does not encode packets, open a
serial port, or claim that torque-off was observed on real hardware.  Every
valid stop request attempts each servo ID in deterministic order, even when
an earlier attempt is reported as failed.  Any incomplete or failed stop
keeps the fault latched and requires the external servo supply to be cut.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from host.eight_servo_plan_model import MAX_SERVO_ID
from host.four_finger_config_rules import EXPECTED_FOUR_FINGER_ROLES


EXPECTED_SERVO_COUNT = len(EXPECTED_FOUR_FINGER_ROLES)


@dataclass(frozen=True)
class GroupStopResult:
    """Auditable outcome of a simulated group-stop attempt."""

    valid_request: bool
    attempted_ids: tuple[int, ...]
    torque_off_ok_ids: tuple[int, ...]
    torque_off_failed_ids: tuple[int, ...]
    interrupted: bool
    all_attempts_completed: bool
    fault_latched: bool
    external_power_cut_required: bool
    errors: tuple[str, ...]

    @property
    def all_torque_off_confirmed(self) -> bool:
        return (
            self.valid_request
            and self.all_attempts_completed
            and not self.torque_off_failed_ids
            and len(self.torque_off_ok_ids) == EXPECTED_SERVO_COUNT
        )


def _valid_ids(servo_ids: Sequence[object]) -> tuple[bool, tuple[int, ...], list[str]]:
    errors: list[str] = []
    values = tuple(servo_ids)
    if len(values) != EXPECTED_SERVO_COUNT:
        errors.append(f"exactly {EXPECTED_SERVO_COUNT} servo IDs are required")
    if any(type(value) is not int or not 1 <= value <= MAX_SERVO_ID for value in values):
        errors.append("every servo ID must be an integer in 1..253")
    if len(set(values)) != len(values):
        errors.append("servo IDs must be unique")
    return not errors, tuple(value for value in values if type(value) is int), errors


def simulate_group_stop(
    servo_ids: Sequence[object],
    *,
    torque_off_fail_ids: Iterable[object] = (),
    interrupt_after_attempts: int | None = None,
) -> GroupStopResult:
    """Simulate an ordered eight-ID stop without producing bus traffic.

    ``torque_off_fail_ids`` represents injected failures in the offline
    harness.  ``interrupt_after_attempts`` represents a broken/interrupted
    stop procedure; omitted means all IDs are still attempted.
    """

    valid, ids, errors = _valid_ids(servo_ids)
    fail_set = set(torque_off_fail_ids)
    if any(type(value) is not int for value in fail_set):
        errors.append("torque_off_fail_ids must contain only integer IDs")
    if not isinstance(interrupt_after_attempts, (int, type(None))) or isinstance(
        interrupt_after_attempts, bool
    ):
        errors.append("interrupt_after_attempts must be null or an integer")
    elif interrupt_after_attempts is not None and interrupt_after_attempts < 0:
        errors.append("interrupt_after_attempts must be non-negative")

    if errors:
        return GroupStopResult(
            valid_request=False,
            attempted_ids=(),
            torque_off_ok_ids=(),
            torque_off_failed_ids=(),
            interrupted=False,
            all_attempts_completed=False,
            fault_latched=True,
            external_power_cut_required=True,
            errors=tuple(errors),
        )

    limit = len(ids)
    interrupted = False
    if interrupt_after_attempts is not None and interrupt_after_attempts < limit:
        limit = interrupt_after_attempts
        interrupted = True
    attempted = ids[:limit]
    failed = tuple(servo_id for servo_id in attempted if servo_id in fail_set)
    succeeded = tuple(servo_id for servo_id in attempted if servo_id not in fail_set)
    completed = not interrupted and len(attempted) == EXPECTED_SERVO_COUNT
    return GroupStopResult(
        valid_request=True,
        attempted_ids=attempted,
        torque_off_ok_ids=succeeded,
        torque_off_failed_ids=failed,
        interrupted=interrupted,
        all_attempts_completed=completed,
        fault_latched=bool(failed) or not completed,
        external_power_cut_required=True,
        errors=(),
    )

