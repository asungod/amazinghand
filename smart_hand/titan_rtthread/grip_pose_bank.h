#ifndef GRIP_POSE_BANK_H
#define GRIP_POSE_BANK_H

#include "grip_policy.h"
#include "servo_safety_gate.h"

#include <stdint.h>

#define GRIP_POSE_PROFILE_COUNT 3u

typedef struct
{
    grip_action_t action;
    uint8_t configured;
    servo_gate_logical_target_t targets[SERVO_GATE_COUNT];
} grip_pose_profile_t;

typedef struct
{
    grip_pose_profile_t profiles[GRIP_POSE_PROFILE_COUNT];
} grip_pose_bank_t;

typedef enum
{
    GRIP_POSE_OK = 0,
    GRIP_POSE_NO_ACTION,
    GRIP_POSE_NOT_CONFIGURED,
    GRIP_POSE_INVALID_PROFILE
} grip_pose_result_t;

void grip_pose_bank_init(grip_pose_bank_t *bank);
grip_pose_result_t grip_pose_bank_resolve(
    const grip_pose_bank_t *bank,
    const grip_decision_t *decision,
    servo_gate_logical_target_t targets[SERVO_GATE_COUNT]);

#endif
