#include "scs0009_stream.h"

#include <assert.h>
#include <stdio.h>

static scs0009_stream_result_t feed_packet(scs0009_stream_parser_t *parser,
                                           const uint8_t *packet,
                                           size_t length,
                                           scs0009_status_packet_t *status)
{
    size_t index;
    scs0009_stream_result_t result = SCS0009_STREAM_NONE;
    for (index = 0u; index < length; ++index)
    {
        result = scs0009_stream_feed(parser, packet[index], status);
    }
    return result;
}

int main(void)
{
    const uint8_t valid[] = {
        0xFFu, 0xFFu, 0x01u, 0x04u, 0x00u, 0x01u, 0xFFu, 0xFAu};
    const uint8_t wrong_id[] = {
        0xFFu, 0xFFu, 0x02u, 0x04u, 0x00u, 0x01u, 0xFFu, 0xF9u};
    uint8_t corrupt[sizeof(valid)];
    scs0009_stream_parser_t parser;
    scs0009_status_packet_t status;
    size_t index;

    scs0009_stream_init(&parser, 1u);
    for (index = 0u; index + 1u < sizeof(valid); ++index)
    {
        assert(scs0009_stream_feed(&parser, valid[index], &status) ==
               SCS0009_STREAM_NONE);
    }
    assert(scs0009_stream_feed(&parser, valid[sizeof(valid) - 1u], &status) ==
           SCS0009_STREAM_FRAME);
    assert(parser.frames_ok == 1u);
    assert(status.id == 1u && scs0009_decode_u16_be(status.params) == 511u);

    scs0009_stream_init(&parser, 1u);
    assert(scs0009_stream_feed(&parser, 0x12u, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0x34u, &status) == SCS0009_STREAM_NONE);
    assert(feed_packet(&parser, valid, sizeof(valid), &status) == SCS0009_STREAM_FRAME);
    assert(parser.bytes_discarded == 2u && parser.frames_ok == 1u);

    scs0009_stream_init(&parser, 1u);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_REJECTED);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_REJECTED);
    for (index = 2u; index < sizeof(valid); ++index)
    {
        (void)scs0009_stream_feed(&parser, valid[index], &status);
    }
    assert(parser.frames_ok == 1u);

    scs0009_stream_init(&parser, 1u);
    for (index = 0u; index < sizeof(valid); ++index)
    {
        corrupt[index] = valid[index];
    }
    corrupt[sizeof(corrupt) - 1u] ^= 1u;
    assert(feed_packet(&parser, corrupt, sizeof(corrupt), &status) ==
           SCS0009_STREAM_REJECTED);
    assert(parser.bad_checksum == 1u);
    assert(feed_packet(&parser, valid, sizeof(valid), &status) == SCS0009_STREAM_FRAME);
    assert(parser.frames_ok == 1u);

    scs0009_stream_init(&parser, 1u);
    assert(feed_packet(&parser, wrong_id, sizeof(wrong_id), &status) ==
           SCS0009_STREAM_REJECTED);
    assert(parser.wrong_id == 1u);
    assert(feed_packet(&parser, valid, sizeof(valid), &status) == SCS0009_STREAM_FRAME);

    scs0009_stream_init(&parser, 1u);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0x01u, &status) == SCS0009_STREAM_NONE);
    assert(scs0009_stream_feed(&parser, 0xFFu, &status) == SCS0009_STREAM_REJECTED);
    assert(parser.bad_length == 1u);
    assert(feed_packet(&parser, valid, sizeof(valid), &status) == SCS0009_STREAM_FRAME);

    scs0009_stream_init(&parser, 1u);
    (void)scs0009_stream_feed(&parser, 0xFFu, &status);
    (void)scs0009_stream_feed(&parser, 0xFFu, &status);
    (void)scs0009_stream_feed(&parser, 0x01u, &status);
    scs0009_stream_reset(&parser);
    assert(parser.length == 0u && parser.expected_length == 0u);
    assert(feed_packet(&parser, valid, sizeof(valid), &status) == SCS0009_STREAM_FRAME);

    puts("SCS0009 stream tests passed");
    return 0;
}
