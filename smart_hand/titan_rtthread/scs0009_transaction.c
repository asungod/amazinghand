#include "scs0009_transaction.h"

#include <string.h>

void scs0009_transaction_init(scs0009_transaction_t *transaction)
{
    if (transaction == NULL)
    {
        return;
    }
    memset(transaction, 0, sizeof(*transaction));
    transaction->state = SCS0009_TXN_IDLE;
}

int scs0009_transaction_begin(scs0009_transaction_t *transaction,
                              uint8_t expected_id,
                              uint32_t now_ms,
                              uint32_t timeout_ms)
{
    if (transaction == NULL || expected_id > SCS0009_MAX_ID || timeout_ms == 0u)
    {
        return 0;
    }
    if (transaction->state != SCS0009_TXN_IDLE)
    {
        transaction->busy_rejections++;
        return 0;
    }
    scs0009_stream_init(&transaction->parser, expected_id);
    transaction->state = SCS0009_TXN_WAIT_STATUS;
    transaction->started_ms = now_ms;
    transaction->timeout_ms = timeout_ms;
    transaction->expected_id = expected_id;
    transaction->servo_error = 0u;
    transaction->transactions_started++;
    return 1;
}

scs0009_transaction_state_t scs0009_transaction_feed(
    scs0009_transaction_t *transaction,
    uint8_t byte,
    scs0009_status_packet_t *status)
{
    scs0009_stream_result_t stream_result;
    if (transaction == NULL || status == NULL ||
        transaction->state != SCS0009_TXN_WAIT_STATUS)
    {
        return transaction == NULL ? SCS0009_TXN_ABORTED : transaction->state;
    }
    stream_result = scs0009_stream_feed(&transaction->parser, byte, status);
    if (stream_result == SCS0009_STREAM_REJECTED)
    {
        transaction->rejected_frames++;
    }
    else if (stream_result == SCS0009_STREAM_FRAME)
    {
        transaction->servo_error = status->error;
        if (status->error != 0u)
        {
            transaction->state = SCS0009_TXN_SERVO_ERROR;
            transaction->transactions_servo_error++;
        }
        else
        {
            transaction->state = SCS0009_TXN_COMPLETE;
            transaction->transactions_complete++;
        }
    }
    return transaction->state;
}

scs0009_transaction_state_t scs0009_transaction_tick(
    scs0009_transaction_t *transaction,
    uint32_t now_ms)
{
    uint32_t elapsed;
    if (transaction == NULL)
    {
        return SCS0009_TXN_ABORTED;
    }
    if (transaction->state != SCS0009_TXN_WAIT_STATUS)
    {
        return transaction->state;
    }
    elapsed = now_ms - transaction->started_ms;
    if (elapsed >= transaction->timeout_ms)
    {
        transaction->state = SCS0009_TXN_TIMEOUT;
        transaction->transactions_timeout++;
        scs0009_stream_reset(&transaction->parser);
    }
    return transaction->state;
}

void scs0009_transaction_abort(scs0009_transaction_t *transaction)
{
    if (transaction != NULL && transaction->state == SCS0009_TXN_WAIT_STATUS)
    {
        transaction->state = SCS0009_TXN_ABORTED;
        scs0009_stream_reset(&transaction->parser);
    }
}

void scs0009_transaction_reset(scs0009_transaction_t *transaction)
{
    if (transaction != NULL && transaction->state != SCS0009_TXN_WAIT_STATUS)
    {
        transaction->state = SCS0009_TXN_IDLE;
        transaction->expected_id = 0u;
        transaction->servo_error = 0u;
        scs0009_stream_reset(&transaction->parser);
    }
}
