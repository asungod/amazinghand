#include "servo_motion_monitor.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    const servo_gate_raw_goal_t goals[SERVO_GATE_COUNT] = {
        {1u, 523u, 60u}, {2u, 499u, 60u}};
    servo_gate_raw_goal_t duplicate[SERVO_GATE_COUNT] = {
        {1u, 523u, 60u}, {1u, 499u, 60u}};
    servo_motion_monitor_t monitor;

    servo_motion_monitor_init(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 100u, 500u));
    assert(!servo_motion_monitor_start(&monitor, goals, 5u, 100u, 500u));
    assert(monitor.busy_rejections == 1u);
    assert(servo_motion_monitor_observe(&monitor, 1u, 520u, 1u, 0u) ==
           SERVO_MOTION_WAIT_FEEDBACK);
    assert(servo_motion_monitor_observe(&monitor, 2u, 503u, 1u, 0u) ==
           SERVO_MOTION_COMPLETE);
    assert(monitor.motions_complete == 1u);

    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 200u, 20u));
    assert(servo_motion_monitor_observe(&monitor, 1u, 523u, 1u, 0u) ==
           SERVO_MOTION_WAIT_FEEDBACK);
    assert(servo_motion_monitor_tick(&monitor, 220u) == SERVO_MOTION_TIMEOUT);
    assert(monitor.motions_timeout == 1u);

    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 300u, 20u));
    assert(servo_motion_monitor_observe(&monitor, 2u, 0u, 0u, 0u) ==
           SERVO_MOTION_FEEDBACK_FAILED);
    assert(monitor.failed_id == 2u);

    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 400u, 20u));
    assert(servo_motion_monitor_observe(&monitor, 1u, 523u, 1u, 0x20u) ==
           SERVO_MOTION_SERVO_ERROR);
    assert(monitor.failed_id == 1u && monitor.servo_error == 0x20u);

    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 0xFFFFFFF0u, 32u));
    assert(servo_motion_monitor_tick(&monitor, 0x0000000Fu) ==
           SERVO_MOTION_WAIT_FEEDBACK);
    assert(servo_motion_monitor_tick(&monitor, 0x00000010u) ==
           SERVO_MOTION_TIMEOUT);

    servo_motion_monitor_reset(&monitor);
    assert(!servo_motion_monitor_start(&monitor, duplicate, 5u, 0u, 20u));
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 0u, 20u));
    assert(servo_motion_monitor_observe(&monitor, 3u, 500u, 1u, 0u) ==
           SERVO_MOTION_FEEDBACK_FAILED);

    servo_motion_monitor_reset(&monitor);
    assert(servo_motion_monitor_start(&monitor, goals, 5u, 0u, 20u));
    servo_motion_monitor_abort(&monitor);
    assert(monitor.state == SERVO_MOTION_ABORTED);

    puts("Servo motion monitor tests passed");
    return 0;
}
