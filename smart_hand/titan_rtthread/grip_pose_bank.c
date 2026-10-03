#include "grip_pose_bank.h"

#include <string.h>

void grip_pose_bank_init(grip_pose_bank_t *bank)
{
    if (bank != NULL)
    {
        memset(bank, 0, sizeof(*bank));
        bank->profiles[0].action = GRIP_ACTION_CYLINDRICAL;
        bank->profiles[1].action = GRIP_ACTION_POWER;
        bank->profiles[2].action = GRIP_ACTION_PRECISION;
    }
}

grip_pose_result_t grip_pose_bank_resolve(
    const grip_pose_bank_t *bank,
    const grip_decision_t *decision,
    servo_gate_logical_target_t targets[SERVO_GATE_COUNT])
{
    const grip_pose_profile_t *match = NULL;
    size_t index;
    if (bank == NULL || decision == NULL || targets == NULL)
    {
        return GRIP_POSE_INVALID_PROFILE;
    }
    if (decision->reason != GRIP_REASON_ACCEPTED ||
        decision->action == GRIP_ACTION_NONE)
    {
        return GRIP_POSE_NO_ACTION;
    }
    for (index = 0u; index < GRIP_POSE_PROFILE_COUNT; ++index)
    {
        if (bank->profiles[index].action == decision->action)
        {
            if (match != NULL)
            {
                return GRIP_POSE_INVALID_PROFILE;
            }
            match = &bank->profiles[index];
        }
    }
    if (match == NULL || !match->configured)
    {
        return GRIP_POSE_NOT_CONFIGURED;
    }
    if (match->targets[0].id < 1u || match->targets[0].id > 253u ||
        match->targets[1].id < 1u || match->targets[1].id > 253u ||
        match->targets[0].id == match->targets[1].id)
    {
        return GRIP_POSE_INVALID_PROFILE;
    }
    targets[0] = match->targets[0];
    targets[1] = match->targets[1];
    return GRIP_POSE_OK;
}
