#include "servo_feedback_poll.h"

#include <string.h>

#define SCS_PRESENT_POSITION 56u
#define SCS_FEEDBACK_BLOCK_LENGTH 8u

static int time_due(uint32_t now_ms, uint32_t due_ms)
{
    return (int32_t)(now_ms - due_ms) >= 0;
}

static void finish_current(servo_feedback_poll_t *poll,
                           uint32_t now_ms,
                           int success)
{
    if (!success)
    {
        poll->observations[poll->current_index].read_ok = 0u;
        poll->failed_reads++;
    }
    scs0009_transaction_reset(&poll->transaction);
    if (poll->current_index + 1u < SERVO_GATE_COUNT)
    {
        poll->current_index++;
        poll->next_due_ms = now_ms;
    }
    else
    {
        poll->current_index = 0u;
        poll->completed_cycles++;
        poll->next_due_ms = now_ms + poll->period_ms;
    }
}

int servo_feedback_poll_init(servo_feedback_poll_t *poll,
                             uint8_t id1,
                             uint8_t id2,
                             uint32_t now_ms,
                             uint32_t period_ms,
                             uint32_t response_timeout_ms)
{
    size_t index;
    if (poll == NULL || id1 < 1u || id1 > 253u || id2 < 1u || id2 > 253u ||
        id1 == id2 || period_ms == 0u || response_timeout_ms == 0u ||
        response_timeout_ms > period_ms)
    {
        return 0;
    }
    memset(poll, 0, sizeof(*poll));
    scs0009_transaction_init(&poll->transaction);
    poll->ids[0] = id1;
    poll->ids[1] = id2;
    poll->period_ms = period_ms;
    poll->response_timeout_ms = response_timeout_ms;
    poll->next_due_ms = now_ms;
    for (index = 0u; index < SERVO_GATE_COUNT; ++index)
    {
        poll->observations[index].id = poll->ids[index];
        poll->observations[index].read_ok = 0u;
        poll->observations[index].age_ms = UINT32_MAX;
    }
    return 1;
}

size_t servo_feedback_poll_prepare(servo_feedback_poll_t *poll,
                                   uint32_t now_ms,
                                   uint8_t *packet,
                                   size_t capacity)
{
    size_t packet_length;
    uint8_t id;
    if (poll == NULL || packet == NULL ||
        poll->transaction.state != SCS0009_TXN_IDLE ||
        !time_due(now_ms, poll->next_due_ms))
    {
        return 0u;
    }
    id = poll->ids[poll->current_index];
    packet_length = scs0009_build_read(id, SCS_PRESENT_POSITION,
                                       SCS_FEEDBACK_BLOCK_LENGTH,
                                       packet, capacity);
    if (packet_length == 0u ||
        !scs0009_transaction_begin(&poll->transaction, id, now_ms,
                                   poll->response_timeout_ms))
    {
        return 0u;
    }
    return packet_length;
}

void servo_feedback_poll_note_tx_failed(servo_feedback_poll_t *poll,
                                        uint32_t now_ms)
{
    if (poll != NULL && poll->transaction.state == SCS0009_TXN_WAIT_STATUS)
    {
        scs0009_transaction_abort(&poll->transaction);
        finish_current(poll, now_ms, 0);
    }
}

void servo_feedback_poll_feed(servo_feedback_poll_t *poll,
                              uint8_t byte,
                              uint32_t now_ms)
{
    scs0009_status_packet_t status;
    scs0009_transaction_state_t state;
    servo_gate_observation_t *observation;
    if (poll == NULL || poll->transaction.state != SCS0009_TXN_WAIT_STATUS)
    {
        return;
    }
    state = scs0009_transaction_feed(&poll->transaction, byte, &status);
    if (state == SCS0009_TXN_COMPLETE)
    {
        if (status.param_count != SCS_FEEDBACK_BLOCK_LENGTH)
        {
            finish_current(poll, now_ms, 0);
            return;
        }
        observation = &poll->observations[poll->current_index];
        observation->position_raw = scs0009_decode_u16_be(&status.params[0]);
        poll->speed_raw[poll->current_index] =
            scs0009_decode_u16_be(&status.params[2]);
        poll->load_raw[poll->current_index] =
            scs0009_decode_u16_be(&status.params[4]);
        observation->voltage_raw = status.params[6];
        observation->temperature_raw = status.params[7];
        observation->read_ok = 1u;
        observation->age_ms = 0u;
        poll->observed_ms[poll->current_index] = now_ms;
        poll->successful_reads++;
        finish_current(poll, now_ms, 1);
    }
    else if (state == SCS0009_TXN_SERVO_ERROR)
    {
        finish_current(poll, now_ms, 0);
    }
}

void servo_feedback_poll_tick(servo_feedback_poll_t *poll, uint32_t now_ms)
{
    if (poll != NULL && poll->transaction.state == SCS0009_TXN_WAIT_STATUS &&
        scs0009_transaction_tick(&poll->transaction, now_ms) ==
            SCS0009_TXN_TIMEOUT)
    {
        finish_current(poll, now_ms, 0);
    }
}

void servo_feedback_poll_snapshot(
    const servo_feedback_poll_t *poll,
    uint32_t now_ms,
    servo_gate_observation_t observations[SERVO_GATE_COUNT])
{
    size_t index;
    if (poll == NULL || observations == NULL)
    {
        return;
    }
    for (index = 0u; index < SERVO_GATE_COUNT; ++index)
    {
        observations[index] = poll->observations[index];
        observations[index].age_ms = observations[index].read_ok
                                         ? now_ms - poll->observed_ms[index]
                                         : UINT32_MAX;
    }
}

void servo_feedback_poll_detail_snapshot(
    const servo_feedback_poll_t *poll,
    uint32_t now_ms,
    servo_feedback_detail_t details[SERVO_GATE_COUNT])
{
    size_t index;
    if (poll == NULL || details == NULL)
    {
        return;
    }
    for (index = 0u; index < SERVO_GATE_COUNT; ++index)
    {
        details[index].id = poll->observations[index].id;
        details[index].position_raw = poll->observations[index].position_raw;
        details[index].speed_raw = poll->speed_raw[index];
        details[index].load_raw = poll->load_raw[index];
        details[index].voltage_raw = poll->observations[index].voltage_raw;
        details[index].temperature_raw = poll->observations[index].temperature_raw;
        details[index].read_ok = poll->observations[index].read_ok;
        details[index].age_ms = details[index].read_ok
                                    ? now_ms - poll->observed_ms[index]
                                    : UINT32_MAX;
    }
}
