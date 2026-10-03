#include "scs0009_packet.h"
#include "servo_safety_gate.h"

#include <assert.h>
#include <stdio.h>

static const servo_gate_calibration_t calibration[SERVO_GATE_COUNT] = {
    {1u, 1, 511u, 300u, 700u, 20u, 60u},
    {2u, -1, 511u, 280u, 720u, 20u, 60u}};

static void reset_observations(servo_gate_observation_t observations[SERVO_GATE_COUNT])
{
    observations[0] = (servo_gate_observation_t){1u, 511u, 60u, 25u, 1u, 5u};
    observations[1] = (servo_gate_observation_t){2u, 511u, 60u, 25u, 1u, 5u};
}

int main(void)
{
    servo_safety_gate_t gate;
    servo_gate_observation_t observations[SERVO_GATE_COUNT];
    servo_gate_logical_target_t targets[SERVO_GATE_COUNT] = {
        {1u, 12}, {2u, 12}};
    servo_gate_raw_goal_t goals[SERVO_GATE_COUNT];
    uint8_t packet[32];
    size_t packet_length;

    reset_observations(observations);
    assert(servo_safety_gate_init(&gate, calibration, 100u, 50u, 70u, 50u));
    assert(servo_safety_gate_arm(&gate, observations));
    assert(servo_safety_gate_plan_logical(&gate, targets, observations, goals));
    assert(goals[0].id == 1u && goals[0].position_raw == 523u);
    assert(goals[1].id == 2u && goals[1].position_raw == 499u);

    /* Integration edge: only authorized goals reach the packet encoder. */
    packet_length = scs0009_build_sync_write_positions(
        goals[0].id, goals[0].position_raw, goals[1].id,
        goals[1].position_raw, 0u, goals[0].speed_raw,
        packet, sizeof(packet));
    assert(packet_length == 22u);
    assert(packet[2] == SCS0009_BROADCAST_ID && packet[4] == 0x83u);

    observations[0].age_ms = 101u;
    assert(!servo_safety_gate_plan_logical(&gate, targets, observations, goals));
    assert(!gate.armed && gate.last_block_reason == SERVO_GATE_BLOCK_FEEDBACK_STALE);

    reset_observations(observations);
    assert(servo_safety_gate_arm(&gate, observations));
    targets[0].offset_from_center = 21;
    assert(!servo_safety_gate_plan_logical(&gate, targets, observations, goals));
    assert(gate.last_block_reason == SERVO_GATE_BLOCK_STEP_TOO_LARGE);

    targets[0].offset_from_center = 12;
    observations[1].read_ok = 0u;
    assert(!servo_safety_gate_plan_logical(&gate, targets, observations, goals));
    assert(!gate.armed && gate.last_block_reason == SERVO_GATE_BLOCK_FEEDBACK_FAILED);

    reset_observations(observations);
    assert(servo_safety_gate_arm(&gate, observations));
    servo_safety_gate_note_bus_write(&gate, 0);
    assert(gate.fault_latched && !gate.armed);
    assert(!servo_safety_gate_arm(&gate, observations));
    assert(servo_safety_gate_clear_fault(&gate));
    assert(servo_safety_gate_arm(&gate, observations));

    puts("Servo safety gate C tests passed");
    return 0;
}
