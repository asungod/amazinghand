#ifndef SCS0009_STREAM_H
#define SCS0009_STREAM_H

#include "scs0009_packet.h"

#include <stddef.h>
#include <stdint.h>

#define SCS0009_MAX_STATUS_PACKET (SCS0009_MAX_STATUS_PARAMS + 6u)

typedef enum
{
    SCS0009_STREAM_NONE = 0,
    SCS0009_STREAM_FRAME,
    SCS0009_STREAM_REJECTED
} scs0009_stream_result_t;

typedef struct
{
    uint8_t buffer[SCS0009_MAX_STATUS_PACKET];
    size_t length;
    size_t expected_length;
    uint8_t expected_id;
    uint32_t frames_ok;
    uint32_t bad_length;
    uint32_t bad_checksum;
    uint32_t wrong_id;
    uint32_t bytes_discarded;
} scs0009_stream_parser_t;

void scs0009_stream_init(scs0009_stream_parser_t *parser, uint8_t expected_id);
void scs0009_stream_reset(scs0009_stream_parser_t *parser);
scs0009_stream_result_t scs0009_stream_feed(scs0009_stream_parser_t *parser,
                                            uint8_t byte,
                                            scs0009_status_packet_t *status);

#endif
