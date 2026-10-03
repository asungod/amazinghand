#include "eight_servo_safety_gate.h"

#include <string.h>

static int calibration_valid(const eight_servo_calibration_t *calibration)
{
    return calibration != NULL && calibration->configured == 1u &&
           calibration->id >= 1u && calibration->id <= 253u &&
           (calibration->direction_sign == 1 ||
            calibration->direction_sign == -1) &&
           calibration->soft_min_raw < calibration->soft_max_raw &&
           calibration->soft_max_raw <= 1023u &&
           calibration->center_raw >= calibration->soft_min_raw &&
           calibration->center_raw <= calibration->soft_max_raw &&
           calibration->max_step_raw > 0u &&
           calibration->speed_limit_raw > 0u;
}

static int ids_unique_calibration(
    const eight_servo_calibration_t values[EIGHT_SERVO_COUNT])
{
    size_t index;
    size_t previous;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        for (previous = 0u; previous < index; ++previous)
        {
            if (values[index].id == values[previous].id)
            {
                return 0;
            }
        }
    }
    return 1;
}

static const eight_servo_observation_t *find_observation(
    const eight_servo_observation_t values[EIGHT_SERVO_COUNT], uint8_t id)
{
    size_t index;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        if (values[index].id == id)
        {
            return &values[index];
        }
    }
    return NULL;
}

static const eight_servo_target_t *find_target(
    const eight_servo_target_t values[EIGHT_SERVO_COUNT], uint8_t id)
{
    size_t index;
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        if (values[index].id == id)
        {
            return &values[index];
        }
    }
    return NULL;
}

static int observations_valid(
    eight_servo_safety_gate_t *gate,
    const eight_servo_observation_t observations[EIGHT_SERVO_COUNT])
{
    size_t index;
    size_t previous;
    if (observations == NULL)
    {
        gate->last_block_reason = EIGHT_SERVO_BLOCK_ID_MISMATCH;
        return 0;
    }
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        const eight_servo_calibration_t *calibration =
            &gate->calibration[index];
        const eight_servo_observation_t *observation;
        for (previous = 0u; previous < index; ++previous)
        {
            if (observations[index].id == observations[previous].id)
            {
                gate->last_block_reason = EIGHT_SERVO_BLOCK_ID_MISMATCH;
                return 0;
            }
        }
        observation = find_observation(observations, calibration->id);
        if (observation == NULL)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_ID_MISMATCH;
            return 0;
        }
        if (!observation->read_ok)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_FEEDBACK_FAILED;
            return 0;
        }
        if (observation->age_ms > gate->max_feedback_age_ms)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_FEEDBACK_STALE;
            return 0;
        }
        if (observation->position_raw < calibration->soft_min_raw ||
            observation->position_raw > calibration->soft_max_raw)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_POSITION_UNSAFE;
            return 0;
        }
        if (observation->voltage_raw < gate->voltage_min_raw ||
            observation->voltage_raw > gate->voltage_max_raw)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_VOLTAGE_UNSAFE;
            return 0;
        }
        if (observation->temperature_raw >= gate->temperature_max_raw)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_TEMPERATURE_UNSAFE;
            return 0;
        }
    }
    return 1;
}

int eight_servo_safety_gate_init(
    eight_servo_safety_gate_t *gate,
    const eight_servo_calibration_t calibration[EIGHT_SERVO_COUNT],
    uint32_t max_feedback_age_ms,
    uint8_t voltage_min_raw,
    uint8_t voltage_max_raw,
    uint8_t temperature_max_raw)
{
    size_t index;
    if (gate == NULL)
    {
        return 0;
    }
    memset(gate, 0, sizeof(*gate));
    gate->last_block_reason = EIGHT_SERVO_BLOCK_CONFIG_INVALID;
    if (calibration == NULL || max_feedback_age_ms == 0u ||
        voltage_min_raw > voltage_max_raw || temperature_max_raw == 0u)
    {
        return 0;
    }
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        if (!calibration_valid(&calibration[index]))
        {
            return 0;
        }
    }
    if (!ids_unique_calibration(calibration))
    {
        return 0;
    }
    memcpy(gate->calibration, calibration, sizeof(gate->calibration));
    gate->max_feedback_age_ms = max_feedback_age_ms;
    gate->voltage_min_raw = voltage_min_raw;
    gate->voltage_max_raw = voltage_max_raw;
    gate->temperature_max_raw = temperature_max_raw;
    gate->initialized = 1u;
    gate->last_block_reason = EIGHT_SERVO_BLOCK_DISARMED;
    return 1;
}

int eight_servo_safety_gate_arm(
    eight_servo_safety_gate_t *gate,
    const eight_servo_observation_t observations[EIGHT_SERVO_COUNT])
{
    if (gate == NULL || !gate->initialized)
    {
        return 0;
    }
    if (gate->fault_latched)
    {
        gate->last_block_reason = EIGHT_SERVO_BLOCK_FAULT_LATCHED;
        return 0;
    }
    if (!observations_valid(gate, observations))
    {
        return 0;
    }
    gate->armed = 1u;
    gate->last_block_reason = EIGHT_SERVO_BLOCK_NONE;
    return 1;
}

void eight_servo_safety_gate_disarm(eight_servo_safety_gate_t *gate)
{
    if (gate != NULL)
    {
        gate->armed = 0u;
        gate->last_block_reason = EIGHT_SERVO_BLOCK_DISARMED;
    }
}

int eight_servo_safety_gate_plan_once(
    eight_servo_safety_gate_t *gate,
    const eight_servo_target_t targets[EIGHT_SERVO_COUNT],
    const eight_servo_observation_t observations[EIGHT_SERVO_COUNT],
    eight_servo_goal_t goals[EIGHT_SERVO_COUNT])
{
    size_t index;
    if (gate == NULL || targets == NULL || goals == NULL ||
        !gate->initialized)
    {
        return 0;
    }
    if (gate->fault_latched)
    {
        gate->last_block_reason = EIGHT_SERVO_BLOCK_FAULT_LATCHED;
        return 0;
    }
    if (!gate->armed)
    {
        gate->last_block_reason = EIGHT_SERVO_BLOCK_DISARMED;
        return 0;
    }
    if (!observations_valid(gate, observations))
    {
        gate->armed = 0u;
        return 0;
    }
    for (index = 0u; index < EIGHT_SERVO_COUNT; ++index)
    {
        const eight_servo_calibration_t *calibration =
            &gate->calibration[index];
        const eight_servo_observation_t *observation =
            find_observation(observations, calibration->id);
        const eight_servo_target_t *target =
            find_target(targets, calibration->id);
        int32_t raw_target;
        int32_t delta;
        if (target == NULL || observation == NULL)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_ID_MISMATCH;
            gate->armed = 0u;
            return 0;
        }
        raw_target = (int32_t)calibration->center_raw +
                     ((int32_t)calibration->direction_sign *
                      (int32_t)target->offset_from_center);
        if (raw_target < (int32_t)calibration->soft_min_raw ||
            raw_target > (int32_t)calibration->soft_max_raw)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_TARGET_UNSAFE;
            gate->armed = 0u;
            return 0;
        }
        delta = raw_target - (int32_t)observation->position_raw;
        if (delta < 0)
        {
            delta = -delta;
        }
        if (delta > (int32_t)calibration->max_step_raw)
        {
            gate->last_block_reason = EIGHT_SERVO_BLOCK_STEP_TOO_LARGE;
            gate->armed = 0u;
            return 0;
        }
        goals[index].id = calibration->id;
        goals[index].position_raw = (uint16_t)raw_target;
        goals[index].speed_raw = calibration->speed_limit_raw;
    }
    gate->armed = 0u;
    gate->last_block_reason = EIGHT_SERVO_BLOCK_NONE;
    return 1;
}

void eight_servo_safety_gate_note_bus_write(eight_servo_safety_gate_t *gate,
                                            int success)
{
    if (gate != NULL && !success)
    {
        gate->fault_latched = 1u;
        gate->armed = 0u;
        gate->last_block_reason = EIGHT_SERVO_BLOCK_BUS_WRITE_FAILED;
    }
}

int eight_servo_safety_gate_clear_fault(eight_servo_safety_gate_t *gate)
{
    if (gate == NULL || gate->armed)
    {
        return 0;
    }
    gate->fault_latched = 0u;
    gate->last_block_reason = EIGHT_SERVO_BLOCK_DISARMED;
    return 1;
}
