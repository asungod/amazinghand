"""Run the PDM/RT-Thread adaptation-layer assertions and wrap them for Python.

The assertions live in tests/test_voice_audio_titan_c.c: the code under test is
the FSP PDM driver binding, whose interesting failures are all about what the
interrupt does with the driver's buffer, and those are cheapest to express in C
next to the stub that models the driver. This module exists so
`python -m unittest smart_hand.tests.*` also exercises it, and so the repo's
usual "compile it, run it, read the output" contract holds.

It is deliberately stricter than a returncode check: every named case must
report ok, because a case that quietly disappears from main() would otherwise
leave the suite green with the coverage gone.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITAN_DIR = PROJECT_ROOT / "titan_rtthread"
TESTS_DIR = PROJECT_ROOT / "tests"
STUBS_DIR = TESTS_DIR / "stubs"

TEST_C = TESTS_DIR / "test_voice_audio_titan_c.c"
SOURCES = [
    TEST_C,
    TITAN_DIR / "voice_audio_titan.c",
    TITAN_DIR / "voice_audio.c",
]
# The stubs are the driver model the assertions depend on, so a change to a
# header has to force a rebuild too.
STUB_HEADERS = [
    STUBS_DIR / "rtthread.h",
    STUBS_DIR / "rthw.h",
    STUBS_DIR / "rtdevice.h",
    STUBS_DIR / "board.h",
    STUBS_DIR / "hal_data.h",
]
TEST_EXE = TESTS_DIR / "test_voice_audio_titan_c.exe"

# Every case main() runs, in order. These are the requirements the file covers;
# a case that stops reporting is a coverage regression, not a formatting change.
EXPECTED_CASES = [
    "1-cold-start-contiguous",
    "2-restart-no-first-block-replay",
    "3-failed-start-not-running-and-recovers",
    "4-callbacks-before-start-returns",
    "5-fsp-granularity-rules",
    "6-error-events-counted",
    "7-one-second-wrap",
    "7b-ring-overrun-accounting",
    "8-probe-smoke",
    "9-stats-match-samples",
    "10-reset-stats-keeps-the-cursor",
]

# The C file reported 281 checks when this was written. The floor exists to
# catch a case that keeps its name but loses its assertions; it is not a
# target to keep in step.
MIN_CHECKS = 200

CASE_LINE = re.compile(
    r"^\[case\] (\S+): (ok|FAILED) \((?:(\d+) failures, )?(\d+) checks\)$"
)
PASSED_LINE = re.compile(
    r"^C voice audio titan tests passed \((\d+) checks\)$", re.MULTILINE
)


class VoiceAudioTitanTests(unittest.TestCase):
    def test_failed_case_line_is_parsed(self):
        line = "[case] 5-fsp-granularity-rules: FAILED (3 failures, 23 checks)"
        match = CASE_LINE.match(line)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), "5-fsp-granularity-rules")
        self.assertEqual(match.group(2), "FAILED")
        self.assertEqual(int(match.group(4)), 23)

    @classmethod
    def setUpClass(cls):
        sources = SOURCES + STUB_HEADERS
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in sources
        ):
            # -I stubs first: <rtthread.h>, <rthw.h> and <board.h> must resolve
            # to the host stubs, not to any real RT-Thread or BSP header.
            cmd = [
                "gcc", "-std=gnu11", "-Wall", "-Wextra",
                "-I", str(STUBS_DIR), "-I", str(TITAN_DIR),
                *[str(src) for src in SOURCES],
                "-o", str(TEST_EXE), "-lm",
            ]
            built = subprocess.run(cmd, capture_output=True, text=True)
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the titan voice test:\n"
                    + " ".join(cmd) + "\n" + built.stderr
                )
        cls.result = subprocess.run(
            [str(TEST_EXE)], capture_output=True, text=True
        )
        cls.cases = {}
        for line in cls.result.stdout.splitlines():
            match = CASE_LINE.match(line)
            if match:
                cls.cases[match.group(1)] = (match.group(2), int(match.group(4)))

    def _failure_note(self, message):
        return "%s\n--- stdout ---\n%s\n--- stderr ---\n%s" % (
            message, self.result.stdout, self.result.stderr,
        )

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            self._failure_note("titan voice assertions failed"),
        )
        self.assertNotIn("FAIL ", self.result.stdout)
        self.assertIsNotNone(
            PASSED_LINE.search(self.result.stdout),
            self._failure_note("the pass marker is missing"),
        )

    def test_every_case_reports_ok(self):
        missing = [name for name in EXPECTED_CASES if name not in self.cases]
        failed = [name for name, (status, _) in self.cases.items()
                  if status != "ok"]
        self.assertEqual(
            missing, [], self._failure_note("cases did not run"),
        )
        self.assertEqual(
            failed, [], self._failure_note("cases reported FAILED"),
        )

    def test_check_count_did_not_collapse(self):
        marker = PASSED_LINE.search(self.result.stdout)
        if marker is None:
            self.fail(self._failure_note("no check count to read"))
        total = int(marker.group(1))
        self.assertGreaterEqual(
            total, MIN_CHECKS,
            self._failure_note(
                "only %d checks ran; a case may have lost its assertions" % total
            ),
        )


if __name__ == "__main__":
    unittest.main()
