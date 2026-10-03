#ifndef SERVO_MOTION_MONITOR_H
#define SERVO_MOTION_MONITOR_H

#include "servo_safety_gate.h"

#include <stdint.h>

typedef enum
{
    SERVO_MOTION_IDLE = 0,
    SERVO_MOTION_WAIT_FEEDBACK,
    SERVO_MOTION_COMPLETE,
    SERVO_MOTION_FEEDBACK_FAILED,
    SERVO_MOTION_SERVO_ERROR,
    SERVO_MOTION_TIMEOUT,
    SERVO_MOTION_ABORTED
} servo_motion_state_t;

typedef struct
{
    servo_motion_state_t state;
    servo_gate_raw_goal_t goals[SERVO_GATE_COUNT];
    uint16_t last_positions[SERVO_GATE_COUNT];
    uint8_t seen[SERVO_GATE_COUNT];
    uint16_t tolerance_raw;
    uint32_t started_ms;
    uint32_t timeout_ms;
    uint8_t failed_id;
    uint8_t servo_error;
    uint32_t motions_started;
    uint32_t motions_complete;
    uint32_t motions_timeout;
    uint32_t motions_failed;
    uint32_t busy_rejections;
} servo_motion_monitor_t;

void servo_motion_monitor_init(servo_motion_monitor_t *monitor);
int servo_motion_monitor_start(
    servo_motion_monitor_t *monitor,
    const servo_gate_raw_goal_t goals[SERVO_GATE_COUNT],
    uint16_t tolerance_raw,
    uint32_t now_ms,
    uint32_t timeout_ms);
servo_motion_state_t servo_motion_monitor_observe(
    servo_motion_monitor_t *monitor,
    uint8_t servo_id,
    uint16_t position_raw,
    uint8_t read_ok,
    uint8_t servo_error);
servo_motion_state_t servo_motion_monitor_tick(servo_motion_monitor_t *monitor,
                                               uint32_t now_ms);
void servo_motion_monitor_abort(servo_motion_monitor_t *monitor);
void servo_motion_monitor_reset(servo_motion_monitor_t *monitor);

#endif
