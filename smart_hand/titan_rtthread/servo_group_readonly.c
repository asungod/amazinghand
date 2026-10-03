#include "servo_group_readonly.h"

#include <string.h>

#define SCS_PRESENT_POSITION 56u
#define SCS_FEEDBACK_BLOCK_LENGTH 8u

static void finish_current(servo_group_readonly_t *group, int success)
{
    if (!success)
    {
        group->staged[group->current_index].read_ok = 0u;
        group->cycle_valid = 0u;
        group->failed_reads++;
    }
    scs0009_transaction_reset(&group->transaction);
    if (group->current_index + 1u < group->count)
    {
        group->current_index++;
        return;
    }
    group->cycle_active = 0u;
    group->cycle_complete = 1u;
    group->completed_cycles++;
    if (!group->cycle_valid)
    {
        group->invalid_cycles++;
    }
}

int servo_group_readonly_init(servo_group_readonly_t *group,
                              const uint8_t *ids,
                              size_t count,
                              uint32_t response_timeout_ms)
{
    size_t first;
    size_t second;
    if (group == NULL || ids == NULL || count == 0u ||
        count > SERVO_GROUP_READONLY_MAX_COUNT || response_timeout_ms == 0u)
    {
        return 0;
    }
    for (first = 0u; first < count; ++first)
    {
        if (ids[first] < 1u || ids[first] > SCS0009_MAX_ID)
        {
            return 0;
        }
        for (second = first + 1u; second < count; ++second)
        {
            if (ids[first] == ids[second])
            {
                return 0;
            }
        }
    }
    memset(group, 0, sizeof(*group));
    scs0009_transaction_init(&group->transaction);
    group->count = count;
    group->response_timeout_ms = response_timeout_ms;
    for (first = 0u; first < count; ++first)
    {
        group->ids[first] = ids[first];
        group->staged[first].id = ids[first];
    }
    return 1;
}

int servo_group_readonly_begin_cycle(servo_group_readonly_t *group)
{
    size_t index;
    if (group == NULL || group->count == 0u || group->cycle_active ||
        group->transaction.state != SCS0009_TXN_IDLE)
    {
        return 0;
    }
    group->generation++;
    if (group->generation == 0u)
    {
        group->generation = 1u;
    }
    group->current_index = 0u;
    group->cycle_active = 1u;
    group->cycle_complete = 0u;
    group->cycle_valid = 1u;
    for (index = 0u; index < group->count; ++index)
    {
        memset(&group->staged[index], 0, sizeof(group->staged[index]));
        group->staged[index].id = group->ids[index];
        group->staged[index].generation = group->generation;
    }
    return 1;
}

size_t servo_group_readonly_prepare(servo_group_readonly_t *group,
                                    uint32_t now_ms,
                                    uint8_t *packet,
                                    size_t capacity)
{
    size_t packet_length;
    uint8_t id;
    if (group == NULL || packet == NULL || !group->cycle_active ||
        group->transaction.state != SCS0009_TXN_IDLE)
    {
        return 0u;
    }
    id = group->ids[group->current_index];
    packet_length = scs0009_build_read(id, SCS_PRESENT_POSITION,
                                       SCS_FEEDBACK_BLOCK_LENGTH,
                                       packet, capacity);
    if (packet_length == 0u ||
        !scs0009_transaction_begin(&group->transaction, id, now_ms,
                                   group->response_timeout_ms))
    {
        return 0u;
    }
    return packet_length;
}

void servo_group_readonly_abort_cycle(servo_group_readonly_t *group)
{
    if (group == NULL || !group->cycle_active)
    {
        return;
    }
    group->staged[group->current_index].read_ok = 0u;
    group->cycle_valid = 0u;
    group->failed_reads++;
    if (group->transaction.state != SCS0009_TXN_IDLE)
    {
        scs0009_transaction_abort(&group->transaction);
    }
    scs0009_transaction_reset(&group->transaction);
    group->cycle_active = 0u;
    /* Nothing usable came out of this cycle, so it is not "complete". */
    group->cycle_complete = 0u;
    group->aborted_cycles++;
}

void servo_group_readonly_note_tx_failed(servo_group_readonly_t *group)
{
    if (group != NULL && group->cycle_active &&
        group->transaction.state == SCS0009_TXN_WAIT_STATUS)
    {
        scs0009_transaction_abort(&group->transaction);
        finish_current(group, 0);
    }
}

void servo_group_readonly_feed(servo_group_readonly_t *group, uint8_t byte)
{
    scs0009_status_packet_t status;
    scs0009_transaction_state_t state;
    servo_group_readonly_sample_t *sample;
    if (group == NULL || !group->cycle_active ||
        group->transaction.state != SCS0009_TXN_WAIT_STATUS)
    {
        return;
    }
    state = scs0009_transaction_feed(&group->transaction, byte, &status);
    if (state == SCS0009_TXN_COMPLETE)
    {
        if (status.param_count != SCS_FEEDBACK_BLOCK_LENGTH)
        {
            finish_current(group, 0);
            return;
        }
        sample = &group->staged[group->current_index];
        sample->position_raw = scs0009_decode_u16_be(&status.params[0]);
        sample->speed_raw = scs0009_decode_u16_be(&status.params[2]);
        sample->load_raw = scs0009_decode_u16_be(&status.params[4]);
        sample->voltage_raw = status.params[6];
        sample->temperature_raw = status.params[7];
        sample->read_ok = 1u;
        group->successful_reads++;
        finish_current(group, 1);
    }
    else if (state == SCS0009_TXN_SERVO_ERROR)
    {
        finish_current(group, 0);
    }
}

void servo_group_readonly_tick(servo_group_readonly_t *group,
                               uint32_t now_ms)
{
    if (group != NULL && group->cycle_active &&
        group->transaction.state == SCS0009_TXN_WAIT_STATUS &&
        scs0009_transaction_tick(&group->transaction, now_ms) ==
            SCS0009_TXN_TIMEOUT)
    {
        finish_current(group, 0);
    }
}

int servo_group_readonly_snapshot(
    const servo_group_readonly_t *group,
    servo_group_readonly_sample_t *samples,
    size_t capacity,
    size_t *sample_count)
{
    size_t index;
    if (sample_count != NULL)
    {
        *sample_count = 0u;
    }
    if (group == NULL || samples == NULL || sample_count == NULL ||
        !group->cycle_complete || !group->cycle_valid ||
        capacity < group->count)
    {
        return 0;
    }
    for (index = 0u; index < group->count; ++index)
    {
        if (!group->staged[index].read_ok ||
            group->staged[index].generation != group->generation)
        {
            return 0;
        }
    }
    memcpy(samples, group->staged,
           group->count * sizeof(servo_group_readonly_sample_t));
    *sample_count = group->count;
    return 1;
}
