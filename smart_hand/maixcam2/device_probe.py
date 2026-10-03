"""Minimal MaixCAM2 bring-up probe.

Run this file on the MaixCAM2 from MaixVision.  It performs no writes to
external hardware and only reports the detected board and UART devices.
"""

from maix import sys, uart


print("=== MaixCAM2 device probe ===")
print("device:", sys.device_id())
print("uart devices:", uart.list_devices())
print("expected project UART: /dev/ttyS4 (A21 TX, A22 RX)")

