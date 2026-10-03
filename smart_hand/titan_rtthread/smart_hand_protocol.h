#ifndef SMART_HAND_PROTOCOL_H
#define SMART_HAND_PROTOCOL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SHP_MAX_FRAME_SIZE 128
#define SHP_MAX_ARGS 8

typedef enum
{
    SHP_TYPE_UNKNOWN = 0,
    SHP_TYPE_PING,
    SHP_TYPE_ACK,
    SHP_TYPE_VISION,
    SHP_TYPE_STATUS,
    SHP_TYPE_TRAIN,
    SHP_TYPE_TRAINSTAT,
    SHP_TYPE_SIGN,
    SHP_TYPE_SIGNSTAT
} shp_message_type_t;

typedef struct
{
    shp_message_type_t type;
    uint16_t sequence;
    uint8_t arg_count;
    uint32_t args[SHP_MAX_ARGS];
} shp_message_t;

typedef struct
{
    char buffer[SHP_MAX_FRAME_SIZE];
    size_t length;
} shp_parser_t;

void shp_parser_init(shp_parser_t *parser);
int shp_parser_feed(shp_parser_t *parser, uint8_t byte, shp_message_t *message);
uint16_t shp_crc16_ccitt(const uint8_t *data, size_t length);
int shp_encode(char *output,
               size_t output_size,
               const char *type,
               uint16_t sequence,
               const uint32_t *args,
               uint8_t arg_count);

#ifdef __cplusplus
}
#endif

#endif
