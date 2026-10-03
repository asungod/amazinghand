"""Compatibility entrypoint for offline UART frame acceptance.

The real implementation lives in no_servo_uart_acceptance.py and uses the
project ASCII protocol ($TYPE,seq,...*CRC). This wrapper never opens serial.
"""

from no_servo_uart_acceptance import main

if __name__ == "__main__":
    raise SystemExit(main())
