"""Move SCS0009 IDs 1/2 to raw electrical midpoint, hold, then release."""

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


SERVO_IDS = (1, 2)
RAW_ELECTRICAL_MIDPOINT = 511
MAX_TEMPERATURE_C = 50
MAX_SAFE_SPEED = 100
EXPECTED_MODEL = 1284
HOLD_TOLERANCE = 8


def check(packet: scscl, result: int, error: int, label: str) -> None:
    if result != COMM_SUCCESS:
        raise RuntimeError(f"{label}: {packet.getTxRxResult(result)}")
    if error:
        raise RuntimeError(f"{label}: {packet.getRxPacketError(error)}")


def read_position(packet: scscl, servo_id: int) -> int:
    position, result, error = packet.ReadPos(servo_id)
    check(packet, result, error, f"read position ID={servo_id}")
    if not 0 <= position <= 1023:
        raise RuntimeError(f"implausible position ID={servo_id}: {position}")
    return position


def read_status(packet: scscl, servo_id: int) -> tuple[int, int, int]:
    position = read_position(packet, servo_id)
    voltage, result, error = packet.read1ByteTxRx(
        servo_id, SCSCL_PRESENT_VOLTAGE
    )
    check(packet, result, error, f"read voltage ID={servo_id}")
    temperature, result, error = packet.read1ByteTxRx(
        servo_id, SCSCL_PRESENT_TEMPERATURE
    )
    check(packet, result, error, f"read temperature ID={servo_id}")
    return position, voltage, temperature


def read_torque(packet: scscl, servo_id: int) -> int:
    torque, result, error = packet.read1ByteTxRx(
        servo_id, SCSCL_TORQUE_ENABLE
    )
    check(packet, result, error, f"read torque ID={servo_id}")
    return torque


def read_angle_limits(packet: scscl, servo_id: int) -> tuple[int, int]:
    minimum, result, error = packet.read2ByteTxRx(
        servo_id, SCSCL_MIN_ANGLE_LIMIT_L
    )
    check(packet, result, error, f"read minimum angle limit ID={servo_id}")
    maximum, result, error = packet.read2ByteTxRx(
        servo_id, SCSCL_MAX_ANGLE_LIMIT_L
    )
    check(packet, result, error, f"read maximum angle limit ID={servo_id}")
    return minimum, maximum


def wait_for_position(
    packet: scscl,
    servo_id: int,
    target: int,
    tolerance: int = 8,
    timeout_s: float = 12.0,
) -> int:
    deadline = time.monotonic() + timeout_s
    last = -1
    while time.monotonic() < deadline:
        last = read_position(packet, servo_id)
        if abs(last - target) <= tolerance:
            return last
        time.sleep(0.05)
    raise RuntimeError(
        f"ID={servo_id} reference timeout: target={target}, last_position={last}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--speed", type=int, default=100)
    parser.add_argument("--hold-seconds", type=int, default=120)
    parser.add_argument("--frame-mounted-confirmed", action="store_true")
    args = parser.parse_args()

    if not args.frame_mounted_confirmed:
        print("REFUSED: mount IDs 1/2 in the finger frame before centering.")
        return 2
    if not 5 <= args.hold_seconds <= 300:
        print("REFUSED: hold-seconds must be 5..300.")
        return 2
    if not 1 <= args.speed <= MAX_SAFE_SPEED:
        print(f"REFUSED: speed must be 1..{MAX_SAFE_SPEED}.")
        return 2

    port = PortHandler(args.port)
    packet = scscl(port)
    enabled: list[int] = []
    try:
        if not port.openPort() or not port.setBaudRate(args.baud):
            raise RuntimeError("could not open/configure serial port")

        starts: dict[int, int] = {}
        for servo_id in SERVO_IDS:
            model, result, error = packet.ping(servo_id)
            check(packet, result, error, f"ping ID={servo_id}")
            if model != EXPECTED_MODEL:
                raise RuntimeError(
                    f"unexpected model ID={servo_id}: {model} "
                    f"(expected {EXPECTED_MODEL})"
                )
            position, voltage, temperature = read_status(packet, servo_id)
            torque = read_torque(packet, servo_id)
            minimum, maximum = read_angle_limits(packet, servo_id)
            if not 50 <= voltage <= 70:
                raise RuntimeError(f"unsafe voltage ID={servo_id}: {voltage / 10:.1f}V")
            if temperature >= MAX_TEMPERATURE_C:
                raise RuntimeError(
                    f"temperature too high ID={servo_id}: {temperature}C"
                )
            if torque != 0:
                raise RuntimeError(f"torque already enabled ID={servo_id}: {torque}")
            if not minimum <= RAW_ELECTRICAL_MIDPOINT <= maximum:
                raise RuntimeError(
                    f"electrical midpoint outside angle limits ID={servo_id}: "
                    f"{minimum}..{maximum}"
                )
            starts[servo_id] = position
            print(
                f"READY: ID={servo_id} model={model} position={position} "
                f"voltage={voltage / 10:.1f}V temperature={temperature}C "
                f"limits={minimum}..{maximum}"
            )

        for servo_id in SERVO_IDS:
            # Apply torque at the measured position first to avoid a startup jump.
            result, error = packet.WritePos(
                servo_id, starts[servo_id], 0, args.speed
            )
            check(packet, result, error, f"hold start ID={servo_id}")
            result, error = packet.write1ByteTxRx(
                servo_id, SCSCL_TORQUE_ENABLE, 1
            )
            check(packet, result, error, f"enable torque ID={servo_id}")
            enabled.append(servo_id)

            # Move one motor to the electrical midpoint before moving the other.
            # This reduces peak current; it does not establish mechanical center.
            result, error = packet.WritePos(
                servo_id, RAW_ELECTRICAL_MIDPOINT, 0, args.speed
            )
            check(packet, result, error, f"reference ID={servo_id}")
            reached = wait_for_position(packet, servo_id, RAW_ELECTRICAL_MIDPOINT)
            print(f"AT_REFERENCE: ID={servo_id} position={reached}")

        print(
            f"HOLDING: both servos near raw electrical midpoint "
            f"{RAW_ELECTRICAL_MIDPOINT} for "
            f"{args.hold_seconds}s. Fit horns now; Ctrl+C also releases torque."
        )
        deadline = time.monotonic() + args.hold_seconds
        next_report = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_report:
                report: list[str] = []
                for servo_id in SERVO_IDS:
                    position, voltage, temperature = read_status(packet, servo_id)
                    if not 50 <= voltage <= 70 or temperature >= MAX_TEMPERATURE_C:
                        raise RuntimeError(
                            f"unsafe hold status ID={servo_id}: position={position}, "
                            f"voltage={voltage / 10:.1f}V, temperature={temperature}C"
                        )
                    if abs(position - RAW_ELECTRICAL_MIDPOINT) > HOLD_TOLERANCE:
                        raise RuntimeError(
                            f"position drift during hold ID={servo_id}: "
                            f"position={position}, target={RAW_ELECTRICAL_MIDPOINT}"
                        )
                    report.append(
                        f"ID{servo_id}:pos={position},V={voltage / 10:.1f},T={temperature}"
                    )
                remaining = max(0, int(deadline - now))
                print(f"HOLD STATUS ({remaining}s left): " + " | ".join(report))
                next_report = now + 5.0
            time.sleep(0.1)

        print("PASS: electrical-reference hold completed; releasing torque.")
        return 0
    except KeyboardInterrupt:
        print("STOP: interrupted; releasing torque.")
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}; releasing torque.")
        return 1
    finally:
        for servo_id in SERVO_IDS:
            try:
                packet.write1ByteTxRx(servo_id, SCSCL_TORQUE_ENABLE, 0)
            except Exception:
                pass
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
