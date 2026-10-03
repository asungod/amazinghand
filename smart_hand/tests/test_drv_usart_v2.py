"""Host-run stub tests for drv_usart_v2.c's RX-callback null-FIFO guard.

The assertions live in tests/test_drv_usart_v2_c.c; this module drives the build
and run, and turns the C program's "[case] <name>: ok|FAILED (<n> checks)" lines
into unittest results, the same contract tests/test_voice_audio_titan.py uses.

What is under test
------------------
D:/Micu/RTTWorkspace/titan_uart_test/libraries/HAL_Drivers/drv_usart_v2.c, read
only. The file is a firmware driver for the Titan board: R_SCI_B_UART_Open()
enables receive and the RXI/ERI interrupts before it returns (ra/fsp/src/
r_sci_b_uart/r_sci_b_uart.c:381-388), while serial->serial_rx is only published
later by the RX-enable step of rt_device_open() (serial_v2.c:779-785). A byte
arriving inside that window used to hit RT_ASSERT(rx_fifo != RT_NULL) -- live,
because RT_USING_DEBUG is defined -- and stop the firmware at start-up. The
patch routes every byte through ra_uart_queue_rx_char(), which drops the byte
and bumps a read-only counter while the FIFO is unpublished.

Overridable knobs (so this suite is not pinned to one machine):

    DRV_USART_V2_C   absolute path of drv_usart_v2.c
                     (default: D:/Micu/RTTWorkspace/titan_uart_test/
                      libraries/HAL_Drivers/drv_usart_v2.c)
    DRV_USART_V2_H_DIR
                     directory holding drv_usart_v2.h, which the module
                     includes with angle brackets (default: the directory of
                     DRV_USART_V2_C). Only needed when the .c is pointed at a
                     copy that lives away from its own header.
    CC               C compiler to use (default: gcc)

Mutation verification
---------------------
test_mutant_* rebuild the module from a temporary copy with the null-pointer
guard deleted (the historical RT_ASSERT form restored) and require the run to
FAIL. A green suite whose assertions survive deleting the guard would be
proving nothing, so this is part of the suite rather than a one-off check.
The temporary copy is never written into the firmware tree.
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
STUBS_DIR = TESTS_DIR / "stubs_usart"

TEST_C = TESTS_DIR / "test_drv_usart_v2_c.c"
TEST_EXE = TESTS_DIR / "test_drv_usart_v2_c.exe"

DEFAULT_DRV_USART_V2_C = Path(
    "D:/Micu/RTTWorkspace/titan_uart_test/libraries/HAL_Drivers/drv_usart_v2.c"
)
DRV_USART_V2_C = Path(os.environ.get("DRV_USART_V2_C", DEFAULT_DRV_USART_V2_C))
# Where drv_usart_v2.h lives. The module includes it as <drv_usart_v2.h>, so the
# directory has to be on the search path; by default it sits next to the .c.
MODULE_DIR = Path(
    os.environ.get("DRV_USART_V2_H_DIR", str(DRV_USART_V2_C.parent))
)

CC = os.environ.get("CC", "gcc")

# Only UART1 and UART2 exist on this board (rtconfig.h:359,362); defining more
# would drag in UARTn_CONFIG entries the stub set deliberately does not have.
# SOC_SERIES_R7KA8P1 (rtconfig.h:344) keeps the same #if branches as firmware.
BASE_FLAGS = [
    "-std=gnu11", "-Wall", "-Wextra",
    "-DRT_USING_SERIAL_V2",
    "-DBSP_USING_UART1", "-DBSP_USING_UART2",
    "-DSOC_SERIES_R7KA8P1",
]

# -I order matters and is load bearing: the stubs must come first, because the
# module directory also contains drv_common.h -- the real one, which would pull
# the whole BSP in. <drv_usart_v2.h> is included with angle brackets by the
# module, so the module directory has to be on the search path as well.
INCLUDES = ["-I", str(STUBS_DIR), "-I", str(MODULE_DIR)]

# Every case main() runs, in order. A case that stops reporting is a coverage
# regression, not a formatting change.
EXPECTED_CASES = [
    "1-null-fifo-drops-rx-char",
    "2-published-fifo-queues-and-notifies",
    "3-non-rx-char-events-untouched",
    "4-per-uart-isolation",
    "5-null-serial-direct-helper",
    "6-open-window-byte-dropped",
    "7-open-window-after-publish-delivers",
    "8-byte-exactness-256",
    "9-drop-counter-accounted",
    "10-registration-and-config",
]

# The suite reported 294 checks when this was written. The floor catches a case
# that keeps its name but loses its assertions; it is not a target to track.
MIN_CHECKS = 250

CASE_LINE = re.compile(r"^\[case\] (\S+): (ok|FAILED) \((\d+) checks\)$")
PASSED_LINE = re.compile(
    r"^C drv_usart_v2 tests passed \((\d+) checks\)$", re.MULTILINE
)

# The historical code the patch replaced. Deleting the guard and putting the
# assertion back is exactly the regression the tests have to catch.
MUTANTS = [
    (
        "rx-fifo-guard-restored-to-assert",
        "    rx_fifo = (struct rt_serial_rx_fifo *) serial->serial_rx;\n"
        "\n"
        "    if (rx_fifo == RT_NULL)\n"
        "    {\n"
        "        g_uart_rx_dropped_before_fifo++;\n"
        "        return -RT_ERROR;\n"
        "    }\n",
        "    rx_fifo = (struct rt_serial_rx_fifo *) serial->serial_rx;\n"
        "\n"
        "    RT_ASSERT(rx_fifo != RT_NULL);\n",
        "RT_ASSERT(rx_fifo != RT_NULL)",
        "1-null-fifo-drops-rx-char",
    ),
    (
        "serial-guard-restored-to-assert",
        "    if (serial == RT_NULL)\n"
        "    {\n"
        "        g_uart_rx_dropped_before_fifo++;\n"
        "        return -RT_ERROR;\n"
        "    }\n",
        "    RT_ASSERT(serial != RT_NULL);\n",
        "RT_ASSERT(serial != RT_NULL)",
        "5-null-serial-direct-helper",
    ),
    (
        # The literal form of "delete the guard": no check at all. On the host
        # this does not segfault, because &(rx_fifo->rb) of a NULL rx_fifo is
        # address 0 (rb is the struct's first member) and the harness's stubs
        # refuse a NULL ringbuffer by counting it -- so the suite fails on
        # assertions instead of on an access violation. On firmware the same
        # mutant would fault inside the real rt_ringbuffer_putchar().
        "rx-fifo-guard-deleted",
        "    if (rx_fifo == RT_NULL)\n"
        "    {\n"
        "        g_uart_rx_dropped_before_fifo++;\n"
        "        return -RT_ERROR;\n"
        "    }\n"
        "\n",
        "",
        "空 FIFO 时不得调用 rt_ringbuffer_putchar()",
        "1-null-fifo-drops-rx-char",
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
        '-DDRV_USART_V2_C_PATH="%s"' % module_path.as_posix(),
        str(TEST_C), "-o", str(exe), "-lm",
    ]
    return subprocess.run(cmd, capture_output=True)


class DrvUsartV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DRV_USART_V2_C.exists():
            raise AssertionError(
                "module under test not found: %s\n"
                "set DRV_USART_V2_C to its absolute path" % DRV_USART_V2_C
            )
        inputs = [TEST_C, DRV_USART_V2_C] + sorted(STUBS_DIR.glob("*.h"))
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in inputs
        ):
            built = build(TEST_EXE, DRV_USART_V2_C)
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the drv_usart_v2 stub test:\n"
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

        The primary build folds the module into the test translation unit (the
        drop counter and ra_uart_queue_rx_char() are file-static, see the C
        file's header). This check keeps the other half honest: the module must
        also compile as its own unit, so a stub that only works by accident
        when combined with the test file would be caught here.
        """
        cmd = [CC, *BASE_FLAGS, *INCLUDES, "-fsyntax-only", str(DRV_USART_V2_C)]
        built = subprocess.run(cmd, capture_output=True)
        self.assertEqual(
            built.returncode, 0,
            "the module does not compile standalone:\n"
            + " ".join(cmd) + "\n" + _decode(built.stderr),
        )

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            self._failure_note("drv_usart_v2 stub assertions failed"),
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
        source = DRV_USART_V2_C.read_text(encoding="utf-8")
        occurrences = source.count(old)
        self.assertEqual(
            occurrences, 1,
            "cannot mutate %s: the guard block appears %d times in %s "
            "(the module changed; update the mutation text)"
            % (name, occurrences, DRV_USART_V2_C),
        )
        mutant_source = source.replace(old, new)
        self.assertNotIn(
            old, mutant_source, "mutation did not take effect for %s" % name,
        )

        with tempfile.TemporaryDirectory(prefix="drv_usart_v2_mutant_") as tmp:
            mutant = Path(tmp) / "drv_usart_v2_mutant.c"
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
            "the %s mutant PASSED the suite -- the tests do not catch a deleted "
            "null-FIFO guard\n--- stdout ---\n%s" % (name, stdout),
        )
        self.assertIn(
            marker, stdout + stderr,
            "%s: expected the assertion failure to name %s\n"
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

    def test_mutant_rx_fifo_guard_removed_fails(self):
        name, old, new, marker, failing_case = MUTANTS[0]
        self._build_and_run_mutant(name, old, new, marker, failing_case)

    def test_mutant_serial_guard_removed_fails(self):
        name, old, new, marker, failing_case = MUTANTS[1]
        self._build_and_run_mutant(name, old, new, marker, failing_case)

    def test_mutant_rx_fifo_guard_deleted_fails(self):
        name, old, new, marker, failing_case = MUTANTS[2]
        self._build_and_run_mutant(name, old, new, marker, failing_case)


if __name__ == "__main__":
    unittest.main()
