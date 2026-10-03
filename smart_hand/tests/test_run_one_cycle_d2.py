"""Run the run_one_cycle() D2 wiring assertions and wrap them for the Python suite.

The assertions live in tests/test_run_one_cycle_d2_c.c because the code under
test is C. This module exists so `python -m unittest smart_hand.tests.*` also
exercises it -- same contract as tests/test_drv_usart_v2.py and
tests/test_servo_group_recovery.py.

What is under test
------------------
src/servo_bus_readonly_rt.c's run_one_cycle(), read only. That function has
three ways out of a bad state; two of them cannot make progress at all and must
end the cycle with servo_group_readonly_abort_cycle() before returning, because
servo_group_readonly_begin_cycle() refuses to start while cycle_active is set:

    (A) servo_group_readonly_prepare() returns 0
    (B) the transmit never completes within SERVO_BUS_TX_TIMEOUT_MS (20 ms)
    (C) R_SCI_B_UART_Write() != FSP_SUCCESS

(C) is different on purpose: note_tx_failed() advances to the next servo and
only ends the cycle once the last one is done. The suite asserts all three
directions, so "fixing" (C) into an abort fails too.

The C test is folded into the test translation unit (run_one_cycle() and
g_group are file-static), so this module also keeps a standalone
`gcc -fsyntax-only` check on the module itself. The module is never modified;
the mutation tests rebuild from a temporary copy that is thrown away.

Overridable knobs (so this suite is not pinned to one machine):

    FIRMWARE_SRC_DIR  directory holding servo_bus_readonly_rt.c and friends
                      (default: D:/Micu/RTTWorkspace/titan_uart_test/src)
    SERVO_BUS_READONLY_RT_C
                      absolute path of servo_bus_readonly_rt.c, when it is
                      not under FIRMWARE_SRC_DIR
    CC                C compiler to use (default: gcc)
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"
STUBS_DIR = TESTS_DIR / "stubs_servo"

TEST_C = TESTS_DIR / "test_run_one_cycle_d2_c.c"
TEST_EXE = TESTS_DIR / "test_run_one_cycle_d2_c.exe"

FIRMWARE_SRC = Path(
    os.environ.get("FIRMWARE_SRC_DIR", r"D:/Micu/RTTWorkspace/titan_uart_test/src")
)
MODULE = Path(
    os.environ.get("SERVO_BUS_READONLY_RT_C",
                   str(FIRMWARE_SRC / "servo_bus_readonly_rt.c"))
)

CC = os.environ.get("CC", "gcc")

# Everything the module reaches at link time that is also host-compilable.
# servo_bus_readonly_rt.c itself is not here: the C test #includes it.
SOURCES = [
    "scs0009_packet.c",
    "scs0009_stream.c",
    "scs0009_transaction.c",
    "servo_group_readonly.c",
    "eight_servo_pose_bank.c",
    "eight_servo_safety_gate.c",
]

BASE_FLAGS = ["-std=gnu11", "-Wall", "-Wextra"]
INCLUDES = ["-I", str(STUBS_DIR), "-I", str(FIRMWARE_SRC)]

# Every case main() runs, in order. A case that stops reporting is a coverage
# regression, not a formatting change.
EXPECTED_CASES = [
    "0-harness-selfcheck",
    "1-prepare-zero-aborts-and-recovers",
    "2-tx-timeout-aborts-and-recovers",
    "3-write-failure-does-not-abort",
]

# The suite reported 128 checks when this was written. The floor catches a case
# that keeps its name but loses its assertions; it is not a target to track.
MIN_CHECKS = 110

CASE_LINE = re.compile(r"^\[case\] (\S+): (ok|FAILED) \((\d+) checks\)$")
PASSED_LINE = re.compile(
    r"^C run_one_cycle D2 wiring tests passed \((\d+) checks\)$", re.MULTILINE
)

# Each entry: mutation name, exact source text to replace, replacement,
# a substring that must appear in the failing assertion, and the case that must
# report FAILED. The needles are indentation-sensitive on purpose: the two abort
# calls differ only by indentation (12 vs 20 spaces), which is what makes each
# needle unique in the file.
MUTANTS = [
    (
        "prepare-path-returns-without-abort",
        "            servo_group_readonly_abort_cycle(&g_group);\n"
        "            set_leds(1u, 0u, 0u);\n"
        "            return;",
        "            set_leds(1u, 0u, 0u);\n"
        "            return;",
        "prepare() 返回 0 后周期必须自己结束",
        "1-prepare-zero-aborts-and-recovers",
    ),
    (
        "tx-timeout-path-returns-without-abort",
        "                    servo_group_readonly_abort_cycle(&g_group);\n"
        "                    set_leds(1u, 0u, 0u);\n"
        "                    drain_servo_uart();\n"
        "                    return;",
        "                    set_leds(1u, 0u, 0u);\n"
        "                    drain_servo_uart();\n"
        "                    return;",
        "TX 超时后周期必须自己结束",
        "2-tx-timeout-aborts-and-recovers",
    ),
    (
        # The two no-progress paths and the per-servo failure path are not
        # interchangeable; swapping one in for another has to fail.
        "prepare-path-uses-note-tx-failed-instead",
        "            servo_group_readonly_abort_cycle(&g_group);\n"
        "            set_leds(1u, 0u, 0u);\n"
        "            return;",
        "            servo_group_readonly_note_tx_failed(&g_group);\n"
        "            set_leds(1u, 0u, 0u);\n"
        "            return;",
        "prepare() 返回 0 后周期必须自己结束",
        "1-prepare-zero-aborts-and-recovers",
    ),
    (
        # The reverse direction: aborting on a per-servo write failure is the
        # other half of "do not confuse the three paths".
        "tx-write-failure-path-aborts-instead",
        "            servo_group_readonly_note_tx_failed(&g_group);\n"
        "            continue;",
        "            servo_group_readonly_abort_cycle(&g_group);\n"
        "            continue;",
        "发送失败路径不得 abort 周期",
        "3-write-failure-does-not-abort",
    ),
]


def _decode(raw: bytes) -> str:
    """The C program prints UTF-8; the console codepage here is cp936.

    MinGW's stdout is in text mode, so lines arrive CRLF-terminated; the case
    regexes are anchored with $, so normalise before matching.
    """
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _run(cmd: list) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True)


def build(exe: Path, module_path: Path) -> subprocess.CompletedProcess:
    cmd = [
        CC, *BASE_FLAGS, *INCLUDES,
        '-DSERVO_BUS_READONLY_RT_C_PATH="%s"' % module_path.as_posix(),
        str(TEST_C),
        *[str(FIRMWARE_SRC / name) for name in SOURCES],
        "-o", str(exe), "-lm",
    ]
    return subprocess.run(cmd, capture_output=True)


class RunOneCycleD2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in SOURCES if not (FIRMWARE_SRC / name).is_file()]
        if missing or not MODULE.is_file():
            raise unittest.SkipTest(
                f"firmware sources not found under {FIRMWARE_SRC}: {missing}"
                f" (module: {MODULE}). Set FIRMWARE_SRC_DIR to "
                "<titan_uart_test>/src."
            )

        inputs = [TEST_C, MODULE] + sorted(STUBS_DIR.glob("*.h")) + [
            FIRMWARE_SRC / name for name in SOURCES
        ]
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in inputs
        ):
            built = build(TEST_EXE, MODULE)
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the run_one_cycle D2 stub test:\n"
                    + _decode(built.stdout) + _decode(built.stderr)
                )
        cls.result = _run([str(TEST_EXE)])
        cls.stdout = _decode(cls.result.stdout)
        cls.stderr = _decode(cls.result.stderr)
        cls.cases = {}
        for line in cls.stdout.splitlines():
            match = CASE_LINE.match(line)
            if match:
                cls.cases[match.group(1)] = (match.group(2), int(match.group(3)))

    def _failure_note(self, message):
        return "%s\n--- stdout ---\n%s\n--- stderr ---\n%s" % (
            message, self.stdout, self.stderr,
        )

    def test_module_compiles_standalone(self):
        """The module must still compile on its own against the stubs.

        The primary build folds the module into the test translation unit
        (run_one_cycle() and g_group are file-static, see the C file's header).
        This check keeps the other half honest: the module must also compile as
        its own unit, so a stub that only works by accident when combined with
        the test file would be caught here.
        """
        cmd = [CC, *BASE_FLAGS, *INCLUDES, "-fsyntax-only", str(MODULE)]
        built = subprocess.run(cmd, capture_output=True)
        self.assertEqual(
            built.returncode, 0,
            "the module does not compile standalone:\n"
            + " ".join(cmd) + "\n" + _decode(built.stderr),
        )

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            self._failure_note("run_one_cycle D2 wiring assertions failed"),
        )
        self.assertNotIn("FAIL ", self.stdout)
        self.assertIsNotNone(
            PASSED_LINE.search(self.stdout),
            self._failure_note("the pass marker is missing"),
        )

    def test_every_case_reports_ok(self):
        missing = [name for name in EXPECTED_CASES if name not in self.cases]
        failed = [name for name, (status, _) in self.cases.items()
                  if status != "ok"]
        self.assertEqual(missing, [], self._failure_note("cases did not run"))
        self.assertEqual(
            failed, [], self._failure_note("cases reported FAILED"),
        )

    def test_check_count_did_not_collapse(self):
        marker = PASSED_LINE.search(self.stdout)
        if marker is None:
            self.fail(self._failure_note("no check count to read"))
        total = int(marker.group(1))
        self.assertGreaterEqual(
            total, MIN_CHECKS,
            self._failure_note(
                "only %d checks ran; a case may have lost its assertions" % total
            ),
        )

    def _build_and_run_mutant(self, name, old, new, marker, failing_case):
        source = MODULE.read_text(encoding="utf-8")
        occurrences = source.count(old)
        self.assertEqual(
            occurrences, 1,
            "cannot mutate %s: the block appears %d times in %s "
            "(the module changed; update the mutation text)"
            % (name, occurrences, MODULE),
        )
        mutant_source = source.replace(old, new)
        self.assertNotIn(
            old, mutant_source, "mutation did not take effect for %s" % name,
        )

        with tempfile.TemporaryDirectory(prefix="run_one_cycle_d2_mutant_") as tmp:
            mutant = Path(tmp) / "servo_bus_readonly_rt_mutant.c"
            mutant.write_text(mutant_source, encoding="utf-8")
            exe = Path(tmp) / "mutant.exe"
            built = build(exe, mutant)
            self.assertEqual(
                built.returncode, 0,
                "the %s mutant did not even compile:\n%s"
                % (name, _decode(built.stderr)),
            )
            ran = _run([str(exe)])

        stdout = _decode(ran.stdout)
        stderr = _decode(ran.stderr)
        self.assertNotEqual(
            ran.returncode, 0,
            "the %s mutant PASSED the suite -- the tests do not catch this "
            "lost abort_cycle() call\n--- stdout ---\n%s" % (name, stdout),
        )
        self.assertIn(
            marker, stdout + stderr,
            "%s: expected the assertion failure to mention %s\n"
            "--- stdout ---\n%s\n--- stderr ---\n%s"
            % (name, marker, stdout, stderr),
        )
        self.assertIn(
            "[case] %s: FAILED" % failing_case, stdout,
            "%s: expected case %s to report FAILED\n--- stdout ---\n%s"
            % (name, failing_case, stdout),
        )
        self.assertNotIn(
            "tests passed", stdout,
            "%s: the pass marker must not survive the mutation" % name,
        )

    def test_mutant_prepare_path_returns_without_abort(self):
        name, old, new, marker, failing_case = MUTANTS[0]
        self._build_and_run_mutant(name, old, new, marker, failing_case)

    def test_mutant_tx_timeout_path_returns_without_abort(self):
        name, old, new, marker, failing_case = MUTANTS[1]
        self._build_and_run_mutant(name, old, new, marker, failing_case)

    def test_mutant_prepare_path_uses_note_tx_failed(self):
        name, old, new, marker, failing_case = MUTANTS[2]
        self._build_and_run_mutant(name, old, new, marker, failing_case)

    def test_mutant_tx_write_failure_path_aborts(self):
        name, old, new, marker, failing_case = MUTANTS[3]
        self._build_and_run_mutant(name, old, new, marker, failing_case)


if __name__ == "__main__":
    unittest.main()
