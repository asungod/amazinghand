#ifndef EIGHT_SERVO_SAFETY_GATE_H
#define EIGHT_SERVO_SAFETY_GATE_H

#include <stddef.h>
#include <stdint.h>

#define EIGHT_SERVO_COUNT 8u

typedef struct
{
    uint8_t id;
    uint8_t configured;
    int8_t direction_sign;
    uint16_t center_raw;
    uint16_t soft_min_raw;
    uint16_t soft_max_raw;
    uint16_t max_step_raw;
    uint16_t speed_limit_raw;
} eight_servo_calibration_t;

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint8_t voltage_raw;
    uint8_t temperature_raw;
    uint8_t read_ok;
    uint32_t age_ms;
} eight_servo_observation_t;

typedef struct
{
    uint8_t id;
    int16_t offset_from_center;
} eight_servo_target_t;

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint16_t speed_raw;
} eight_servo_goal_t;

typedef enum
{
    EIGHT_SERVO_BLOCK_NONE = 0,
    EIGHT_SERVO_BLOCK_CONFIG_INVALID,
    EIGHT_SERVO_BLOCK_DISARMED,
    EIGHT_SERVO_BLOCK_FAULT_LATCHED,
    EIGHT_SERVO_BLOCK_ID_MISMATCH,
    EIGHT_SERVO_BLOCK_FEEDBACK_FAILED,
    EIGHT_SERVO_BLOCK_FEEDBACK_STALE,
    EIGHT_SERVO_BLOCK_POSITION_UNSAFE,
    EIGHT_SERVO_BLOCK_VOLTAGE_UNSAFE,
    EIGHT_SERVO_BLOCK_TEMPERATURE_UNSAFE,
    EIGHT_SERVO_BLOCK_TARGET_UNSAFE,
    EIGHT_SERVO_BLOCK_STEP_TOO_LARGE,
    EIGHT_SERVO_BLOCK_BUS_WRITE_FAILED
} eight_servo_block_reason_t;

typedef struct
{
    eight_servo_calibration_t calibration[EIGHT_SERVO_COUNT];
    uint32_t max_feedback_age_ms;
    uint8_t voltage_min_raw;
    uint8_t voltage_max_raw;
    uint8_t temperature_max_raw;
    uint8_t initialized;
    uint8_t armed;
    uint8_t fault_latched;
    eight_servo_block_reason_t last_block_reason;
} eight_servo_safety_gate_t;

int eight_servo_safety_gate_init(
    eight_servo_safety_gate_t *gate,
    const eight_servo_calibration_t calibration[EIGHT_SERVO_COUNT],
    uint32_t max_feedback_age_ms,
    uint8_t voltage_min_raw,
    uint8_t voltage_max_raw,
    uint8_t temperature_max_raw);
int eight_servo_safety_gate_arm(
    eight_servo_safety_gate_t *gate,
    const eight_servo_observation_t observations[EIGHT_SERVO_COUNT]);
void eight_servo_safety_gate_disarm(eight_servo_safety_gate_t *gate);
int eight_servo_safety_gate_plan_once(
    eight_servo_safety_gate_t *gate,
    const eight_servo_target_t targets[EIGHT_SERVO_COUNT],
    const eight_servo_observation_t observations[EIGHT_SERVO_COUNT],
    eight_servo_goal_t goals[EIGHT_SERVO_COUNT]);
void eight_servo_safety_gate_note_bus_write(eight_servo_safety_gate_t *gate,
                                            int success);
int eight_servo_safety_gate_clear_fault(eight_servo_safety_gate_t *gate);

#endif
