"""MaixCAM2 UART2 loopback probe (single file, no project imports).

Default behaviour on a PC: print JSON with hardware_accessed=false and exit.
On MaixCAM2 this script configures B0/B1 as UART2, sends one fixed frame to
/dev/ttyS2, and waits for an exact echo.  It does not import other smart_hand
files, does not touch GPIO power rails, and does not talk to servos.

This batch must not be used to guess pins or to reconnect boards.
"""

from __future__ import annotations

import json
import sys


DEVICE = "/dev/ttyS2"
BAUD = 115200
TX_PIN = "B0"
TX_FUNC = "UART2_TX"
RX_PIN = "B1"
RX_FUNC = "UART2_RX"
TEST_FRAME = b"UART2_LOOPBACK_PROBE_v1\n"
READ_TIMEOUT_MS = 300


def classify_echo(sent, received):
    if received == sent:
        return "echo_ok"
    if not received:
        return "no_echo"
    if sent.startswith(received) and len(received) < len(sent):
        return "partial_echo"
    return "malformed_echo"


def build_report(
    hardware_accessed,
    serial_opened,
    tx_bytes,
    rx_bytes,
    timeouts,
    result,
    reason,
    extra=None,
):
    report = {
        "probe": "uart2_loopback_probe_single_file",
        "hardware_accessed": bool(hardware_accessed),
        "serial_opened": bool(serial_opened),
        "device": DEVICE,
        "baud": BAUD,
        "tx_pin": TX_PIN,
        "rx_pin": RX_PIN,
        "tx_bytes": int(tx_bytes),
        "rx_bytes": int(rx_bytes),
        "timeouts": int(timeouts),
        "result": result,
        "reason": reason,
        "test_frame_hex": TEST_FRAME.hex(),
    }
    if extra:
        report.update(extra)
    return report


def run_with_serial(serial, now_ms, sleep_ms, read_timeout_ms=READ_TIMEOUT_MS):
    """Send TEST_FRAME and wait for an exact echo using injected I/O.

    serial must provide write(bytes)->int and read()->bytes (possibly empty).
    now_ms()/sleep_ms() are injected so this function has no Maix import.
    """
    sent = serial.write(TEST_FRAME)
    if sent is None:
        sent = len(TEST_FRAME)
    sent = int(sent)
    deadline = now_ms() + int(read_timeout_ms)
    buf = bytearray()
    timeouts = 0
    while now_ms() < deadline and len(buf) < len(TEST_FRAME):
        chunk = serial.read() or b""
        if chunk:
            buf.extend(chunk)
        else:
            timeouts += 1
            sleep_ms(10)
    received = bytes(buf)
    result = classify_echo(TEST_FRAME, received)
    return build_report(
        hardware_accessed=True,
        serial_opened=True,
        tx_bytes=sent,
        rx_bytes=len(received),
        timeouts=timeouts,
        result=result,
        reason="echo compared against fixed TEST_FRAME",
        extra={"rx_hex": received.hex()},
    )


def run_on_maix():
    from maix import err, pinmap, time, uart

    err.check_raise(
        pinmap.set_pin_function(TX_PIN, TX_FUNC),
        "failed to configure B0 as UART2_TX",
    )
    err.check_raise(
        pinmap.set_pin_function(RX_PIN, RX_FUNC),
        "failed to configure B1 as UART2_RX",
    )
    serial = uart.UART(DEVICE, BAUD)
    return run_with_serial(
        serial,
        now_ms=time.ticks_ms,
        sleep_ms=time.sleep_ms,
    )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print("UART2 loopback probe. On PC this only prints dry JSON.")
        return 0

    # PC / this offline batch: never import serial, never open a port.
    try:
        import maix  # noqa: F401
    except ImportError:
        report = build_report(
            hardware_accessed=False,
            serial_opened=False,
            tx_bytes=0,
            rx_bytes=0,
            timeouts=0,
            result="dry_run_not_on_maix",
            reason="maix module absent; refuse to open any serial device",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    report = run_on_maix()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "echo_ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
