#include "scs0009_transaction.h"

#include <assert.h>
#include <stdio.h>

static scs0009_transaction_state_t feed_bytes(
    scs0009_transaction_t *transaction,
    const uint8_t *data,
    size_t length,
    scs0009_status_packet_t *status)
{
    size_t index;
    scs0009_transaction_state_t state = transaction->state;
    for (index = 0u; index < length; ++index)
    {
        state = scs0009_transaction_feed(transaction, data[index], status);
    }
    return state;
}

int main(void)
{
    const uint8_t ack_id1[] = {0xFFu, 0xFFu, 0x01u, 0x02u, 0x00u, 0xFCu};
    const uint8_t error_id1[] = {0xFFu, 0xFFu, 0x01u, 0x02u, 0x20u, 0xDCu};
    uint8_t corrupt[sizeof(ack_id1)] = {0xFFu, 0xFFu, 0x01u, 0x02u, 0x00u, 0xFDu};
    scs0009_transaction_t transaction;
    scs0009_status_packet_t status;

    scs0009_transaction_init(&transaction);
    assert(scs0009_transaction_begin(&transaction, 1u, 100u, 10u));
    assert(!scs0009_transaction_begin(&transaction, 1u, 101u, 10u));
    assert(transaction.busy_rejections == 1u);
    assert(feed_bytes(&transaction, ack_id1, sizeof(ack_id1), &status) ==
           SCS0009_TXN_COMPLETE);
    assert(transaction.transactions_complete == 1u && status.error == 0u);

    scs0009_transaction_reset(&transaction);
    assert(scs0009_transaction_begin(&transaction, 1u, 200u, 10u));
    assert(feed_bytes(&transaction, error_id1, sizeof(error_id1), &status) ==
           SCS0009_TXN_SERVO_ERROR);
    assert(transaction.servo_error == 0x20u);

    scs0009_transaction_reset(&transaction);
    assert(scs0009_transaction_begin(&transaction, 1u, 300u, 10u));
    assert(feed_bytes(&transaction, corrupt, sizeof(corrupt), &status) ==
           SCS0009_TXN_WAIT_STATUS);
    assert(transaction.rejected_frames == 1u);
    assert(feed_bytes(&transaction, ack_id1, sizeof(ack_id1), &status) ==
           SCS0009_TXN_COMPLETE);

    scs0009_transaction_reset(&transaction);
    assert(scs0009_transaction_begin(&transaction, 1u, 0xFFFFFFF0u, 32u));
    assert(scs0009_transaction_tick(&transaction, 0x0000000Fu) ==
           SCS0009_TXN_WAIT_STATUS);
    assert(scs0009_transaction_tick(&transaction, 0x00000010u) ==
           SCS0009_TXN_TIMEOUT);
    assert(transaction.transactions_timeout == 1u);

    scs0009_transaction_reset(&transaction);
    assert(scs0009_transaction_begin(&transaction, 1u, 400u, 10u));
    scs0009_transaction_abort(&transaction);
    assert(transaction.state == SCS0009_TXN_ABORTED);
    scs0009_transaction_reset(&transaction);
    assert(transaction.state == SCS0009_TXN_IDLE);

    assert(!scs0009_transaction_begin(&transaction, 254u, 500u, 10u));
    assert(!scs0009_transaction_begin(&transaction, 1u, 500u, 0u));

    puts("SCS0009 transaction tests passed");
    return 0;
}
