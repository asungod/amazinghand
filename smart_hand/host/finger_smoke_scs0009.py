"""Low-amplitude opposed-pair smoke test after fitting the finger horns."""

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
    SCSCL_PRESENT_TEMPERATURE,
    SCSCL_PRESENT_VOLTAGE,
    SCSCL_GOAL_POSITION_L,
    SCSCL_PRESENT_LOAD_L,
    SCSCL_PRESENT_CURRENT_L,
    SCSCL_MOVING,
    SCSCL_TORQUE_ENABLE,
    scscl,
)


SERVO_IDS = (1, 2)
MAX_TEMPERATURE_C = 50
MIN_TEST_DELTA = 2
MAX_POSITION_TOLERANCE = 2
STABLE_SAMPLE_COUNT = 3
STABLE_POSITION_DELTA = 1
VERIFY_TIMEOUT_S = 2.0


def check(packet: scscl, result: int, error: int, label: str) -> None:
    if result != COMM_SUCCESS:
        raise RuntimeError(f"{label}: {packet.getTxRxResult(result)}")
    if error:
        raise RuntimeError(f"{label}: {packet.getRxPacketError(error)}")


def read_position(packet: scscl, servo_id: int) -> int:
    value, result, error = packet.ReadPos(servo_id)
    check(packet, result, error, f"read position ID={servo_id}")
    return value


def write_positions_checked(packet: scscl, goals: dict[int, int], speed: int) -> None:
    """Write each goal with a response, then read the goal register back."""
    for servo_id in SERVO_IDS:
        result, error = packet.WritePos(servo_id, goals[servo_id], 0, speed)
        check(packet, result, error, f"write goal ID={servo_id}")
        goal, result, error = packet.read2ByteTxRx(
            servo_id, SCSCL_GOAL_POSITION_L
        )
        check(packet, result, error, f"read back goal ID={servo_id}")
        if goal != goals[servo_id]:
            raise RuntimeError(
                f"ID={servo_id} goal write did not stick: "
                f"requested={goals[servo_id]} read_back={goal}"
            )


def compute_position_tolerance(delta: int) -> int:
    """Keep verification error strictly smaller than the commanded motion."""
    if delta < MIN_TEST_DELTA:
        raise ValueError(f"delta must be at least {MIN_TEST_DELTA}")
    return min(MAX_POSITION_TOLERANCE, delta - 1)


def require_positions_at_goals(
    actual: dict[int, int], goals: dict[int, int], tolerance: int
) -> None:
    if tolerance < 0:
        raise ValueError("position tolerance must be non-negative")
    for servo_id in SERVO_IDS:
        if abs(actual[servo_id] - goals[servo_id]) > tolerance:
            raise RuntimeError(
                f"ID={servo_id} target={goals[servo_id]} actual={actual[servo_id]} "
                f"tolerance={tolerance}"
            )


def read_motion_snapshot(packet: scscl) -> dict[int, dict[str, int]]:
    snapshot: dict[int, dict[str, int]] = {}
    for servo_id in SERVO_IDS:
        position = read_position(packet, servo_id)
        moving, result, error = packet.read1ByteTxRx(servo_id, SCSCL_MOVING)
        check(packet, result, error, f"read moving ID={servo_id}")
        load, result, error = packet.read2ByteTxRx(servo_id, SCSCL_PRESENT_LOAD_L)
        check(packet, result, error, f"read load ID={servo_id}")
        current, result, error = packet.read2ByteTxRx(
            servo_id, SCSCL_PRESENT_CURRENT_L
        )
        check(packet, result, error, f"read current ID={servo_id}")
        snapshot[servo_id] = {
            "position": position,
            "moving": moving,
            "load_raw": load,
            "current_raw": current,
        }
    return snapshot


def wait_until_pair_stable_at(
    packet: scscl,
    goals: dict[int, int],
    tolerance: int,
    timeout_s: float = VERIFY_TIMEOUT_S,
) -> dict[int, int]:
    """Require both servos to be repeatedly stable and inside strict tolerance."""
    deadline = time.monotonic() + timeout_s
    previous: dict[int, int] | None = None
    stable_samples = 0
    actual = {servo_id: read_position(packet, servo_id) for servo_id in SERVO_IDS}
    while time.monotonic() < deadline:
        actual = {servo_id: read_position(packet, servo_id) for servo_id in SERVO_IDS}
        inside_tolerance = all(
            abs(actual[servo_id] - goals[servo_id]) <= tolerance
            for servo_id in SERVO_IDS
        )
        stable = previous is not None and all(
            abs(actual[servo_id] - previous[servo_id]) <= STABLE_POSITION_DELTA
            for servo_id in SERVO_IDS
        )
        if inside_tolerance and stable:
            stable_samples += 1
            if stable_samples >= STABLE_SAMPLE_COUNT:
                require_positions_at_goals(actual, goals, tolerance)
                return actual
        else:
            stable_samples = 0
        previous = actual
        time.sleep(0.03)
    snapshot = read_motion_snapshot(packet)
    raise RuntimeError(
        f"pair did not become stable at target; goals={goals} actual={actual} "
        f"tolerance={tolerance} snapshot={snapshot}"
    )


def require_safe_status(packet: scscl, servo_id: int) -> None:
    voltage, result, error = packet.read1ByteTxRx(
        servo_id, SCSCL_PRESENT_VOLTAGE
    )
    check(packet, result, error, f"read voltage ID={servo_id}")
    temperature, result, error = packet.read1ByteTxRx(
        servo_id, SCSCL_PRESENT_TEMPERATURE
    )
    check(packet, result, error, f"read temperature ID={servo_id}")
    if not 50 <= voltage <= 70 or temperature >= MAX_TEMPERATURE_C:
        raise RuntimeError(
            f"unsafe status ID={servo_id}: voltage_raw={voltage}, "
            f"temperature={temperature}C"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument(
        "--center1",
        type=int,
        required=True,
        help="measured safe mechanical reference for servo ID 1",
    )
    parser.add_argument(
        "--center2",
        type=int,
        required=True,
        help="measured safe mechanical reference for servo ID 2",
    )
    parser.add_argument("--delta", type=int, default=12)
    parser.add_argument("--speed", type=int, default=60)
    parser.add_argument("--mechanism-free-confirmed", action="store_true")
    args = parser.parse_args()

    if not args.mechanism_free_confirmed:
        print("REFUSED: manually verify the assembled finger moves freely first.")
        return 2
    if not MIN_TEST_DELTA <= args.delta <= 20:
        print(
            f"REFUSED: first mechanism delta must be "
            f"{MIN_TEST_DELTA}..20 raw counts."
        )
        return 2

    tolerance = compute_position_tolerance(args.delta)

    centers = {1: args.center1, 2: args.center2}
    close_goals = {1: args.center1 + args.delta, 2: args.center2 - args.delta}
    open_goals = {1: args.center1 - args.delta, 2: args.center2 + args.delta}
    if any(not 20 <= value <= 1003 for value in (*centers.values(), *close_goals.values(), *open_goals.values())):
        print("REFUSED: center/delta would approach a servo travel limit.")
        return 2

    port = PortHandler(args.port)
    packet = scscl(port)
    enabled: list[int] = []
    try:
        if not port.openPort() or not port.setBaudRate(args.baud):
            raise RuntimeError("could not open/configure serial port")

        starts: dict[int, int] = {}
        for servo_id in SERVO_IDS:
            _model, result, error = packet.ping(servo_id)
            check(packet, result, error, f"ping ID={servo_id}")
            starts[servo_id] = read_position(packet, servo_id)
            require_safe_status(packet, servo_id)
            if abs(starts[servo_id] - centers[servo_id]) > 20:
                raise RuntimeError(
                    f"ID={servo_id} is not near calibrated center: "
                    f"position={starts[servo_id]}, center={centers[servo_id]}"
                )

        print(
            f"START: {starts}; CENTERS: {centers}; "
            f"STRICT_TOLERANCE: {tolerance}"
        )
        for servo_id in SERVO_IDS:
            result, error = packet.WritePos(
                servo_id, starts[servo_id], 0, args.speed
            )
            check(packet, result, error, f"hold start ID={servo_id}")
            result, error = packet.write1ByteTxRx(
                servo_id, SCSCL_TORQUE_ENABLE, 1
            )
            check(packet, result, error, f"enable torque ID={servo_id}")
            enabled.append(servo_id)

        phases = (
            ("SMALL_CLOSE", close_goals),
            ("CENTER_AFTER_CLOSE", centers),
            ("SMALL_OPEN", open_goals),
            ("FINAL_CENTER", centers),
        )
        for label, goals in phases:
            write_positions_checked(packet, goals, args.speed)
            actual = wait_until_pair_stable_at(packet, goals, tolerance)
            for servo_id in SERVO_IDS:
                require_safe_status(packet, servo_id)
            print(f"{label}: goals={goals} actual={actual}")

        print("PASS: assembled finger small close/open test verified.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}; releasing torque.")
        return 1
    finally:
        for servo_id in enabled:
            try:
                packet.write1ByteTxRx(servo_id, SCSCL_TORQUE_ENABLE, 0)
            except Exception:
                pass
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
