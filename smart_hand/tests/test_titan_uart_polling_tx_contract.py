"""Offline regression lock for the Titan UART2 ACK-blocking fix.

Root cause: ``smart_hand/titan_rtthread/smart_hand_uart.c`` configures an
RT-Thread serial v2 device.  A non-zero ``tx_bufsz`` selects the buffered TX
path, whose transmit completion the Titan RA8P1 driver does not implement, so
the first ACK write blocks forever.  The fix pins ``config.tx_bufsz = 0``
during configuration -- before ``rt_device_control(..., RT_DEVICE_CTRL_CONFIG,
&config)`` -- so the verified polling TX path is used.

Scope is deliberately narrow: the TX-buffer root cause, plus the two link
facts the fix must not disturb (uart2 at 115200 8N1, interrupt-driven RX).
Protocol, ACK and policy details belong to the suites that already own them.

Read-only and offline: no serial port, no board, no file is written; mutants
are built in memory from the source text.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UART_SOURCE = PROJECT_ROOT / "titan_rtthread" / "smart_hand_uart.c"

HARDWARE_ACCESSED = False

MISSING_FIX = (
    "`config.tx_bufsz = 0;` is the whole fix; without it serial v2 takes the "
    "buffered TX path and the first ACK blocks forever"
)

TX_BUFSZ_ZERO = re.compile(r"\bconfig\s*\.\s*tx_bufsz\s*=\s*0[uU]?\s*;")
TX_BUFSZ_ASSIGN = re.compile(r"\btx_bufsz\s*=\s*([^;]*);")
CONFIG_DECL = re.compile(
    r"\bstruct\s+serial_configure\s+config\s*=\s*RT_SERIAL_CONFIG_DEFAULT\s*;"
)
CONFIG_REINIT = re.compile(r"(?<!\w)config\s*=\s*RT_SERIAL_CONFIG_DEFAULT\s*;")
CTRL_CONFIG = re.compile(r"\brt_device_control\s*\([^;]*RT_DEVICE_CTRL_CONFIG[^;]*\)")
COMM_INIT = re.compile(r"\bsmart_hand_comm_init\s*\([^)]*\)\s*\{")
INT_RX = re.compile(r"\brt_device_open\s*\([^;]*RT_DEVICE_FLAG_INT_RX")
UART_NAME = re.compile(r"#\s*define\s+SMART_HAND_UART_NAME\s+\"([^\"]*)\"")

LINK_FIELDS = {
    "baud_rate": "BAUD_RATE_115200",
    "data_bits": "DATA_BITS_8",
    "stop_bits": "STOP_BITS_1",
    "parity": "PARITY_NONE",
}


def blank_comments_and_literals(text: str) -> str:
    """Same-length copy with comment and literal bodies blanked out.

    Offsets stay valid, and a statement that exists only inside a comment or a
    string can no longer satisfy the contract.
    """
    out: list[str] = []
    index, length, state, quote = 0, len(text), "code", ""
    while index < length:
        char = text[index]
        following = text[index + 1:index + 2]
        if state == "code":
            if char == "/" and following in ("/", "*"):
                state = "line" if following == "/" else "block"
                out.append("  ")
                index += 2
                continue
            if char in ("\"", "'"):
                state, quote = "literal", char
            out.append(char)
        elif state == "line":
            if char == "\n":
                state = "code"
            out.append("\n" if char == "\n" else " ")
        elif state == "block":
            if char == "*" and following == "/":
                state = "code"
                out.append("  ")
                index += 2
                continue
            out.append("\n" if char == "\n" else " ")
        elif char == "\\" and index + 1 < length:
            out.append("  ")
            index += 2
            continue
        elif char == quote:
            state = "code"
            out.append(char)
        else:
            out.append("\n" if char == "\n" else " ")
        index += 1
    return "".join(out)


def comm_init_span(code: str) -> tuple[int, int]:
    """Brace range of the ``smart_hand_comm_init`` body."""
    found = COMM_INIT.search(code)
    if found is None:
        raise AssertionError("smart_hand_comm_init definition not found")
    start = code.index("{", found.end() - 1)
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "{":
            depth += 1
        elif code[index] == "}":
            depth -= 1
            if depth == 0:
                return start, index
    raise AssertionError("unbalanced braces in smart_hand_comm_init")


class UartSource:
    """The few offsets and link fields this contract reasons about."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.code = blank_comments_and_literals(text)
        self.init_open, self.init_close = comm_init_span(self.code)
        found = TX_BUFSZ_ZERO.search(self.code)
        self.tx_span = found.span() if found else None
        found = CONFIG_DECL.search(self.code)
        self.decl_end = found.end() if found else None
        found = CTRL_CONFIG.search(self.code)
        self.ctrl_start = found.start() if found else None

    def link_fields(self) -> dict[str, str]:
        fields = {}
        for name in LINK_FIELDS:
            found = re.search(r"\bconfig\s*\.\s*%s\s*=\s*([^;]+);" % name, self.code)
            fields[name] = re.sub(r"\s+", " ", found.group(1)).strip() if found else ""
        return fields

    def failures(self) -> list[str]:
        """Every way the polling-TX configuration can be broken."""
        broken = []
        for found in TX_BUFSZ_ASSIGN.finditer(self.code):
            if found.group(1).strip().rstrip("uU") != "0":
                broken.append("non-zero tx_bufsz assignment")
                break
        if self.tx_span is None:
            return broken + ["config.tx_bufsz = 0 missing"]
        if not self.init_open < self.tx_span[0] < self.init_close:
            broken.append("tx_bufsz set outside smart_hand_comm_init")
        if self.decl_end is None:
            broken.append("struct serial_configure config declaration missing")
        elif self.tx_span[0] < self.decl_end:
            broken.append("tx_bufsz set before config is declared")
        if self.ctrl_start is None:
            broken.append("RT_DEVICE_CTRL_CONFIG call missing")
        elif self.tx_span[1] > self.ctrl_start:
            broken.append("tx_bufsz set after RT_DEVICE_CTRL_CONFIG")
        elif CONFIG_REINIT.search(self.code, self.tx_span[1], self.ctrl_start):
            broken.append("config re-initialised before RT_DEVICE_CTRL_CONFIG")
        return broken


def assert_polling_tx_contract(text: str) -> None:
    """Raise ``AssertionError`` unless polling TX is pinned before config."""
    broken = UartSource(text).failures()
    if broken:
        raise AssertionError("polling TX contract violated: %s" % "; ".join(broken))


# --- in-memory mutants; nothing here writes to disk ------------------------
def _tx_span(text: str) -> tuple[int, int]:
    span = UartSource(text).tx_span
    if span is None:
        raise AssertionError("no `config.tx_bufsz = 0;` to mutate")
    return span


def mutant_deleted(text: str) -> str:
    start, stop = _tx_span(text)
    return text[:start] + text[stop:]


def mutant_nonzero(text: str) -> str:
    start, stop = _tx_span(text)
    return text[:start] + "config.tx_bufsz = 256;" + text[stop:]


def mutant_after_control(text: str) -> str:
    start, stop = _tx_span(text)
    statement = text[start:stop]
    moved = text[:start] + text[stop:]
    source = UartSource(moved)
    if source.ctrl_start is None:
        raise AssertionError("no RT_DEVICE_CTRL_CONFIG call to move past")
    end = source.code.index(";", source.ctrl_start) + 1
    return moved[:end] + "\n    " + statement + moved[end:]


def mutant_config_reinit(text: str) -> str:
    _, stop = _tx_span(text)
    return text[:stop] + "\n    config = RT_SERIAL_CONFIG_DEFAULT;" + text[stop:]


class SourceFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = UART_SOURCE.read_text(encoding="utf-8-sig")
        cls.source = UartSource(cls.text)


class PollingTxConfigurationTests(SourceFixture):
    """The fix exists, and lands where it actually takes effect."""

    def tx_span(self) -> tuple[int, int]:
        self.assertIsNotNone(self.source.tx_span, MISSING_FIX)
        return self.source.tx_span

    def test_uart_source_present(self):
        self.assertTrue(UART_SOURCE.is_file(), UART_SOURCE)

    def test_tx_bufsz_zero_inside_comm_init(self):
        start, _ = self.tx_span()
        self.assertTrue(self.source.init_open < start < self.source.init_close)

    def test_tx_bufsz_zero_follows_config_declaration(self):
        self.assertIsNotNone(self.source.decl_end, "config declaration not found")
        self.assertGreater(self.tx_span()[0], self.source.decl_end)

    def test_tx_bufsz_zero_precedes_device_control_config(self):
        self.assertIsNotNone(self.source.ctrl_start, "CTRL_CONFIG call not found")
        self.assertLess(
            self.tx_span()[1],
            self.source.ctrl_start,
            "setting tx_bufsz after RT_DEVICE_CTRL_CONFIG leaves buffered TX active",
        )

    def test_config_not_reinitialised_before_control(self):
        self.assertIsNone(
            CONFIG_REINIT.search(
                self.source.code, self.tx_span()[1], self.source.ctrl_start
            ),
            "re-initialising config would silently restore the buffered TX path",
        )

    def test_no_nonzero_tx_bufsz_assignment(self):
        values = [m.group(1).strip() for m in TX_BUFSZ_ASSIGN.finditer(self.source.code)]
        self.assertTrue(values, MISSING_FIX)
        for value in values:
            self.assertEqual(value.rstrip("uU"), "0", values)

    def test_contract_holds_for_shipped_source(self):
        assert_polling_tx_contract(self.text)


class LinkParameterTests(SourceFixture):
    """Link facts the TX-path fix must leave alone."""

    def test_uart_device_is_uart2(self):
        found = UART_NAME.search(self.text)
        self.assertIsNotNone(found, "SMART_HAND_UART_NAME not defined")
        self.assertEqual(found.group(1), "uart2")

    def test_serial_line_is_115200_8n1(self):
        self.assertEqual(self.source.link_fields(), LINK_FIELDS)

    def test_rx_stays_interrupt_driven(self):
        self.assertIsNotNone(
            INT_RX.search(self.source.code),
            "RX must stay on RT_DEVICE_FLAG_INT_RX; the fix only pins TX",
        )


class MutationTests(SourceFixture):
    """Weakening the fix must turn these tests red."""

    def assert_rejected(self, mutated: str, expected: str) -> None:
        with self.assertRaises(AssertionError) as raised:
            assert_polling_tx_contract(mutated)
        self.assertIn(expected, str(raised.exception))

    def test_deleting_tx_bufsz_fails(self):
        self.assert_rejected(mutant_deleted(self.text), "config.tx_bufsz = 0 missing")

    def test_nonzero_tx_bufsz_fails(self):
        self.assert_rejected(mutant_nonzero(self.text), "non-zero tx_bufsz assignment")

    def test_moving_tx_bufsz_after_control_fails(self):
        self.assert_rejected(
            mutant_after_control(self.text), "tx_bufsz set after RT_DEVICE_CTRL_CONFIG"
        )

    def test_config_reinit_before_control_fails(self):
        self.assert_rejected(
            mutant_config_reinit(self.text),
            "config re-initialised before RT_DEVICE_CTRL_CONFIG",
        )


class OfflineGuaranteeTests(unittest.TestCase):
    def test_read_only_offline_contract(self):
        self.assertFalse(HARDWARE_ACCESSED)
        self.assertTrue(UART_SOURCE.is_file(), UART_SOURCE)
        self.assertEqual(UART_SOURCE.drive.upper(), PROJECT_ROOT.drive.upper())


if __name__ == "__main__":
    unittest.main()
