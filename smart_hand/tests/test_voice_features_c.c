#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "voice_features.h"

/*
 * Host-side checks for the Titan log-Mel front end.
 *
 * Beyond the self-contained assertions below, this program prints the full
 * feature map and its int8 quantisation so that
 * tests/test_voice_features.py can prove the C and Python implementations
 * agree. Keep the PRINT_ blocks in sync with that parser.
 */

static voice_frontend_t g_frontend;
static int16_t g_pcm[VOICE_WINDOW_SAMPLES];
static float g_logmel[VOICE_FEATURE_COUNT];
static int8_t g_quantized[VOICE_FEATURE_COUNT];

static const float kQuantScale = 0.0625f;
static const int32_t kQuantZeroPoint = 37;

static uint32_t next_random(uint32_t *state)
{
    *state = (*state) * 1664525U + 1013904223U;
    return *state;
}

static void fill_deterministic_pcm(int16_t *pcm, uint32_t count, uint32_t seed)
{
    uint32_t state = seed;
    uint32_t i;
    for (i = 0U; i < count; ++i)
    {
        pcm[i] = (int16_t)(next_random(&state) >> 16);
    }
}

static void fill_tone(int16_t *pcm, uint32_t count, float hz, float amplitude)
{
    uint32_t i;
    for (i = 0U; i < count; ++i)
    {
        float phase = (2.0f * 3.14159265358979323846f * hz * (float)i) /
                      (float)VOICE_SAMPLE_RATE_HZ;
        pcm[i] = (int16_t)(amplitude * sinf(phase));
    }
}

static uint32_t argmax_band(const float *frame)
{
    uint32_t best = 0U;
    uint32_t i;
    for (i = 1U; i < VOICE_MEL_BANDS; ++i)
    {
        if (frame[i] > frame[best])
        {
            best = i;
        }
    }
    return best;
}

static void test_config_contract(void)
{
    assert(VOICE_FRAME_LEN == 400U);
    assert(VOICE_FRAME_HOP == 160U);
    assert(VOICE_WINDOW_SAMPLES == 16000U);
    assert(VOICE_NUM_FRAMES == 98U);
    assert(VOICE_FFT_SIZE == 512U);
    assert(VOICE_MEL_BANDS == 40U);
    assert(VOICE_FEATURE_COUNT == 3920U);
    assert(VOICE_MEL_BIN_COUNT == 257U);
}

static void test_silence_hits_log_floor(void)
{
    float expected = logf(VOICE_LOG_FLOOR);
    uint32_t i;
    float worst = 0.0f;

    memset(g_pcm, 0, sizeof(g_pcm));
    voice_frontend_window(&g_frontend, g_pcm, g_logmel);

    for (i = 0U; i < VOICE_FEATURE_COUNT; ++i)
    {
        float diff = fabsf(g_logmel[i] - expected);
        if (diff > worst)
        {
            worst = diff;
        }
    }
    /* Digital silence must land exactly on the floor, not on -inf or NaN. */
    assert(worst < 1.0e-4f);
}

static void test_tone_localises_in_mel(void)
{
    float frame[VOICE_MEL_BANDS];
    uint32_t band;

    fill_tone(g_pcm, VOICE_WINDOW_SAMPLES, 1000.0f, 10000.0f);
    voice_frontend_frame(&g_frontend, g_pcm, frame);

    band = argmax_band(frame);
    /*
     * 1000 Hz on the HTK mel scale sits near band 13 of 40 spanning
     * 20..7600 Hz. Allow a two-band neighbourhood for window smearing.
     */
    assert(band >= 12U);
    assert(band <= 15U);
}

static void test_quantisation_rounding(void)
{
    const float values[6] = {0.4f, 0.5f, -0.5f, 0.0f, 127.6f, -130.0f};
    int8_t out[6];

    voice_quantize_int8(values, 6U, 1.0f, 0, out);
    assert(out[0] == 0);   /* 0.4 -> 0 */
    assert(out[1] == 1);   /* 0.5 -> 1, half away from zero */
    assert(out[2] == -1);  /* -0.5 -> -1, half away from zero */
    assert(out[3] == 0);
    assert(out[4] == 127); /* clamped */
    assert(out[5] == -128);

    /* A non-positive scale must be rejected without writing. */
    out[0] = 42;
    voice_quantize_int8(values, 6U, 0.0f, 0, out);
    assert(out[0] == 42);
}

static void test_features_are_finite(void)
{
    uint32_t i;
    fill_deterministic_pcm(g_pcm, VOICE_WINDOW_SAMPLES, 0x5A17C0DEU);
    voice_frontend_window(&g_frontend, g_pcm, g_logmel);

    for (i = 0U; i < VOICE_FEATURE_COUNT; ++i)
    {
        assert(isfinite(g_logmel[i]));
    }
}

int main(void)
{
    voice_frontend_init(&g_frontend);
    assert(g_frontend.initialized == 1U);

    test_config_contract();
    test_silence_hits_log_floor();
    test_tone_localises_in_mel();
    test_quantisation_rounding();
    test_features_are_finite();

    /* The same deterministic signal the Python reference generates. */
    fill_deterministic_pcm(g_pcm, VOICE_WINDOW_SAMPLES, 0x5A17C0DEU);
    voice_frontend_window(&g_frontend, g_pcm, g_logmel);
    voice_quantize_int8(g_logmel, VOICE_FEATURE_COUNT, kQuantScale,
                        kQuantZeroPoint, g_quantized);

    printf("CONFIG %u %u %u %u %u %u\n", VOICE_SAMPLE_RATE_HZ,
           VOICE_FRAME_LEN, VOICE_FRAME_HOP, VOICE_NUM_FRAMES,
           VOICE_MEL_BANDS, VOICE_FEATURE_COUNT);
    printf("QUANT_SCALE %.9g %d\n", (double)kQuantScale,
           (int)kQuantZeroPoint);

    printf("LOGMEL %u\n", VOICE_FEATURE_COUNT);
    {
        uint32_t i;
        for (i = 0U; i < VOICE_FEATURE_COUNT; ++i)
        {
            printf("%.7g%c", (double)g_logmel[i],
                   (i + 1U == VOICE_FEATURE_COUNT) ? '\n' : ' ');
        }
    }

    printf("QUANT %u\n", VOICE_FEATURE_COUNT);
    {
        uint32_t i;
        for (i = 0U; i < VOICE_FEATURE_COUNT; ++i)
        {
            printf("%d%c", (int)g_quantized[i],
                   (i + 1U == VOICE_FEATURE_COUNT) ? '\n' : ' ');
        }
    }

    puts("C voice feature tests passed");
    return 0;
}
