#include <stdio.h>

#include "titan_trust_runtime.h"

static grip_vision_payload_t make_payload(uint32_t x,
                                          uint32_t y,
                                          uint32_t width,
                                          uint32_t height,
                                          uint32_t confidence)
{
    grip_vision_payload_t payload;
    payload.class_id = 39U;
    payload.center_x = x;
    payload.center_y = y;
    payload.width = width;
    payload.height = height;
    payload.confidence = confidence;
    return payload;
}

int main(void)
{
    titan_trust_runtime_t runtime;
    titan_trust_result_t result;
    grip_vision_payload_t payload;
    uint32_t now_ms = 1000U;
    int index;

    titan_trust_runtime_init(&runtime);
    titan_trust_runtime_evaluate(&runtime, now_ms, &result);
    if (result.ready || result.classification != TITAN_TRUST_ANOMALOUS)
    {
        fprintf(stderr, "empty runtime did not fail closed\n");
        return 1;
    }

    for (index = 0; index < 8; ++index)
    {
        payload = make_payload((uint32_t)(32000 + index * 80),
                               (uint32_t)(30000 + index * 40),
                               12000U,
                               26000U,
                               90U);
        titan_trust_runtime_note_valid(&runtime, &payload, 0U, now_ms);
        now_ms += 500U;
    }
    titan_trust_runtime_evaluate(&runtime, now_ms - 450U, &result);
    if (!result.ready || result.classification != TITAN_TRUST_TRUSTED)
    {
        fprintf(stderr, "stable window was not trusted: %s\n",
                titan_trust_class_name(result.classification));
        return 1;
    }

    for (index = 0; index < 6; ++index)
    {
        titan_trust_runtime_note_invalid(&runtime);
        titan_trust_runtime_note_duplicate_or_old(&runtime);
    }
    titan_trust_runtime_evaluate(&runtime, now_ms + 1000U, &result);
    if (!result.ready || result.classification != TITAN_TRUST_ANOMALOUS)
    {
        fprintf(stderr, "fault-injected window was not anomalous: %s\n",
                titan_trust_class_name(result.classification));
        return 1;
    }

    puts("TITAN TRUST RUNTIME TEST PASSED");
    return 0;
}

