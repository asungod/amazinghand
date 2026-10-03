"""TFLite-compatible int8 requantisation arithmetic.

The C inference engine in smart_hand/titan_rtthread/voice_kws.c must produce the
same numbers as the TFLite reference model. TFLite does not store its
requantisation multipliers in the flatbuffer -- it derives them at load time
from the per-tensor scales -- so the exporter has to reproduce that derivation
here and bake the results into the generated header.

Both functions below are line-for-line ports of the reference implementation:

  tensorflow/lite/kernels/internal/quantization_util.cc       QuantizeMultiplier
  tensorflow/lite/kernels/internal/common.h                   MultiplyByQuantizedMultiplier
  tensorflow/lite/kernels/internal/round.h                    RoundingDivideByPOT,
                                                              SaturatingRoundingDoublingHighMul

Keeping them here, in Python, means the arithmetic is testable without a
cross-compiler and the C side only has to implement the integer part.
"""

from __future__ import annotations

import math

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1


def _saturating_cast_int32(value: int) -> int:
    return max(INT32_MIN, min(INT32_MAX, value))


def quantize_multiplier(effective_scale: float) -> tuple[int, int]:
    """Return (quantized_multiplier, shift) for a positive effective scale.

    Mirrors tflite::QuantizeMultiplier. The returned multiplier is the Q0.31
    representation of the mantissa, and shift is chosen so that

        real_multiplier == multiplier * 2**-31 * 2**shift
    """
    if effective_scale <= 0.0:
        raise ValueError(f"effective_scale must be positive, got {effective_scale}")

    mantissa, shift = math.frexp(effective_scale)  # mantissa in [0.5, 1)
    quantized = int(round(mantissa * (1 << 31)))
    if quantized == (1 << 31):
        quantized //= 2
        shift += 1
    return quantized, shift


def rounding_divide_by_pot(x: int, exponent: int) -> int:
    """Mirrors tflite::RoundingDivideByPOT for a non-negative exponent."""
    if exponent == 0:
        return x
    mask = (1 << exponent) - 1
    remainder = x & mask
    threshold = (mask >> 1) + (1 if x < 0 else 0)
    return (x >> exponent) + (1 if remainder > threshold else 0)


def saturating_rounding_doubling_high_mul(a: int, b: int) -> int:
    """Mirrors tflite::SaturatingRoundingDoublingHighMul."""
    overflow = a == b and a == INT32_MIN
    a_64 = int(a)
    b_64 = int(b)
    ab_64 = a_64 * b_64
    nudge = 1 << 30 if ab_64 >= 0 else (1 - (1 << 30))
    ab_x2_high_64 = (ab_64 + nudge) // (1 << 31)
    if overflow:
        return INT32_MAX
    return _saturating_cast_int32(ab_x2_high_64)


def multiply_by_quantized_multiplier(x: int, multiplier: int, shift: int) -> int:
    """Mirrors tflite::MultiplyByQuantizedMultiplier."""
    left_shift = shift if shift > 0 else 0
    right_shift = 0 if shift > 0 else -shift
    return rounding_divide_by_pot(
        saturating_rounding_doubling_high_mul(x * (1 << left_shift), multiplier),
        right_shift,
    )


def requantize_accumulator(acc: int,
                           input_scale: float,
                           weight_scale: float,
                           output_scale: float) -> tuple[int, int]:
    """Return (multiplier, shift) for an int32 accumulator -> int8 conversion."""
    return quantize_multiplier((input_scale * weight_scale) / output_scale)


def rescale_accumulator(acc: int,
                        input_scale: float,
                        output_scale: float) -> tuple[int, int]:
    """Return (multiplier, shift) when only the activation scale changes.

    Used by pooling and by the bias add, where there is no weight scale.
    """
    return quantize_multiplier(input_scale / output_scale)
