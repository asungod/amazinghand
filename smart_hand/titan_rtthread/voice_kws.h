#ifndef SMART_HAND_VOICE_KWS_H
#define SMART_HAND_VOICE_KWS_H

#include "voice_config.h"
#include "voice_model_data.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * int8 keyword-spotting inference for Titan, Cortex-M85 CPU.
 *
 * No RT-Thread, UART, GPIO, filesystem, or heap. All state lives in the
 * caller's voice_kws_t, so nothing here can allocate or block.
 *
 * Why not TFLM: ra/npu/tflite-micro/ is present in the firmware tree but is
 * C++ and is excluded from both build systems (ra/SConscript only globs
 * ethos-u-core-driver, and Debug/makefile has no C++ rules). Adding it would
 * mean restructuring a safety-frozen firmware. This engine implements exactly
 * the eight operators the exported model uses, and
 * smart_hand/tests/test_voice_kws.py checks it against the TFLite reference.
 *
 * The arithmetic mirrors TFLite's int8 reference kernels:
 *   - accumulate in int32, then requantise with a per-channel multiplier/shift
 *     pair baked into voice_model_data.h by the exporter
 *   - fused ReLU clamps to the output zero point
 *   - average pooling is a rounded integer mean, valid because the exported
 *     model gives its pooling layers matching input/output scales
 */

typedef struct
{
    int8_t stage_a[VOICE_MODEL_L0_OUT_COUNT];
    int8_t stage_b[VOICE_MODEL_L0_OUT_COUNT];
    int8_t logits[VOICE_MODEL_CLASS_COUNT];
    uint8_t initialized;
} voice_kws_t;

void voice_kws_init(voice_kws_t *kws);

/*
 * Run the network on VOICE_MODEL_INPUT_COUNT already-quantised features.
 * Returns 0 on success, -1 on a null argument or an uninitialised context.
 * kws->logits holds VOICE_MODEL_CLASS_COUNT int8 logits afterwards.
 */
int voice_kws_run(voice_kws_t *kws, const int8_t *features);

/*
 * Run layers 0..stop_after only and copy that layer's output to `out`.
 * Returns the element count written, or -1 on a bad argument or short buffer.
 *
 * This exists so tests/test_voice_kws.py can diff the engine against the
 * TFLite reference one layer at a time instead of only comparing final logits.
 * It is not part of the firmware's normal path.
 */
int voice_kws_run_until(voice_kws_t *kws,
                        const int8_t *features,
                        uint32_t stop_after,
                        int8_t *out,
                        uint32_t capacity);

/* Index of the highest logit. Ties resolve to the lowest index. */
int voice_kws_argmax(const int8_t *logits);

/*
 * Dequantise logits to probabilities.
 * Softmax is computed in float over CLASS_COUNT values; it is presentation
 * only and never feeds a control decision.
 */
void voice_kws_probabilities(const int8_t *logits, float *out_probabilities);

/*
 * End-to-end helper: float log-Mel (VOICE_FEATURE_COUNT values, as produced by
 * voice_frontend_window) -> int8 -> network -> probabilities.
 * Writes the winning class index and its probability.
 */
int voice_kws_predict(voice_kws_t *kws,
                      const float *logmel,
                      int *out_class,
                      float *out_confidence);

#ifdef __cplusplus
}
#endif

#endif
