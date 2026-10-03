#include "servo_motion_monitor.h"

#include <string.h>

static int goal_index(const servo_motion_monitor_t *monitor, uint8_t servo_id)
{
    size_t index;
    for (index = 0u; index < SERVO_GATE_COUNT; ++index)
    {
        if (monitor->goals[index].id == servo_id)
        {
            return (int)index;
        }
    }
    return -1;
}

static uint16_t absolute_difference(uint16_t left, uint16_t right)
{
    return left >= right ? (uint16_t)(left - right) : (uint16_t)(right - left);
}

void servo_motion_monitor_init(servo_motion_monitor_t *monitor)
{
    if (monitor != NULL)
    {
        memset(monitor, 0, sizeof(*monitor));
        monitor->state = SERVO_MOTION_IDLE;
    }
}

int servo_motion_monitor_start(
    servo_motion_monitor_t *monitor,
    const servo_gate_raw_goal_t goals[SERVO_GATE_COUNT],
    uint16_t tolerance_raw,
    uint32_t now_ms,
    uint32_t timeout_ms)
{
    if (monitor == NULL || goals == NULL || goals[0].id < 1u || goals[0].id > 253u ||
        goals[1].id < 1u || goals[1].id > 253u || goals[0].id == goals[1].id ||
        goals[0].position_raw > 1023u || goals[1].position_raw > 1023u ||
        timeout_ms == 0u)
    {
        return 0;
    }
    if (monitor->state != SERVO_MOTION_IDLE)
    {
        monitor->busy_rejections++;
        return 0;
    }
    monitor->goals[0] = goals[0];
    monitor->goals[1] = goals[1];
    monitor->seen[0] = 0u;
    monitor->seen[1] = 0u;
    monitor->last_positions[0] = 0u;
    monitor->last_positions[1] = 0u;
    monitor->tolerance_raw = tolerance_raw;
    monitor->started_ms = now_ms;
    monitor->timeout_ms = timeout_ms;
    monitor->failed_id = 0u;
    monitor->servo_error = 0u;
    monitor->state = SERVO_MOTION_WAIT_FEEDBACK;
    monitor->motions_started++;
    return 1;
}

servo_motion_state_t servo_motion_monitor_observe(
    servo_motion_monitor_t *monitor,
    uint8_t servo_id,
    uint16_t position_raw,
    uint8_t read_ok,
    uint8_t servo_error)
{
    int index;
    size_t check_index;
    if (monitor == NULL)
    {
        return SERVO_MOTION_ABORTED;
    }
    if (monitor->state != SERVO_MOTION_WAIT_FEEDBACK)
    {
        return monitor->state;
    }
    index = goal_index(monitor, servo_id);
    if (index < 0 || !read_ok || position_raw > 1023u)
    {
        monitor->failed_id = servo_id;
        monitor->state = SERVO_MOTION_FEEDBACK_FAILED;
        monitor->motions_failed++;
        return monitor->state;
    }
    if (servo_error != 0u)
    {
        monitor->failed_id = servo_id;
        monitor->servo_error = servo_error;
        monitor->state = SERVO_MOTION_SERVO_ERROR;
        monitor->motions_failed++;
        return monitor->state;
    }
    monitor->last_positions[index] = position_raw;
    monitor->seen[index] = 1u;
    for (check_index = 0u; check_index < SERVO_GATE_COUNT; ++check_index)
    {
        if (!monitor->seen[check_index] ||
            absolute_difference(monitor->last_positions[check_index],
                                monitor->goals[check_index].position_raw) >
                monitor->tolerance_raw)
        {
            return monitor->state;
        }
    }
    monitor->state = SERVO_MOTION_COMPLETE;
    monitor->motions_complete++;
    return monitor->state;
}

servo_motion_state_t servo_motion_monitor_tick(servo_motion_monitor_t *monitor,
                                               uint32_t now_ms)
{
    if (monitor == NULL)
    {
        return SERVO_MOTION_ABORTED;
    }
    if (monitor->state == SERVO_MOTION_WAIT_FEEDBACK &&
        (uint32_t)(now_ms - monitor->started_ms) >= monitor->timeout_ms)
    {
        monitor->state = SERVO_MOTION_TIMEOUT;
        monitor->motions_timeout++;
    }
    return monitor->state;
}

void servo_motion_monitor_abort(servo_motion_monitor_t *monitor)
{
    if (monitor != NULL && monitor->state == SERVO_MOTION_WAIT_FEEDBACK)
    {
        monitor->state = SERVO_MOTION_ABORTED;
    }
}

void servo_motion_monitor_reset(servo_motion_monitor_t *monitor)
{
    if (monitor != NULL && monitor->state != SERVO_MOTION_WAIT_FEEDBACK)
    {
        monitor->state = SERVO_MOTION_IDLE;
        monitor->failed_id = 0u;
        monitor->servo_error = 0u;
    }
}
