#ifndef SERVO_SAFETY_GATE_H
#define SERVO_SAFETY_GATE_H

#include <stddef.h>
#include <stdint.h>

#define SERVO_GATE_COUNT 2u

typedef struct
{
    uint8_t id;
    int8_t direction_sign;
    uint16_t center_raw;
    uint16_t soft_min_raw;
    uint16_t soft_max_raw;
    uint16_t max_step_raw;
    uint16_t speed_limit_raw;
} servo_gate_calibration_t;

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint8_t voltage_raw;
    uint8_t temperature_raw;
    uint8_t read_ok;
    uint32_t age_ms;
} servo_gate_observation_t;

typedef struct
{
    uint8_t id;
    int16_t offset_from_center;
} servo_gate_logical_target_t;

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint16_t speed_raw;
} servo_gate_raw_goal_t;

typedef enum
{
    SERVO_GATE_BLOCK_NONE = 0,
    SERVO_GATE_BLOCK_CONFIG_INVALID,
    SERVO_GATE_BLOCK_DISARMED,
    SERVO_GATE_BLOCK_FAULT_LATCHED,
    SERVO_GATE_BLOCK_ID_MISMATCH,
    SERVO_GATE_BLOCK_FEEDBACK_FAILED,
    SERVO_GATE_BLOCK_FEEDBACK_STALE,
    SERVO_GATE_BLOCK_POSITION_UNSAFE,
    SERVO_GATE_BLOCK_VOLTAGE_UNSAFE,
    SERVO_GATE_BLOCK_TEMPERATURE_UNSAFE,
    SERVO_GATE_BLOCK_TARGET_UNSAFE,
    SERVO_GATE_BLOCK_STEP_TOO_LARGE,
    SERVO_GATE_BLOCK_BUS_WRITE_FAILED
} servo_gate_block_reason_t;

typedef struct
{
    servo_gate_calibration_t calibration[SERVO_GATE_COUNT];
    uint32_t max_feedback_age_ms;
    uint8_t voltage_min_raw;
    uint8_t voltage_max_raw;
    uint8_t temperature_max_raw;
    uint8_t initialized;
    uint8_t armed;
    uint8_t fault_latched;
    servo_gate_block_reason_t last_block_reason;
} servo_safety_gate_t;

int servo_safety_gate_init(servo_safety_gate_t *gate,
                           const servo_gate_calibration_t calibration[SERVO_GATE_COUNT],
                           uint32_t max_feedback_age_ms,
                           uint8_t voltage_min_raw,
                           uint8_t voltage_max_raw,
                           uint8_t temperature_max_raw);
int servo_safety_gate_arm(servo_safety_gate_t *gate,
                          const servo_gate_observation_t observations[SERVO_GATE_COUNT]);
void servo_safety_gate_disarm(servo_safety_gate_t *gate);
int servo_safety_gate_plan_logical(
    servo_safety_gate_t *gate,
    const servo_gate_logical_target_t targets[SERVO_GATE_COUNT],
    const servo_gate_observation_t observations[SERVO_GATE_COUNT],
    servo_gate_raw_goal_t goals[SERVO_GATE_COUNT]);
void servo_safety_gate_note_bus_write(servo_safety_gate_t *gate, int success);
int servo_safety_gate_clear_fault(servo_safety_gate_t *gate);

#endif
