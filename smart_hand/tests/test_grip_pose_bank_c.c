#include "grip_pose_bank.h"

#include <assert.h>
#include <stdio.h>

static const servo_gate_calibration_t calibration[SERVO_GATE_COUNT] = {
    {1u, 1, 511u, 300u, 700u, 20u, 60u},
    {2u, -1, 511u, 280u, 720u, 20u, 60u}};

int main(void)
{
    grip_pose_bank_t bank;
    grip_vision_payload_t vision = {39u, 320u, 240u, 80u, 120u, 90u};
    grip_decision_t decision;
    servo_gate_logical_target_t targets[SERVO_GATE_COUNT];
    servo_gate_observation_t observations[SERVO_GATE_COUNT] = {
        {1u, 511u, 60u, 25u, 1u, 5u},
        {2u, 511u, 60u, 25u, 1u, 5u}};
    servo_gate_raw_goal_t goals[SERVO_GATE_COUNT];
    servo_safety_gate_t gate;

    grip_pose_bank_init(&bank);
    decision = grip_policy_decide(&vision, 70u);
    assert(decision.action == GRIP_ACTION_CYLINDRICAL);
    assert(grip_pose_bank_resolve(&bank, &decision, targets) ==
           GRIP_POSE_NOT_CONFIGURED);

    /* Test-only values prove the boundary; production values remain unset
     * until the physical finger is calibrated. */
    bank.profiles[0].configured = 1u;
    bank.profiles[0].targets[0] = (servo_gate_logical_target_t){1u, 12};
    bank.profiles[0].targets[1] = (servo_gate_logical_target_t){2u, 12};
    assert(grip_pose_bank_resolve(&bank, &decision, targets) == GRIP_POSE_OK);
    assert(servo_safety_gate_init(&gate, calibration, 100u, 50u, 70u, 50u));
    assert(servo_safety_gate_arm(&gate, observations));
    assert(servo_safety_gate_plan_logical(&gate, targets, observations, goals));
    assert(goals[0].position_raw == 523u && goals[1].position_raw == 499u);

    vision.confidence = 69u;
    decision = grip_policy_decide(&vision, 70u);
    assert(grip_pose_bank_resolve(&bank, &decision, targets) ==
           GRIP_POSE_NO_ACTION);

    vision.confidence = 90u;
    decision = grip_policy_decide(&vision, 70u);
    bank.profiles[0].targets[1].id = 1u;
    assert(grip_pose_bank_resolve(&bank, &decision, targets) ==
           GRIP_POSE_INVALID_PROFILE);

    grip_pose_bank_init(&bank);
    bank.profiles[1].action = GRIP_ACTION_CYLINDRICAL;
    assert(grip_pose_bank_resolve(&bank, &decision, targets) ==
           GRIP_POSE_INVALID_PROFILE);

    puts("Grip pose bank C tests passed");
    return 0;
}
