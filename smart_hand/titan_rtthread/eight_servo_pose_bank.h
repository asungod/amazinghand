#ifndef EIGHT_SERVO_POSE_BANK_H
#define EIGHT_SERVO_POSE_BANK_H

#include "eight_servo_safety_gate.h"
#include "grip_policy.h"

#include <stdint.h>

#define EIGHT_SERVO_POSE_PROFILE_COUNT 3u

typedef struct
{
    grip_action_t action;
    uint8_t configured;
    eight_servo_target_t targets[EIGHT_SERVO_COUNT];
} eight_servo_pose_profile_t;

typedef struct
{
    eight_servo_pose_profile_t profiles[EIGHT_SERVO_POSE_PROFILE_COUNT];
} eight_servo_pose_bank_t;

typedef enum
{
    EIGHT_SERVO_POSE_OK = 0,
    EIGHT_SERVO_POSE_NO_ACTION,
    EIGHT_SERVO_POSE_NOT_CONFIGURED,
    EIGHT_SERVO_POSE_INVALID_PROFILE
} eight_servo_pose_result_t;

void eight_servo_pose_bank_init(eight_servo_pose_bank_t *bank);
eight_servo_pose_result_t eight_servo_pose_bank_resolve(
    const eight_servo_pose_bank_t *bank,
    const grip_decision_t *decision,
    eight_servo_target_t targets[EIGHT_SERVO_COUNT]);

#endif
