"""Trigger the fixed Titan index-finger lateral bench test via SWD mailbox."""

from __future__ import annotations

import sys
import time

from pyocd.core.helpers import ConnectHelper


PROBE_ID = "0001A0000001"
TARGET = "R7KA8P1KF"
FREQUENCY_HZ = 1_000_000
REQUEST_ADDRESS = 0x22000400
RESULT_ADDRESS = 0x22000420
INDEX_LATERAL_MAGIC = 0x534D4C31
TIMEOUT_SECONDS = 20.0


def main() -> int:
    with ConnectHelper.session_with_chosen_probe(
        unique_id=PROBE_ID,
        target_override=TARGET,
        frequency=FREQUENCY_HZ,
        connect_mode="attach",
        load_svd=False,
    ) as session:
        target = session.target
        target.write32(RESULT_ADDRESS, 0)
        target.write32(REQUEST_ADDRESS, INDEX_LATERAL_MAGIC)
        target.flush()
        print("TRIGGERED fixed index lateral test")

        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            result = target.read32(RESULT_ADDRESS)
            request = target.read32(REQUEST_ADDRESS)
            if result != 0:
                print(f"RESULT={result} REQUEST=0x{request:08X}")
                return 0 if result == 1 else 2
            time.sleep(0.2)

        request = target.read32(REQUEST_ADDRESS)
        print(f"TIMEOUT REQUEST=0x{request:08X}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
