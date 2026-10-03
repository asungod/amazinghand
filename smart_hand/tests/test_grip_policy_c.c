#include "grip_policy.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static grip_vision_payload_t payload(uint32_t class_id, uint32_t confidence)
{
    grip_vision_payload_t value = {class_id, 320u, 240u, 80u, 120u, confidence};
    return value;
}

int main(void)
{
    grip_vision_payload_t vision;
    grip_decision_t decision;

    vision = payload(39u, 90u);
    decision = grip_policy_decide(&vision, GRIP_POLICY_DEFAULT_MIN_CONFIDENCE);
    assert(decision.action == GRIP_ACTION_CYLINDRICAL);
    assert(strcmp(grip_policy_action_name(decision.action),
                  "CYLINDRICAL_GRASP") == 0);

    vision = payload(41u, 90u);
    assert(grip_policy_decide(&vision, 70u).action == GRIP_ACTION_POWER);
    vision = payload(65u, 90u);
    assert(grip_policy_decide(&vision, 70u).action == GRIP_ACTION_PRECISION);

    vision = payload(39u, 69u);
    decision = grip_policy_decide(&vision, 70u);
    assert(decision.action == GRIP_ACTION_NONE &&
           decision.reason == GRIP_REASON_LOW_CONFIDENCE);
    vision.confidence = 70u;
    assert(grip_policy_decide(&vision, 70u).action == GRIP_ACTION_CYLINDRICAL);

    vision = payload(47u, 99u);
    decision = grip_policy_decide(&vision, 70u);
    assert(decision.action == GRIP_ACTION_NONE &&
           decision.reason == GRIP_REASON_UNSUPPORTED_CLASS);

    vision = payload(39u, 90u);
    vision.width = 0u;
    assert(grip_policy_decide(&vision, 70u).reason == GRIP_REASON_INVALID_PAYLOAD);
    vision.width = 80u;
    vision.center_x = 65536u;
    assert(grip_policy_decide(&vision, 70u).reason == GRIP_REASON_INVALID_PAYLOAD);
    vision.center_x = 320u;
    vision.confidence = 101u;
    assert(grip_policy_decide(&vision, 70u).reason == GRIP_REASON_INVALID_PAYLOAD);
    assert(grip_policy_decide(NULL, 70u).reason == GRIP_REASON_INVALID_PAYLOAD);
    assert(grip_policy_decide(&vision, 101u).reason ==
           GRIP_REASON_INVALID_CONFIGURATION);

    assert(strcmp(grip_policy_reason_name(GRIP_REASON_ACCEPTED), "accepted") == 0);
    puts("Grip policy C tests passed");
    return 0;
}
