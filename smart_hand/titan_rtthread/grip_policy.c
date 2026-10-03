#include "grip_policy.h"

#include <stddef.h>

#define VISION_MAX_VALUE 0xFFFFu
#define COCO_BOTTLE 39u
#define COCO_CUP 41u
#define COCO_REMOTE 65u

static grip_decision_t no_action(grip_reason_t reason, uint16_t class_id)
{
    grip_decision_t decision;
    decision.action = GRIP_ACTION_NONE;
    decision.reason = reason;
    decision.class_id = class_id;
    return decision;
}

grip_decision_t grip_policy_decide(const grip_vision_payload_t *payload,
                                   uint8_t minimum_confidence)
{
    grip_decision_t decision;
    if (minimum_confidence > 100u)
    {
        return no_action(GRIP_REASON_INVALID_CONFIGURATION, 0u);
    }
    if (payload == NULL || payload->class_id > VISION_MAX_VALUE ||
        payload->center_x > VISION_MAX_VALUE || payload->center_y > VISION_MAX_VALUE ||
        payload->width == 0u || payload->width > VISION_MAX_VALUE ||
        payload->height == 0u || payload->height > VISION_MAX_VALUE ||
        payload->confidence > 100u)
    {
        return no_action(GRIP_REASON_INVALID_PAYLOAD, 0u);
    }
    if (payload->confidence < minimum_confidence)
    {
        return no_action(GRIP_REASON_LOW_CONFIDENCE, (uint16_t)payload->class_id);
    }

    decision.reason = GRIP_REASON_ACCEPTED;
    decision.class_id = (uint16_t)payload->class_id;
    switch (payload->class_id)
    {
    case COCO_BOTTLE:
        decision.action = GRIP_ACTION_CYLINDRICAL;
        break;
    case COCO_CUP:
        decision.action = GRIP_ACTION_POWER;
        break;
    case COCO_REMOTE:
        decision.action = GRIP_ACTION_PRECISION;
        break;
    default:
        return no_action(GRIP_REASON_UNSUPPORTED_CLASS,
                         (uint16_t)payload->class_id);
    }
    return decision;
}

const char *grip_policy_action_name(grip_action_t action)
{
    switch (action)
    {
    case GRIP_ACTION_CYLINDRICAL:
        return "CYLINDRICAL_GRASP";
    case GRIP_ACTION_POWER:
        return "POWER_GRASP";
    case GRIP_ACTION_PRECISION:
        return "PRECISION_GRASP";
    case GRIP_ACTION_NONE:
    default:
        return "NO_ACTION";
    }
}

const char *grip_policy_reason_name(grip_reason_t reason)
{
    switch (reason)
    {
    case GRIP_REASON_ACCEPTED:
        return "accepted";
    case GRIP_REASON_INVALID_PAYLOAD:
        return "invalid_payload";
    case GRIP_REASON_INVALID_CONFIGURATION:
        return "invalid_configuration";
    case GRIP_REASON_LOW_CONFIDENCE:
        return "low_confidence";
    case GRIP_REASON_UNSUPPORTED_CLASS:
        return "unsupported_class";
    default:
        return "unknown";
    }
}
