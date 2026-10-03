#ifndef TITAN_TRUST_RUNTIME_H
#define TITAN_TRUST_RUNTIME_H

#include "grip_policy.h"
#include "titan_trust_model.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TITAN_TRUST_WINDOW_SIZE 8U
#define TITAN_TRUST_MIN_VALID_SAMPLES 3U

typedef struct
{
    float confidence_pct;
    float motion_pct;
    float scale_change_pct;
    float interval_ms;
    float gap_delta;
    float invalid_delta;
    float duplicate_old_delta;
} titan_trust_sample_t;

typedef struct
{
    titan_trust_sample_t samples[TITAN_TRUST_WINDOW_SIZE];
    grip_vision_payload_t last_payload;
    uint32_t last_valid_ms;
    uint16_t valid_samples;
    uint16_t pending_invalid_samples;
    uint16_t pending_duplicate_old_samples;
    uint8_t write_index;
    uint8_t have_last;
    uint8_t initialized;
} titan_trust_runtime_t;

typedef struct
{
    float features[TITAN_TRUST_FEATURE_COUNT];
    float logits[TITAN_TRUST_CLASS_COUNT];
    titan_trust_class_t classification;
    uint8_t ready;
} titan_trust_result_t;

void titan_trust_runtime_init(titan_trust_runtime_t *runtime);

void titan_trust_runtime_note_valid(
    titan_trust_runtime_t *runtime,
    const grip_vision_payload_t *payload,
    uint16_t forward_gap_delta,
    uint32_t now_ms);

void titan_trust_runtime_note_invalid(titan_trust_runtime_t *runtime);
void titan_trust_runtime_note_duplicate_or_old(titan_trust_runtime_t *runtime);

/* Advisory only. A non-ready window fails closed to ANOMALOUS. */
void titan_trust_runtime_evaluate(
    const titan_trust_runtime_t *runtime,
    uint32_t now_ms,
    titan_trust_result_t *result);

#ifdef __cplusplus
}
#endif

#endif
