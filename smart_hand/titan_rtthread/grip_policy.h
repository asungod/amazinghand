#ifndef GRIP_POLICY_H
#define GRIP_POLICY_H

#include <stdint.h>

#define GRIP_POLICY_DEFAULT_MIN_CONFIDENCE 70u

typedef enum
{
    GRIP_ACTION_NONE = 0,
    GRIP_ACTION_CYLINDRICAL,
    GRIP_ACTION_POWER,
    GRIP_ACTION_PRECISION
} grip_action_t;

typedef enum
{
    GRIP_REASON_ACCEPTED = 0,
    GRIP_REASON_INVALID_PAYLOAD,
    GRIP_REASON_INVALID_CONFIGURATION,
    GRIP_REASON_LOW_CONFIDENCE,
    GRIP_REASON_UNSUPPORTED_CLASS
} grip_reason_t;

typedef struct
{
    uint32_t class_id;
    uint32_t center_x;
    uint32_t center_y;
    uint32_t width;
    uint32_t height;
    uint32_t confidence;
} grip_vision_payload_t;

typedef struct
{
    grip_action_t action;
    grip_reason_t reason;
    uint16_t class_id;
} grip_decision_t;

grip_decision_t grip_policy_decide(const grip_vision_payload_t *payload,
                                   uint8_t minimum_confidence);
const char *grip_policy_action_name(grip_action_t action);
const char *grip_policy_reason_name(grip_reason_t reason);

#endif
