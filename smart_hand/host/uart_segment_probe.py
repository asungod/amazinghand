"""PC-side UART segment / loopback helper.

Default is dry-run.  Opening a serial port requires all three gates at once:

1. explicit --port (no enumerate, no default COM)
2. --confirm-hardware
3. baud exactly 115200

This tool does not flash, toggle GPIO, switch power, or talk to servos.
This offline batch should only be executed as dry-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


ALLOWED_BAUD = 115200
TEST_FRAME = b"UART2_LOOPBACK_PROBE_v1\n"
DEFAULT_TIMEOUT_S = 0.3


def classify_echo(sent, received):
    if received == sent:
        return "echo_ok"
    if not received:
        return "no_echo"
    if sent.startswith(received) and len(received) < len(sent):
        return "partial_echo"
    return "malformed_echo"


def dry_run_report():
    return {
        "probe": "uart_segment_probe",
        "mode": "dry-run",
        "hardware_accessed": False,
        "serial_opened": False,
        "tx_bytes": 0,
        "rx_bytes": 0,
        "timeouts": 0,
        "result": "dry_run_planned",
        "reason": (
            "default dry-run; no port enumeration; serial is not imported "
            "and not opened"
        ),
        "baud": ALLOWED_BAUD,
        "test_frame_hex": TEST_FRAME.hex(),
        "live_requires": ["--port", "--confirm-hardware", "baud=115200"],
    }


def live_gate_error(args):
    """Return an error string if live gates fail.  Must run before serial import."""
    want_live = bool(getattr(args, "port", None)) or bool(
        getattr(args, "confirm_hardware", False)
    )
    if not want_live:
        return None
    if not getattr(args, "port", None):
        return "live mode requires explicit --port (no auto-enumerate, no default)"
    if not getattr(args, "confirm_hardware", False):
        return "live mode requires --confirm-hardware before any serial open"
    baud = int(getattr(args, "baud", ALLOWED_BAUD) or ALLOWED_BAUD)
    if baud != ALLOWED_BAUD:
        return "only baud {} is allowed (got {})".format(ALLOWED_BAUD, baud)
    return None


class FakeSerial:
    """In-process serial stand-in for unit tests.  Never touches hardware."""

    def __init__(self, response=b"", raise_on_open=False, chunk_size=0):
        self.response = bytes(response)
        self.raise_on_open = raise_on_open
        self.chunk_size = int(chunk_size)
        self.opened = False
        self.closed = False
        self.written = b""
        self._offset = 0
        self.port = None
        self.baudrate = None
        self.timeout = None

    def open(self):
        if self.raise_on_open:
            raise OSError("fake serial open failed")
        self.opened = True

    def close(self):
        self.closed = True
        self.opened = False

    def write(self, data):
        self.written += bytes(data)
        return len(data)

    def read(self, size=1):
        if self._offset >= len(self.response):
            return b""
        if self.chunk_size > 0:
            size = min(size, self.chunk_size)
        end = min(self._offset + size, len(self.response))
        chunk = self.response[self._offset:end]
        self._offset = end
        return chunk

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def collect_until(serial, expected_len, timeout_s):
    """Read up to expected_len bytes.  Empty reads increment timeouts."""
    buf = bytearray()
    timeouts = 0
    # Bound the loop so mocks without a clock cannot spin forever.
    max_empty = max(1, int(timeout_s / 0.01) if timeout_s else 1)
    empty = 0
    while len(buf) < expected_len and empty < max_empty:
        chunk = serial.read(expected_len - len(buf)) or b""
        if chunk:
            buf.extend(chunk)
        else:
            timeouts += 1
            empty += 1
    return bytes(buf), timeouts


def run_loopback(serial, frame=TEST_FRAME, timeout_s=DEFAULT_TIMEOUT_S):
    if not getattr(serial, "opened", True):
        serial.open()
    tx_n = serial.write(frame)
    received, timeouts = collect_until(serial, len(frame), timeout_s)
    result = classify_echo(frame, received)
    return {
        "hardware_accessed": True,
        "serial_opened": True,
        "tx_bytes": int(tx_n),
        "rx_bytes": len(received),
        "timeouts": int(timeouts),
        "result": result,
        "reason": "compared RX against fixed TEST_FRAME",
        "rx_hex": received.hex(),
        "test_frame_hex": frame.hex(),
    }


def open_real_serial(port, baud, timeout_s):
    import serial  # imported only after gates pass

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = timeout_s
    ser.open()
    return ser


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="UART segment loopback helper (default dry-run)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan-only (already the default when --port is omitted)",
    )
    parser.add_argument(
        "--port",
        default=None,
        help="Explicit serial port, e.g. COM14.  No default, no scan.",
    )
    parser.add_argument(
        "--confirm-hardware",
        action="store_true",
        help="Required with --port.  Confirm isolated loopback / authorized UART only.",
    )
    parser.add_argument("--baud", type=int, default=ALLOWED_BAUD)
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help="Read timeout in seconds for a live run",
    )
    parser.add_argument("--json-out", default=None)
    return parser


def emit(report, json_out=None):
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if json_out:
        with open(json_out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return text


def main(argv=None, serial_factory=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    want_live = bool(args.port) or bool(args.confirm_hardware)
    if not want_live or args.dry_run and not args.port:
        report = dry_run_report()
        emit(report, args.json_out)
        return 0 if report["hardware_accessed"] is False else 1

    err = live_gate_error(args)
    if err:
        report = {
            "probe": "uart_segment_probe",
            "mode": "live_rejected",
            "hardware_accessed": False,
            "serial_opened": False,
            "tx_bytes": 0,
            "rx_bytes": 0,
            "timeouts": 0,
            "result": "gate_rejected",
            "reason": err,
            "port": args.port,
            "baud": args.baud,
        }
        emit(report, args.json_out)
        return 2

    factory = serial_factory or open_real_serial
    serial = None
    try:
        serial = factory(args.port, args.baud, args.timeout_s)
        if hasattr(serial, "open") and not getattr(serial, "opened", True):
            serial.open()
        loop = run_loopback(serial, TEST_FRAME, args.timeout_s)
    except (OSError, ValueError) as exc:
        report = {
            "probe": "uart_segment_probe",
            "mode": "live",
            "hardware_accessed": True,
            "serial_opened": False,
            "tx_bytes": 0,
            "rx_bytes": 0,
            "timeouts": 0,
            "result": "open_failed",
            "reason": str(exc),
            "port": args.port,
            "baud": args.baud,
        }
        emit(report, args.json_out)
        return 1
    finally:
        if serial is not None and hasattr(serial, "close"):
            try:
                serial.close()
            except OSError:
                pass

    report = {
        "probe": "uart_segment_probe",
        "mode": "live",
        "port": args.port,
        "baud": args.baud,
    }
    report.update(loop)
    emit(report, args.json_out)
    return 0 if report["result"] == "echo_ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
