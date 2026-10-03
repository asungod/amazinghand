"""Safely change one isolated SCS0009 servo ID without commanding motion."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_ROOT = PROJECT_ROOT / "third_party" / "STServo_Python" / "stservo-env"
sys.path.insert(0, str(VENDOR_ROOT))
sys.path.insert(0, str(VENDOR_ROOT / "Lib" / "site-packages"))

from scservo_sdk import COMM_SUCCESS, PortHandler, scs_id, scscl  # type: ignore  # noqa: E402


def ping(packet: scscl, servo_id: int) -> tuple[bool, int, int]:
    model, result, error = packet.ping(servo_id)
    return result == COMM_SUCCESS and error == 0, model, error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="For example COM4")
    parser.add_argument("--old-id", required=True, type=int)
    parser.add_argument("--new-id", required=True, type=int)
    parser.add_argument("--baud", type=int, default=1_000_000)
    parser.add_argument(
        "--only-one-servo-connected",
        action="store_true",
        help="Mandatory safety acknowledgement",
    )
    args = parser.parse_args()

    if not args.only_one_servo_connected:
        print("REFUSED: disconnect every servo except the one whose ID will change.")
        return 2
    if not (0 <= args.old_id <= 253 and 0 <= args.new_id <= 253):
        print("REFUSED: IDs must be in range 0..253.")
        return 2
    if args.old_id == args.new_id:
        print("REFUSED: old and new IDs are identical.")
        return 2

    port = PortHandler(args.port)
    packet = scscl(port)
    try:
        if not port.openPort() or not port.setBaudRate(args.baud):
            print("ERROR: could not open/configure serial port.")
            return 3

        old_ok, old_model, _ = ping(packet, args.old_id)
        new_ok, _, _ = ping(packet, args.new_id)
        if not old_ok:
            print(f"REFUSED: old ID {args.old_id} did not respond.")
            return 4
        if new_ok:
            print(f"REFUSED: new ID {args.new_id} already responds.")
            return 4
        print(f"Verified one responding servo: ID={args.old_id}, model={old_model}.")

        result, error = packet.unLockEprom(args.old_id)
        if result != COMM_SUCCESS or error != 0:
            print("ERROR: could not unlock servo configuration.")
            return 5

        write_result, write_error = packet.write1ByteTxRx(
            args.old_id, scs_id, args.new_id
        )
        time.sleep(0.1)

        # The reply can be lost when the device changes address, so verification
        # is based on read-only pings at both the old and new addresses.
        changed, new_model, _ = ping(packet, args.new_id)
        old_still_responds, _, _ = ping(packet, args.old_id)
        if not changed or old_still_responds:
            if old_still_responds:
                packet.LockEprom(args.old_id)
            print(
                "ERROR: ID change was not verified "
                f"(write_result={write_result}, write_error={write_error})."
            )
            return 6

        lock_result, lock_error = packet.LockEprom(args.new_id)
        if lock_result != COMM_SUCCESS or lock_error != 0:
            print("WARNING: ID changed, but configuration lock was not acknowledged.")
            return 7

        final_ok, final_model, _ = ping(packet, args.new_id)
        if not final_ok or final_model != new_model:
            print("ERROR: final verification ping failed.")
            return 8

        print(
            f"PASS: servo model={final_model} changed from ID={args.old_id} "
            f"to ID={args.new_id}; no motion command was sent."
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 9
    finally:
        port.closePort()


if __name__ == "__main__":
    raise SystemExit(main())
