#include "servo_feedback_poll.h"

#include <assert.h>
#include <stdio.h>

static size_t make_feedback(uint8_t id,
                            uint16_t position,
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
    packet[7] = 0u;
    packet[8] = 0x12u;
    packet[9] = 0u;
    packet[10] = 0x34u;
    packet[11] = voltage;
    packet[12] = temperature;
    for (index = 2u; index < 13u; ++index)
    {
        sum = (uint8_t)(sum + packet[index]);
    }
    packet[13] = (uint8_t)(~sum);
    return 14u;
}

static void feed(servo_feedback_poll_t *poll,
                 const uint8_t *packet,
                 size_t length,
                 uint32_t now_ms)
{
    size_t index;
    for (index = 0u; index < length; ++index)
    {
        servo_feedback_poll_feed(poll, packet[index], now_ms);
    }
}

int main(void)
{
    servo_feedback_poll_t poll;
    servo_gate_observation_t snapshot[SERVO_GATE_COUNT];
    servo_feedback_detail_t details[SERVO_GATE_COUNT];
    uint8_t request[16];
    uint8_t response[14];
    size_t length;

    assert(servo_feedback_poll_init(&poll, 1u, 2u, 100u, 50u, 5u));
    length = servo_feedback_poll_prepare(&poll, 100u, request, sizeof(request));
    assert(length == 8u && request[2] == 1u && request[5] == 56u && request[6] == 8u);
    feed(&poll, response, make_feedback(1u, 511u, 60u, 25u, response), 101u);

    length = servo_feedback_poll_prepare(&poll, 101u, request, sizeof(request));
    assert(length == 8u && request[2] == 2u);
    feed(&poll, response, make_feedback(2u, 512u, 59u, 26u, response), 102u);
    assert(poll.successful_reads == 2u && poll.completed_cycles == 1u);
    assert(servo_feedback_poll_prepare(&poll, 151u, request, sizeof(request)) == 0u);
    assert(servo_feedback_poll_prepare(&poll, 152u, request, sizeof(request)) == 8u);

    servo_feedback_poll_snapshot(&poll, 154u, snapshot);
    assert(snapshot[0].read_ok && snapshot[0].position_raw == 511u);
    assert(snapshot[0].voltage_raw == 60u && snapshot[0].temperature_raw == 25u);
    assert(snapshot[0].age_ms == 53u && snapshot[1].age_ms == 52u);
    servo_feedback_poll_detail_snapshot(&poll, 154u, details);
    assert(details[0].speed_raw == 0x12u && details[0].load_raw == 0x34u);
    assert(details[0].position_raw == 511u && details[0].age_ms == 53u);

    /* Current ID1 request times out; scheduler continues to ID2 without
     * presenting the old ID1 value as fresh. */
    servo_feedback_poll_tick(&poll, 157u);
    assert(poll.failed_reads == 1u);
    servo_feedback_poll_snapshot(&poll, 157u, snapshot);
    assert(!snapshot[0].read_ok && snapshot[0].age_ms == UINT32_MAX);
    assert(servo_feedback_poll_prepare(&poll, 157u, request, sizeof(request)) == 8u);
    assert(request[2] == 2u);
    servo_feedback_poll_note_tx_failed(&poll, 158u);
    assert(poll.failed_reads == 2u && poll.completed_cycles == 2u);

    assert(!servo_feedback_poll_init(&poll, 1u, 1u, 0u, 50u, 5u));
    assert(!servo_feedback_poll_init(&poll, 1u, 2u, 0u, 5u, 6u));

    puts("Servo feedback poll tests passed");
    return 0;
}
