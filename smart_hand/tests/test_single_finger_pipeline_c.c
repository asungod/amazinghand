#include "grip_policy.h"
#include "grip_pose_bank.h"
#include "scs0009_packet.h"
#include "servo_motion_monitor.h"
#include "servo_safety_gate.h"

#include <assert.h>
#include <stdio.h>

static const servo_gate_calibration_t test_calibration[SERVO_GATE_COUNT] = {
    {1u, 1, 511u, 300u, 700u, 20u, 60u},
    {2u, -1, 511u, 280u, 720u, 20u, 60u}};

static void fresh_observations(
    servo_gate_observation_t observations[SERVO_GATE_COUNT])
{
    observations[0] = (servo_gate_observation_t){1u, 511u, 60u, 25u, 1u, 5u};
    observations[1] = (servo_gate_observation_t){2u, 511u, 60u, 25u, 1u, 5u};
}

/*
 * Offline composition of the intended Titan single-finger path:
 *   VISION payload -> grip_policy -> grip_pose_bank -> servo_safety_gate
 *                 -> scs0009 sync write packet -> servo_motion_monitor
 *
 * This is NOT the current smart_hand_uart.c runtime path. As of 2026-08-12,
 * handle_message() only prints a confidence-only POWER_GRASP/NO_ACTION string
 * and never calls these modules. Values below marked FIXTURE are test-only and
 * must never be copied into production pose banks or calibration CSVs.
 */
int main(void)
{
    grip_vision_payload_t vision = {39u, 320u, 240u, 80u, 120u, 90u};
    grip_vision_payload_t cup = {41u, 320u, 240u, 80u, 120u, 90u};
    grip_vision_payload_t remote = {65u, 320u, 240u, 80u, 120u, 90u};
    grip_vision_payload_t low_conf = {39u, 320u, 240u, 80u, 120u, 69u};
    grip_vision_payload_t unsupported = {1u, 320u, 240u, 80u, 120u, 99u};
    grip_decision_t decision;
    grip_pose_bank_t poses;
    servo_gate_logical_target_t logical[SERVO_GATE_COUNT];
    servo_gate_observation_t observations[SERVO_GATE_COUNT];
    servo_gate_raw_goal_t goals[SERVO_GATE_COUNT];
    servo_safety_gate_t safety;
    servo_motion_monitor_t monitor;
    uint8_t packet[32];
    size_t packet_length = 0u;

    grip_pose_bank_init(&poses);

    /* Class-based policy (gap vs uart confidence-only POWER_GRASP diagnostic). */
    decision = grip_policy_decide(&vision, 70u);
    assert(decision.action == GRIP_ACTION_CYLINDRICAL);
    assert(grip_policy_decide(&cup, 70u).action == GRIP_ACTION_POWER);
    assert(grip_policy_decide(&remote, 70u).action == GRIP_ACTION_PRECISION);
    assert(grip_policy_decide(&low_conf, 70u).action == GRIP_ACTION_NONE);
    assert(grip_policy_decide(&unsupported, 70u).action == GRIP_ACTION_NONE);

    /* Normal startup is intentionally blocked: production pose bank empty. */
    assert(grip_pose_bank_resolve(&poses, &decision, logical) ==
           GRIP_POSE_NOT_CONFIGURED);
    assert(packet_length == 0u);

    /*
     * FIXTURE ONLY: temporary pose offsets to exercise the complete offline path.
     * Production grip_pose_bank must remain unconfigured until mechanical calibration.
     */
    poses.profiles[0].configured = 1u;
    poses.profiles[0].targets[0] = (servo_gate_logical_target_t){1u, 12};
    poses.profiles[0].targets[1] = (servo_gate_logical_target_t){2u, 12};
    poses.profiles[1].configured = 1u;
    poses.profiles[1].targets[0] = (servo_gate_logical_target_t){1u, 10};
    poses.profiles[1].targets[1] = (servo_gate_logical_target_t){2u, 10};
    poses.profiles[2].configured = 1u;
    poses.profiles[2].targets[0] = (servo_gate_logical_target_t){1u, 6};
    poses.profiles[2].targets[1] = (servo_gate_logical_target_t){2u, 6};

    /* Even with FIXTURE poses configured, unsupported/low-conf never emit packets. */
    decision = grip_policy_decide(&unsupported, 70u);
    assert(grip_pose_bank_resolve(&poses, &decision, logical) == GRIP_POSE_NO_ACTION);
    decision = grip_policy_decide(&low_conf, 70u);
    assert(grip_pose_bank_resolve(&poses, &decision, logical) == GRIP_POSE_NO_ACTION);

    decision = grip_policy_decide(&vision, 70u);
    assert(grip_pose_bank_resolve(&poses, &decision, logical) == GRIP_POSE_OK);
    fresh_observations(observations);
    /* FIXTURE ONLY calibration bounds — not production soft limits. */
    assert(servo_safety_gate_init(&safety, test_calibration, 100u, 50u, 70u, 50u));
    assert(servo_safety_gate_arm(&safety, observations));
    assert(servo_safety_gate_plan_logical(&safety, logical, observations, goals));
    packet_length = scs0009_build_sync_write_positions(
        goals[0].id, goals[0].position_raw,
        goals[1].id, goals[1].position_raw,
        0u, goals[0].speed_raw, packet, sizeof(packet));
    assert(packet_length == 22u && packet[2] == SCS0009_BROADCAST_ID);

    servo_motion_monitor_init(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 100u, 500u));
    assert(servo_motion_monitor_observe(&monitor, 1u, 522u, 1u, 0u) ==
           SERVO_MOTION_WAIT_FEEDBACK);
    assert(servo_motion_monitor_observe(&monitor, 2u, 501u, 1u, 0u) ==
           SERVO_MOTION_COMPLETE);

    /* Failure path: stale feedback prevents packet creation. */
    packet_length = 0u;
    servo_safety_gate_disarm(&safety);
    fresh_observations(observations);
    observations[0].age_ms = 101u;
    assert(!servo_safety_gate_arm(&safety, observations));
    if (safety.armed &&
        servo_safety_gate_plan_logical(&safety, logical, observations, goals))
    {
        packet_length = scs0009_build_sync_write_positions(
            goals[0].id, goals[0].position_raw,
            goals[1].id, goals[1].position_raw,
            0u, goals[0].speed_raw, packet, sizeof(packet));
    }
    assert(packet_length == 0u);

    /* Disarmed gate must not plan motion (models link-loss / explicit disarm). */
    packet_length = 0u;
    servo_safety_gate_disarm(&safety);
    fresh_observations(observations);
    if (safety.armed &&
        servo_safety_gate_plan_logical(&safety, logical, observations, goals))
    {
        packet_length = scs0009_build_sync_write_positions(
            goals[0].id, goals[0].position_raw,
            goals[1].id, goals[1].position_raw,
            0u, goals[0].speed_raw, packet, sizeof(packet));
    }
    assert(packet_length == 0u);
    assert(!safety.armed);

    /* Integration edge: one missing post-write response cannot complete motion. */
    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 1000u, 20u));
    assert(servo_motion_monitor_observe(&monitor, 1u, 523u, 1u, 0u) ==
           SERVO_MOTION_WAIT_FEEDBACK);
    assert(servo_motion_monitor_tick(&monitor, 1020u) == SERVO_MOTION_TIMEOUT);

    puts("Single-finger pipeline C integration tests passed");
    return 0;
}
