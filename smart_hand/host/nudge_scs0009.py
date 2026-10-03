"""Perform a tiny, reversible motion test on one loose SCS0009 servo."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = PROJECT_ROOT / "third_party" / "STServo_Python" / "stservo-env"
sys.path.insert(0, str(VENDOR_ROOT))
sys.path.insert(0, str(VENDOR_ROOT / "Lib" / "site-packages"))

from scservo_sdk import (  # type: ignore  # noqa: E402
    COMM_SUCCESS,
    PortHandler,
    SCSCL_MAX_ANGLE_LIMIT_L,
    SCSCL_MIN_ANGLE_LIMIT_L,
    SCSCL_PRESENT_TEMPERATURE,
    SCSCL_PRESENT_VOLTAGE,
    SCSCL_TORQUE_ENABLE,
    scscl,
)


RAW_ELECTRICAL_MIDPOINT = 511
MAX_TEMPERATURE_C = 50
SAFE_ENDPOINT_MARGIN = 30
POSITION_TOLERANCE = 2
STABLE_SAMPLE_COUNT = 3
STABLE_POSITION_DELTA = 2
LIMIT_RECOVERY_WINDOW = 5


def require_success(packet: scscl, result: int, error: int, operation: str) -> None:
    if result != COMM_SUCCESS:
        raise RuntimeError(f"{operation}: {packet.getTxRxResult(result)}")
    if error != 0:
        raise RuntimeError(f"{operation}: {packet.getRxPacketError(error)}")


def compute_safe_target(start: int, delta: int) -> int:
    """Return an inward test target, refusing uncalibrated endpoint starts."""
    if not 0 <= start <= 1023:
        raise RuntimeError(f"implausible start position: {start}")
    if not SAFE_ENDPOINT_MARGIN <= start <= 1023 - SAFE_ENDPOINT_MARGIN:
        raise RuntimeError(
            f"start position {start} is inside the uncalibrated endpoint zone; "
            "read-only diagnosis is required before motion"
        )
    direction = 1 if start <= RAW_ELECTRICAL_MIDPOINT else -1
    target = start + direction * delta
    if not SAFE_ENDPOINT_MARGIN <= target <= 1023 - SAFE_ENDPOINT_MARGIN:
        raise RuntimeError(f"target {target} is inside the endpoint exclusion zone")
    return target


def compute_limit_recovery_target(
    start: int,
    delta: int,
    minimum: int,
    maximum: int,
) -> int:
    """Return a one-way target that moves inward from a configured limit."""
    if not 0 <= minimum < maximum <= 1023:
        raise RuntimeError(
            f"implausible configured limits: minimum={minimum}, maximum={maximum}"
        )
    if not minimum <= start <= maximum:
        raise RuntimeError(
            f"start position {start} is outside configured limits {minimum}..{maximum}"
        )
    if start - minimum <= LIMIT_RECOVERY_WINDOW:
        target = start + delta
    elif maximum - start <= LIMIT_RECOVERY_WINDOW:
        target = start - delta
    else:
        raise RuntimeError(
            f"start position {start} is not close enough to configured limit "
            f"{minimum}..{maximum} for recovery mode"
        )
    if not minimum < target < maximum:
        raise RuntimeError(
            f"recovery target {target} does not move safely inside {minimum}..{maximum}"
        )
    return target


def wait_until_stable_at(
    packet: scscl,
    servo_id: int,
    expected: int,
    timeout_s: float = 2.0,
) -> int:
    """Require several stable, in-tolerance samples; moving=0 alone is insufficient."""
    deadline = time.monotonic() + timeout_s
    last_position = -1
    stable_samples = 0
    while time.monotonic() < deadline:
        position, result, error = packet.ReadPos(servo_id)
        require_success(packet, result, error, "read position")
        moving, result, error = packet.ReadMoving(servo_id)
        require_success(packet, result, error, "read moving")
        position_is_stable = (
            last_position >= 0
            and abs(position - last_position) <= STABLE_POSITION_DELTA
        )
        if (
            moving == 0
            and abs(position - expected) <= POSITION_TOLERANCE
            and position_is_stable
        ):
            stable_samples += 1
            if stable_samples >= STABLE_SAMPLE_COUNT:
                return position
        else:
            stable_samples = 0
        last_position = position
        time.sleep(0.03)
    raise RuntimeError(
        f"target verification timeout; expected={expected}, "
        f"last_position={last_position}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--id", required=True, type=int)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--delta", type=int, default=16)
    parser.add_argument("--speed", type=int, default=100)
    parser.add_argument("--loose-servo-confirmed", action="store_true")
    parser.add_argument(
        "--limit-recovery-confirmed",
        action="store_true",
        help="one-way inward move from a verified configured limit; no automatic return",
    )
    args = parser.parse_args()

    if not args.loose_servo_confirmed:
        print("REFUSED: confirm the servo is loose, unobstructed, and not in a mechanism.")
        return 2
    if not (2 <= args.delta <= 30):
        print("REFUSED: delta must be between 2 and 30 raw counts.")
        return 2

    port = PortHandler(args.port)
    packet = scscl(port)
    torque_enabled = False
    try:
        if not port.openPort() or not port.setBaudRate(args.baud):
            raise RuntimeError("could not open/configure serial port")

        model, result, error = packet.ping(args.id)
        require_success(packet, result, error, "ping")
        start, result, error = packet.ReadPos(args.id)
        require_success(packet, result, error, "read start position")
        minimum, result, error = packet.read2ByteTxRx(
            args.id, SCSCL_MIN_ANGLE_LIMIT_L
        )
        require_success(packet, result, error, "read minimum angle limit")
        maximum, result, error = packet.read2ByteTxRx(
            args.id, SCSCL_MAX_ANGLE_LIMIT_L
        )
        require_success(packet, result, error, "read maximum angle limit")
        torque_state, result, error = packet.read1ByteTxRx(
            args.id, SCSCL_TORQUE_ENABLE
        )
        require_success(packet, result, error, "read torque state")
        if torque_state != 0:
            raise RuntimeError(
                f"servo torque is already enabled (raw={torque_state}); refusing test"
            )
        voltage, result, error = packet.read1ByteTxRx(
            args.id, SCSCL_PRESENT_VOLTAGE
        )
        require_success(packet, result, error, "read voltage")
        temperature, result, error = packet.read1ByteTxRx(
            args.id, SCSCL_PRESENT_TEMPERATURE
        )
        require_success(packet, result, error, "read temperature")
        if not 50 <= voltage <= 70:
            raise RuntimeError(f"unsafe servo voltage_raw={voltage}; expected 50..70")
        if temperature >= MAX_TEMPERATURE_C:
            raise RuntimeError(f"servo temperature too high: {temperature} C")
        # 511 is the servo's electrical midpoint, not a measured mechanical center.
        if args.limit_recovery_confirmed:
            target = compute_limit_recovery_target(
                start, args.delta, minimum, maximum
            )
            mode = "one-way limit recovery"
        else:
            target = compute_safe_target(start, args.delta)
            mode = "reversible nudge"
        print(
            f"START: ID={args.id} model={model} position={start} target={target} "
            f"limits={minimum}..{maximum} mode={mode} "
            f"voltage={voltage / 10:.1f}V temperature={temperature}C"
        )

        # Load the current position before applying holding torque, minimizing
        # any startup jump if the shaft has been moved by hand.
        result, error = packet.WritePos(args.id, start, 0, args.speed)
        require_success(packet, result, error, "write initial hold position")
        result, error = packet.write1ByteTxRx(args.id, SCSCL_TORQUE_ENABLE, 1)
        require_success(packet, result, error, "enable torque")
        torque_enabled = True

        result, error = packet.WritePos(args.id, target, 0, args.speed)
        require_success(packet, result, error, "write small target")
        time.sleep(0.08)
        reached = wait_until_stable_at(packet, args.id, target)
        time.sleep(0.25)

        if args.limit_recovery_confirmed:
            print(f"MOTION: reached={reached}; recovery leaves shaft away from limit")
            print("PASS: one-way inward limit recovery verified; torque will be disabled.")
            return 0

        result, error = packet.WritePos(args.id, start, 0, args.speed)
        require_success(packet, result, error, "return to start")
        time.sleep(0.08)
        returned = wait_until_stable_at(packet, args.id, start)

        print(f"MOTION: reached={reached} returned={returned}")
        if (
            abs(reached - target) > POSITION_TOLERANCE
            or abs(returned - start) > POSITION_TOLERANCE
        ):
            raise RuntimeError("position verification outside tolerance")
        print("PASS: tiny motion and automatic return verified.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if torque_enabled:
            try:
                packet.write1ByteTxRx(args.id, SCSCL_TORQUE_ENABLE, 0)
            except Exception:
                pass
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
