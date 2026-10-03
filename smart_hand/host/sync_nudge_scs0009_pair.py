"""Tiny synchronized motion/return test for loose SCS0009 IDs 1 and 2."""

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
    SCSCL_TORQUE_ENABLE,
    scscl,
)


SERVO_IDS = (1, 2)
RAW_ELECTRICAL_MIDPOINT = 511
MAX_TEMPERATURE_C = 50
SAFE_ENDPOINT_MARGIN = 30


def check(packet: scscl, result: int, error: int, label: str) -> None:
    if result != COMM_SUCCESS:
        raise RuntimeError(f"{label}: {packet.getTxRxResult(result)}")
    if error:
        raise RuntimeError(f"{label}: {packet.getRxPacketError(error)}")


def sync_positions(packet: scscl, positions: dict[int, int], speed: int) -> None:
    packet.groupSyncWrite.clearParam()
    for servo_id in SERVO_IDS:
        if not packet.SyncWritePos(servo_id, positions[servo_id], 0, speed):
            raise RuntimeError(f"sync addParam failed for ID={servo_id}")
    result = packet.groupSyncWrite.txPacket()
    packet.groupSyncWrite.clearParam()
    if result != COMM_SUCCESS:
        raise RuntimeError(f"sync tx: {packet.getTxRxResult(result)}")


def read_positions(packet: scscl) -> dict[int, int]:
    values: dict[int, int] = {}
    for servo_id in SERVO_IDS:
        value, result, error = packet.ReadPos(servo_id)
        check(packet, result, error, f"read position ID={servo_id}")
        values[servo_id] = value
    return values


def compute_safe_target(position: int, delta: int) -> int:
    """Return an inward target while excluding uncalibrated endpoint zones."""
    if not 0 <= position <= 1023:
        raise RuntimeError(f"implausible start position: {position}")
    if not SAFE_ENDPOINT_MARGIN <= position <= 1023 - SAFE_ENDPOINT_MARGIN:
        raise RuntimeError(
            f"start position {position} is inside the uncalibrated endpoint zone"
        )
    direction = 1 if position <= RAW_ELECTRICAL_MIDPOINT else -1
    target = position + direction * delta
    if not SAFE_ENDPOINT_MARGIN <= target <= 1023 - SAFE_ENDPOINT_MARGIN:
        raise RuntimeError(f"target {target} is inside the endpoint exclusion zone")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument("--delta", type=int, default=16)
    parser.add_argument("--speed", type=int, default=100)
    parser.add_argument("--loose-servos-confirmed", action="store_true")
    args = parser.parse_args()

    if not args.loose_servos_confirmed:
        print("REFUSED: confirm both servos are loose, unobstructed, and unmounted.")
        return 2
    if not 1 <= args.delta <= 30:
        print("REFUSED: delta must be 1..30 raw counts.")
        return 2

    port = PortHandler(args.port)
    packet = scscl(port)
    enabled: list[int] = []
    try:
        if not port.openPort() or not port.setBaudRate(args.baud):
            raise RuntimeError("could not open/configure serial port")

        starts: dict[int, int] = {}
        targets: dict[int, int] = {}
        for servo_id in SERVO_IDS:
            _model, result, error = packet.ping(servo_id)
            check(packet, result, error, f"ping ID={servo_id}")
            position, result, error = packet.ReadPos(servo_id)
            check(packet, result, error, f"read start ID={servo_id}")
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
            # 511 is an electrical midpoint, not a measured mechanical center.
            target = compute_safe_target(position, args.delta)
            starts[servo_id] = position
            targets[servo_id] = target

        print(f"START: {starts}; TARGET: {targets}")
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

        sync_positions(packet, targets, args.speed)
        time.sleep(0.6)
        reached = read_positions(packet)

        sync_positions(packet, starts, args.speed)
        time.sleep(0.6)
        returned = read_positions(packet)
        print(f"REACHED: {reached}; RETURNED: {returned}")

        for servo_id in SERVO_IDS:
            if abs(reached[servo_id] - targets[servo_id]) > 8:
                raise RuntimeError(f"ID={servo_id} did not reach synchronized target")
            if abs(returned[servo_id] - starts[servo_id]) > 8:
                raise RuntimeError(f"ID={servo_id} did not return to start")
        print("PASS: synchronized pair motion and return verified.")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
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
