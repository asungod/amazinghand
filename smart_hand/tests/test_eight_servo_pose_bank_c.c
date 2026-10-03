#include "eight_servo_pose_bank.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    eight_servo_pose_bank_t bank;
    eight_servo_target_t targets[EIGHT_SERVO_COUNT];
    grip_decision_t decision;
    size_t index;

    eight_servo_pose_bank_init(&bank);
    decision.action = GRIP_ACTION_CYLINDRICAL;
    decision.reason = GRIP_REASON_ACCEPTED;
    decision.class_id = 39u;
    assert(eight_servo_pose_bank_resolve(&bank, &decision, targets) ==
           EIGHT_SERVO_POSE_NOT_CONFIGURED);

    bank.profiles[0].configured = 1u;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        bank.profiles[0].targets[index].id = (uint8_t)(index + 1u);
        bank.profiles[0].targets[index].offset_from_center =
            (int16_t)(10 + index);
    }
    assert(eight_servo_pose_bank_resolve(&bank, &decision, targets) ==
           EIGHT_SERVO_POSE_OK);
    assert(targets[0].id == 1u && targets[7].id == 8u);

    bank.profiles[0].targets[7].id = 1u;
    assert(eight_servo_pose_bank_resolve(&bank, &decision, targets) ==
           EIGHT_SERVO_POSE_INVALID_PROFILE);

    decision.reason = GRIP_REASON_LOW_CONFIDENCE;
    assert(eight_servo_pose_bank_resolve(&bank, &decision, targets) ==
           EIGHT_SERVO_POSE_NO_ACTION);

    puts("Eight-servo pose bank tests passed");
    return 0;
}
