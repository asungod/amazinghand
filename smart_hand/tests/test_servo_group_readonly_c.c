#include "servo_group_readonly.h"

#include <assert.h>
#include <stdio.h>

static size_t make_feedback(uint8_t id,
                            uint16_t position,
                            uint16_t speed,
                            uint16_t load,
                            uint8_t voltage,
                            uint8_t temperature,
                            uint8_t packet[14])
{
    uint8_t sum = 0u;
    size_t index;
    packet[0] = 0xFFu;
    packet[1] = 0xFFu;
    packet[2] = id;
    packet[3] = 10u;
    packet[4] = 0u;
    packet[5] = (uint8_t)(position >> 8u);
    packet[6] = (uint8_t)position;
    packet[7] = (uint8_t)(speed >> 8u);
    packet[8] = (uint8_t)speed;
    packet[9] = (uint8_t)(load >> 8u);
    packet[10] = (uint8_t)load;
    packet[11] = voltage;
    packet[12] = temperature;
    for (index = 2u; index < 13u; ++index)
    {
        sum = (uint8_t)(sum + packet[index]);
    }
    packet[13] = (uint8_t)(~sum);
    return 14u;
}

static void feed(servo_group_readonly_t *group,
                 const uint8_t *packet,
                 size_t length)
{
    size_t index;
    for (index = 0u; index < length; ++index)
    {
        servo_group_readonly_feed(group, packet[index]);
    }
}

static void complete_one(servo_group_readonly_t *group,
                         uint8_t id,
                         uint16_t position,
                         uint32_t now_ms)
{
    uint8_t request[8];
    uint8_t response[14];
    assert(servo_group_readonly_prepare(group, now_ms, request,
                                        sizeof(request)) == 8u);
    assert(request[2] == id && request[5] == 56u && request[6] == 8u);
    feed(group, response,
         make_feedback(id, position, (uint16_t)(id + 10u),
                       (uint16_t)(id + 20u), (uint8_t)(50u + id),
                       (uint8_t)(20u + id), response));
}

int main(void)
{
    const uint8_t ids[8] = {1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u};
    const uint8_t duplicate_ids[3] = {1u, 2u, 1u};
    const uint8_t bad_ids[2] = {0u, 1u};
    servo_group_readonly_t group;
    servo_group_readonly_sample_t samples[8];
    uint8_t request[8];
    uint8_t wrong_response[14];
    size_t count;
    size_t index;

    assert(!servo_group_readonly_init(&group, ids, 0u, 5u));
    assert(!servo_group_readonly_init(&group, ids, 9u, 5u));
    assert(!servo_group_readonly_init(&group, duplicate_ids, 3u, 5u));
    assert(!servo_group_readonly_init(&group, bad_ids, 2u, 5u));
    assert(!servo_group_readonly_init(&group, ids, 8u, 0u));

    assert(servo_group_readonly_init(&group, ids, 8u, 5u));
    assert(servo_group_readonly_begin_cycle(&group));
    assert(!servo_group_readonly_begin_cycle(&group));
    for (index = 0u; index < 8u; ++index)
    {
        complete_one(&group, ids[index], (uint16_t)(500u + index),
                     (uint32_t)(100u + index));
    }
    assert(group.cycle_complete && group.cycle_valid && !group.cycle_active);
    assert(group.completed_cycles == 1u && group.invalid_cycles == 0u);
    assert(group.successful_reads == 8u && group.failed_reads == 0u);
    assert(servo_group_readonly_snapshot(&group, samples, 8u, &count));
    assert(count == 8u);
    for (index = 0u; index < count; ++index)
    {
        assert(samples[index].id == ids[index]);
        assert(samples[index].position_raw == (uint16_t)(500u + index));
        assert(samples[index].speed_raw == (uint16_t)(ids[index] + 10u));
        assert(samples[index].load_raw == (uint16_t)(ids[index] + 20u));
        assert(samples[index].generation == 1u && samples[index].read_ok);
    }

    /* A timeout in a new generation invalidates the entire snapshot, while
     * the scanner still visits every remaining ID for diagnostics. */
    assert(servo_group_readonly_begin_cycle(&group));
    assert(servo_group_readonly_prepare(&group, 200u, request,
                                        sizeof(request)) == 8u);
    servo_group_readonly_tick(&group, 205u);
    for (index = 1u; index < 8u; ++index)
    {
        complete_one(&group, ids[index], (uint16_t)(600u + index),
                     (uint32_t)(205u + index));
    }
    count = 99u;
    assert(group.cycle_complete && !group.cycle_valid);
    assert(!servo_group_readonly_snapshot(&group, samples, 8u, &count));
    assert(count == 0u && group.invalid_cycles == 1u);

    /* Wrong-ID traffic cannot satisfy a request. A transmit failure also
     * advances safely and prevents publication of a mixed snapshot. */
    assert(servo_group_readonly_begin_cycle(&group));
    assert(servo_group_readonly_prepare(&group, 300u, request,
                                        sizeof(request)) == 8u);
    feed(&group, wrong_response,
         make_feedback(2u, 700u, 0u, 0u, 50u, 25u, wrong_response));
    assert(group.transaction.state == SCS0009_TXN_WAIT_STATUS);
    servo_group_readonly_tick(&group, 305u);
    assert(servo_group_readonly_prepare(&group, 306u, request,
                                        sizeof(request)) == 8u);
    servo_group_readonly_note_tx_failed(&group);
    for (index = 2u; index < 8u; ++index)
    {
        complete_one(&group, ids[index], (uint16_t)(700u + index),
                     (uint32_t)(306u + index));
    }
    assert(group.completed_cycles == 3u && group.invalid_cycles == 2u);
    assert(group.failed_reads == 3u);
    assert(!servo_group_readonly_snapshot(&group, samples, 8u, &count));

    puts("Eight-servo read-only group tests passed");
    return 0;
}
