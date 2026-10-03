#include "scs0009_packet.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static void expect_bytes(const uint8_t *actual,
                         const uint8_t *expected,
                         size_t length)
{
    assert(memcmp(actual, expected, length) == 0);
}

int main(void)
{
    uint8_t packet[SCS0009_SYNC_WRITE_POSITION_MAX_PACKET_SIZE] = {0u};
    scs0009_status_packet_t status;
    size_t length;

    const uint8_t ping_id1[] = {0xFFu, 0xFFu, 0x01u, 0x02u, 0x01u, 0xFBu};
    length = scs0009_build_ping(1u, packet, sizeof(packet));
    assert(length == sizeof(ping_id1));
    expect_bytes(packet, ping_id1, length);

    {
        const uint8_t reg_write_id3[] = {
            0xFFu, 0xFFu, 0x03u, 0x09u, 0x04u, 0x2Au, 0x02u,
            0x92u, 0x00u, 0x00u, 0x00u, 0x3Cu, 0xF5u};
        length = scs0009_build_reg_write_position(
            3u, 658u, 0u, 60u, packet, sizeof(packet));
        assert(length == sizeof(reg_write_id3));
        expect_bytes(packet, reg_write_id3, length);
        assert(scs0009_build_reg_write_position(
                   3u, 1024u, 0u, 60u, packet, sizeof(packet)) == 0u);
    }

    {
        const uint8_t action[] = {
            0xFFu, 0xFFu, 0xFEu, 0x02u, 0x05u, 0xFAu};
        length = scs0009_build_action(packet, sizeof(packet));
        assert(length == sizeof(action));
        expect_bytes(packet, action, length);
        assert(scs0009_build_action(packet, sizeof(action) - 1u) == 0u);
    }

    const uint8_t read_position_id1[] = {
        0xFFu, 0xFFu, 0x01u, 0x04u, 0x02u, 0x38u, 0x02u, 0xBEu};
    length = scs0009_build_read(1u, 56u, 2u, packet, sizeof(packet));
    assert(length == sizeof(read_position_id1));
    expect_bytes(packet, read_position_id1, length);

    const uint8_t torque_id1[] = {
        0xFFu, 0xFFu, 0x01u, 0x04u, 0x03u, 0x28u, 0x01u, 0xCEu};
    length = scs0009_build_torque(1u, 1u, packet, sizeof(packet));
    assert(length == sizeof(torque_id1));
    expect_bytes(packet, torque_id1, length);

    const uint8_t position_id1[] = {
        0xFFu, 0xFFu, 0x01u, 0x09u, 0x03u, 0x2Au, 0x01u,
        0xFFu, 0x00u, 0x00u, 0x00u, 0x64u, 0x64u};
    length = scs0009_build_write_position(1u, 511u, 0u, 100u,
                                          packet, sizeof(packet));
    assert(length == sizeof(position_id1));
    expect_bytes(packet, position_id1, length);

    length = scs0009_build_sync_write_positions(1u, 523u, 2u, 499u,
                                                 0u, 60u, packet, sizeof(packet));
    assert(length == 22u);
    assert(packet[0] == 0xFFu && packet[1] == 0xFFu);
    assert(packet[2] == 0xFEu && packet[3] == 18u && packet[4] == 0x83u);
    assert(packet[5] == 42u && packet[6] == 6u);
    assert(packet[7] == 1u && scs0009_decode_u16_be(&packet[8]) == 523u);
    assert(packet[14] == 2u && scs0009_decode_u16_be(&packet[15]) == 499u);

    {
        scs0009_sync_goal_t goals[SCS0009_SYNC_WRITE_MAX_COUNT];
        size_t index;
        for (index = 0u; index < SCS0009_SYNC_WRITE_MAX_COUNT; ++index)
        {
            goals[index].id = (uint8_t)(index + 1u);
            goals[index].position = (uint16_t)(500u + index);
            goals[index].time_raw = 0u;
            goals[index].speed_raw = 60u;
        }
        length = scs0009_build_sync_write_position_group(
            goals, SCS0009_SYNC_WRITE_MAX_COUNT, packet, sizeof(packet));
        assert(length == 64u);
        assert(packet[2] == SCS0009_BROADCAST_ID && packet[3] == 60u);
        assert(packet[7] == 1u && scs0009_decode_u16_be(&packet[8]) == 500u);
        assert(packet[56] == 8u && scs0009_decode_u16_be(&packet[57]) == 507u);
        assert(scs0009_build_sync_write_position_group(
                   goals, SCS0009_SYNC_WRITE_MAX_COUNT, packet,
                   sizeof(packet) - 1u) == 0u);
        goals[7].id = 1u;
        assert(scs0009_build_sync_write_position_group(
                   goals, SCS0009_SYNC_WRITE_MAX_COUNT, packet,
                   sizeof(packet)) == 0u);
    }

    {
        const uint8_t status_position[] = {
            0xFFu, 0xFFu, 0x01u, 0x04u, 0x00u, 0x01u, 0xFFu, 0xFAu};
        assert(scs0009_parse_status(status_position, sizeof(status_position),
                                    1u, &status) == SCS0009_PACKET_OK);
        assert(status.id == 1u && status.error == 0u && status.param_count == 2u);
        assert(scs0009_decode_u16_be(status.params) == 511u);

        packet[0] = 0u;
        memcpy(packet, status_position, sizeof(status_position));
        packet[7] ^= 1u;
        assert(scs0009_parse_status(packet, sizeof(status_position), 1u, &status) ==
               SCS0009_PACKET_BAD_CHECKSUM);
        assert(scs0009_parse_status(status_position, sizeof(status_position),
                                    2u, &status) == SCS0009_PACKET_BAD_ID);
        assert(scs0009_parse_status(status_position, sizeof(status_position) - 1u,
                                    1u, &status) == SCS0009_PACKET_BAD_LENGTH);
    }

    assert(scs0009_build_ping(254u, packet, sizeof(packet)) == 0u);
    assert(scs0009_build_torque(1u, 2u, packet, sizeof(packet)) == 0u);
    assert(scs0009_build_write_position(1u, 1024u, 0u, 60u,
                                        packet, sizeof(packet)) == 0u);
    assert(scs0009_build_sync_write_positions(1u, 511u, 1u, 511u,
                                               0u, 60u, packet,
                                               sizeof(packet)) == 0u);

    puts("SCS0009 packet tests passed");
    return 0;
}
