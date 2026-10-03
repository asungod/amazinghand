#ifndef SERVO_FEEDBACK_POLL_H
#define SERVO_FEEDBACK_POLL_H

#include "scs0009_transaction.h"
#include "servo_safety_gate.h"

#include <stddef.h>
#include <stdint.h>

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint16_t speed_raw;
    uint16_t load_raw;
    uint8_t voltage_raw;
    uint8_t temperature_raw;
    uint8_t read_ok;
    uint32_t age_ms;
} servo_feedback_detail_t;

typedef struct
{
    scs0009_transaction_t transaction;
    servo_gate_observation_t observations[SERVO_GATE_COUNT];
    uint32_t observed_ms[SERVO_GATE_COUNT];
    uint16_t speed_raw[SERVO_GATE_COUNT];
    uint16_t load_raw[SERVO_GATE_COUNT];
    uint8_t ids[SERVO_GATE_COUNT];
    uint8_t current_index;
    uint32_t next_due_ms;
    uint32_t period_ms;
    uint32_t response_timeout_ms;
    uint32_t successful_reads;
    uint32_t failed_reads;
    uint32_t completed_cycles;
} servo_feedback_poll_t;

int servo_feedback_poll_init(servo_feedback_poll_t *poll,
                             uint8_t id1,
                             uint8_t id2,
                             uint32_t now_ms,
                             uint32_t period_ms,
                             uint32_t response_timeout_ms);
size_t servo_feedback_poll_prepare(servo_feedback_poll_t *poll,
                                   uint32_t now_ms,
                                   uint8_t *packet,
                                   size_t capacity);
void servo_feedback_poll_note_tx_failed(servo_feedback_poll_t *poll,
                                        uint32_t now_ms);
void servo_feedback_poll_feed(servo_feedback_poll_t *poll,
                              uint8_t byte,
                              uint32_t now_ms);
void servo_feedback_poll_tick(servo_feedback_poll_t *poll, uint32_t now_ms);
void servo_feedback_poll_snapshot(
    const servo_feedback_poll_t *poll,
    uint32_t now_ms,
    servo_gate_observation_t observations[SERVO_GATE_COUNT]);
void servo_feedback_poll_detail_snapshot(
    const servo_feedback_poll_t *poll,
    uint32_t now_ms,
    servo_feedback_detail_t details[SERVO_GATE_COUNT]);

#endif
