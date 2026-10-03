"""Run the D2 cycle-recovery assertions and wrap them for the Python suite.

The assertions live in tests/test_servo_group_recovery_c.c because the code
under test is C. This module exists so `python -m unittest smart_hand.tests.*`
also exercises it.

What it covers: servo_group_readonly_abort_cycle() ends a cycle that cannot
make progress, so the next begin_cycle() succeeds. Before the D2 fix a failed
prepare or a transmit timeout returned without clearing cycle_active, and
begin_cycle() refuses to start while it is set -- one such failure silenced the
servo bus until reboot.

The firmware sources are outside this repository, so the path is overridable:

    FIRMWARE_SRC_DIR=<path to titan_uart_test/src>
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = PROJECT_ROOT / "tests"

FIRMWARE_SRC = Path(
    os.environ.get("FIRMWARE_SRC_DIR", r"D:/Micu/RTTWorkspace/titan_uart_test/src")
)

TEST_C = TESTS_DIR / "test_servo_group_recovery_c.c"
TEST_EXE = TESTS_DIR / "test_servo_group_recovery_c.exe"

# servo_group_readonly.c reaches the SCS0009 helpers through its header.
SOURCES = [
    "servo_group_readonly.c",
    "scs0009_transaction.c",
    "scs0009_packet.c",
    "scs0009_stream.c",
]


class ServoGroupRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        missing = [name for name in SOURCES if not (FIRMWARE_SRC / name).is_file()]
        if missing:
            raise unittest.SkipTest(
                f"firmware sources not found under {FIRMWARE_SRC}: {missing}. "
                "Set FIRMWARE_SRC_DIR to <titan_uart_test>/src."
            )

        inputs = [TEST_C] + [FIRMWARE_SRC / name for name in SOURCES]
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in inputs
        ):
            cmd = [
                "gcc", "-std=gnu11", "-Wall", "-Wextra",
                "-I", str(FIRMWARE_SRC),
                str(TEST_C),
                *[str(FIRMWARE_SRC / name) for name in SOURCES],
                "-o", str(TEST_EXE), "-lm",
            ]
            built = subprocess.run(cmd, capture_output=True, text=True)
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the D2 recovery test:\n"
                    + " ".join(cmd) + "\n" + built.stderr
                )
        cls.result = subprocess.run([str(TEST_EXE)], capture_output=True, text=True)

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            "D2 recovery assertions failed:\n"
            + self.result.stdout + self.result.stderr,
        )
        self.assertIn("C servo group recovery tests passed", self.result.stdout)

    def test_abort_cycle_exists_and_is_exported(self):
        """The fix has to be reachable from the driver, not a private helper."""
        header = (FIRMWARE_SRC / "servo_group_readonly.h").read_text(
            encoding="utf-8", errors="replace"
        )
        self.assertIn("void servo_group_readonly_abort_cycle(", header)
        self.assertIn("aborted_cycles", header)


if __name__ == "__main__":
    unittest.main()
