"""Verify the hand-written int8 engine against the TFLite reference model.

smart_hand/titan_rtthread/voice_kws.c reimplements the eight operators the
exported model uses, because TFLM is C++ and neither build system compiles it.
That reimplementation is only trustworthy if it is checked against the thing it
replaces, which is what this module does: the same int8 feature bytes go into
the TFLite interpreter and into the C engine, and the logits are compared.

Requires TensorFlow, so it runs under D:\\voice_kws_env rather than the plain
interpreter used by the other test modules:

    D:/voice_kws_env/Scripts/python.exe -m unittest smart_hand.tests.test_voice_kws -v

The test skips itself when TensorFlow is unavailable rather than failing, so
the rest of the suite still runs on a bare Python install.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TITAN_DIR = PROJECT_ROOT / "titan_rtthread"
AI_DIR = PROJECT_ROOT / "titan_ai" / "voice"
GEN_DIR = AI_DIR / "generated"
TESTS_DIR = PROJECT_ROOT / "tests"

sys.path.insert(0, str(AI_DIR))

import voice_features_ref as fe  # noqa: E402

MODEL_PATH = GEN_DIR / "voice_kws_int8.tflite"
HEADER_PATH = GEN_DIR / "voice_model_data.h"
TEST_C = TESTS_DIR / "test_voice_kws_c.c"
TEST_EXE = TESTS_DIR / "test_voice_kws_c.exe"

SAMPLE_COUNT = 24
SEED = 424242

try:
    import tensorflow as tf  # noqa: E402

    TF_AVAILABLE = True
except Exception:  # pragma: no cover - depends on the interpreter used
    TF_AVAILABLE = False


def _np_int8(array) -> np.ndarray:
    return array.astype(np.uint8).view(np.int8)


def _build_exe() -> None:
    sources = [
        TEST_C,
        TITAN_DIR / "voice_kws.c",
        TITAN_DIR / "voice_features.c",
        GEN_DIR / "voice_model_data.c",
    ]
    if TEST_EXE.exists() and all(
        TEST_EXE.stat().st_mtime >= src.stat().st_mtime for src in sources
    ):
        return
    cmd = [
        "gcc", "-std=gnu11", "-Wall", "-Wextra", "-O2",
        "-I", str(TITAN_DIR), "-I", str(GEN_DIR),
        str(TEST_C),
        str(TITAN_DIR / "voice_kws.c"),
        str(TITAN_DIR / "voice_features.c"),
        str(GEN_DIR / "voice_model_data.c"),
        "-o", str(TEST_EXE), "-lm",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(
            "failed to build the C engine test:\n" + " ".join(cmd) + "\n" + result.stderr
        )


def _make_features() -> np.ndarray:
    """Two kinds of input: adversarial random bytes, and realistic ones.

    Random int8 is the harsher test -- it drives every accumulator to both
    saturation ends -- while frontend-derived features confirm the realistic
    path agrees too.
    """
    rng = np.random.default_rng(SEED)
    half = SAMPLE_COUNT // 2

    random_part = _np_int8(rng.integers(0, 256, size=(half, fe.FEATURE_COUNT)))

    frontend = fe.VoiceFrontend()
    realistic = []
    for i in range(SAMPLE_COUNT - half):
        pcm = fe.deterministic_pcm(fe.WINDOW_SAMPLES, seed=0x1000 + i)
        logmel = frontend.window(pcm)
        # Mirrors voice_kws_predict: quantise with the model's input params.
        params = _input_quant_params()
        realistic.append(fe.quantize_int8(logmel, params[0], params[1]))
    return np.concatenate([random_part, np.stack(realistic)]).astype(np.int8)


def _header_defines() -> dict:
    text = HEADER_PATH.read_text(encoding="utf-8")
    values = {}
    for match in re.finditer(
        r"^#define\s+(VOICE_MODEL_[A-Z0-9_]+)\s+\(?([-0-9.eE+]+)f?\s*\)?\s*$",
        text,
        flags=re.MULTILINE,
    ):
        values[match.group(1)] = float(match.group(2))
    return values


def _input_quant_params():
    defines = _header_defines()
    return defines["VOICE_MODEL_L0_IN_SCALE"], int(defines["VOICE_MODEL_L0_IN_ZP"])


@unittest.skipUnless(TF_AVAILABLE, "TensorFlow is required for the TFLite reference")
@unittest.skipUnless(MODEL_PATH.exists(), "run train_voice_kws.py first")
class VoiceKwsTfliteAgreementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.features = _make_features()

        # Pass bytes, not a path: the project directory has a non-ASCII name and
        # TFLite's C++ file layer opens paths through the ANSI code page.
        cls.interpreter = tf.lite.Interpreter(
            model_content=MODEL_PATH.read_bytes(),
            experimental_op_resolver_type=(
                tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES
            ),
            # TFLite's memory planner reuses intermediate buffers. Without this
            # flag, reading a mid-graph tensor returns whatever was written
            # there last, which silently produces garbage comparisons.
            experimental_preserve_all_tensors=True,
        )
        cls.interpreter.allocate_tensors()
        cls.input_detail = cls.interpreter.get_input_details()[0]
        cls.output_detail = cls.interpreter.get_output_details()[0]

        cls.tflite_logits = cls._run_tflite(cls.features)

        _build_exe()
        with tempfile.TemporaryDirectory() as tmp:
            feat_path = Path(tmp) / "features.bin"
            logit_path = Path(tmp) / "logits.bin"
            feat_path.write_bytes(cls.features.tobytes())
            result = subprocess.run(
                [str(TEST_EXE), str(feat_path), str(logit_path)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise AssertionError(
                    "C engine driver failed:\n" + result.stdout + result.stderr
                )
            raw = np.frombuffer(logit_path.read_bytes(), dtype=np.int8)
        cls.c_logits = raw.reshape(len(cls.features), -1)

    @classmethod
    def _run_tflite(cls, features: np.ndarray) -> np.ndarray:
        out = []
        shape = tuple(cls.input_detail["shape"])
        for row in features:
            cls.interpreter.set_tensor(
                cls.input_detail["index"], row.reshape(shape)
            )
            cls.interpreter.invoke()
            out.append(
                cls.interpreter.get_tensor(cls.output_detail["index"]).reshape(-1)
            )
        return np.stack(out)

    def test_shapes_line_up(self):
        self.assertEqual(self.features.shape[1], int(_header_defines()["VOICE_MODEL_INPUT_COUNT"]))
        self.assertEqual(self.tflite_logits.shape, self.c_logits.shape)
        self.assertEqual(self.c_logits.shape[1], int(_header_defines()["VOICE_MODEL_CLASS_COUNT"]))

    def test_argmax_matches_tflite_on_every_sample(self):
        """The decision is what matters: the predicted intent must never differ."""
        tflite_best = np.argmax(self.tflite_logits.astype(np.int16), axis=1)
        c_best = np.argmax(self.c_logits.astype(np.int16), axis=1)
        mismatches = np.flatnonzero(tflite_best != c_best)
        if mismatches.size:
            first = int(mismatches[0])
            self.fail(
                f"{mismatches.size}/{len(tflite_best)} samples predict a different "
                f"class; first at index {first}: tflite={int(tflite_best[first])}, "
                f"c={int(c_best[first])}"
            )

    def test_logits_are_numerically_close(self):
        """Quantised logits should agree except where a requant lands on a tie."""
        diff = np.abs(self.tflite_logits.astype(np.int32) - self.c_logits.astype(np.int32))
        exact = float(np.mean(diff == 0)) * 100.0
        print(
            f"\n  int8 logit agreement: exact {exact:.2f}%, "
            f"max |diff| {int(diff.max())}, mean |diff| {diff.mean():.4f}"
        )
        self.assertLessEqual(
            int(diff.max()), 1,
            f"logits differ by more than one quantisation step: {int(diff.max())}",
        )

    def test_engine_relies_on_matching_pool_scales(self):
        """voice_avgpool2x2_valid skips rescaling, which requires equal scales.

        If a future export breaks that assumption the pooling arithmetic is
        silently wrong, so assert it rather than trusting the topology.
        """
        defines = _header_defines()
        for layer in (3, 6):
            self.assertEqual(
                defines[f"VOICE_MODEL_L{layer}_IN_SCALE"],
                defines[f"VOICE_MODEL_L{layer}_OUT_SCALE"],
                f"layer {layer} pooling needs equal in/out scales",
            )
            self.assertEqual(
                defines[f"VOICE_MODEL_L{layer}_IN_ZP"],
                defines[f"VOICE_MODEL_L{layer}_OUT_ZP"],
                f"layer {layer} pooling needs equal in/out zero points",
            )

    def test_metrics_never_claim_field_validation(self):
        """Guards the honesty contract carried over from titan_trust."""
        import json

        metrics = json.loads(
            (GEN_DIR / "voice_training_metrics.json").read_text(encoding="utf-8")
        )
        self.assertFalse(metrics["field_accuracy_validated"])
        self.assertFalse(metrics["hardware_inference_validated"])
        self.assertFalse(metrics["controls_servo"])


if __name__ == "__main__":
    unittest.main()
