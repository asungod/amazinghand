#ifndef SMART_HAND_VOICE_FEATURES_H
#define SMART_HAND_VOICE_FEATURES_H

#include "voice_config.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host-testable log-Mel front end for Titan keyword spotting.
 * No RT-Thread, UART, GPIO, filesystem, or heap: every buffer is caller-owned
 * and the module keeps no global state.
 *
 * Numeric contract, in order. smart_hand/titan_ai/voice/voice_features_ref.py
 * reproduces these exact steps, and tests/test_voice_features.py asserts that
 * the two implementations agree.
 *
 *   1. int16 mono PCM at VOICE_SAMPLE_RATE_HZ.
 *   2. Per 25 ms frame: remove the frame mean, apply a Hann window, zero-pad
 *      to VOICE_FFT_SIZE, forward FFT in float32.
 *   3. Power spectrum re^2 + im^2 over VOICE_MEL_BIN_COUNT bins.
 *   4. VOICE_MEL_BANDS triangular filters on the HTK mel scale, spanning
 *      VOICE_MEL_LOW_HZ .. VOICE_MEL_HIGH_HZ.
 *   5. natural log of max(band_energy, VOICE_LOG_FLOOR).
 *   6. affine int8 quantisation with a calibration-supplied scale and zero
 *      point. Steps 2-5 are float32 and are expected to agree within a small
 *      tolerance; step 6 is integer and MUST be bit-exact.
 */

#define VOICE_MEL_BIN_COUNT (VOICE_FFT_SIZE / 2U + 1U)

typedef struct
{
    float hann[VOICE_FRAME_LEN];
    float twiddle_re[VOICE_FFT_SIZE / 2U];
    float twiddle_im[VOICE_FFT_SIZE / 2U];
    float mel_weight[VOICE_MEL_BANDS][VOICE_MEL_BIN_COUNT];
    float scratch_re[VOICE_FFT_SIZE];
    float scratch_im[VOICE_FFT_SIZE];
    uint8_t initialized;
} voice_frontend_t;

/*
 * Builds the Hann window, FFT twiddles, and mel filterbank.
 * Deterministic, allocation-free; safe to call once at start-up.
 */
void voice_frontend_init(voice_frontend_t *frontend);

/*
 * One 25 ms frame.
 *   samples    : VOICE_FRAME_LEN int16 samples
 *   out_logmel : VOICE_MEL_BANDS floats, overwritten
 */
void voice_frontend_frame(voice_frontend_t *frontend,
                          const int16_t *samples,
                          float *out_logmel);

/*
 * The full sliding map over a 1.0 s window.
 *   samples    : VOICE_WINDOW_SAMPLES int16 samples
 *   out_logmel : VOICE_FEATURE_COUNT floats, frame-major
 */
void voice_frontend_window(voice_frontend_t *frontend,
                           const int16_t *samples,
                           float *out_logmel);

/*
 * Integer affine quantisation to int8. Bit-exact between C and the Python
 * reference, because both perform one IEEE-754 single-precision division
 * followed by floor/ceil based half-away-from-zero rounding.
 *
 *   q = clamp(round_half_away_from_zero(value / scale) + zero_point, -128, 127)
 *
 * A scale of zero or negative is rejected and leaves out_int8 untouched.
 */
void voice_quantize_int8(const float *values,
                         uint32_t count,
                         float scale,
                         int32_t zero_point,
                         int8_t *out_int8);

/* Test helper: largest absolute difference between two vectors. */
float voice_features_max_abs_diff(const float *a,
                                  const float *b,
                                  uint32_t count);

#ifdef __cplusplus
}
#endif

#endif
