#include "voice_features.h"

#include <math.h>
#include <string.h>

#define VOICE_TWO_PI (6.28318530717958647692f)

static float voice_hz_to_mel(float hz)
{
    return VOICE_MEL_SCALE * logf(1.0f + (hz / VOICE_MEL_HZ_PER_MEL));
}

static float voice_mel_to_hz(float mel)
{
    return VOICE_MEL_HZ_PER_MEL * (expf(mel / VOICE_MEL_SCALE) - 1.0f);
}

/*
 * Iterative in-place radix-2 Cooley-Tukey FFT.
 * Twiddles are precomputed as exp(-j*2*pi*k/n) for k in [0, n/2).
 */
static void voice_fft(float *re,
                      float *im,
                      const float *twiddle_re,
                      const float *twiddle_im,
                      uint32_t n)
{
    uint32_t i;
    uint32_t j = 0U;
    uint32_t len;

    for (i = 1U; i < n; ++i)
    {
        uint32_t bit = n >> 1;
        while ((j & bit) != 0U)
        {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if (i < j)
        {
            float tr = re[i];
            float ti = im[i];
            re[i] = re[j];
            im[i] = im[j];
            re[j] = tr;
            im[j] = ti;
        }
    }

    for (len = 2U; len <= n; len <<= 1)
    {
        uint32_t half = len >> 1;
        uint32_t step = n / len;
        uint32_t base;
        for (base = 0U; base < n; base += len)
        {
            uint32_t k;
            for (k = 0U; k < half; ++k)
            {
                float wr = twiddle_re[k * step];
                float wi = twiddle_im[k * step];
                uint32_t a = base + k;
                uint32_t b = a + half;
                float tr = (re[b] * wr) - (im[b] * wi);
                float ti = (re[b] * wi) + (im[b] * wr);
                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] = re[a] + tr;
                im[a] = im[a] + ti;
            }
        }
    }
}

void voice_frontend_init(voice_frontend_t *frontend)
{
    uint32_t i;
    uint32_t band;
    float bin_points[VOICE_MEL_BANDS + 2U];
    float mel_low;
    float mel_high;

    if (frontend == NULL)
    {
        return;
    }

    memset(frontend, 0, sizeof(*frontend));

    /* Hann window, denominator (N-1) so the endpoints are exactly zero. */
    for (i = 0U; i < VOICE_FRAME_LEN; ++i)
    {
        float phase = (VOICE_TWO_PI * (float)i) / (float)(VOICE_FRAME_LEN - 1U);
        frontend->hann[i] = 0.5f - (0.5f * cosf(phase));
    }

    /* FFT twiddles, exp(-j*2*pi*k/N). */
    for (i = 0U; i < (VOICE_FFT_SIZE / 2U); ++i)
    {
        float phase = (VOICE_TWO_PI * (float)i) / (float)VOICE_FFT_SIZE;
        frontend->twiddle_re[i] = cosf(phase);
        frontend->twiddle_im[i] = -sinf(phase);
    }

    /*
     * Triangular mel filterbank. VOICE_MEL_BANDS + 2 points define the
     * left/centre/right edges of every band; band m uses points m, m+1, m+2.
     */
    mel_low = voice_hz_to_mel(VOICE_MEL_LOW_HZ);
    mel_high = voice_hz_to_mel(VOICE_MEL_HIGH_HZ);
    for (i = 0U; i < (VOICE_MEL_BANDS + 2U); ++i)
    {
        float mel =
            mel_low + ((mel_high - mel_low) * (float)i) / (float)(VOICE_MEL_BANDS + 1U);
        bin_points[i] = (voice_mel_to_hz(mel) * (float)VOICE_FFT_SIZE) /
                        (float)VOICE_SAMPLE_RATE_HZ;
    }

    for (band = 0U; band < VOICE_MEL_BANDS; ++band)
    {
        float left = bin_points[band];
        float centre = bin_points[band + 1U];
        float right = bin_points[band + 2U];
        uint32_t k;
        for (k = 0U; k < VOICE_MEL_BIN_COUNT; ++k)
        {
            float bin = (float)k;
            float weight = 0.0f;
            if ((bin >= left) && (bin <= centre) && (centre > left))
            {
                weight = (bin - left) / (centre - left);
            }
            else if ((bin > centre) && (bin <= right) && (right > centre))
            {
                weight = (right - bin) / (right - centre);
            }
            frontend->mel_weight[band][k] = weight;
        }
    }

    frontend->initialized = 1U;
}

void voice_frontend_frame(voice_frontend_t *frontend,
                          const int16_t *samples,
                          float *out_logmel)
{
    float mean = 0.0f;
    uint32_t i;
    uint32_t band;

    if ((frontend == NULL) || (samples == NULL) || (out_logmel == NULL) ||
        (frontend->initialized == 0U))
    {
        return;
    }

    /* Remove the frame mean so a PDM DC offset cannot dominate band 0. */
    for (i = 0U; i < VOICE_FRAME_LEN; ++i)
    {
        mean += (float)samples[i];
    }
    mean /= (float)VOICE_FRAME_LEN;

    memset(frontend->scratch_re, 0, sizeof(frontend->scratch_re));
    memset(frontend->scratch_im, 0, sizeof(frontend->scratch_im));

    for (i = 0U; i < VOICE_FRAME_LEN; ++i)
    {
        frontend->scratch_re[i] = ((float)samples[i] - mean) * frontend->hann[i];
    }

    voice_fft(frontend->scratch_re,
              frontend->scratch_im,
              frontend->twiddle_re,
              frontend->twiddle_im,
              VOICE_FFT_SIZE);

    for (band = 0U; band < VOICE_MEL_BANDS; ++band)
    {
        float acc = 0.0f;
        uint32_t k;
        for (k = 0U; k < VOICE_MEL_BIN_COUNT; ++k)
        {
            float weight = frontend->mel_weight[band][k];
            if (weight != 0.0f)
            {
                float re = frontend->scratch_re[k];
                float im = frontend->scratch_im[k];
                acc += ((re * re) + (im * im)) * weight;
            }
        }
        if (acc < VOICE_LOG_FLOOR)
        {
            acc = VOICE_LOG_FLOOR;
        }
        out_logmel[band] = logf(acc);
    }
}

void voice_frontend_window(voice_frontend_t *frontend,
                           const int16_t *samples,
                           float *out_logmel)
{
    uint32_t frame;

    if ((frontend == NULL) || (samples == NULL) || (out_logmel == NULL))
    {
        return;
    }

    for (frame = 0U; frame < VOICE_NUM_FRAMES; ++frame)
    {
        uint32_t offset = frame * VOICE_FRAME_HOP;
        voice_frontend_frame(frontend,
                             &samples[offset],
                             &out_logmel[frame * VOICE_MEL_BANDS]);
    }
}

void voice_quantize_int8(const float *values,
                         uint32_t count,
                         float scale,
                         int32_t zero_point,
                         int8_t *out_int8)
{
    uint32_t i;

    if ((values == NULL) || (out_int8 == NULL) || !(scale > 0.0f))
    {
        return;
    }

    for (i = 0U; i < count; ++i)
    {
        /*
         * One IEEE-754 single division, then half-away-from-zero rounding in
         * float32. The Python reference performs the identical sequence, so
         * the resulting integers are bit-exact rather than merely close.
         */
        float scaled = values[i] / scale;
        int32_t quantized;

        if (scaled >= 0.0f)
        {
            quantized = (int32_t)floorf(scaled + 0.5f);
        }
        else
        {
            quantized = (int32_t)ceilf(scaled - 0.5f);
        }

        quantized += zero_point;
        if (quantized > 127)
        {
            quantized = 127;
        }
        else if (quantized < -128)
        {
            quantized = -128;
        }
        out_int8[i] = (int8_t)quantized;
    }
}

float voice_features_max_abs_diff(const float *a,
                                  const float *b,
                                  uint32_t count)
{
    float worst = 0.0f;
    uint32_t i;

    if ((a == NULL) || (b == NULL))
    {
        return 0.0f;
    }

    for (i = 0U; i < count; ++i)
    {
        float diff = fabsf(a[i] - b[i]);
        if (diff > worst)
        {
            worst = diff;
        }
    }
    return worst;
}
