"""Generate deterministic UART parser fault cases with expected outcomes."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from protocol import StreamParser, crc16_ccitt, encode_frame  # noqa: E402


def raw_frame(body_text):
    body = body_text.encode("ascii")
    return b"$" + body + b"*%04X\r\n" % crc16_ccitt(body)


def message(message_type, sequence, *args):
    return {"type": message_type, "seq": sequence, "args": list(args)}


def build_cases():
    ping_1 = encode_frame("PING", 1)
    ping_2 = encode_frame("PING", 2)
    vision_3 = encode_frame("VISION", 3, 41, 320, 240, 80, 120, 91)
    broken_vision = bytearray(encode_frame("VISION", 7, 47, 100, 120, 30, 40, 88))
    broken_vision[3] ^= 1

    return [
        {
            "name": "normal_ping",
            "purpose": "baseline valid frame",
            "chunks": [ping_1],
            "expected": [message("PING", 1)],
        },
        {
            "name": "fragmented_vision",
            "purpose": "one frame split at arbitrary UART read boundaries",
            "chunks": [vision_3[:2], vision_3[2:9], vision_3[9:]],
            "expected": [message("VISION", 3, 41, 320, 240, 80, 120, 91)],
        },
        {
            "name": "concatenated_frames",
            "purpose": "multiple complete frames in one UART read",
            "chunks": [ping_1 + vision_3],
            "expected": [
                message("PING", 1),
                message("VISION", 3, 41, 320, 240, 80, 120, 91),
            ],
        },
        {
            "name": "crc_error_then_recovery",
            "purpose": "drop a corrupted frame and recover the next valid frame",
            "chunks": [bytes(broken_vision) + ping_2],
            "expected": [message("PING", 2)],
        },
        {
            "name": "garbage_prefix",
            "purpose": "ignore boot text and noise before a frame header",
            "chunks": [b"boot log\r\nnoise\x00\xff" + ping_1],
            "expected": [message("PING", 1)],
        },
        {
            "name": "unterminated_then_new_header",
            "purpose": "restart parsing when a new header arrives before newline",
            "chunks": [b"$VISION,9,broken", ping_2],
            "expected": [message("PING", 2)],
        },
        {
            "name": "oversized_unterminated_then_recovery",
            "purpose": "bound parser memory and recover after oversized input",
            "chunks": [b"$" + b"A" * 200, ping_1],
            "expected": [message("PING", 1)],
        },
        {
            "name": "unknown_type_then_recovery",
            "purpose": "drop a valid-CRC unsupported type and continue",
            "chunks": [raw_frame("UNKNOWN,5") + ping_2],
            "expected": [message("PING", 2)],
        },
        {
            "name": "sequence_rollover",
            "purpose": "accept the unsigned 16-bit sequence boundary",
            "chunks": [encode_frame("PING", 65535), encode_frame("PING", 0)],
            "expected": [message("PING", 65535), message("PING", 0)],
        },
        {
            "name": "maximum_status_payload",
            "purpose": "accept the unsigned 32-bit argument boundary",
            "chunks": [encode_frame("STATUS", 8, 0xFFFFFFFF, 0)],
            "expected": [message("STATUS", 8, 0xFFFFFFFF, 0)],
        },
    ]


def verify_cases(cases):
    failures = []
    for case in cases:
        parser = StreamParser()
        actual = []
        for chunk in case["chunks"]:
            actual.extend(parser.feed(chunk))
        if actual != case["expected"]:
            failures.append(
                "{} expected {!r}, got {!r}".format(case["name"], case["expected"], actual)
            )
    return failures


def serializable_cases(cases):
    return {
        "format_version": 1,
        "cases": [
            {
                "name": case["name"],
                "purpose": case["purpose"],
                "chunks_hex": [chunk.hex().upper() for chunk in case["chunks"]],
                "expected": case["expected"],
            }
            for case in cases
        ],
    }


def load_corpus(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format_version") != 1 or not isinstance(data.get("cases"), list):
        raise ValueError("unsupported UART corpus format")
    cases = []
    for item in data["cases"]:
        cases.append(
            {
                "name": item["name"],
                "purpose": item["purpose"],
                "chunks": [bytes.fromhex(value) for value in item["chunks_hex"]],
                "expected": item["expected"],
            }
        )
    return cases


def write_corpus(path, cases):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(serializable_cases(cases), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = build_cases()
    failures = verify_cases(cases)
    if failures:
        print("UART fault corpus verification failed:", file=sys.stderr)
        for failure in failures:
            print("-", failure, file=sys.stderr)
        return 1
    if args.output is not None:
        write_corpus(args.output, cases)
        print("Wrote {} verified UART cases to {}".format(len(cases), args.output))
    else:
        print("Verified {} in-memory UART fault cases".format(len(cases)))
    print("UART FAULT CORPUS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
