"""Reference log-Mel front end for Titan keyword spotting.

This module mirrors smart_hand/titan_rtthread/voice_features.c step for step.
Training must consume features produced by THIS module, not by librosa or
tf.signal, otherwise the model is trained on a different feature distribution
than the firmware computes.

The FFT below is written as an explicit radix-2 butterfly loop rather than
np.fft.rfft. np.fft computes in double precision internally and uses its own
factorisation; the loop here reproduces the C operation order element by
element, which keeps the float32 disagreement small enough that the int8
quantisation step agrees exactly.

Tests: smart_hand/tests/test_voice_features.py
"""

from __future__ import annotations

import numpy as np

# --- contract constants; must equal smart_hand/titan_rtthread/voice_config.h ---
SAMPLE_RATE_HZ = 16000
FRAME_LEN_MS = 25
FRAME_HOP_MS = 10
FRAME_LEN = SAMPLE_RATE_HZ * FRAME_LEN_MS // 1000  # 400
FRAME_HOP = SAMPLE_RATE_HZ * FRAME_HOP_MS // 1000  # 160
WINDOW_MS = 1000
WINDOW_SAMPLES = SAMPLE_RATE_HZ * WINDOW_MS // 1000  # 16000
NUM_FRAMES = (WINDOW_SAMPLES - FRAME_LEN) // FRAME_HOP + 1  # 98
FFT_SIZE = 512
MEL_BANDS = 40
MEL_LOW_HZ = 20.0
MEL_HIGH_HZ = 7600.0
FEATURE_COUNT = NUM_FRAMES * MEL_BANDS  # 3920
LOG_FLOOR = 1.0e-6
MEL_HZ_PER_MEL = 700.0
MEL_SCALE = 1127.0
MEL_BIN_COUNT = FFT_SIZE // 2 + 1  # 257

_TWO_PI = np.float32(6.28318530717958647692)
_F32 = np.float32


def hz_to_mel(hz):
    return MEL_SCALE * np.log1p(np.asarray(hz, dtype=np.float64) / MEL_HZ_PER_MEL)


def mel_to_hz(mel):
    return MEL_HZ_PER_MEL * (np.exp(np.asarray(mel, dtype=np.float64) / MEL_SCALE) - 1.0)


def _bit_reverse_indices(n: int) -> np.ndarray:
    idx = np.zeros(n, dtype=np.int64)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        idx[i] = j
    return idx


def _fft(re: np.ndarray, im: np.ndarray, tw_re: np.ndarray, tw_im: np.ndarray, n: int):
    """In-place radix-2 FFT, batched. Mirrors voice_features.c:voice_fft."""
    rev = _bit_reverse_indices(n)
    re = re[rev].copy()
    im = im[rev].copy()

    length = 2
    while length <= n:
        half = length // 2
        step = n // length
        k = np.arange(half, dtype=np.int64) * step
        w_re = tw_re[k]
        w_im = tw_im[k]

        re_b = re.reshape(-1, length)
        im_b = im.reshape(-1, length)
        a_re = re_b[:, :half].copy()
        a_im = im_b[:, :half].copy()
        b_re = re_b[:, half:].copy()
        b_im = im_b[:, half:].copy()

        tr = (b_re * w_re) - (b_im * w_im)
        ti = (b_re * w_im) + (b_im * w_re)

        re_b[:, half:] = a_re - tr
        im_b[:, half:] = a_im - ti
        re_b[:, :half] = a_re + tr
        im_b[:, :half] = a_im + ti
        length *= 2
    return re, im


class VoiceFrontend:
    """Holds the window, twiddles and mel filterbank. Build once, reuse."""

    def __init__(self):
        n = np.arange(FRAME_LEN, dtype=np.float32)
        denom = _F32(FRAME_LEN - 1)
        phase = (_TWO_PI * n) / denom
        self.hann = (_F32(0.5) - (_F32(0.5) * np.cos(phase).astype(np.float32))).astype(np.float32)

        k = np.arange(FFT_SIZE // 2, dtype=np.float32)
        tphase = (_TWO_PI * k) / _F32(FFT_SIZE)
        self.twiddle_re = np.cos(tphase).astype(np.float32)
        self.twiddle_im = (-np.sin(tphase)).astype(np.float32)

        mel_low = hz_to_mel(MEL_LOW_HZ)
        mel_high = hz_to_mel(MEL_HIGH_HZ)
        points = MEL_BANDS + 2
        mel_points = mel_low + (mel_high - mel_low) * np.arange(points) / (points - 1)
        bin_points = mel_to_hz(mel_points) * FFT_SIZE / SAMPLE_RATE_HZ

        weights = np.zeros((MEL_BANDS, MEL_BIN_COUNT), dtype=np.float32)
        bins = np.arange(MEL_BIN_COUNT, dtype=np.float64)
        for band in range(MEL_BANDS):
            left, centre, right = bin_points[band : band + 3]
            rising = (bins >= left) & (bins <= centre)
            falling = (bins > centre) & (bins <= right)
            if centre > left:
                weights[band, rising] = ((bins[rising] - left) / (centre - left)).astype(np.float32)
            if right > centre:
                weights[band, falling] = ((right - bins[falling]) / (right - centre)).astype(np.float32)
        self.mel_weight = weights

    def frame(self, samples: np.ndarray) -> np.ndarray:
        """One 25 ms frame of int16 samples -> MEL_BANDS float32 log-mel values."""
        x = samples.astype(np.float32)
        mean = _F32(np.float32(x.mean(dtype=np.float32)))

        re = np.zeros(FFT_SIZE, dtype=np.float32)
        im = np.zeros(FFT_SIZE, dtype=np.float32)
        re[:FRAME_LEN] = (x - mean) * self.hann

        re, im = _fft(re, im, self.twiddle_re, self.twiddle_im, FFT_SIZE)

        re = re[:MEL_BIN_COUNT]
        im = im[:MEL_BIN_COUNT]
        power = (re * re) + (im * im)
        energy = self.mel_weight @ power.astype(np.float32)
        energy = np.maximum(energy, _F32(LOG_FLOOR))
        return np.log(energy).astype(np.float32)

    def window(self, samples: np.ndarray) -> np.ndarray:
        """WINDOW_SAMPLES int16 samples -> FEATURE_COUNT float32, frame-major."""
        samples = np.asarray(samples, dtype=np.int16)
        expected = NUM_FRAMES * FRAME_HOP + FRAME_LEN - FRAME_HOP
        if samples.shape[0] < expected:
            raise ValueError(
                f"need at least {expected} samples, got {samples.shape[0]}"
            )

        out = np.empty((NUM_FRAMES, MEL_BANDS), dtype=np.float32)
        for f in range(NUM_FRAMES):
            offset = f * FRAME_HOP
            out[f] = self.frame(samples[offset : offset + FRAME_LEN])
        return out.reshape(-1)


def quantize_int8(values, scale, zero_point) -> np.ndarray:
    """Bit-exact mirror of voice_features.c:voice_quantize_int8."""
    if not scale > 0.0:
        raise ValueError("scale must be positive")

    scaled = np.asarray(values, dtype=np.float32) / _F32(scale)
    pos = scaled >= _F32(0.0)
    rounded = np.where(
        pos,
        np.floor(scaled + _F32(0.5)),
        np.ceil(scaled - _F32(0.5)),
    )
    q = rounded.astype(np.int64) + int(zero_point)
    return np.clip(q, -128, 127).astype(np.int8)


def deterministic_pcm(count: int, seed: int = 0x5A17C0DE) -> np.ndarray:
    """Mirror of the C host test's LCG, so both sides analyse identical audio.

    The C side does (int16_t)(state >> 16), which reinterprets the low 16 bits
    as two's complement. Building the array as uint16 and viewing it as int16
    reproduces that exactly, and avoids numpy's out-of-bound conversion error.
    """
    state = seed & 0xFFFFFFFF
    raw = np.empty(count, dtype=np.uint16)
    for i in range(count):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        raw[i] = (state >> 16) & 0xFFFF
    return raw.view(np.int16)
