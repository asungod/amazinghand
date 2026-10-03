#include "voice_kws.h"

#include "voice_features.h"

#include <math.h>
#include <string.h>

/*
 * Layer indices are fixed by the topology the exporter validates:
 *   0 conv2d 3x3 s2 SAME     6 avgpool 2x2 s2 VALID
 *   1 dwconv 3x3 s1 SAME     7 fully_connected
 *   2 conv2d 1x1
 *   3 avgpool 2x2 s2 VALID
 *   4 dwconv 3x3 s1 SAME
 *   5 conv2d 1x1
 */

/* --- TFLite integer arithmetic ------------------------------------------- */

static int32_t voice_rounding_divide_by_pot(int32_t x, int exponent)
{
    int32_t mask;
    int32_t remainder;
    int32_t threshold;
    if (exponent == 0)
    {
        return x;
    }
    mask = (int32_t)((1u << exponent) - 1u);
    remainder = x & mask;
    threshold = (mask >> 1) + ((x < 0) ? 1 : 0);
    return (x >> exponent) + ((remainder > threshold) ? 1 : 0);
}

static int32_t voice_saturating_rounding_doubling_high_mul(int32_t a, int32_t b)
{
    int overflow = (a == b) && (a == INT32_MIN);
    int64_t ab = (int64_t)a * (int64_t)b;
    int64_t nudge = (ab >= 0) ? (int64_t)1 << 30 : (1 - ((int64_t)1 << 30));
    int64_t high = (ab + nudge) / ((int64_t)1 << 31);
    if (overflow)
    {
        return INT32_MAX;
    }
    if (high > INT32_MAX)
    {
        return INT32_MAX;
    }
    if (high < INT32_MIN)
    {
        return INT32_MIN;
    }
    return (int32_t)high;
}

static int32_t voice_multiply_by_quantized_multiplier(int32_t x,
                                                      int32_t multiplier,
                                                      int shift)
{
    int left_shift = (shift > 0) ? shift : 0;
    int right_shift = (shift > 0) ? 0 : -shift;
    int32_t scaled = x * (int32_t)(1u << left_shift);
    return voice_rounding_divide_by_pot(
        voice_saturating_rounding_doubling_high_mul(scaled, multiplier),
        right_shift);
}

static int8_t voice_clamp_int8(int32_t value, int32_t minimum)
{
    if (value > 127)
    {
        return (int8_t)127;
    }
    if (value < minimum)
    {
        return (int8_t)minimum;
    }
    return (int8_t)value;
}

/* --- SAME padding geometry ----------------------------------------------- */

static int voice_same_pad_before(uint32_t input, uint32_t kernel, uint32_t stride)
{
    uint32_t output = (input + stride - 1u) / stride;
    uint32_t needed = ((output - 1u) * stride) + kernel;
    uint32_t total = (needed > input) ? (needed - input) : 0u;
    return (int)(total / 2u);
}

/* --- operators ------------------------------------------------------------ */

static void voice_conv2d(const int8_t *input,
                         const int8_t *weights,
                         const int32_t *bias,
                         const int32_t *multipliers,
                         const int8_t *shifts,
                         uint32_t in_h, uint32_t in_w, uint32_t in_c,
                         uint32_t out_h, uint32_t out_w, uint32_t out_c,
                         uint32_t kernel_h, uint32_t kernel_w,
                         uint32_t stride,
                         int32_t in_zero_point,
                         int32_t out_zero_point,
                         int relu,
                         int8_t *output)
{
    int pad_top = voice_same_pad_before(in_h, kernel_h, stride);
    int pad_left = voice_same_pad_before(in_w, kernel_w, stride);
    uint32_t oh;
    uint32_t ow;
    uint32_t oc;

    for (oh = 0u; oh < out_h; ++oh)
    {
        for (ow = 0u; ow < out_w; ++ow)
        {
            for (oc = 0u; oc < out_c; ++oc)
            {
                int32_t acc = bias[oc];
                uint32_t kh;
                for (kh = 0u; kh < kernel_h; ++kh)
                {
                    int ih = (int)(oh * stride) - pad_top + (int)kh;
                    uint32_t kw;
                    if ((ih < 0) || (ih >= (int)in_h))
                    {
                        continue;
                    }
                    for (kw = 0u; kw < kernel_w; ++kw)
                    {
                        int iw = (int)(ow * stride) - pad_left + (int)kw;
                        uint32_t ic;
                        if ((iw < 0) || (iw >= (int)in_w))
                        {
                            continue;
                        }
                        for (ic = 0u; ic < in_c; ++ic)
                        {
                            int32_t x = input[(((uint32_t)ih * in_w) + (uint32_t)iw) * in_c + ic];
                            int32_t w =
                                weights[((oc * kernel_h + kh) * kernel_w + kw) * in_c + ic];
                            /* TFLite accumulates (input - input_zero_point). */
                            acc += (x - in_zero_point) * w;
                        }
                    }
                }
                acc = voice_multiply_by_quantized_multiplier(acc, multipliers[oc], shifts[oc]);
                acc += out_zero_point;
                output[((oh * out_w) + ow) * out_c + oc] =
                    voice_clamp_int8(acc, relu ? out_zero_point : -128);
            }
        }
    }
}

static void voice_depthwise_conv2d(const int8_t *input,
                                   const int8_t *weights,
                                   const int32_t *bias,
                                   const int32_t *multipliers,
                                   const int8_t *shifts,
                                   uint32_t in_h, uint32_t in_w, uint32_t channels,
                                   uint32_t kernel_h, uint32_t kernel_w,
                                   int32_t in_zero_point,
                                   int32_t out_zero_point,
                                   int relu,
                                   int8_t *output)
{
    int pad_top = voice_same_pad_before(in_h, kernel_h, 1u);
    int pad_left = voice_same_pad_before(in_w, kernel_w, 1u);
    uint32_t oh;
    uint32_t ow;
    uint32_t c;

    for (oh = 0u; oh < in_h; ++oh)
    {
        for (ow = 0u; ow < in_w; ++ow)
        {
            for (c = 0u; c < channels; ++c)
            {
                int32_t acc = bias[c];
                uint32_t kh;
                for (kh = 0u; kh < kernel_h; ++kh)
                {
                    int ih = (int)oh - pad_top + (int)kh;
                    uint32_t kw;
                    if ((ih < 0) || (ih >= (int)in_h))
                    {
                        continue;
                    }
                    for (kw = 0u; kw < kernel_w; ++kw)
                    {
                        int iw = (int)ow - pad_left + (int)kw;
                        if ((iw < 0) || (iw >= (int)in_w))
                        {
                            continue;
                        }
                        /* TFLite depthwise weights are [1][kH][kW][channels]. */
                        acc += (input[(((uint32_t)ih * in_w) + (uint32_t)iw) * channels + c] -
                                in_zero_point) *
                               weights[((kh * kernel_w) + kw) * channels + c];
                    }
                }
                acc = voice_multiply_by_quantized_multiplier(acc, multipliers[c], shifts[c]);
                acc += out_zero_point;
                output[((oh * in_w) + ow) * channels + c] =
                    voice_clamp_int8(acc, relu ? out_zero_point : -128);
            }
        }
    }
}

/*
 * Rounded integer mean, matching TFLite's int8 AveragePool. The exported model
 * gives both pooling layers identical input/output scales and zero points, so
 * the zero point cancels and no rescale is required -- voice_model_data.h is
 * asserted for that in tests/test_voice_kws.py.
 */
static void voice_avgpool2x2_valid(const int8_t *input,
                                   uint32_t in_h, uint32_t in_w, uint32_t channels,
                                   int8_t *output)
{
    uint32_t out_h = in_h / 2u;
    uint32_t out_w = in_w / 2u;
    uint32_t oh;
    uint32_t ow;
    uint32_t c;
    const int32_t count = 4;

    for (oh = 0u; oh < out_h; ++oh)
    {
        for (ow = 0u; ow < out_w; ++ow)
        {
            for (c = 0u; c < channels; ++c)
            {
                int32_t acc = 0;
                uint32_t dy;
                for (dy = 0u; dy < 2u; ++dy)
                {
                    uint32_t dx;
                    for (dx = 0u; dx < 2u; ++dx)
                    {
                        acc += input[((((oh * 2u) + dy) * in_w) + ((ow * 2u) + dx)) * channels + c];
                    }
                }
                acc = (acc > 0) ? ((acc + (count / 2)) / count)
                                : ((acc - (count / 2)) / count);
                if (acc > 127)
                {
                    acc = 127;
                }
                if (acc < -128)
                {
                    acc = -128;
                }
                output[((oh * out_w) + ow) * channels + c] = (int8_t)acc;
            }
        }
    }
}

static void voice_fully_connected(const int8_t *input,
                                  const int8_t *weights,
                                  const int32_t *bias,
                                  const int32_t *multipliers,
                                  const int8_t *shifts,
                                  uint32_t in_count,
                                  uint32_t out_count,
                                  int32_t in_zero_point,
                                  int32_t out_zero_point,
                                  int8_t *output)
{
    uint32_t oc;
    for (oc = 0u; oc < out_count; ++oc)
    {
        int32_t acc = bias[oc];
        uint32_t i;
        for (i = 0u; i < in_count; ++i)
        {
            acc += (input[i] - in_zero_point) * weights[(oc * in_count) + i];
        }
        acc = voice_multiply_by_quantized_multiplier(acc, multipliers[oc], shifts[oc]);
        acc += out_zero_point;
        output[oc] = voice_clamp_int8(acc, -128);
    }
}

/* --- public API ----------------------------------------------------------- */

void voice_kws_init(voice_kws_t *kws)
{
    if (kws == NULL)
    {
        return;
    }
    memset(kws, 0, sizeof(*kws));
    kws->initialized = 1u;
}

/*
 * Output element count per layer index. Table-driven on purpose: an earlier
 * revision derived this from a chain of comparisons on stop_after and got
 * layers 4, 5 and 6 wrong (it reported the 31360-element layer-0 size for
 * layers 4 and 5, and the 7680-element layer-3 size for layer 6). Those
 * wrong counts made voice_kws_run_until() return -1 against an exactly-sized
 * buffer, i.e. a false failure, and nothing caught it because no test called
 * the function. Sizes come straight from the generated header.
 */
static const uint32_t kVoiceLayerOutCount[VOICE_MODEL_LAYER_COUNT] = {
    VOICE_MODEL_L0_OUT_COUNT,
    VOICE_MODEL_L1_OUT_COUNT,
    VOICE_MODEL_L2_OUT_COUNT,
    VOICE_MODEL_L3_OUT_COUNT,
    VOICE_MODEL_L4_OUT_COUNT,
    VOICE_MODEL_L5_OUT_COUNT,
    VOICE_MODEL_L6_OUT_COUNT,
    VOICE_MODEL_L7_OUT_COUNT,
};

/*
 * Layer chain. stop_after == UINT32_MAX runs the whole network; any lower
 * value halts after that layer index and leaves the result in *out_used so a
 * host test can diff one layer at a time against the TFLite reference.
 */
static int voice_kws_chain(voice_kws_t *kws,
                           const int8_t *features,
                           uint32_t stop_after,
                           const int8_t **out_used)
{
    /* 0: 3x3 stride-2 conv over the full 98x40 log-Mel map */
    voice_conv2d(features,
                 g_voice_model_t0_w, g_voice_model_t0_b,
                 g_voice_model_t0_mult, g_voice_model_t0_shift,
                 VOICE_MODEL_L0_IN_H, VOICE_MODEL_L0_IN_W, VOICE_MODEL_L0_IN_C,
                 VOICE_MODEL_L0_OUT_H, VOICE_MODEL_L0_OUT_W, VOICE_MODEL_L0_OUT_C,
                 VOICE_MODEL_L0_KERNEL_H, VOICE_MODEL_L0_KERNEL_W, 2u,
                 VOICE_MODEL_L0_IN_ZP, VOICE_MODEL_L0_OUT_ZP, 1, kws->stage_a);
    if (stop_after < 1u) { *out_used = kws->stage_a; return 0; }

    voice_depthwise_conv2d(kws->stage_a,
                           g_voice_model_t1_w, g_voice_model_t1_b,
                           g_voice_model_t1_mult, g_voice_model_t1_shift,
                           VOICE_MODEL_L1_IN_H, VOICE_MODEL_L1_IN_W, VOICE_MODEL_L1_IN_C,
                           VOICE_MODEL_L1_KERNEL_H, VOICE_MODEL_L1_KERNEL_W,
                           VOICE_MODEL_L1_IN_ZP, VOICE_MODEL_L1_OUT_ZP, 1, kws->stage_b);
    if (stop_after < 2u) { *out_used = kws->stage_b; return 0; }

    voice_conv2d(kws->stage_b,
                 g_voice_model_t2_w, g_voice_model_t2_b,
                 g_voice_model_t2_mult, g_voice_model_t2_shift,
                 VOICE_MODEL_L2_IN_H, VOICE_MODEL_L2_IN_W, VOICE_MODEL_L2_IN_C,
                 VOICE_MODEL_L2_OUT_H, VOICE_MODEL_L2_OUT_W, VOICE_MODEL_L2_OUT_C,
                 VOICE_MODEL_L2_KERNEL_H, VOICE_MODEL_L2_KERNEL_W, 1u,
                 VOICE_MODEL_L2_IN_ZP, VOICE_MODEL_L2_OUT_ZP, 1, kws->stage_a);
    if (stop_after < 3u) { *out_used = kws->stage_a; return 0; }

    voice_avgpool2x2_valid(kws->stage_a,
                           VOICE_MODEL_L3_IN_H, VOICE_MODEL_L3_IN_W, VOICE_MODEL_L3_IN_C,
                           kws->stage_b);
    if (stop_after < 4u) { *out_used = kws->stage_b; return 0; }

    voice_depthwise_conv2d(kws->stage_b,
                           g_voice_model_t4_w, g_voice_model_t4_b,
                           g_voice_model_t4_mult, g_voice_model_t4_shift,
                           VOICE_MODEL_L4_IN_H, VOICE_MODEL_L4_IN_W, VOICE_MODEL_L4_IN_C,
                           VOICE_MODEL_L4_KERNEL_H, VOICE_MODEL_L4_KERNEL_W,
                           VOICE_MODEL_L4_IN_ZP, VOICE_MODEL_L4_OUT_ZP, 1, kws->stage_a);
    if (stop_after < 5u) { *out_used = kws->stage_a; return 0; }

    voice_conv2d(kws->stage_a,
                 g_voice_model_t5_w, g_voice_model_t5_b,
                 g_voice_model_t5_mult, g_voice_model_t5_shift,
                 VOICE_MODEL_L5_IN_H, VOICE_MODEL_L5_IN_W, VOICE_MODEL_L5_IN_C,
                 VOICE_MODEL_L5_OUT_H, VOICE_MODEL_L5_OUT_W, VOICE_MODEL_L5_OUT_C,
                 VOICE_MODEL_L5_KERNEL_H, VOICE_MODEL_L5_KERNEL_W, 1u,
                 VOICE_MODEL_L5_IN_ZP, VOICE_MODEL_L5_OUT_ZP, 1, kws->stage_b);
    if (stop_after < 6u) { *out_used = kws->stage_b; return 0; }

    voice_avgpool2x2_valid(kws->stage_b,
                           VOICE_MODEL_L6_IN_H, VOICE_MODEL_L6_IN_W, VOICE_MODEL_L6_IN_C,
                           kws->stage_a);
    if (stop_after < 7u) { *out_used = kws->stage_a; return 0; }

    voice_fully_connected(kws->stage_a,
                          g_voice_model_t7_w, g_voice_model_t7_b,
                          g_voice_model_t7_mult, g_voice_model_t7_shift,
                          VOICE_MODEL_L7_IN_CHANNELS, VOICE_MODEL_L7_OUT_CHANNELS,
                          VOICE_MODEL_L7_IN_ZP, VOICE_MODEL_L7_OUT_ZP, kws->logits);

    *out_used = kws->logits;
    return 0;
}

int voice_kws_run(voice_kws_t *kws, const int8_t *features)
{
    const int8_t *unused = NULL;
    if ((kws == NULL) || (features == NULL) || (kws->initialized == 0u))
    {
        return -1;
    }
    return voice_kws_chain(kws, features, UINT32_MAX, &unused);
}

int voice_kws_run_until(voice_kws_t *kws,
                        const int8_t *features,
                        uint32_t stop_after,
                        int8_t *out,
                        uint32_t capacity)
{
    const int8_t *used = NULL;
    uint32_t count;
    if ((kws == NULL) || (features == NULL) || (out == NULL) ||
        (kws->initialized == 0u))
    {
        return -1;
    }
    if (voice_kws_chain(kws, features, stop_after, &used) != 0)
    {
        return -1;
    }
    if (stop_after >= (uint32_t)VOICE_MODEL_LAYER_COUNT)
    {
        return -1;
    }
    count = kVoiceLayerOutCount[stop_after];
    if (count > capacity)
    {
        return -1;
    }
    memcpy(out, used, count);
    return (int)count;
}

int voice_kws_argmax(const int8_t *logits)
{
    int best = 0;
    int i;
    if (logits == NULL)
    {
        return -1;
    }
    for (i = 1; i < (int)VOICE_MODEL_CLASS_COUNT; ++i)
    {
        if (logits[i] > logits[best])
        {
            best = i;
        }
    }
    return best;
}

void voice_kws_probabilities(const int8_t *logits, float *out_probabilities)
{
    float max_logit;
    float total = 0.0f;
    int i;

    if ((logits == NULL) || (out_probabilities == NULL))
    {
        return;
    }

    /* TFLite's final tensor zero point is not -128, so dequantise first. */
    max_logit = ((float)logits[0] - (float)VOICE_MODEL_L7_OUT_ZP) *
                VOICE_MODEL_L7_OUT_SCALE;
    for (i = 1; i < (int)VOICE_MODEL_CLASS_COUNT; ++i)
    {
        float value = ((float)logits[i] - (float)VOICE_MODEL_L7_OUT_ZP) *
                      VOICE_MODEL_L7_OUT_SCALE;
        if (value > max_logit)
        {
            max_logit = value;
        }
    }

    for (i = 0; i < (int)VOICE_MODEL_CLASS_COUNT; ++i)
    {
        float value = ((float)logits[i] - (float)VOICE_MODEL_L7_OUT_ZP) *
                      VOICE_MODEL_L7_OUT_SCALE;
        float e = expf(value - max_logit);
        out_probabilities[i] = e;
        total += e;
    }
    if (total <= 0.0f)
    {
        total = 1.0f;
    }
    for (i = 0; i < (int)VOICE_MODEL_CLASS_COUNT; ++i)
    {
        out_probabilities[i] /= total;
    }
}

int voice_kws_predict(voice_kws_t *kws,
                      const float *logmel,
                      int *out_class,
                      float *out_confidence)
{
    int8_t features[VOICE_MODEL_INPUT_COUNT];
    float probabilities[VOICE_MODEL_CLASS_COUNT];
    int best;

    if ((kws == NULL) || (logmel == NULL) || (out_class == NULL) ||
        (out_confidence == NULL))
    {
        return -1;
    }

    voice_quantize_int8(logmel, VOICE_MODEL_INPUT_COUNT,
                        VOICE_MODEL_L0_IN_SCALE, VOICE_MODEL_L0_IN_ZP, features);

    if (voice_kws_run(kws, features) != 0)
    {
        return -1;
    }

    voice_kws_probabilities(kws->logits, probabilities);
    best = voice_kws_argmax(kws->logits);
    *out_class = best;
    *out_confidence = (best >= 0) ? probabilities[best] : 0.0f;
    return 0;
}
