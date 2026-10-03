"""Check whether application code can claim MaixCAM2 UART4.

Run from MaixVision with nothing connected to A21/A22.  The script only sends
one short ASCII line and reports whether opening UART4 succeeded.
"""

from maix import err, pinmap, uart


DEVICE = "/dev/ttyS4"
BAUD = 115200

print("=== UART4 open probe ===")

try:
    err.check_raise(
        pinmap.set_pin_function("A21", "UART4_TX"),
        "failed to configure A21 as UART4_TX",
    )
    err.check_raise(
        pinmap.set_pin_function("A22", "UART4_RX"),
        "failed to configure A22 as UART4_RX",
    )
    serial = uart.UART(DEVICE, BAUD)
    sent = serial.write(b"SMART_HAND_UART4_PROBE\r\n")
    print("UART4 OPEN OK")
    print("write result:", sent)
except Exception as exc:
    print("UART4 OPEN FAILED:", repr(exc))

