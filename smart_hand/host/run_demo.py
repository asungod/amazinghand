"""Run the communication logic without either development board."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from protocol import StreamParser, encode_frame  # noqa: E402


def titan_process(raw_bytes):
    parser = StreamParser()
    replies = []
    for message in parser.feed(raw_bytes):
        print("Titan RX:", message)
        replies.append(encode_frame("ACK", message["seq"], 0))
    return b"".join(replies)


def main():
    maix_parser = StreamParser()
    ping = encode_frame("PING", 1)
    vision = encode_frame("VISION", 2, 3, 320, 240, 80, 120, 96)

    print("Maix TX:", ping.decode().strip())
    response = titan_process(ping[:4] + ping[4:] + vision)
    for message in maix_parser.feed(response):
        print("Maix RX:", message)

    broken = bytearray(encode_frame("VISION", 3, 2, 100, 100, 30, 40, 88))
    broken[8] ^= 0x01
    valid_after_error = encode_frame("PING", 4)
    print("\nInjecting one corrupted frame, then a valid frame...")
    response = titan_process(b"garbage" + bytes(broken) + valid_after_error)
    parsed = maix_parser.feed(response)
    print("Recovered ACKs:", parsed)
    assert [item["seq"] for item in parsed] == [4]
    print("Demo passed")


if __name__ == "__main__":
    main()

