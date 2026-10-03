"""Read-only discovery probe for one Feetech SCS0009 servo.

This tool only sends protocol PING packets. It does not enable torque, command
motion, change an ID, or write any servo register.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = PROJECT_ROOT / "third_party" / "STServo_Python" / "stservo-env"
VENDOR_SITE_PACKAGES = VENDOR_ROOT / "Lib" / "site-packages"

sys.path.insert(0, str(VENDOR_ROOT))
sys.path.insert(0, str(VENDOR_SITE_PACKAGES))

from serial.tools import list_ports  # type: ignore  # noqa: E402
from scservo_sdk import COMM_SUCCESS, PortHandler, scscl  # type: ignore  # noqa: E402


DEFAULT_BAUD = 1_000_000

# SCSCL read-only status register addresses from the vendor SDK.
PRESENT_POSITION = 56
PRESENT_SPEED = 58
PRESENT_LOAD = 60
PRESENT_VOLTAGE = 62
PRESENT_TEMPERATURE = 63
MOVING = 66
PRESENT_CURRENT = 69
MIN_ANGLE_LIMIT = 9
MAX_ANGLE_LIMIT = 11
TORQUE_ENABLE = 40
GOAL_POSITION = 42


def available_ports() -> list[str]:
    return [item.device for item in list_ports.comports()]


def choose_port(requested: str | None) -> str:
    ports = available_ports()
    if requested:
        return requested
    if len(ports) == 1:
        return ports[0]
    if not ports:
        raise RuntimeError("No serial port found. Check the adapter USB cable and jumper B.")
    raise RuntimeError(
        "Multiple serial ports found: "
        + ", ".join(ports)
        + ". Run again with --port COMx."
    )


def parse_ids(text: str) -> list[int]:
    result: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first_text, last_text = part.split("-", 1)
            first, last = int(first_text), int(last_text)
            result.extend(range(first, last + 1))
        else:
            result.append(int(part))
    if not result or any(item < 0 or item > 253 for item in result):
        raise ValueError("Servo IDs must be in range 0..253")
    return list(dict.fromkeys(result))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Adapter serial port, for example COM4")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument(
        "--ids",
        default="1,0-20",
        help="Read-only ID scan order/range (default: 1,0-20)",
    )
    args = parser.parse_args()

    port_name = choose_port(args.port)
    servo_ids = parse_ids(args.ids)
    print("SCS0009 READ-ONLY PING")
    print(f"port={port_name} baud={args.baud} ids={servo_ids}")
    print("No register will be written and no motion command will be sent.")

    port = PortHandler(port_name)
    packet = scscl(port)
    try:
        opened = port.openPort()
    except Exception as exc:
        print(f"ERROR: cannot open {port_name}: {exc}")
        print("Close serial monitors/servo tools that may already be using this COM port.")
        return 2
    if not opened:
        print(f"ERROR: cannot open {port_name}; close other serial software first.")
        return 2

    try:
        if not port.setBaudRate(args.baud):
            print(f"ERROR: cannot set baud rate {args.baud}.")
            return 3

        found: list[tuple[int, int]] = []
        for servo_id in servo_ids:
            model, comm_result, servo_error = packet.ping(servo_id)
            if comm_result == COMM_SUCCESS:
                found.append((servo_id, model))
                print(f"FOUND: ID={servo_id} model={model} error=0x{servo_error:02X}")

        if not found:
            print("NO SERVO RESPONSE")
            print("Check: external 6.0 V on, jumper B, one servo, D/V/G order, COM port.")
            return 1

        for servo_id, _model in found:
            min_limit, min_result, min_error = packet.read2ByteTxRx(
                servo_id, MIN_ANGLE_LIMIT
            )
            max_limit, max_result, max_error = packet.read2ByteTxRx(
                servo_id, MAX_ANGLE_LIMIT
            )
            torque_enabled, torque_result, torque_error = packet.read1ByteTxRx(
                servo_id, TORQUE_ENABLE
            )
            goal_position, goal_result, goal_error = packet.read2ByteTxRx(
                servo_id, GOAL_POSITION
            )
            position, pos_result, pos_error = packet.read2ByteTxRx(
                servo_id, PRESENT_POSITION
            )
            speed, speed_result, speed_error = packet.read2ByteTxRx(
                servo_id, PRESENT_SPEED
            )
            load, load_result, load_error = packet.read2ByteTxRx(
                servo_id, PRESENT_LOAD
            )
            voltage, voltage_result, voltage_error = packet.read1ByteTxRx(
                servo_id, PRESENT_VOLTAGE
            )
            temperature, temp_result, temp_error = packet.read1ByteTxRx(
                servo_id, PRESENT_TEMPERATURE
            )
            moving, moving_result, moving_error = packet.read1ByteTxRx(
                servo_id, MOVING
            )
            current, current_result, current_error = packet.read2ByteTxRx(
                servo_id, PRESENT_CURRENT
            )
            results = (
                min_result,
                max_result,
                torque_result,
                goal_result,
                pos_result,
                speed_result,
                load_result,
                voltage_result,
                temp_result,
                moving_result,
                current_result,
            )
            errors = (
                min_error,
                max_error,
                torque_error,
                goal_error,
                pos_error,
                speed_error,
                load_error,
                voltage_error,
                temp_error,
                moving_error,
                current_error,
            )
            if all(item == COMM_SUCCESS for item in results) and not any(errors):
                print(
                    "CONFIG: "
                    f"ID={servo_id} min_limit_raw={min_limit} "
                    f"max_limit_raw={max_limit} torque_enabled={torque_enabled} "
                    f"goal_position_raw={goal_position}"
                )
                print(
                    "STATUS: "
                    f"ID={servo_id} position_raw={position} speed_raw={speed} "
                    f"load_raw={load} voltage_raw={voltage} "
                    f"temperature_C={temperature} moving={moving} current_raw={current}"
                )
            else:
                print(
                    f"STATUS WARNING: ID={servo_id} could not read every status register; "
                    "the successful PING result remains valid."
                )

        print(f"PASS: found {len(found)} servo(s): {found}")
        return 0
    finally:
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
