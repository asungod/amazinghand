#ifndef SCS0009_TRANSACTION_H
#define SCS0009_TRANSACTION_H

#include "scs0009_stream.h"

#include <stdint.h>

typedef enum
{
    SCS0009_TXN_IDLE = 0,
    SCS0009_TXN_WAIT_STATUS,
    SCS0009_TXN_COMPLETE,
    SCS0009_TXN_SERVO_ERROR,
    SCS0009_TXN_TIMEOUT,
    SCS0009_TXN_ABORTED
} scs0009_transaction_state_t;

typedef struct
{
    scs0009_stream_parser_t parser;
    scs0009_transaction_state_t state;
    uint32_t started_ms;
    uint32_t timeout_ms;
    uint8_t expected_id;
    uint8_t servo_error;
    uint32_t transactions_started;
    uint32_t transactions_complete;
    uint32_t transactions_timeout;
    uint32_t transactions_servo_error;
    uint32_t rejected_frames;
    uint32_t busy_rejections;
} scs0009_transaction_t;

void scs0009_transaction_init(scs0009_transaction_t *transaction);
int scs0009_transaction_begin(scs0009_transaction_t *transaction,
                              uint8_t expected_id,
                              uint32_t now_ms,
                              uint32_t timeout_ms);
scs0009_transaction_state_t scs0009_transaction_feed(
    scs0009_transaction_t *transaction,
    uint8_t byte,
    scs0009_status_packet_t *status);
scs0009_transaction_state_t scs0009_transaction_tick(
    scs0009_transaction_t *transaction,
    uint32_t now_ms);
void scs0009_transaction_abort(scs0009_transaction_t *transaction);
void scs0009_transaction_reset(scs0009_transaction_t *transaction);

#endif
