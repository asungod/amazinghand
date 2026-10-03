#include "titan_trust_runtime.h"

#include <stddef.h>
#include <string.h>

#define TITAN_TRUST_COORDINATE_FULL_SCALE 65535.0f

static float absolute_value(float value)
{
    return value < 0.0f ? -value : value;
}

static float clamp_percent(float value)
{
    if (value < 0.0f) return 0.0f;
    if (value > 100.0f) return 100.0f;
    return value;
}

static uint16_t saturating_increment(uint16_t value)
{
    return value == UINT16_MAX ? value : (uint16_t)(value + 1U);
}

void titan_trust_runtime_init(titan_trust_runtime_t *runtime)
{
    if (runtime == NULL) return;
    memset(runtime, 0, sizeof(*runtime));
    runtime->initialized = 1U;
}

void titan_trust_runtime_note_valid(
    titan_trust_runtime_t *runtime,
    const grip_vision_payload_t *payload,
    uint16_t forward_gap_delta,
    uint32_t now_ms)
{
    titan_trust_sample_t sample;

    if (runtime == NULL || payload == NULL || !runtime->initialized) return;
    memset(&sample, 0, sizeof(sample));
    sample.confidence_pct = (float)payload->confidence;
    sample.gap_delta = (float)forward_gap_delta;
    sample.invalid_delta = (float)runtime->pending_invalid_samples;
    sample.duplicate_old_delta =
        (float)runtime->pending_duplicate_old_samples;

    if (runtime->have_last)
    {
        float dx = absolute_value((float)payload->center_x -
                                  (float)runtime->last_payload.center_x);
        float dy = absolute_value((float)payload->center_y -
                                  (float)runtime->last_payload.center_y);
        uint64_t previous_area =
            (uint64_t)runtime->last_payload.width * runtime->last_payload.height;
        uint64_t current_area = (uint64_t)payload->width * payload->height;

        sample.motion_pct = clamp_percent(
            ((dx + dy) * 50.0f) / TITAN_TRUST_COORDINATE_FULL_SCALE);
        if (previous_area > 0U)
        {
            uint64_t area_delta = current_area > previous_area
                                      ? current_area - previous_area
                                      : previous_area - current_area;
            sample.scale_change_pct = clamp_percent(
                ((float)area_delta * 100.0f) / (float)previous_area);
        }
        sample.interval_ms = (float)(now_ms - runtime->last_valid_ms);
    }

    runtime->samples[runtime->write_index] = sample;
    runtime->write_index =
        (uint8_t)((runtime->write_index + 1U) % TITAN_TRUST_WINDOW_SIZE);
    runtime->valid_samples = saturating_increment(runtime->valid_samples);
    runtime->last_payload = *payload;
    runtime->last_valid_ms = now_ms;
    runtime->have_last = 1U;
    runtime->pending_invalid_samples = 0U;
    runtime->pending_duplicate_old_samples = 0U;
}

void titan_trust_runtime_note_invalid(titan_trust_runtime_t *runtime)
{
    if (runtime == NULL || !runtime->initialized) return;
    runtime->pending_invalid_samples =
        saturating_increment(runtime->pending_invalid_samples);
}

void titan_trust_runtime_note_duplicate_or_old(titan_trust_runtime_t *runtime)
{
    if (runtime == NULL || !runtime->initialized) return;
    runtime->pending_duplicate_old_samples =
        saturating_increment(runtime->pending_duplicate_old_samples);
}

void titan_trust_runtime_evaluate(
    const titan_trust_runtime_t *runtime,
    uint32_t now_ms,
    titan_trust_result_t *result)
{
    uint16_t sample_count;
    uint16_t index;
    uint32_t total_observations;
    float invalid_sum = 0.0f;
    float duplicate_old_sum = 0.0f;
    float interval_sum = 0.0f;
    float interval_count = 0.0f;
    float interval_average = 0.0f;

    if (result == NULL) return;
    memset(result, 0, sizeof(*result));
    result->classification = TITAN_TRUST_ANOMALOUS;

    if (runtime == NULL || !runtime->initialized || !runtime->have_last)
    {
        return;
    }

    sample_count = runtime->valid_samples < TITAN_TRUST_WINDOW_SIZE
                       ? runtime->valid_samples
                       : TITAN_TRUST_WINDOW_SIZE;
    if (sample_count < TITAN_TRUST_MIN_VALID_SAMPLES)
    {
        return;
    }

    for (index = 0; index < sample_count; ++index)
    {
        const titan_trust_sample_t *sample = &runtime->samples[index];
        result->features[0] += sample->confidence_pct;
        result->features[1] += sample->motion_pct;
        result->features[2] += sample->scale_change_pct;
        result->features[5] += sample->gap_delta;
        invalid_sum += sample->invalid_delta;
        duplicate_old_sum += sample->duplicate_old_delta;
        if (sample->interval_ms > 0.0f)
        {
            interval_sum += sample->interval_ms;
            interval_count += 1.0f;
        }
    }
    result->features[0] /= (float)sample_count;
    result->features[1] /= (float)sample_count;
    result->features[2] /= (float)sample_count;
    if (interval_count > 0.0f)
    {
        interval_average = interval_sum / interval_count;
        result->features[3] = interval_average;
        for (index = 0; index < sample_count; ++index)
        {
            float interval = runtime->samples[index].interval_ms;
            if (interval > 0.0f)
            {
                result->features[4] +=
                    absolute_value(interval - interval_average);
            }
        }
        result->features[4] /= interval_count;
    }

    result->features[6] = invalid_sum +
                          (float)runtime->pending_invalid_samples;
    result->features[7] = duplicate_old_sum +
                          (float)runtime->pending_duplicate_old_samples;
    result->features[8] = (float)(now_ms - runtime->last_valid_ms);
    total_observations = (uint32_t)sample_count +
                         (uint32_t)result->features[6] +
                         (uint32_t)result->features[7];
    if (total_observations > 0U)
    {
        result->features[9] =
            ((float)sample_count * 100.0f) /
            (float)total_observations;
    }

    result->classification =
        titan_trust_predict(result->features, result->logits);
    result->ready = 1U;
}
