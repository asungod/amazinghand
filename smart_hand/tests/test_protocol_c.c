#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "smart_hand_protocol.h"

static int feed_text(shp_parser_t *parser,
                     const char *text,
                     shp_message_t *message)
{
    int result = 0;
    while (*text != '\0')
    {
        result = shp_parser_feed(parser, (uint8_t)*text++, message);
    }
    return result;
}

static void make_raw_frame(char *output, size_t output_size, const char *body)
{
    uint16_t crc = shp_crc16_ccitt((const uint8_t *)body, strlen(body));
    int written = snprintf(output, output_size, "$%s*%04X\r\n", body, crc);
    assert(written > 0);
    assert((size_t)written < output_size);
}

static uint32_t next_random(uint32_t *state)
{
    *state = *state * 1664525U + 1013904223U;
    return *state;
}

static void test_random_stream_recovery(void)
{
    shp_parser_t parser;
    shp_message_t message;
    uint32_t random_state = 0x5A17C0DEU;
    int iteration;
    int byte_index;

    for (iteration = 0; iteration < 1000; ++iteration)
    {
        shp_parser_init(&parser);
        for (byte_index = 0; byte_index < 512; ++byte_index)
        {
            uint8_t byte = (uint8_t)(next_random(&random_state) >> 24);
            (void)shp_parser_feed(&parser, byte, &message);
        }
        assert(feed_text(&parser, "$PING,4*A637\r\n", &message) == 1);
        assert(message.type == SHP_TYPE_PING);
        assert(message.sequence == 4);
    }
}

int main(void)
{
    shp_parser_t parser;
    shp_message_t message;
    char output[SHP_MAX_FRAME_SIZE];
    uint32_t ack_status = 0;
    int length;
    char raw[SHP_MAX_FRAME_SIZE];

    shp_parser_init(&parser);
    assert(feed_text(&parser, "$PING,1*F692\r\n", &message) == 1);
    assert(message.type == SHP_TYPE_PING);
    assert(message.sequence == 1);
    assert(message.arg_count == 0);

    shp_parser_init(&parser);
    assert(feed_text(&parser,
                     "$VISION,2,3,320,240,80,120,96*46F6\r\n",
                     &message) == 1);
    assert(message.type == SHP_TYPE_VISION);
    assert(message.sequence == 2);
    assert(message.arg_count == 6);
    assert(message.args[0] == 3);
    assert(message.args[5] == 96);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "TRAIN,3,1");
    assert(feed_text(&parser, raw, &message) == 1);
    assert(message.type == SHP_TYPE_TRAIN);
    assert(message.sequence == 3);
    assert(message.arg_count == 1);
    assert(message.args[0] == 1U);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "TRAINSTAT,4,1,3,2,0,7");
    assert(feed_text(&parser, raw, &message) == 1);
    assert(message.type == SHP_TYPE_TRAINSTAT);
    assert(message.sequence == 4);
    assert(message.arg_count == 5);
    assert(message.args[1] == 3U);
    assert(message.args[2] == 2U);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "SIGN,5,1,1,1");
    assert(feed_text(&parser, raw, &message) == 1);
    assert(message.type == SHP_TYPE_SIGN);
    assert(message.sequence == 5);
    assert(message.arg_count == 3);
    assert(message.args[0] == 1U && message.args[1] == 1U &&
           message.args[2] == 1U);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "SIGNSTAT,6,1,5,1,5,0,2,1");
    assert(feed_text(&parser, raw, &message) == 1);
    assert(message.type == SHP_TYPE_SIGNSTAT);
    assert(message.arg_count == 7);
    assert(message.args[3] == 5U && message.args[6] == 1U);

    length = shp_encode(output, sizeof(output), "ACK", 2, &ack_status, 1);
    assert(length > 0);
    assert(strcmp(output, "$ACK,2,0*6B45\r\n") == 0);

    shp_parser_init(&parser);
    assert(feed_text(&parser, "$PING,1*0000\r\n", &message) == -1);
    assert(feed_text(&parser, "garbage$PING,4*A637\r\n", &message) == 1);
    assert(message.sequence == 4);

    shp_parser_init(&parser);
    assert(feed_text(&parser,
                     "$VISION,broken$PING,4*A637\r\n",
                     &message) == 1);
    assert(message.sequence == 4);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "PING,,1");
    assert(feed_text(&parser, raw, &message) == -1);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "VISION,3,-1,1,1,1,1,90");
    assert(feed_text(&parser, raw, &message) == -1);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "PING,65536");
    assert(feed_text(&parser, raw, &message) == -1);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "STATUS,8,4294967295,0");
    assert(feed_text(&parser, raw, &message) == 1);
    assert(message.args[0] == UINT32_MAX);

    shp_parser_init(&parser);
    make_raw_frame(raw, sizeof(raw), "STATUS,8,0,1,2,3,4,5,6,7,8");
    assert(feed_text(&parser, raw, &message) == -1);

    assert(shp_encode(output, sizeof(output), "ACK", 2, NULL, 1) == -1);

    test_random_stream_recovery();

    puts("C protocol tests passed");
    return 0;
}
