"""Verify programmed Titan firmware against the data records in an Intel HEX file."""

from __future__ import annotations

import argparse
import sys

from intelhex import IntelHex
from pyocd.core.helpers import ConnectHelper


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("hex_file")
    parser.add_argument("--probe", default="0001A0000001")
    parser.add_argument("--target", default="R7KA8P1KF")
    parser.add_argument("--frequency", type=int, default=1_000_000)
    parser.add_argument("--chunk-size", type=int, default=1024)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image = IntelHex(args.hex_file)
    segments = image.segments()
    checked = 0

    with ConnectHelper.session_with_chosen_probe(
        unique_id=args.probe,
        target_override=args.target,
        frequency=args.frequency,
        connect_mode="attach",
        load_svd=False,
    ) as session:
        target = session.target
        for start, end in segments:
            for address in range(start, end, args.chunk_size):
                length = min(args.chunk_size, end - address)
                expected = bytes(image.tobinarray(start=address, size=length))
                actual = bytes(target.read_memory_block8(address, length))
                if actual != expected:
                    for offset, (actual_byte, expected_byte) in enumerate(
                        zip(actual, expected)
                    ):
                        if actual_byte != expected_byte:
                            mismatch = address + offset
                            print(
                                f"VERIFY FAIL 0x{mismatch:08x}: "
                                f"device=0x{actual_byte:02x} hex=0x{expected_byte:02x}"
                            )
                            return 1
                    print(f"VERIFY FAIL near 0x{address:08x}")
                    return 1
                checked += length

    print(f"VERIFY OK: {checked} explicit HEX bytes across {len(segments)} segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
