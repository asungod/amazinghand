#include "scs0009_stream.h"

#include <string.h>

#define SCS_HEADER 0xFFu

static void reset_frame(scs0009_stream_parser_t *parser)
{
    parser->length = 0u;
    parser->expected_length = 0u;
}

void scs0009_stream_init(scs0009_stream_parser_t *parser, uint8_t expected_id)
{
    if (parser == NULL)
    {
        return;
    }
    memset(parser, 0, sizeof(*parser));
    parser->expected_id = expected_id;
}

void scs0009_stream_reset(scs0009_stream_parser_t *parser)
{
    if (parser != NULL)
    {
        reset_frame(parser);
    }
}

scs0009_stream_result_t scs0009_stream_feed(scs0009_stream_parser_t *parser,
                                            uint8_t byte,
                                            scs0009_status_packet_t *status)
{
    scs0009_packet_result_t parse_result;
    if (parser == NULL || status == NULL || parser->expected_id > SCS0009_MAX_ID)
    {
        return SCS0009_STREAM_REJECTED;
    }

    if (parser->length == 0u)
    {
        if (byte == SCS_HEADER)
        {
            parser->buffer[0] = byte;
            parser->length = 1u;
        }
        else
        {
            parser->bytes_discarded++;
        }
        return SCS0009_STREAM_NONE;
    }

    if (parser->length == 1u)
    {
        if (byte == SCS_HEADER)
        {
            parser->buffer[1] = byte;
            parser->length = 2u;
        }
        else
        {
            parser->bytes_discarded += 2u;
            reset_frame(parser);
        }
        return SCS0009_STREAM_NONE;
    }

    if (parser->length >= sizeof(parser->buffer))
    {
        parser->bad_length++;
        reset_frame(parser);
        return SCS0009_STREAM_REJECTED;
    }

    parser->buffer[parser->length++] = byte;
    if (parser->length == 3u && parser->buffer[2] > SCS0009_MAX_ID)
    {
        parser->wrong_id++;
        if (byte == SCS_HEADER)
        {
            /* In FF FF FF... noise, the last two bytes are still a possible
             * header. Keep them so the first following legal ID is accepted. */
            parser->buffer[0] = SCS_HEADER;
            parser->buffer[1] = SCS_HEADER;
            parser->length = 2u;
            parser->expected_length = 0u;
        }
        else
        {
            reset_frame(parser);
        }
        return SCS0009_STREAM_REJECTED;
    }
    if (parser->length == 4u)
    {
        if (parser->buffer[3] < 2u ||
            (size_t)parser->buffer[3] + 4u > sizeof(parser->buffer))
        {
            parser->bad_length++;
            reset_frame(parser);
            return SCS0009_STREAM_REJECTED;
        }
        parser->expected_length = (size_t)parser->buffer[3] + 4u;
    }

    if (parser->expected_length == 0u || parser->length < parser->expected_length)
    {
        return SCS0009_STREAM_NONE;
    }

    parse_result = scs0009_parse_status(parser->buffer,
                                        parser->length,
                                        parser->expected_id,
                                        status);
    if (parse_result == SCS0009_PACKET_OK)
    {
        parser->frames_ok++;
        reset_frame(parser);
        return SCS0009_STREAM_FRAME;
    }
    if (parse_result == SCS0009_PACKET_BAD_CHECKSUM)
    {
        parser->bad_checksum++;
    }
    else if (parse_result == SCS0009_PACKET_BAD_ID)
    {
        parser->wrong_id++;
    }
    else
    {
        parser->bad_length++;
    }
    /* A rejected packet is discarded in full.  Retaining its final 0xFF as a
     * possible next header can consume the first byte of the following valid
     * FF FF frame and delay recovery by another transaction. */
    reset_frame(parser);
    return SCS0009_STREAM_REJECTED;
}
