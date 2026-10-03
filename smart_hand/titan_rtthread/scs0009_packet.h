#ifndef SCS0009_PACKET_H
#define SCS0009_PACKET_H

#include <stddef.h>
#include <stdint.h>

#define SCS0009_MAX_ID 253u
#define SCS0009_BROADCAST_ID 254u
#define SCS0009_MAX_STATUS_PARAMS 16u
#define SCS0009_SYNC_WRITE_MAX_COUNT 8u
#define SCS0009_SYNC_WRITE_POSITION_MAX_PACKET_SIZE 64u

typedef struct
{
    uint8_t id;
    uint16_t position;
    uint16_t time_raw;
    uint16_t speed_raw;
} scs0009_sync_goal_t;

typedef enum
{
    SCS0009_PACKET_OK = 0,
    SCS0009_PACKET_INVALID_ARGUMENT,
    SCS0009_PACKET_BUFFER_TOO_SMALL,
    SCS0009_PACKET_BAD_HEADER,
    SCS0009_PACKET_BAD_LENGTH,
    SCS0009_PACKET_BAD_ID,
    SCS0009_PACKET_BAD_CHECKSUM
} scs0009_packet_result_t;

typedef struct
{
    uint8_t id;
    uint8_t error;
    uint8_t params[SCS0009_MAX_STATUS_PARAMS];
    size_t param_count;
} scs0009_status_packet_t;

size_t scs0009_build_ping(uint8_t id, uint8_t *output, size_t capacity);
size_t scs0009_build_read(uint8_t id,
                          uint8_t address,
                          uint8_t data_length,
                          uint8_t *output,
                          size_t capacity);
size_t scs0009_build_torque(uint8_t id,
                            uint8_t enable,
                            uint8_t *output,
                            size_t capacity);
size_t scs0009_build_write_position(uint8_t id,
                                    uint16_t position,
                                    uint16_t time_raw,
                                    uint16_t speed_raw,
                                    uint8_t *output,
                                    size_t capacity);
size_t scs0009_build_reg_write_position(uint8_t id,
                                        uint16_t position,
                                        uint16_t time_raw,
                                        uint16_t speed_raw,
                                        uint8_t *output,
                                        size_t capacity);
size_t scs0009_build_action(uint8_t *output, size_t capacity);
size_t scs0009_build_sync_write_positions(uint8_t id1,
                                          uint16_t position1,
                                          uint8_t id2,
                                          uint16_t position2,
                                          uint16_t time_raw,
                                          uint16_t speed_raw,
                                          uint8_t *output,
                                          size_t capacity);
size_t scs0009_build_sync_write_position_group(
    const scs0009_sync_goal_t *goals,
    size_t goal_count,
    uint8_t *output,
    size_t capacity);
scs0009_packet_result_t scs0009_parse_status(const uint8_t *packet,
                                             size_t packet_length,
                                             uint8_t expected_id,
                                             scs0009_status_packet_t *status);
uint16_t scs0009_decode_u16_be(const uint8_t *data);

#endif
