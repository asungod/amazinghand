#include "smart_hand_protocol.h"

#include <stdio.h>
#include <string.h>

static int parse_hex16(const char *text, uint16_t *value)
{
    uint16_t result = 0;
    size_t i;

    if (text == NULL || value == NULL || strlen(text) != 4U) return -1;
    for (i = 0; i < 4U; ++i)
    {
        uint8_t digit;
        char ch = text[i];

        if (ch >= '0' && ch <= '9') digit = (uint8_t)(ch - '0');
        else if (ch >= 'A' && ch <= 'F') digit = (uint8_t)(ch - 'A' + 10);
        else if (ch >= 'a' && ch <= 'f') digit = (uint8_t)(ch - 'a' + 10);
        else return -1;
        result = (uint16_t)((result << 4) | digit);
    }
    *value = result;
    return 0;
}

static int parse_u32_decimal(const char *text, uint32_t maximum, uint32_t *value)
{
    uint32_t result = 0;
    const char *cursor = text;

    if (text == NULL || value == NULL || *text == '\0') return -1;
    while (*cursor != '\0')
    {
        uint32_t digit;

        if (*cursor < '0' || *cursor > '9') return -1;
        digit = (uint32_t)(*cursor - '0');
        if (result > (maximum - digit) / 10U) return -1;
        result = result * 10U + digit;
        ++cursor;
    }
    *value = result;
    return 0;
}

static int next_token(char **cursor, char **token)
{
    char *comma;

    if (cursor == NULL || token == NULL || *cursor == NULL || **cursor == '\0') return -1;
    *token = *cursor;
    comma = strchr(*cursor, ',');
    if (comma == NULL)
    {
        *cursor = NULL;
    }
    else
    {
        *comma = '\0';
        *cursor = comma + 1;
        if (**cursor == '\0') return -1;
    }
    return **token == '\0' ? -1 : 0;
}

uint16_t shp_crc16_ccitt(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xFFFF;
    size_t i;
    int bit;

    for (i = 0; i < length; ++i)
    {
        crc ^= (uint16_t)data[i] << 8;
        for (bit = 0; bit < 8; ++bit)
        {
            crc = (crc & 0x8000U) ? (uint16_t)((crc << 1) ^ 0x1021U)
                                  : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

void shp_parser_init(shp_parser_t *parser)
{
    if (parser != NULL)
    {
        parser->length = 0;
    }
}

static shp_message_type_t parse_type(const char *text)
{
    if (strcmp(text, "PING") == 0) return SHP_TYPE_PING;
    if (strcmp(text, "ACK") == 0) return SHP_TYPE_ACK;
    if (strcmp(text, "VISION") == 0) return SHP_TYPE_VISION;
    if (strcmp(text, "STATUS") == 0) return SHP_TYPE_STATUS;
    if (strcmp(text, "TRAIN") == 0) return SHP_TYPE_TRAIN;
    if (strcmp(text, "TRAINSTAT") == 0) return SHP_TYPE_TRAINSTAT;
    if (strcmp(text, "SIGN") == 0) return SHP_TYPE_SIGN;
    if (strcmp(text, "SIGNSTAT") == 0) return SHP_TYPE_SIGNSTAT;
    return SHP_TYPE_UNKNOWN;
}

static int parse_complete_frame(char *frame, shp_message_t *message)
{
    char *asterisk;
    char *token;
    char *cursor;
    uint32_t value;
    uint16_t expected_crc;
    uint16_t actual_crc;

    if (frame[0] != '$' || message == NULL) return -1;
    asterisk = strrchr(frame, '*');
    if (asterisk == NULL || strlen(asterisk + 1) != 4U) return -1;

    if (parse_hex16(asterisk + 1, &expected_crc) != 0) return -1;
    actual_crc = shp_crc16_ccitt((const uint8_t *)&frame[1],
                                 (size_t)(asterisk - &frame[1]));
    if (actual_crc != expected_crc) return -1;

    *asterisk = '\0';
    cursor = &frame[1];
    if (next_token(&cursor, &token) != 0) return -1;
    message->type = parse_type(token);
    if (message->type == SHP_TYPE_UNKNOWN) return -1;

    if (next_token(&cursor, &token) != 0) return -1;
    if (parse_u32_decimal(token, 65535U, &value) != 0) return -1;
    message->sequence = (uint16_t)value;
    message->arg_count = 0;

    while (cursor != NULL)
    {
        if (message->arg_count >= SHP_MAX_ARGS) return -1;
        if (next_token(&cursor, &token) != 0) return -1;
        if (parse_u32_decimal(token, UINT32_MAX, &value) != 0) return -1;
        message->args[message->arg_count++] = (uint32_t)value;
    }
    return 0;
}

int shp_parser_feed(shp_parser_t *parser, uint8_t byte, shp_message_t *message)
{
    int result;

    if (parser == NULL || message == NULL) return -1;

    if (byte == '$')
    {
        parser->buffer[0] = '$';
        parser->length = 1;
        return 0;
    }
    if (parser->length == 0) return 0;

    if (byte == '\n')
    {
        if (parser->length > 0U && parser->buffer[parser->length - 1U] == '\r')
        {
            --parser->length;
        }
        parser->buffer[parser->length] = '\0';
        result = parse_complete_frame(parser->buffer, message);
        parser->length = 0;
        return result == 0 ? 1 : -1;
    }

    if (parser->length >= SHP_MAX_FRAME_SIZE - 1U)
    {
        parser->length = 0;
        return -1;
    }
    parser->buffer[parser->length++] = (char)byte;
    return 0;
}

int shp_encode(char *output,
               size_t output_size,
               const char *type,
               uint16_t sequence,
               const uint32_t *args,
               uint8_t arg_count)
{
    char body[SHP_MAX_FRAME_SIZE];
    size_t used;
    uint8_t i;
    uint16_t crc;
    int written;

    if (output == NULL || type == NULL || arg_count > SHP_MAX_ARGS) return -1;
    if (arg_count > 0U && args == NULL) return -1;
    written = snprintf(body, sizeof(body), "%s,%u", type, (unsigned)sequence);
    if (written < 0 || (size_t)written >= sizeof(body)) return -1;
    used = (size_t)written;

    for (i = 0; i < arg_count; ++i)
    {
        written = snprintf(body + used, sizeof(body) - used,
                           ",%lu", (unsigned long)args[i]);
        if (written < 0 || (size_t)written >= sizeof(body) - used) return -1;
        used += (size_t)written;
    }

    crc = shp_crc16_ccitt((const uint8_t *)body, used);
    written = snprintf(output, output_size, "$%s*%04X\r\n", body, crc);
    if (written < 0 || (size_t)written >= output_size) return -1;
    return written;
}
