"""Run the PCM ring-buffer assertions and wrap them for the Python suite.

The assertions themselves live in tests/test_voice_audio_c.c, because the code
under test is C and the interesting cases (index wrap-around, a consumer that
falls behind, a push larger than the buffer) are cheap to express there. This
module exists so `python -m unittest smart_hand.tests.*` also exercises it.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITAN_DIR = PROJECT_ROOT / "titan_rtthread"
TESTS_DIR = PROJECT_ROOT / "tests"

TEST_C = TESTS_DIR / "test_voice_audio_c.c"
SOURCE_C = TITAN_DIR / "voice_audio.c"
TEST_EXE = TESTS_DIR / "test_voice_audio_c.exe"


class VoiceAudioRingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sources = [TEST_C, SOURCE_C]
        if not TEST_EXE.exists() or any(
            TEST_EXE.stat().st_mtime < src.stat().st_mtime for src in sources
        ):
            cmd = [
                "gcc", "-std=gnu11", "-Wall", "-Wextra",
                "-I", str(TITAN_DIR),
                str(TEST_C), str(SOURCE_C),
                "-o", str(TEST_EXE), "-lm",
            ]
            built = subprocess.run(cmd, capture_output=True, text=True)
            if built.returncode != 0:
                raise AssertionError(
                    "failed to build the ring-buffer test:\n"
                    + " ".join(cmd) + "\n" + built.stderr
                )
        cls.result = subprocess.run(
            [str(TEST_EXE)], capture_output=True, text=True
        )

    def test_c_assertions_pass(self):
        self.assertEqual(
            self.result.returncode, 0,
            "ring-buffer assertions failed:\n" + self.result.stdout + self.result.stderr,
        )
        self.assertIn("C voice audio tests passed", self.result.stdout)


if __name__ == "__main__":
    unittest.main()
