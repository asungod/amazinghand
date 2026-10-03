"""Offline regression lock for the AITRUST send path in ``smart_hand_uart.c``.

Why this file exists
--------------------
The AITRUST frame's *policy* is host-testable and lives in
``smart_hand_status_telemetry.c`` (see ``test_smart_hand_status_telemetry_c.c``).
The *glue* is not: ``smart_hand_uart.c`` needs RT-Thread and a serial device, so
no host test compiles it, and the project's own convention is not to stub the
driver for tests.

That left three behaviour-determining facts with zero protection, all of them
load-bearing for requirement 2 ("a failed write may only be counted, and must
not block the existing ACK/STATUS/mechanical-hand link"):

1. ``send_aitrust()`` is gated by ``smart_hand_aitrust_due()``.
2. ``smart_hand_aitrust_note_attempt()`` is called **before** the write, so the
   500 ms floor applies to *attempts* -- a failing write cannot fall through to
   a retry on the next 50 ms tick of the same polled-TX UART that carries ACK.
3. ``smart_hand_aitrust_note_sent()`` only runs on the success path, so the
   sequence numbers frames that actually went out.

Each of these was independently demonstrated to be unprotected: moving the
bookkeeping, or deleting the gate, leaves every other suite green.

This module pins them from the source text, the same way
``test_titan_uart_polling_tx_contract.py`` pins ``tx_bufsz``. Read-only and
offline: no serial port, no board, and mutants are built in memory only.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
UART_SOURCE = PROJECT_ROOT / "titan_rtthread" / "smart_hand_uart.c"

HARDWARE_ACCESSED = False

SEND_AITRUST_DEF = re.compile(r"\bstatic\s+void\s+send_aitrust\s*\(\s*void\s*\)\s*\{")
RX_THREAD_DEF = re.compile(r"\bstatic\s+void\s+rx_thread_entry\s*\([^)]*\)\s*\{")
COMM_INIT_DEF = re.compile(r"(?<!\w)smart_hand_comm_init\s*\(\s*void\s*\)\s*\{")
SEND_AITRUST_CALL = re.compile(r"\bsend_aitrust\s*\(\s*\)\s*;")
DUE_CALL = re.compile(r"\bsmart_hand_aitrust_due\s*\(")
ATTEMPT_CALL = re.compile(r"\bsmart_hand_aitrust_note_attempt\s*\(")
SENT_CALL = re.compile(r"\bsmart_hand_aitrust_note_sent\s*\(")
FAILED_CALL = re.compile(r"\bsmart_hand_aitrust_note_failed\s*\(")
LINK_INIT_CALL = re.compile(r"\bsmart_hand_aitrust_link_init\s*\(")
SEND_MESSAGE_AITRUST = re.compile(r"\bsend_message\s*\(\s*\"AITRUST\"")
RT_EOK = re.compile(r"\bRT_EOK\b")
AITRUST_ARG_COUNT = re.compile(r"\bSH_AITRUST_ARG_COUNT\b")

# Anything on the motion / safety / training path. send_aitrust must touch none
# of it: the classification is advisory and may not authorize anything.
FORBIDDEN_IN_SENDER = re.compile(
    r"\b(servo_[a-z_]*|eight_servo_[a-z_]*|grip_policy_[a-z_]*|"
    r"smart_hand_vision_state_[a-z_]*|smart_hand_sequence_guard_[a-z_]*|"
    r"smart_hand_status_pack)\s*\("
)

MISSING_SENDER = "send_aitrust() definition not found in smart_hand_uart.c"

# `input.<field> = <expr>;` inside send_aitrust(). The right-hand side is what
# actually decides the frozen wire fields -- the packer only passes it through.
FIELD_ASSIGN = re.compile(r"\binput\s*\.\s*(\w+)\s*=\s*([^;]+);")

# field -> the source it MUST be read from. A constant here silently rewrites a
# frozen field; every one of these was demonstrated to survive before this map
# existed (the packer tests cannot see them: they never compile this file).
FIELD_SOURCES = {
    "model_ready": r"\bg_titan_trust_result\s*\.\s*ready\b",
    "classification": r"\(\s*uint8_t\s*\)\s*g_titan_trust_result\s*\.\s*classification\b",
    "have_vision": r"\bg_vision_state\s*\.\s*have_vision\b",
    "have_last_vision": r"\bg_vision_seen\b",
    "last_vision_ms": r"\bg_vision_last_seen_ms\b",
    "now_ms": r"\bcurrent_ms\b",
}

# A right-hand side that carries no identifier at all is a hard-coded field.
HAS_IDENTIFIER = re.compile(r"[A-Za-z_]")

# The input struct must start zeroed, or a field nobody assigns ships .bss.
INPUT_ZEROED = re.compile(r"\brt_memset\s*\(\s*&input\s*,\s*0\s*,\s*sizeof\s*\(\s*input\s*\)\s*\)")


def blank_comments_and_literals(text: str) -> str:
    """Return a same-length copy with comment and string bodies blanked.

    Offsets stay valid, so a span computed on the blanked copy indexes the
    original. A statement that exists only inside a comment or a log string can
    then no longer satisfy the contract.
    """
    out = list(text)
    i, n, state = 0, len(text), "code"
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state == "code":
            if ch == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                state, i = "block", i + 2
                continue
            if ch == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                state, i = "line", i + 2
                continue
            if ch == '"':
                out[i] = " "
                state, i = "str", i + 1
                continue
            if ch == "'":
                out[i] = " "
                state, i = "chr", i + 1
                continue
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                state, i = "code", i + 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        # str / chr
        if ch == "\\":
            out[i] = " "
            if i + 1 < n:
                out[i + 1] = " "
            i += 2
            continue
        if (state == "str" and ch == '"') or (state == "chr" and ch == "'"):
            out[i] = " "
            state, i = "code", i + 1
            continue
        if ch != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


def _brace_span(code: str, open_index: int) -> tuple[int, int]:
    """Span of a brace-delimited block whose opening ``{`` is at ``open_index``."""
    depth, i, n = 0, open_index, len(code)
    while i < n:
        if code[i] == "{":
            depth += 1
        elif code[i] == "}":
            depth -= 1
            if depth == 0:
                return open_index, i + 1
        i += 1
    raise AssertionError("unbalanced braces from offset %d" % open_index)


class AitrustGlueSource:
    """Spans and invariants of the AITRUST glue, computed from the source text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.code = blank_comments_and_literals(text)

        found = SEND_AITRUST_DEF.search(self.code)
        self.sender_span = _brace_span(self.code, found.end() - 1) if found else None

        found = RX_THREAD_DEF.search(self.code)
        self.rx_span = _brace_span(self.code, found.end() - 1) if found else None

        found = COMM_INIT_DEF.search(self.code)
        self.init_span = _brace_span(self.code, found.end() - 1) if found else None

        self.send_calls = [m.start() for m in SEND_AITRUST_CALL.finditer(self.code)]
        self.due_calls = [m.start() for m in DUE_CALL.finditer(self.code)]
        self.attempt_calls = [m.start() for m in ATTEMPT_CALL.finditer(self.code)]
        self.sent_calls = [m.start() for m in SENT_CALL.finditer(self.code)]
        self.failed_calls = [m.start() for m in FAILED_CALL.finditer(self.code)]
        self.link_init_calls = [m.start() for m in LINK_INIT_CALL.finditer(self.code)]
        # The frame type is a string LITERAL, and blanking replaces literal
        # bodies with spaces -- so this one has to be found in the raw text.
        # Offsets are identical because blanking is length-preserving, and the
        # span filter below keeps a mention inside a comment from counting.
        self.write_calls = [m.start() for m in SEND_MESSAGE_AITRUST.finditer(self.text)]

    def _in_sender(self, offsets: list[int]) -> list[int]:
        if self.sender_span is None:
            return []
        lo, hi = self.sender_span
        return [o for o in offsets if lo <= o < hi]

    def write_offset(self) -> int | None:
        """Offset of the single AITRUST write inside send_aitrust(), if any."""
        sends = self._in_sender(self.write_calls)
        return sends[0] if len(sends) == 1 else None

    def failures(self) -> list[str]:
        broken: list[str] = []
        if self.sender_span is None:
            return [MISSING_SENDER]

        write = self.write_offset()
        if write is None:
            broken.append(
                'expected exactly one send_message("AITRUST") in send_aitrust()'
            )
            return broken

        dues = self._in_sender(self.due_calls)
        if not dues:
            broken.append("smart_hand_aitrust_due missing from send_aitrust()")
        elif dues[0] > write:
            broken.append("due() gate must precede the write")

        attempts = self._in_sender(self.attempt_calls)
        if not attempts:
            broken.append("smart_hand_aitrust_note_attempt missing from send_aitrust()")
        elif attempts[0] > write:
            broken.append("attempt must be booked before the write")

        sents = self._in_sender(self.sent_calls)
        if not sents:
            broken.append("smart_hand_aitrust_note_sent missing from send_aitrust()")
        elif sents[0] < write:
            broken.append("note_sent must follow the write")
        elif not RT_EOK.search(self.code, write, sents[0]):
            broken.append("note_sent must sit on the RT_EOK success path")

        faileds = self._in_sender(self.failed_calls)
        if not faileds:
            broken.append("smart_hand_aitrust_note_failed missing from send_aitrust()")
        elif not any(o > write for o in faileds):
            broken.append("note_failed must cover the write-failure path")

        if not AITRUST_ARG_COUNT.search(self.code, write, write + 120):
            broken.append("AITRUST must be sent with SH_AITRUST_ARG_COUNT args")

        # One call site, on the rx thread -- never from init or an ISR path.
        if len(self.send_calls) != 1:
            broken.append("send_aitrust() must have exactly one call site")
        elif self.rx_span is None or not (
            self.rx_span[0] <= self.send_calls[0] < self.rx_span[1]
        ):
            broken.append("send_aitrust() must be called from rx_thread_entry")

        # Bookkeeping must be initialised at start-up, or the first frame is
        # gated by whatever .bss happened to hold.
        if self.init_span is None or not self._in_init_init():
            broken.append("smart_hand_aitrust_link_init missing from smart_hand_comm_init")

        lo, hi = self.sender_span
        forbidden = FORBIDDEN_IN_SENDER.search(self.code, lo, hi)
        if forbidden:
            broken.append(
                "send_aitrust touches the motion/safety path: %s" % forbidden.group(0)
            )

        # The five-to-six lines that fill the input struct are the only place the
        # frozen wire fields get their values. Pin where each one comes from.
        if not INPUT_ZEROED.search(self.code, lo, hi):
            broken.append("the input struct must be zeroed before it is filled")
        assigned = self.field_assignments()
        for field, pattern in FIELD_SOURCES.items():
            rhs = assigned.get(field)
            if rhs is None:
                broken.append("input.%s is never assigned in send_aitrust()" % field)
                continue
            if not re.search(pattern, rhs):
                broken.append(
                    "input.%s must be read from its source, not from %r" % (field, rhs.strip())
                )
        return broken

    def field_assignments(self) -> dict[str, str]:
        """field -> right-hand side (blanked code) for `input.X = ...;` in the sender."""
        if self.sender_span is None:
            return {}
        lo, hi = self.sender_span
        return {
            m.group(1): m.group(2) for m in FIELD_ASSIGN.finditer(self.code, lo, hi)
        }

    def _in_init_init(self) -> bool:
        lo, hi = self.init_span
        return any(lo <= o < hi for o in self.link_init_calls)


def assert_aitrust_glue_contract(text: str) -> None:
    """Raise ``AssertionError`` unless the AITRUST send path keeps its order."""
    broken = AitrustGlueSource(text).failures()
    if broken:
        raise AssertionError("AITRUST glue contract violated: %s" % "; ".join(broken))


# --- in-memory mutants; nothing here writes to disk ------------------------
def _sender_span(text: str) -> tuple[int, int]:
    span = AitrustGlueSource(text).sender_span
    if span is None:
        raise AssertionError(MISSING_SENDER)
    return span


def _if_block_span(text: str, at: int) -> tuple[int, int]:
    """Line-aligned span of the ``if (...) { ... }`` statement containing ``at``."""
    source = AitrustGlueSource(text)
    lo, _ = _sender_span(text)
    starts = list(re.finditer(r"\bif\s*\(", source.code[lo:at]))
    if not starts:
        raise AssertionError("no `if (` before offset %d in send_aitrust()" % at)
    if_start = lo + starts[-1].start()
    open_brace = source.code.index("{", at)
    _, close = _brace_span(source.code, open_brace)
    return text.rindex("\n", lo, if_start) + 1, close + 1


def _insert_at_sender_end(text: str, block: str) -> str:
    _, hi = _sender_span(text)
    insert = text.rindex("\n", 0, hi - 1) + 1
    return text[:insert] + block + text[insert:]


def mutant_attempt_after_write(text: str) -> str:
    """Book the attempt only after the write -- the natural-looking mistake."""
    source = AitrustGlueSource(text)
    lo, _ = _sender_span(text)
    start = source.attempt_calls[0]
    line_start = text.rindex("\n", lo, start) + 1
    line_end = text.index("\n", text.index(";", start)) + 1
    statement = text[line_start:line_end]
    body = text[:line_start] + text[line_end:]
    return _insert_at_sender_end(body, statement)


def mutant_no_due_gate(text: str) -> str:
    """Delete the 500 ms gate: every tick would try to send."""
    source = AitrustGlueSource(text)
    start, stop = _if_block_span(text, source.due_calls[0])
    return text[:start] + text[stop:]


def mutant_gate_after_write(text: str) -> str:
    """Keep the gate but evaluate it after the write, so it protects nothing."""
    source = AitrustGlueSource(text)
    start, stop = _if_block_span(text, source.due_calls[0])
    block = text[start:stop]
    return _insert_at_sender_end(text[:start] + text[stop:], block)


def mutant_unguarded_sent(text: str) -> str:
    """Drop the success comparison, so a failed write is counted as sent."""
    source = AitrustGlueSource(text)
    write = source.write_offset()
    if write is None:
        raise AssertionError(MISSING_SENDER)
    found = RT_EOK.search(source.code, write, write + 200)
    if found is None:
        raise AssertionError("no RT_EOK guard after the AITRUST write")
    if text[found.start() - 3 : found.start()] != "== ":
        raise AssertionError("unexpected guard shape around RT_EOK")
    return text[: found.start() - 3] + text[found.end() :]


def mutant_second_call_site(text: str) -> str:
    """Call the sender from start-up too, not just from the rx thread."""
    source = AitrustGlueSource(text)
    lo, hi = source.init_span
    anchor = text.index("smart_hand_aitrust_link_init", lo)
    end = text.index("\n", anchor) + 1
    return text[:end] + "    send_aitrust();\n" + text[end:]


def mutant_touches_the_gate(text: str) -> str:
    """Let the sender read the safety gate -- the boundary this pins."""
    lo, hi = _sender_span(text)
    anchor = AitrustGlueSource(text).write_offset()
    if anchor is None:
        raise AssertionError(MISSING_SENDER)
    line_start = text.rindex("\n", lo, anchor) + 1
    return (
        text[:line_start]
        + "    (void)servo_bus_safety_gate_armed();\n"
        + text[line_start:]
    )


def mutant_field_constant(text: str, field: str, value: str) -> str:
    """Hard-code one input field -- the mistake the mapping contract forbids.

    Each of these was demonstrated to survive before the mapping check existed:
    they live in smart_hand_uart.c, which no host test compiles, so the packer
    tests cannot see them and the ordering checks do not look at the values.
    """
    source = AitrustGlueSource(text)
    lo, hi = _sender_span(text)
    for found in FIELD_ASSIGN.finditer(source.code, lo, hi):
        if found.group(1) == field:
            return text[: found.start(2)] + value + text[found.end(2) :]
    raise AssertionError("input.%s not assigned in send_aitrust()" % field)


def mutant_no_input_zeroing(text: str) -> str:
    """Stop zeroing the input struct before filling it."""
    source = AitrustGlueSource(text)
    lo, hi = _sender_span(text)
    found = INPUT_ZEROED.search(source.code, lo, hi)
    if found is None:
        raise AssertionError("input is not zeroed in send_aitrust()")
    line_start = text.rindex("\n", lo, found.start()) + 1
    line_end = text.index("\n", text.index(";", found.start())) + 1
    return text[:line_start] + text[line_end:]


class SourceFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = UART_SOURCE.read_text(encoding="utf-8-sig")
        cls.source = AitrustGlueSource(cls.text)

    def aitrust_write(self) -> int:
        offset = self.source.write_offset()
        self.assertIsNotNone(offset, 'no send_message("AITRUST") inside send_aitrust()')
        return offset


class SendOrderingTests(SourceFixture):
    """The three facts that decide whether a failing write can hurt the link."""

    def test_sender_exists(self):
        self.assertTrue(UART_SOURCE.is_file(), UART_SOURCE)
        self.assertIsNotNone(self.source.sender_span, MISSING_SENDER)

    def test_gate_precedes_the_write(self):
        dues = self.source._in_sender(self.source.due_calls)
        self.assertTrue(dues, "smart_hand_aitrust_due missing")
        self.assertLess(dues[0], self.aitrust_write())

    def test_attempt_is_booked_before_the_write(self):
        attempts = self.source._in_sender(self.source.attempt_calls)
        self.assertTrue(attempts, "smart_hand_aitrust_note_attempt missing")
        self.assertLess(
            attempts[0],
            self.aitrust_write(),
            "book the attempt before the write, or a failing write retries every tick",
        )

    def test_sent_only_on_the_success_path(self):
        sents = self.source._in_sender(self.source.sent_calls)
        self.assertTrue(sents, "smart_hand_aitrust_note_sent missing")
        write = self.aitrust_write()
        self.assertGreater(sents[0], write)
        self.assertRegex(
            self.source.code[write : sents[0]],
            r"RT_EOK",
            "note_sent must be guarded by the RT_EOK comparison",
        )

    def test_failure_is_counted_on_the_write_path(self):
        faileds = self.source._in_sender(self.source.failed_calls)
        self.assertTrue(faileds, "smart_hand_aitrust_note_failed missing")
        self.assertTrue(
            any(o > self.aitrust_write() for o in faileds),
            "the write-failure path must reach note_failed",
        )

    def test_exactly_one_call_site_on_the_rx_thread(self):
        self.assertEqual(len(self.source.send_calls), 1, self.source.send_calls)
        lo, hi = self.source.rx_span
        self.assertTrue(lo <= self.source.send_calls[0] < hi)

    def test_link_state_is_initialised_at_startup(self):
        self.assertTrue(self.source._in_init_init())

    def test_sender_stays_off_the_motion_path(self):
        lo, hi = self.source.sender_span
        found = FORBIDDEN_IN_SENDER.search(self.source.code, lo, hi)
        self.assertIsNone(found, found.group(0) if found else "")

    def test_contract_holds_for_shipped_source(self):
        assert_aitrust_glue_contract(self.text)


class FieldMappingTests(SourceFixture):
    """Where each frozen wire field gets its value.

    The ordering checks above say *when* things happen; these say *what* goes on
    the wire. Both live in the same uncompiled file, so both need pinning here.
    """

    def test_input_is_zeroed_before_it_is_filled(self):
        lo, hi = self.source.sender_span
        self.assertRegex(self.source.code[lo:hi], INPUT_ZEROED.pattern)

    def test_every_field_is_assigned_from_its_declared_source(self):
        assigned = self.source.field_assignments()
        self.assertEqual(sorted(assigned), sorted(FIELD_SOURCES), assigned)
        for field, pattern in FIELD_SOURCES.items():
            self.assertRegex(assigned[field], pattern, field)

    def test_no_field_is_hard_coded(self):
        """A constant right-hand side is a frozen field silently rewritten."""
        for field, rhs in self.source.field_assignments().items():
            with self.subTest(field=field):
                self.assertRegex(rhs, HAS_IDENTIFIER.pattern, rhs)

    def test_freshness_comes_from_the_vision_state(self):
        """have_vision drives `ready`; a constant there advertises stale vision."""
        self.assertIn("g_vision_state", self.source.field_assignments()["have_vision"])

    def test_age_uses_its_own_timestamp_not_the_vision_state(self):
        """g_vision_state.last_vision_ms is CLEARED on expiry, so the age would
        restart from zero. The glue keeps its own g_vision_seen/_last_seen_ms."""
        assigned = self.source.field_assignments()
        self.assertIn("g_vision_seen", assigned["have_last_vision"])
        self.assertIn("g_vision_last_seen_ms", assigned["last_vision_ms"])


class MutationTests(SourceFixture):
    """Weakening the send order must turn these tests red."""

    def assert_rejected(self, mutated: str, expected: str) -> None:
        with self.assertRaises(AssertionError) as raised:
            assert_aitrust_glue_contract(mutated)
        self.assertIn(expected, str(raised.exception))

    def test_attempt_moved_after_the_write_fails(self):
        self.assert_rejected(
            mutant_attempt_after_write(self.text), "attempt must be booked before"
        )

    def test_deleting_the_gate_fails(self):
        self.assert_rejected(
            mutant_no_due_gate(self.text), "smart_hand_aitrust_due missing"
        )

    def test_gate_evaluated_after_the_write_fails(self):
        self.assert_rejected(
            mutant_gate_after_write(self.text), "due() gate must precede"
        )

    def test_counting_a_failed_write_as_sent_fails(self):
        self.assert_rejected(
            mutant_unguarded_sent(self.text), "note_sent must sit on the RT_EOK"
        )

    def test_a_second_call_site_fails(self):
        self.assert_rejected(
            mutant_second_call_site(self.text),
            "send_aitrust() must have exactly one call site",
        )

    def test_touching_the_safety_gate_fails(self):
        self.assert_rejected(
            mutant_touches_the_gate(self.text), "motion/safety path"
        )

    def test_hard_coded_fields_fail(self):
        """Each of these five survived before the mapping check existed."""
        for field, value in (
            ("model_ready", "1u"),
            ("classification", "0u"),
            ("have_vision", "1u"),
            ("have_last_vision", "0u"),
            ("last_vision_ms", "0u"),
        ):
            with self.subTest(field=field):
                self.assert_rejected(
                    mutant_field_constant(self.text, field, value),
                    "input.%s must be read from its source" % field,
                )

    def test_dropping_the_input_zeroing_fails(self):
        self.assert_rejected(
            mutant_no_input_zeroing(self.text),
            "the input struct must be zeroed",
        )


class OfflineGuaranteeTests(unittest.TestCase):
    def test_read_only_offline_contract(self):
        self.assertFalse(HARDWARE_ACCESSED)
        self.assertTrue(UART_SOURCE.is_file(), UART_SOURCE)
        self.assertEqual(UART_SOURCE.drive.upper(), PROJECT_ROOT.drive.upper())


if __name__ == "__main__":
    unittest.main()
