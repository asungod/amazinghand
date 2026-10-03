"""Train, quantise and export the Titan keyword-spotting model.

Pipeline
--------
  WAV corpus  ->  voice_features_ref log-Mel  ->  small DS-CNN  ->  int8 TFLite
                                                                     |
                              generated C header  <------------------+
                              (weights, scales, requant multipliers)

Run
---
    python train_voice_kws.py --dataset <dir>              # real recordings
    python train_voice_kws.py --synthetic                  # pipeline self-test

The generated C header is consumed by smart_hand/titan_rtthread/voice_kws.c and
checked for numerical agreement by smart_hand/tests/test_voice_kws.py.

SPLIT CONTRACT
--------------
A recorded corpus is split by SPEAKER, never by sample. One person recording 20
takes in the same room, on the same microphone, at the same distance produces
highly correlated samples; splitting those by sample index puts people the
model has already memorised into the validation set, which inflates the
validation number and collapses the moment a stranger speaks to the device.
`speaker_split()` is the only split used for real audio, and it refuses to run
on corpora with fewer than two speakers.

File names carry the speaker: `<speaker>_<distance>_<index>.wav`, e.g.
`spk01_near_003.wav`. The recording protocol is in
tools/voice_dataset/README.md.

HONESTY CONTRACT
----------------
Any metric this script writes is tagged with the corpus it came from and with
the split that produced it. The `synthetic` corpus is deterministic generated
audio used ONLY to prove the plumbing works end to end; it has no speakers at
all, so it is split by sample and written with `split_is_speaker_disjoint:
false` and `accuracy_interpretable_as_keyword_spotting: false` next to the
reason. Real recordings get `split_is_speaker_disjoint: true`. In every case
`field_accuracy_validated`, `hardware_inference_validated` and `controls_servo`
stay false until a human validates them on hardware -- a number measured off
the device is not a field result, matching the convention already used by
smart_hand/titan_ai/generated/training_metrics.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import voice_features_ref as fe  # noqa: E402
import voice_quant as vq  # noqa: E402

# --- intent vocabulary; index order is the on-device class order -------------
LABELS = [
    "开始训练",
    "取消训练",
    "下一个",
    "再来一次",
    "求助",
    "UNKNOWN",
]
CLASS_COUNT = len(LABELS)

# --- topology; must stay in sync with voice_kws.c ----------------------------
INPUT_FRAMES = fe.NUM_FRAMES  # 98
INPUT_MELS = fe.MEL_BANDS  # 40
CONV1_FILTERS = 32
BLOCK_FILTERS = 32
SEED = 20260922

MODEL_OUT = HERE / "generated"
C_HEADER = MODEL_OUT / "voice_model_data.h"
C_SOURCE = MODEL_OUT / "voice_model_data.c"
METRICS_OUT = MODEL_OUT / "voice_training_metrics.json"
TFLITE_OUT = MODEL_OUT / "voice_kws_int8.tflite"


def build_model():
    import tensorflow as tf

    tf.keras.utils.set_random_seed(SEED)

    return tf.keras.Sequential(
        [
            tf.keras.layers.Input(shape=(INPUT_FRAMES, INPUT_MELS, 1)),
            tf.keras.layers.Conv2D(
                CONV1_FILTERS, 3, strides=2, padding="same",
                activation="relu", name="conv1"),
            tf.keras.layers.DepthwiseConv2D(
                3, padding="same", activation="relu", name="dw1"),
            tf.keras.layers.Conv2D(
                BLOCK_FILTERS, 1, padding="same", activation="relu", name="pw1"),
            tf.keras.layers.AveragePooling2D(2, name="pool1"),
            tf.keras.layers.DepthwiseConv2D(
                3, padding="same", activation="relu", name="dw2"),
            tf.keras.layers.Conv2D(
                BLOCK_FILTERS, 1, padding="same", activation="relu", name="pw2"),
            tf.keras.layers.AveragePooling2D(2, name="pool2"),
            tf.keras.layers.Flatten(name="flatten"),
            tf.keras.layers.Dense(CLASS_COUNT, name="logits"),
        ],
        name="titan_voice_kws",
    )


# ---------------------------------------------------------------------------
# corpora
# ---------------------------------------------------------------------------
def synthetic_corpus(samples_per_class: int = 120, rng_seed: int = SEED):
    """Deterministic stand-in audio. Proves the plumbing, proves nothing else.

    Each class gets a distinct spectral signature so that the model has
    something learnable and the export/verify path is exercised end to end.
    """
    rng = np.random.default_rng(rng_seed)
    n = fe.WINDOW_SAMPLES
    t = np.arange(n, dtype=np.float64) / fe.SAMPLE_RATE_HZ

    specs = [
        (300.0, 2),    # 开始训练   : low tone
        (900.0, 2),    # 取消训练   : mid tone
        (2000.0, 2),   # 下一个     : high tone
        (300.0, 6),    # 再来一次   : low harmonic stack
        (1200.0, 3),   # 求助       : mid, three harmonics
        (0.0, 0),      # UNKNOWN    : band-limited noise, no tone
    ]

    xs, ys = [], []
    for class_index, (base_hz, harmonics) in enumerate(specs):
        for _ in range(samples_per_class):
            if harmonics == 0:
                noise = rng.normal(0.0, 0.25, n)
                # crude band limiting so it is not trivially separable by energy
                kernel = np.ones(9) / 9.0
                signal = np.convolve(noise, kernel, mode="same")
            else:
                signal = np.zeros(n)
                for h in range(1, harmonics + 1):
                    signal += np.sin(2 * np.pi * base_hz * h * t + rng.uniform(0, 2 * np.pi)) / h
                signal *= 0.3
                signal += rng.normal(0.0, 0.02, n)

            float_pcm = np.clip(signal, -1.0, 1.0) * 30000.0
            xs.append(float_pcm.astype(np.int16))
            ys.append(class_index)

    return np.stack(xs), np.asarray(ys, dtype=np.int64)


def wav_corpus(dataset_dir: Path):
    """Load <dir>/<label>/*.wav. Requires `soundfile`.

    Returns `(pcm, y, speakers)`. `speakers[i]` is the speaker id parsed from
    sample `i`'s file name; hand that array to speaker_split() -- it is the
    only thing that makes the validation number mean anything.
    """
    import soundfile as sf

    xs, ys, speakers = [], [], []
    for class_index, label in enumerate(LABELS):
        class_dir = dataset_dir / label
        if not class_dir.is_dir():
            raise SystemExit(f"missing class directory: {class_dir}")
        for wav in sorted(class_dir.glob("*.wav")):
            try:
                speaker = parse_speaker(wav)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            audio, rate = sf.read(str(wav), dtype="int16", always_2d=False)
            if audio.ndim != 1:
                raise SystemExit(f"{wav} is not mono")
            if rate != fe.SAMPLE_RATE_HZ:
                raise SystemExit(
                    f"{wav} is {rate} Hz, the contract requires {fe.SAMPLE_RATE_HZ} Hz")
            if audio.shape[0] < fe.WINDOW_SAMPLES:
                audio = np.pad(audio, (0, fe.WINDOW_SAMPLES - audio.shape[0]))
            xs.append(audio[: fe.WINDOW_SAMPLES])
            ys.append(class_index)
            speakers.append(speaker)
    if not xs:
        raise SystemExit(f"no wav files found under {dataset_dir}")
    return np.stack(xs), np.asarray(ys, dtype=np.int64), speakers


# ---------------------------------------------------------------------------
# splitting
# ---------------------------------------------------------------------------
# <speaker>_<distance>_<index>.wav, exactly what tools/voice_dataset/
# record_keyword.py writes. Exactly three underscore-separated fields, the last
# one numeric; anything else is a corpus error, not something to guess at.
SPEAKER_FILENAME_RE = re.compile(
    r"^(?P<speaker>[^_]+)_(?P<distance>[^_]+)_(?P<index>\d+)\.wav$"
)


def parse_speaker(path) -> str:
    """`<speaker>_<distance>_<index>.wav` -> `<speaker>`.

    Pure function so the file-name contract is testable without audio I/O.

    A name that does not match raises instead of falling back to a default
    speaker: a silent fallback would either merge two people into one identity
    or scatter one person's takes across every split, which is exactly the
    leakage this format exists to prevent.
    """
    name = Path(path).name
    match = SPEAKER_FILENAME_RE.match(name)
    if match is None:
        raise ValueError(
            f"录音文件名不符合 <说话人>_<距离>_<序号>.wav 约定：{name!r}。"
            "正确示例：spk01_near_003.wav。"
            "采集与命名规范见 tools/voice_dataset/README.md，"
            "请改名后重新运行（脚本不会替你把无法识别的样本猜到一个说话人名下）。"
        )
    return match.group("speaker")


def speaker_split(speakers, seed: int = SEED):
    """Split samples so that no speaker appears in more than one split.

    `speakers` is the per-sample speaker id array returned by wav_corpus().
    Returns `(train_idx, val_idx, test_idx, info)`.

    Rules, in order of importance:

    * train and validation speaker sets are completely disjoint (always);
    * fewer than two speakers -> refuse to train (SystemExit);
    * exactly two -> one speaker trains, one validates, and there is NO
      independent test set, so test_idx is empty and info says so rather than
      dressing the validation set up as a test set;
    * three or more -> at least one speaker validates, at least one tests, the
      rest train; test speakers are disjoint from both other sets too.

    The split is decided over speaker identities, then expanded to sample
    indices, so every take of a given speaker necessarily lands in the same
    split.
    """
    speakers = np.asarray(speakers)
    if speakers.ndim != 1:
        raise SystemExit("speakers 必须是一维的逐样本说话人列表")
    if speakers.size == 0:
        raise SystemExit("空语料：没有任何样本可供划分")

    unique = sorted(set(speakers.tolist()))
    if len(unique) < 2:
        only = unique[0] if unique else "无"
        raise SystemExit(
            f"语料只有 {len(unique)} 个说话人（{only}），无法做按说话人互斥的划分，"
            "拒绝训练。\n"
            "按说话人划分要求训练集与验证集的说话人完全不重叠，单个说话人的语料"
            "无法同时充当两者。\n"
            "请再录至少 1 位说话人的语料（规范见 tools/voice_dataset/README.md，"
            "每条音频命名为 spk02_near_001.wav 这样带说话人编号的名字），"
            "或者用 --synthetic 只跑管线自检（那条路径不产生识别准确率）。"
        )

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(unique))
    shuffled = [unique[int(i)] for i in order]

    if len(shuffled) == 2:
        train_speakers, val_speakers, test_speakers = shuffled[:1], shuffled[1:], []
    else:
        n_test = max(1, len(shuffled) // 5)
        n_val = max(1, len(shuffled) // 5)
        # Defensive: never let the fraction rule starve the training set.
        if len(shuffled) - n_test - n_val < 1:
            n_test, n_val = 1, 1
        test_speakers = shuffled[:n_test]
        val_speakers = shuffled[n_test : n_test + n_val]
        train_speakers = shuffled[n_test + n_val :]

    sets = [set(train_speakers), set(val_speakers), set(test_speakers)]
    if sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2]:
        raise SystemExit("内部错误：划分出的说话人集合出现重叠，拒绝继续")

    def indices_of(speaker_list):
        if not speaker_list:
            return np.empty(0, dtype=np.int64)
        return np.flatnonzero(np.isin(speakers, speaker_list)).astype(np.int64)

    train_idx, val_idx, test_idx = (
        indices_of(train_speakers), indices_of(val_speakers), indices_of(test_speakers),
    )

    has_test = bool(test_speakers)
    info = {
        "split_scheme": "speaker_disjoint",
        "speaker_disjoint": True,
        "speaker_count": len(shuffled),
        "train_speakers": list(train_speakers),
        "val_speakers": list(val_speakers),
        "test_speakers": list(test_speakers),
        "train_samples": int(train_idx.size),
        "val_samples": int(val_idx.size),
        "test_samples": int(test_idx.size),
        "has_independent_test_speakers": has_test,
        "seed": int(seed),
    }
    if has_test:
        info["note"] = (
            "训练/验证/测试三者的说话人集合两两互斥；测试集来自训练期间从未见过的"
            "说话人，因此 float_test_accuracy 是跨人结果（仍非真机验证结果）。"
        )
    else:
        info["note"] = (
            "语料只有 2 个说话人：无独立测试说话人，不以验证集冒充测试集；"
            "float_val_accuracy 只是留出说话人的验证数字，不作为跨人识别准确率引用。"
        )
    return train_idx, val_idx, test_idx, info


def synthetic_split(n: int, seed: int = SEED, val_fraction: float = 0.25):
    """Pipeline self-test split: random over samples, NOT speaker-disjoint.

    The synthetic corpus has no speakers -- it is deterministic generated audio
    -- so there is nothing to hold out by person and pretending otherwise would
    be a lie in the metrics file. This exists only to exercise
    fit/convert/export, and `speaker_disjoint` is False so the number it
    produces can never be read as an accuracy.
    """
    rng = np.random.default_rng(seed)
    order = rng.permutation(n)
    cut = int(n * (1.0 - val_fraction))
    train_idx, val_idx = order[:cut].astype(np.int64), order[cut:].astype(np.int64)
    info = {
        "split_scheme": "random_by_sample_synthetic_selftest",
        "speaker_disjoint": False,
        "speaker_count": 0,
        "train_speakers": None,
        "val_speakers": None,
        "test_speakers": None,
        "train_samples": int(train_idx.size),
        "val_samples": int(val_idx.size),
        "test_samples": 0,
        "has_independent_test_speakers": False,
        "seed": int(seed),
        "note": (
            "合成自检语料没有真实说话人身份，不可能做按说话人划分，这里按样本随机"
            "切分，只用于验证训练/量化/导出链路可跑通，其数字不得作为关键词识别"
            "准确率引用。真实语料请用 --dataset 走 speaker_split 路径。"
        ),
    }
    return train_idx, val_idx, np.empty(0, dtype=np.int64), info


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------
def _fmt_array(values, per_line: int = 12) -> str:
    out = []
    for i in range(0, len(values), per_line):
        out.append("    " + ", ".join(str(int(v)) for v in values[i : i + per_line]) + ",")
    return "\n".join(out)


def export_c(interpreter, out_header: Path, out_source: Path) -> dict:
    """Walk the TFLite ops in execution order and emit C source.

    Reading the model back instead of re-deriving the quantisation from Keras
    guarantees the C engine is compared against the same numbers TFLite runs.
    """
    ops = interpreter._get_ops_details()
    tensors = interpreter.get_tensor_details()
    quant = {d["index"]: d["quantization"] for d in tensors}
    scales_dict = {d["index"]: d["quantization_parameters"] for d in tensors}

    layers = []
    for op in ops:
        name = op["op_name"]
        # Shape plumbing and format casts carry no arithmetic; the C engine
        # indexes tensors directly instead of materialising reshape ops.
        if name in (
            "RESHAPE", "SHAPE", "PACK", "STRIDED_SLICE", "SLICE",
            "QUANTIZE", "DEQUANTIZE", "SOFTMAX", "DELEGATE",
        ):
            continue
        if name == "CONV_2D":
            kind = "conv2d"
        elif name == "DEPTHWISE_CONV_2D":
            kind = "dwconv2d"
        elif name == "AVERAGE_POOL_2D":
            kind = "avgpool"
        elif name == "FULLY_CONNECTED":
            kind = "fully_connected"
        else:
            raise SystemExit(
                f"unhandled op {name!r}; the C engine only implements a fixed op set")

        inputs = [int(i) for i in op["inputs"]]
        outputs = [int(i) for i in op["outputs"]]
        entry = {"kind": kind, "op": name, "inputs": inputs, "outputs": outputs}

        in_idx, out_idx = inputs[0], outputs[0]
        entry["in_scale"], entry["in_zp"] = _act_quant(scales_dict, in_idx)
        entry["out_scale"], entry["out_zp"] = _act_quant(scales_dict, out_idx)
        # Read the geometry back from the model instead of re-deriving it in C.
        # Fully connected tensors are 2D [batch, features]; normalise to 4D so
        # the engine can index every layer the same way.
        entry["in_shape"] = _norm_shape(tensors[in_idx]["shape"])
        entry["out_shape"] = _norm_shape(tensors[out_idx]["shape"])

        if kind in ("conv2d", "dwconv2d", "fully_connected"):
            w_idx = inputs[1]
            weights = interpreter.get_tensor(w_idx)
            entry["weights"] = weights
            entry["weight_shape"] = list(weights.shape)
            wq = scales_dict[w_idx]
            entry["weight_scales"] = list(np.asarray(wq["scales"], dtype=np.float64))
            entry["weight_zps"] = list(np.asarray(wq["zero_points"], dtype=np.int64))
            assert all(z == 0 for z in entry["weight_zps"]), "expected symmetric weights"

            # Output-channel count. TFLite conv weights are [out, kH, kW, in]
            # but depthwise weights are [1, kH, kW, channels]; using shape[-1]
            # for both silently swaps in-channels for out-channels on conv2d.
            if kind == "dwconv2d":
                entry["out_channels"] = entry["weight_shape"][-1]
                entry["kernel_h"] = entry["weight_shape"][1]
                entry["kernel_w"] = entry["weight_shape"][2]
                entry["in_channels"] = entry["weight_shape"][-1]
            elif kind == "conv2d":
                entry["out_channels"] = entry["weight_shape"][0]
                entry["kernel_h"] = entry["weight_shape"][1]
                entry["kernel_w"] = entry["weight_shape"][2]
                entry["in_channels"] = entry["weight_shape"][3]
            else:
                entry["out_channels"] = entry["weight_shape"][0]
                entry["in_channels"] = entry["weight_shape"][1]

            n_out = entry["out_channels"]
            if len(inputs) > 2 and inputs[2] >= 0:
                entry["bias"] = interpreter.get_tensor(inputs[2]).astype(np.int64)
            else:
                entry["bias"] = np.zeros(n_out, dtype=np.int64)
            assert entry["bias"].size == n_out, "bias length must equal out channels"

            assert len(entry["weight_scales"]) == n_out, (
                f"{kind} has {len(entry['weight_scales'])} weight scales "
                f"but {n_out} output channels"
            )

            mults, shifts = [], []
            for w_scale in entry["weight_scales"]:
                m, s = vq.requantize_accumulator(
                    0, entry["in_scale"], w_scale, entry["out_scale"])
                mults.append(m)
                shifts.append(s)
            entry["multipliers"] = mults
            entry["shifts"] = shifts
        elif kind == "avgpool":
            m, s = vq.rescale_accumulator(0, entry["in_scale"], entry["out_scale"])
            entry["multiplier"] = m
            entry["shift"] = s

        layers.append(entry)

    _validate_topology(layers)
    _write_header(out_header, layers, interpreter)
    _write_source(out_source, layers)
    return {"layers": layers}


def _norm_shape(shape):
    """[batch, features] -> [batch, 1, 1, features]; leave 4D shapes alone."""
    dims = [int(d) for d in shape]
    if len(dims) == 2:
        return [dims[0], 1, 1, dims[1]]
    if len(dims) == 4:
        return dims
    raise SystemExit(f"unsupported tensor rank {len(dims)}: {dims}")


def _validate_topology(layers) -> None:
    """voice_kws.c implements exactly one structure.

    If the Keras model drifts, fail here with a clear message rather than
    letting the firmware silently compute a different function.
    """
    expected = [
        "conv2d", "dwconv2d", "conv2d", "avgpool",
        "dwconv2d", "conv2d", "avgpool", "fully_connected",
    ]
    got = [layer["kind"] for layer in layers]
    if got != expected:
        raise SystemExit(f"topology drift: expected {expected}, got {got}")

    for i, layer in enumerate(layers):
        ih, iw, ic = layer["in_shape"][1], layer["in_shape"][2], layer["in_shape"][3]
        oh, ow, oc = layer["out_shape"][1], layer["out_shape"][2], layer["out_shape"][3]

        if layer["kind"] == "conv2d":
            k = layer["kernel_h"]
            if k not in (1, 3):
                raise SystemExit(f"layer {i}: unsupported kernel {k}x{k}")
            if k == 3:
                # first layer: stride 2 SAME, halving both spatial dims
                if oh != (ih + 1) // 2 or ow != (iw + 1) // 2:
                    raise SystemExit(
                        f"layer {i}: 3x3 conv is expected to be stride-2 SAME, "
                        f"but {ih}x{iw} -> {oh}x{ow}")
            elif (oh, ow) != (ih, iw):
                raise SystemExit(
                    f"layer {i}: 1x1 conv must preserve spatial dims, "
                    f"got {ih}x{iw} -> {oh}x{ow}")
            if ic != layer["in_channels"]:
                raise SystemExit(f"layer {i}: in-channel mismatch")
        elif layer["kind"] == "dwconv2d":
            if layer["kernel_h"] != 3 or (oh, ow) != (ih, iw) or oc != ic:
                raise SystemExit(
                    f"layer {i}: depthwise conv must be 3x3 stride-1 SAME, "
                    f"got {ih}x{iw}x{ic} -> {oh}x{ow}x{oc}")
        elif layer["kind"] == "avgpool":
            # VALID pooling: out = floor((in - k) / stride) + 1. Odd inputs are
            # fine and simply drop the trailing row/column.
            want_h = (ih - 2) // 2 + 1
            want_w = (iw - 2) // 2 + 1
            if (oh, ow) != (want_h, want_w) or oc != ic:
                raise SystemExit(
                    f"layer {i}: pooling must be 2x2 stride-2 VALID, "
                    f"got {ih}x{iw} -> {oh}x{ow}, expected {want_h}x{want_w}")
        elif layer["kind"] == "fully_connected":
            if ih != 1 or iw != 1:
                raise SystemExit(
                    f"layer {i}: fully connected expects a flat input, "
                    f"got {ih}x{iw}x{ic}")


def _act_quant(scales_dict, index):
    params = scales_dict[index]
    scales = np.asarray(params["scales"], dtype=np.float64)
    zps = np.asarray(params["zero_points"], dtype=np.int64)
    if scales.size != 1:
        raise SystemExit(f"tensor {index} is not per-tensor quantised")
    return float(scales[0]), int(zps[0])


def _c_name(index: int, suffix: str) -> str:
    return f"g_voice_model_t{index}_{suffix}"


def _write_header(path: Path, layers, interpreter) -> None:
    lines = [
        "/* GENERATED by smart_hand/titan_ai/voice/train_voice_kws.py -- do not edit. */",
        "#ifndef VOICE_MODEL_DATA_H",
        "#define VOICE_MODEL_DATA_H",
        "",
        "#include <stdint.h>",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        f"#define VOICE_MODEL_LAYER_COUNT {len(layers)}",
        f"#define VOICE_MODEL_INPUT_FRAMES {INPUT_FRAMES}",
        f"#define VOICE_MODEL_INPUT_MELS {INPUT_MELS}",
        f"#define VOICE_MODEL_INPUT_COUNT {INPUT_FRAMES * INPUT_MELS}",
        f"#define VOICE_MODEL_CLASS_COUNT {CLASS_COUNT}",
        "",
    ]

    for i, layer in enumerate(layers):
        # Shapes are written as flat element counts so the engine can index
        # without needing multi-dimensional array syntax in the generated file.
        lines.append(f"/* layer {i}: {layer['op']} */")
        lines.append(f"#define VOICE_MODEL_L{i}_KIND \"{layer['kind']}\"")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_SCALE {layer['in_scale']!r}f")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_ZP {layer['in_zp']}")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_SCALE {layer['out_scale']!r}f")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_ZP {layer['out_zp']}")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_COUNT {int(np.prod(layer['in_shape']))}")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_COUNT {int(np.prod(layer['out_shape']))}")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_H {layer['in_shape'][1]}")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_W {layer['in_shape'][2]}")
        lines.append(f"#define VOICE_MODEL_L{i}_IN_C {layer['in_shape'][3]}")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_H {layer['out_shape'][1]}")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_W {layer['out_shape'][2]}")
        lines.append(f"#define VOICE_MODEL_L{i}_OUT_C {layer['out_shape'][3]}")

        if "weights" in layer:
            n_out = layer["out_channels"]
            n_weights = int(np.prod(layer["weight_shape"]))
            lines.append(f"#define VOICE_MODEL_L{i}_WEIGHT_COUNT {n_weights}")
            lines.append(f"#define VOICE_MODEL_L{i}_OUT_CHANNELS {n_out}")
            if layer["kind"] != "fully_connected":
                lines.append(f"#define VOICE_MODEL_L{i}_IN_CHANNELS {layer['in_channels']}")
                lines.append(f"#define VOICE_MODEL_L{i}_KERNEL_H {layer['kernel_h']}")
                lines.append(f"#define VOICE_MODEL_L{i}_KERNEL_W {layer['kernel_w']}")
            else:
                lines.append(f"#define VOICE_MODEL_L{i}_IN_CHANNELS {layer['in_channels']}")
            lines.append(f"extern const int8_t {_c_name(i, 'w')}[{n_weights}];")
            lines.append(f"extern const int32_t {_c_name(i, 'b')}[{n_out}];")
            lines.append(f"extern const int32_t {_c_name(i, 'mult')}[{n_out}];")
            lines.append(f"extern const int8_t {_c_name(i, 'shift')}[{n_out}];")
        else:
            lines.append(f"#define VOICE_MODEL_L{i}_MULT {layer['multiplier']}")
            lines.append(f"#define VOICE_MODEL_L{i}_SHIFT {layer['shift']}")
        lines.append("")

    lines.append("extern const char *const g_voice_model_labels[VOICE_MODEL_CLASS_COUNT];")
    lines.append("")
    lines.append("#ifdef __cplusplus")
    lines.append("}")
    lines.append("#endif")
    lines.append("")
    lines.append("#endif")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_source(path: Path, layers) -> None:
    parts = [
        "/* GENERATED by smart_hand/titan_ai/voice/train_voice_kws.py -- do not edit. */",
        '#include "voice_model_data.h"',
        "",
    ]
    for i, layer in enumerate(layers):
        if "weights" not in layer:
            continue
        w = layer["weights"].astype(np.int8).reshape(-1)
        parts.append(f"const int8_t {_c_name(i, 'w')}[{w.size}] = {{")
        parts.append(_fmt_array(w))
        parts.append("};")
        parts.append("")
        parts.append(f"const int32_t {_c_name(i, 'b')}[{layer['bias'].size}] = {{")
        parts.append(_fmt_array(layer["bias"]))
        parts.append("};")
        parts.append("")
        parts.append(f"const int32_t {_c_name(i, 'mult')}[{len(layer['multipliers'])}] = {{")
        parts.append(_fmt_array(layer["multipliers"], per_line=6))
        parts.append("};")
        parts.append("")
        parts.append(f"const int8_t {_c_name(i, 'shift')}[{len(layer['shifts'])}] = {{")
        parts.append(_fmt_array(layer["shifts"]))
        parts.append("};")
        parts.append("")

    parts.append("const char *const g_voice_model_labels[VOICE_MODEL_CLASS_COUNT] = {")
    for label in LABELS:
        parts.append(f'    "{label}",')
    parts.append("};")
    parts.append("")
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if not args.dataset and not args.synthetic:
        parser.error("pass --dataset <dir> or --synthetic")

    import tensorflow as tf

    corpus = "synthetic_deterministic_pipeline_selftest" if args.synthetic else "recorded_wav"
    is_real_corpus = not args.synthetic

    # Two clearly separate paths: real recordings are split by speaker, the
    # synthetic self-test is split by sample because it has no speakers. They
    # are never mixed and the metrics record which one ran.
    if args.synthetic:
        pcm, y = synthetic_corpus()
        train_idx, val_idx, test_idx, split_info = synthetic_split(len(y), SEED)
    else:
        pcm, y, speakers = wav_corpus(args.dataset)
        train_idx, val_idx, test_idx, split_info = speaker_split(speakers, SEED)

    print(f"corpus={corpus} samples={len(y)} split={split_info['split_scheme']}")
    print(f"  train: {split_info['train_samples']} samples, "
          f"speakers={split_info['train_speakers']}")
    print(f"  val  : {split_info['val_samples']} samples, "
          f"speakers={split_info['val_speakers']}")
    print(f"  test : {split_info['test_samples']} samples, "
          f"speakers={split_info['test_speakers']}")
    print(f"  speaker_disjoint={split_info['speaker_disjoint']}  {split_info['note']}")

    frontend = fe.VoiceFrontend()
    features = np.stack([frontend.window(x) for x in pcm])
    features = features.reshape(-1, INPUT_FRAMES, INPUT_MELS, 1).astype(np.float32)

    model = build_model()
    model.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss=tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True),
        metrics=["accuracy"],
    )
    history = model.fit(
        features[train_idx], y[train_idx],
        validation_data=(features[val_idx], y[val_idx]),
        epochs=args.epochs, batch_size=args.batch_size, verbose=2,
    )

    # The held-out-speaker number. Only exists when there is a speaker that
    # trained on and validated on neither, which is why it can be None.
    test_accuracy = None
    if test_idx.size:
        _, test_accuracy = model.evaluate(features[test_idx], y[test_idx], verbose=0)
        test_accuracy = float(test_accuracy)
        print(f"test accuracy on unseen speakers: {test_accuracy:.4f}")

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    converter.inference_input_type = tf.int8
    converter.inference_output_type = tf.int8
    converter.representative_dataset = lambda: (
        [features[i : i + 1]] for i in range(min(len(features), 200))
    )
    tflite_bytes = converter.convert()
    TFLITE_OUT.parent.mkdir(parents=True, exist_ok=True)
    TFLITE_OUT.write_bytes(tflite_bytes)

    # Delegates must be off: with XNNPACK active the op list comes back
    # collapsed behind a DELEGATE node and the per-op tensors are no longer the
    # ones the firmware will compute.
    interpreter = tf.lite.Interpreter(
        model_content=tflite_bytes,
        experimental_op_resolver_type=(
            tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES
        ),
    )
    interpreter.allocate_tensors()
    exported = export_c(interpreter, C_HEADER, C_SOURCE)

    # Whether the headline number may be read as a keyword-spotting accuracy at
    # all. Synthetic audio can never clear this bar; real recordings only clear
    # it when an independent test speaker exists. Either way the number is off
    # the device and stays unvalidated in the field.
    if not is_real_corpus:
        accuracy_interpretable = False
        accuracy_reason = (
            "本次运行使用合成自检语料（确定性生成音频，没有任何真实说话人），"
            "该数字只证明训练/量化/导出链路可跑通，不能解读为关键词识别准确率。"
            "真实识别率必须在 --dataset 录制的真实语料上、按说话人切分的测试集上测量。"
        )
    elif not split_info["has_independent_test_speakers"]:
        accuracy_interpretable = False
        accuracy_reason = (
            "本次运行使用真实录音语料，但说话人少于 3 位，没有独立的测试说话人："
            "float_val_accuracy 是留出说话人的验证数字，不以验证集冒充测试集，"
            "因此不将其解读为跨说话人的关键词识别准确率。补录到至少 3 位说话人后再训练。"
        )
    else:
        accuracy_interpretable = True
        accuracy_reason = (
            "本次运行使用真实录音语料，且测试集的说话人与训练/验证说话人完全互斥，"
            "float_test_accuracy 是在未见过的说话人上测得的识别准确率。"
            "该数字仍来自离线训练环境，未经真机验证，故 field_accuracy_validated 保持 false。"
        )

    metrics = {
        "corpus": corpus,
        "corpus_kind": (
            "synthetic_pipeline_selftest" if not is_real_corpus else "recorded_wav"
        ),
        "is_real_corpus": is_real_corpus,
        "labels": LABELS,
        "architecture": "conv2d(32,3x3,s2) -> dwconv3x3 -> pwconv1x1 -> avgpool2x2"
                        " -> dwconv3x3 -> pwconv1x1 -> avgpool2x2 -> flatten -> fc(6)",
        "input_shape": [INPUT_FRAMES, INPUT_MELS, 1],
        "split": split_info,
        "split_is_speaker_disjoint": bool(split_info["speaker_disjoint"]),
        "float_val_accuracy": float(history.history["val_accuracy"][-1]),
        "float_test_accuracy": test_accuracy,
        "accuracy_interpretable_as_keyword_spotting": accuracy_interpretable,
        "accuracy_interpretation_note": accuracy_reason,
        "layer_count": len(exported["layers"]),
        "op_sequence": [layer["op"] for layer in exported["layers"]],
        "tflite_bytes": len(tflite_bytes),
        "field_accuracy_validated": False,
        "hardware_inference_validated": False,
        "controls_servo": False,
        "note": (
            "Accuracy fields above are measured on the corpus named in `corpus` "
            "with the split described in `split`. For "
            "'synthetic_deterministic_pipeline_selftest' they exercise the "
            "pipeline only and are NOT a keyword-spotting result. "
            "field_accuracy_validated stays false until a human measures the "
            "model on the real device; no script may set it."
        ),
    }
    METRICS_OUT.write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"tflite  {len(tflite_bytes)} bytes -> {TFLITE_OUT}")
    print(f"header  -> {C_HEADER}")
    print(f"source  -> {C_SOURCE}")
    print(f"metrics -> {METRICS_OUT}")
    print("op sequence:", metrics["op_sequence"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
