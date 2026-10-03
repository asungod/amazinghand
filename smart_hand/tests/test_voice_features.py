"""Cross-validate the Titan log-Mel front end between C and Python.

The point of this test is the contract that matters for the whole voice
pipeline: whatever the firmware computes at inference time must be what the
training script computed at training time. Two independent implementations
exist for that reason --

    smart_hand/titan_rtthread/voice_features.c          (runs on Titan)
    smart_hand/titan_ai/voice/voice_features_ref.py     (runs at training time)

-- and this module feeds both the same deterministic audio and compares the
results. The float32 stages are allowed a small tolerance; the int8
quantisation stage is required to match exactly, because that is the array the
network actually consumes.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITAN_DIR = PROJECT_ROOT / "titan_rtthread"
AI_DIR = PROJECT_ROOT / "titan_ai" / "voice"
TESTS_DIR = PROJECT_ROOT / "tests"

sys.path.insert(0, str(AI_DIR))

import numpy as np  # noqa: E402
import voice_features_ref as ref  # noqa: E402

CONFIG_HEADER = TITAN_DIR / "voice_config.h"
FEATURES_C = TITAN_DIR / "voice_features.c"
TEST_C = TESTS_DIR / "test_voice_features_c.c"
TEST_EXE = TESTS_DIR / "test_voice_features_c.exe"

# Observed C-vs-Python float32 disagreement on this signal. The FFT butterfly
# order is identical on both sides, so the residual comes from summation order
# in the mel filterbank reduction and from libm versus numpy transcendental
# rounding. It is many orders of magnitude below one int8 quantisation step
# (0.0625), which is why the quantised output can still be required to match
# bit for bit.
LOG_MEL_ABS_TOLERANCE = 1.0e-3

SEED = 0x5A17C0DE


def _parse_simple_defines(header: Path) -> dict:
    """Read `#define NAME <integer-or-float>` entries, skipping derived ones."""
    text = header.read_text(encoding="utf-8")
    values = {}
    for match in re.finditer(
        r"^#define\s+(VOICE_[A-Z0-9_]+)\s+\(?\s*([0-9]+(?:\.[0-9]+)?[fFuUlL]*)\s*\)?\s*$",
        text,
        flags=re.MULTILINE,
    ):
        name, raw = match.group(1), match.group(2)
        values[name] = float(raw.rstrip("fFuUlL"))
    return values


def _ensure_test_binary() -> None:
    """Build the C host test if it is missing or stale."""
    sources = [FEATURES_C, TEST_C]
    if TEST_EXE.exists() and all(
        TEST_EXE.stat().st_mtime >= src.stat().st_mtime for src in sources
    ):
        return

    cmd = [
        "gcc",
        "-std=gnu11",
        "-Wall",
        "-Wextra",
        "-I",
        str(TITAN_DIR),
        str(TEST_C),
        str(FEATURES_C),
        "-o",
        str(TEST_EXE),
        "-lm",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            "failed to build the C voice test:\n"
            + " ".join(cmd)
            + "\n"
            + result.stderr
        )


def _run_test_binary() -> dict:
    _ensure_test_binary()
    result = subprocess.run(
        [str(TEST_EXE)], capture_output=True, text=True, check=True
    )
    stdout = result.stdout
    if "C voice feature tests passed" not in stdout:
        raise AssertionError(
            "C voice feature assertions failed; raw output:\n" + stdout[-4000:]
        )

    parsed = {"raw": stdout}

    config = re.search(r"^CONFIG ((?:\d+ )+\d+)$", stdout, flags=re.MULTILINE)
    if config is None:
        raise AssertionError("no CONFIG line in C output")
    parsed["config"] = [int(v) for v in config.group(1).split()]

    scale = re.search(
        r"^QUANT_SCALE (\S+) (-?\d+)$", stdout, flags=re.MULTILINE
    )
    if scale is None:
        raise AssertionError("no QUANT_SCALE line in C output")
    parsed["quant_scale"] = float(scale.group(1))
    parsed["quant_zero_point"] = int(scale.group(2))

    for key in ("LOGMEL", "QUANT"):
        block = re.search(
            rf"^{key} (\d+)\n([^\n]+)$", stdout, flags=re.MULTILINE
        )
        if block is None:
            raise AssertionError(f"no {key} block in C output")
        count = int(block.group(1))
        values = block.group(2).split()
        if len(values) != count:
            raise AssertionError(
                f"{key} declared {count} values but printed {len(values)}"
            )
        parsed[key] = values

    return parsed


class VoiceFeatureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = _run_test_binary()
        cls.pcm = ref.deterministic_pcm(ref.WINDOW_SAMPLES, SEED)
        cls.py_logmel = ref.VoiceFrontend().window(cls.pcm)

    def test_header_constants_match_python_reference(self):
        """voice_config.h is the single source of truth; catch silent drift."""
        defines = _parse_simple_defines(CONFIG_HEADER)
        expected = {
            "VOICE_SAMPLE_RATE_HZ": ref.SAMPLE_RATE_HZ,
            "VOICE_FRAME_LEN_MS": ref.FRAME_LEN_MS,
            "VOICE_FRAME_HOP_MS": ref.FRAME_HOP_MS,
            "VOICE_WINDOW_MS": ref.WINDOW_MS,
            "VOICE_FFT_SIZE": ref.FFT_SIZE,
            "VOICE_MEL_BANDS": ref.MEL_BANDS,
            "VOICE_MEL_LOW_HZ": ref.MEL_LOW_HZ,
            "VOICE_MEL_HIGH_HZ": ref.MEL_HIGH_HZ,
        }
        for name, want in expected.items():
            self.assertIn(name, defines, f"{name} not found in voice_config.h")
            self.assertEqual(
                defines[name],
                float(want),
                f"{name} drifted: header says {defines[name]}, Python says {want}",
            )

    def test_derived_shape_matches(self):
        config = self.c["config"]
        self.assertEqual(
            config,
            [
                ref.SAMPLE_RATE_HZ,
                ref.FRAME_LEN,
                ref.FRAME_HOP,
                ref.NUM_FRAMES,
                ref.MEL_BANDS,
                ref.FEATURE_COUNT,
            ],
            "C and Python disagree on the derived feature geometry",
        )
        self.assertEqual(len(self.c["LOGMEL"]), ref.FEATURE_COUNT)
        self.assertEqual(len(self.py_logmel), ref.FEATURE_COUNT)

    def test_log_mel_agrees_within_tolerance(self):
        c_values = np.array(
            [float(v) for v in self.c["LOGMEL"]], dtype=np.float32
        )
        worst = float(np.max(np.abs(c_values - self.py_logmel)))
        self.assertLess(
            worst,
            LOG_MEL_ABS_TOLERANCE,
            f"max |C - Python| = {worst:g} exceeds {LOG_MEL_ABS_TOLERANCE:g}",
        )

    def test_int8_quantisation_is_bit_exact(self):
        """The array the network eats must be identical on both sides."""
        c_q = np.array([int(v) for v in self.c["QUANT"]], dtype=np.int16)
        py_q = ref.quantize_int8(
            self.py_logmel,
            self.c["quant_scale"],
            self.c["quant_zero_point"],
        ).astype(np.int16)

        mismatches = int(np.count_nonzero(c_q != py_q))
        self.assertEqual(
            mismatches,
            0,
            f"{mismatches} of {c_q.size} quantised features differ; "
            f"first at index {int(np.argmax(c_q != py_q))} "
            f"(C={c_q[np.argmax(c_q != py_q)]}, "
            f"Python={py_q[np.argmax(c_q != py_q)]})",
        )

    def test_silence_is_representable(self):
        """Silence must floor, not produce -inf, NaN, or a clipping artefact."""
        frontend = ref.VoiceFrontend()
        silence = frontend.window(np.zeros(ref.WINDOW_SAMPLES, dtype=np.int16))
        self.assertTrue(np.all(np.isfinite(silence)))
        self.assertAlmostEqual(
            float(silence[0]), float(np.log(np.float32(ref.LOG_FLOOR))), places=4
        )


if __name__ == "__main__":
    unittest.main()
