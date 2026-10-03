#include "eight_servo_safety_gate.h"
#include "scs0009_packet.h"

#include <assert.h>
#include <stdio.h>

static void make_valid(eight_servo_calibration_t calibration[EIGHT_SERVO_COUNT],
                       eight_servo_observation_t observations[EIGHT_SERVO_COUNT],
                       eight_servo_target_t targets[EIGHT_SERVO_COUNT])
{
    size_t index;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        uint8_t id = (uint8_t)(index + 1u);
        calibration[index].id = id;
        calibration[index].configured = 1u;
        calibration[index].direction_sign = (index & 1u) ? -1 : 1;
        calibration[index].center_raw = 511u;
        calibration[index].soft_min_raw = 400u;
        calibration[index].soft_max_raw = 620u;
        calibration[index].max_step_raw = 20u;
        calibration[index].speed_limit_raw = 60u;
        observations[index].id = id;
        observations[index].position_raw = 511u;
        observations[index].voltage_raw = 50u;
        observations[index].temperature_raw = 25u;
        observations[index].read_ok = 1u;
        observations[index].age_ms = 10u;
        targets[index].id = id;
        targets[index].offset_from_center = 10;
    }
}

int main(void)
{
    eight_servo_safety_gate_t gate;
    eight_servo_calibration_t calibration[EIGHT_SERVO_COUNT];
    eight_servo_observation_t observations[EIGHT_SERVO_COUNT];
    eight_servo_target_t targets[EIGHT_SERVO_COUNT];
    eight_servo_goal_t goals[EIGHT_SERVO_COUNT];
    scs0009_sync_goal_t packet_goals[EIGHT_SERVO_COUNT];
    uint8_t packet[SCS0009_SYNC_WRITE_POSITION_MAX_PACKET_SIZE];
    size_t index;

    make_valid(calibration, observations, targets);
    assert(eight_servo_safety_gate_init(&gate, calibration, 100u, 45u, 60u,
                                        45u));
    assert(!eight_servo_safety_gate_plan_once(&gate, targets, observations,
                                              goals));
    assert(gate.last_block_reason == EIGHT_SERVO_BLOCK_DISARMED);
    assert(eight_servo_safety_gate_arm(&gate, observations));
    assert(eight_servo_safety_gate_plan_once(&gate, targets, observations,
                                             goals));
    assert(!gate.armed);
    assert(goals[0].position_raw == 521u);
    assert(goals[1].position_raw == 501u);
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        packet_goals[index].id = goals[index].id;
        packet_goals[index].position = goals[index].position_raw;
        packet_goals[index].time_raw = 0u;
        packet_goals[index].speed_raw = goals[index].speed_raw;
    }
    assert(scs0009_build_sync_write_position_group(
               packet_goals, EIGHT_SERVO_COUNT, packet, sizeof(packet)) ==
           sizeof(packet));

    assert(!eight_servo_safety_gate_plan_once(&gate, targets, observations,
                                              goals));
    assert(gate.last_block_reason == EIGHT_SERVO_BLOCK_DISARMED);

    assert(eight_servo_safety_gate_arm(&gate, observations));
    observations[3].age_ms = 101u;
    assert(!eight_servo_safety_gate_plan_once(&gate, targets, observations,
                                              goals));
    assert(gate.last_block_reason == EIGHT_SERVO_BLOCK_FEEDBACK_STALE);
    observations[3].age_ms = 10u;

    assert(eight_servo_safety_gate_arm(&gate, observations));
    targets[7].offset_from_center = 30;
    assert(!eight_servo_safety_gate_plan_once(&gate, targets, observations,
                                              goals));
    assert(gate.last_block_reason == EIGHT_SERVO_BLOCK_STEP_TOO_LARGE);
    targets[7].offset_from_center = 10;

    assert(eight_servo_safety_gate_arm(&gate, observations));
    eight_servo_safety_gate_note_bus_write(&gate, 0);
    assert(gate.fault_latched && !gate.armed);
    assert(!eight_servo_safety_gate_arm(&gate, observations));
    assert(eight_servo_safety_gate_clear_fault(&gate));

    calibration[6].configured = 0u;
    assert(!eight_servo_safety_gate_init(&gate, calibration, 100u, 45u, 60u,
                                         45u));
    assert(gate.last_block_reason == EIGHT_SERVO_BLOCK_CONFIG_INVALID);

    puts("Eight-servo safety gate tests passed");
    return 0;
}
