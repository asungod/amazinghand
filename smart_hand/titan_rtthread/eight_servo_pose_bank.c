#include "eight_servo_pose_bank.h"

#include <string.h>

void eight_servo_pose_bank_init(eight_servo_pose_bank_t *bank)
{
    if (bank != NULL)
    {
        memset(bank, 0, sizeof(*bank));
        bank->profiles[0].action = GRIP_ACTION_CYLINDRICAL;
        bank->profiles[1].action = GRIP_ACTION_POWER;
        bank->profiles[2].action = GRIP_ACTION_PRECISION;
    }
}

static int targets_valid(
    const eight_servo_target_t targets[EIGHT_SERVO_COUNT])
{
    size_t index;
    size_t previous;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        if (targets[index].id < 1u || targets[index].id > 253u)
        {
            return 0;
        }
        for (previous = 0u; previous < index; ++previous)
        {
            if (targets[index].id == targets[previous].id)
            {
                return 0;
            }
        }
    }
    return 1;
}

eight_servo_pose_result_t eight_servo_pose_bank_resolve(
    const eight_servo_pose_bank_t *bank,
    const grip_decision_t *decision,
    eight_servo_target_t targets[EIGHT_SERVO_COUNT])
{
    const eight_servo_pose_profile_t *match = NULL;
    size_t index;
    if (bank == NULL || decision == NULL || targets == NULL)
    {
        return EIGHT_SERVO_POSE_INVALID_PROFILE;
    }
    if (decision->reason != GRIP_REASON_ACCEPTED ||
        decision->action == GRIP_ACTION_NONE)
    {
        return EIGHT_SERVO_POSE_NO_ACTION;
    }
    for (index = 0u; index < EIGHT_SERVO_POSE_PROFILE_COUNT; ++index)
    {
        if (bank->profiles[index].action == decision->action)
        {
            if (match != NULL)
            {
                return EIGHT_SERVO_POSE_INVALID_PROFILE;
            }
            match = &bank->profiles[index];
        }
    }
    if (match == NULL || !match->configured)
    {
        return EIGHT_SERVO_POSE_NOT_CONFIGURED;
    }
    if (!targets_valid(match->targets))
    {
        return EIGHT_SERVO_POSE_INVALID_PROFILE;
    }
    memcpy(targets, match->targets, sizeof(match->targets));
    return EIGHT_SERVO_POSE_OK;
}
