#include "scs0009_packet.h"

#define SCS_HEADER 0xFFu
#define SCS_INST_PING 0x01u
#define SCS_INST_READ 0x02u
#define SCS_INST_WRITE 0x03u
#define SCS_INST_REG_WRITE 0x04u
#define SCS_INST_ACTION 0x05u
#define SCS_INST_SYNC_WRITE 0x83u
#define SCS_ADDR_TORQUE_ENABLE 40u
#define SCS_ADDR_GOAL_POSITION 42u

static int valid_unicast_id(uint8_t id)
{
    return id <= SCS0009_MAX_ID;
}

static uint8_t checksum(const uint8_t *packet, size_t total_length)
{
    uint8_t sum = 0u;
    size_t index;
    for (index = 2u; index + 1u < total_length; ++index)
    {
        sum = (uint8_t)(sum + packet[index]);
    }
    return (uint8_t)(~sum);
}

static void finish_packet(uint8_t *output, size_t total_length)
{
    output[0] = SCS_HEADER;
    output[1] = SCS_HEADER;
    output[total_length - 1u] = checksum(output, total_length);
}

static void put_u16_be(uint8_t *output, uint16_t value)
{
    output[0] = (uint8_t)(value >> 8u);
    output[1] = (uint8_t)(value & 0xFFu);
}

size_t scs0009_build_ping(uint8_t id, uint8_t *output, size_t capacity)
{
    const size_t total = 6u;
    if (!valid_unicast_id(id) || output == NULL || capacity < total)
    {
        return 0u;
    }
    output[2] = id;
    output[3] = 2u;
    output[4] = SCS_INST_PING;
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_read(uint8_t id,
                          uint8_t address,
                          uint8_t data_length,
                          uint8_t *output,
                          size_t capacity)
{
    const size_t total = 8u;
    if (!valid_unicast_id(id) || data_length == 0u || output == NULL || capacity < total)
    {
        return 0u;
    }
    output[2] = id;
    output[3] = 4u;
    output[4] = SCS_INST_READ;
    output[5] = address;
    output[6] = data_length;
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_torque(uint8_t id,
                            uint8_t enable,
                            uint8_t *output,
                            size_t capacity)
{
    const size_t total = 8u;
    if (!valid_unicast_id(id) || enable > 1u || output == NULL || capacity < total)
    {
        return 0u;
    }
    output[2] = id;
    output[3] = 4u;
    output[4] = SCS_INST_WRITE;
    output[5] = SCS_ADDR_TORQUE_ENABLE;
    output[6] = enable;
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_write_position(uint8_t id,
                                    uint16_t position,
                                    uint16_t time_raw,
                                    uint16_t speed_raw,
                                    uint8_t *output,
                                    size_t capacity)
{
    const size_t total = 13u;
    if (!valid_unicast_id(id) || position > 1023u || output == NULL || capacity < total)
    {
        return 0u;
    }
    output[2] = id;
    output[3] = 9u;
    output[4] = SCS_INST_WRITE;
    output[5] = SCS_ADDR_GOAL_POSITION;
    put_u16_be(&output[6], position);
    put_u16_be(&output[8], time_raw);
    put_u16_be(&output[10], speed_raw);
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_reg_write_position(uint8_t id,
                                        uint16_t position,
                                        uint16_t time_raw,
                                        uint16_t speed_raw,
                                        uint8_t *output,
                                        size_t capacity)
{
    const size_t total = 13u;
    if (!valid_unicast_id(id) || position > 1023u || output == NULL ||
        capacity < total)
    {
        return 0u;
    }
    output[2] = id;
    output[3] = 9u;
    output[4] = SCS_INST_REG_WRITE;
    output[5] = SCS_ADDR_GOAL_POSITION;
    put_u16_be(&output[6], position);
    put_u16_be(&output[8], time_raw);
    put_u16_be(&output[10], speed_raw);
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_action(uint8_t *output, size_t capacity)
{
    const size_t total = 6u;
    if (output == NULL || capacity < total)
    {
        return 0u;
    }
    output[2] = SCS0009_BROADCAST_ID;
    output[3] = 2u;
    output[4] = SCS_INST_ACTION;
    finish_packet(output, total);
    return total;
}

size_t scs0009_build_sync_write_positions(uint8_t id1,
                                          uint16_t position1,
                                          uint8_t id2,
                                          uint16_t position2,
                                          uint16_t time_raw,
                                          uint16_t speed_raw,
                                          uint8_t *output,
                                          size_t capacity)
{
    scs0009_sync_goal_t goals[2];
    goals[0].id = id1;
    goals[0].position = position1;
    goals[0].time_raw = time_raw;
    goals[0].speed_raw = speed_raw;
    goals[1].id = id2;
    goals[1].position = position2;
    goals[1].time_raw = time_raw;
    goals[1].speed_raw = speed_raw;
    return scs0009_build_sync_write_position_group(goals, 2u, output,
                                                    capacity);
}

size_t scs0009_build_sync_write_position_group(
    const scs0009_sync_goal_t *goals,
    size_t goal_count,
    uint8_t *output,
    size_t capacity)
{
    size_t index;
    size_t previous;
    const size_t total = 8u + (7u * goal_count);
    if (goals == NULL || output == NULL || goal_count == 0u ||
        goal_count > SCS0009_SYNC_WRITE_MAX_COUNT || capacity < total)
    {
        return 0u;
    }
    for (index = 0u; index < goal_count; ++index)
    {
        if (!valid_unicast_id(goals[index].id) ||
            goals[index].position > 1023u)
        {
            return 0u;
        }
        for (previous = 0u; previous < index; ++previous)
        {
            if (goals[previous].id == goals[index].id)
            {
                return 0u;
            }
        }
    }
    output[2] = SCS0009_BROADCAST_ID;
    output[3] = (uint8_t)(total - 4u);
    output[4] = SCS_INST_SYNC_WRITE;
    output[5] = SCS_ADDR_GOAL_POSITION;
    output[6] = 6u;
    for (index = 0u; index < goal_count; ++index)
    {
        size_t offset = 7u + (7u * index);
        output[offset] = goals[index].id;
        put_u16_be(&output[offset + 1u], goals[index].position);
        put_u16_be(&output[offset + 3u], goals[index].time_raw);
        put_u16_be(&output[offset + 5u], goals[index].speed_raw);
    }
    finish_packet(output, total);
    return total;
}

scs0009_packet_result_t scs0009_parse_status(const uint8_t *packet,
                                             size_t packet_length,
                                             uint8_t expected_id,
                                             scs0009_status_packet_t *status)
{
    size_t expected_length;
    size_t param_count;
    size_t index;
    if (packet == NULL || status == NULL || !valid_unicast_id(expected_id))
    {
        return SCS0009_PACKET_INVALID_ARGUMENT;
    }
    if (packet_length < 6u || packet[0] != SCS_HEADER || packet[1] != SCS_HEADER)
    {
        return SCS0009_PACKET_BAD_HEADER;
    }
    expected_length = (size_t)packet[3] + 4u;
    if (packet[3] < 2u || expected_length != packet_length)
    {
        return SCS0009_PACKET_BAD_LENGTH;
    }
    if (packet[2] != expected_id)
    {
        return SCS0009_PACKET_BAD_ID;
    }
    if (packet[packet_length - 1u] != checksum(packet, packet_length))
    {
        return SCS0009_PACKET_BAD_CHECKSUM;
    }
    param_count = (size_t)packet[3] - 2u;
    if (param_count > SCS0009_MAX_STATUS_PARAMS)
    {
        return SCS0009_PACKET_BAD_LENGTH;
    }
    status->id = packet[2];
    status->error = packet[4];
    status->param_count = param_count;
    for (index = 0u; index < param_count; ++index)
    {
        status->params[index] = packet[5u + index];
    }
    return SCS0009_PACKET_OK;
}

uint16_t scs0009_decode_u16_be(const uint8_t *data)
{
    if (data == NULL)
    {
        return 0u;
    }
    return (uint16_t)(((uint16_t)data[0] << 8u) | (uint16_t)data[1]);
}
