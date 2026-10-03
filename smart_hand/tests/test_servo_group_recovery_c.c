#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "servo_group_readonly.h"
#include "scs0009_transaction.h"

/*
 * Host checks for the D2 fix: a cycle that cannot make progress must end
 * itself, never leaving cycle_active set.
 *
 * Why this matters, in one sentence: begin_cycle() refuses to start while
 * cycle_active is set, so a stuck flag silences the servo bus until reboot --
 * g_ready freezes at its old value, publish_cycle() never runs again, and
 * every SIGN/TRAIN/recovery action fails permanently.
 *
 * Everything here is pure logic: no RT-Thread, no FSP, no UART.
 */

#define RESPONSE_TIMEOUT_MS 30u

static servo_group_readonly_t g_group;
static uint8_t g_packet[16];

static void setup_group(size_t count)
{
    uint8_t ids[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t i;
    for (i = 0u; i < count; ++i)
    {
        ids[i] = (uint8_t)(i + 1u);
    }
    assert(servo_group_readonly_init(&g_group, ids, count, RESPONSE_TIMEOUT_MS) == 1);
}

static void test_begin_cycle_refuses_while_active(void)
{
    setup_group(3u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    assert(g_group.cycle_active == 1u);

    /* The guard that turns a stuck flag into a permanent outage. */
    assert(servo_group_readonly_begin_cycle(&g_group) == 0);
    assert(g_group.cycle_active == 1u);
}

static void test_abort_clears_the_active_flag(void)
{
    setup_group(3u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);

    servo_group_readonly_abort_cycle(&g_group);

    assert(g_group.cycle_active == 0u);
    /* Nothing usable came out of it, so it is not a completed cycle and
     * publish_cycle() must not run. */
    assert(g_group.cycle_complete == 0u);
    assert(g_group.cycle_valid == 0u);
    assert(g_group.aborted_cycles == 1u);
    assert(g_group.completed_cycles == 0u);
    assert(g_group.failed_reads == 1u);
    assert(g_group.transaction.state == SCS0009_TXN_IDLE);
}

static void test_next_cycle_recovers_after_abort(void)
{
    /*
     * The property the D2 fix exists for: after an aborted cycle the bus must
     * come back on the very next attempt, not after a reboot.
     */
    setup_group(4u);

    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    servo_group_readonly_abort_cycle(&g_group);

    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    assert(g_group.cycle_active == 1u);
    assert(g_group.current_index == 0u);
    assert(g_group.generation >= 2u);

    /* And that recovered cycle can actually produce a request. */
    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    assert(g_group.transaction.state == SCS0009_TXN_WAIT_STATUS);

    servo_group_readonly_abort_cycle(&g_group);
    assert(g_group.cycle_active == 0u);
    assert(g_group.aborted_cycles == 2u);
}

static void test_abort_is_idempotent_and_null_safe(void)
{
    setup_group(2u);

    /* Aborting a cycle that was never started must do nothing at all. */
    servo_group_readonly_abort_cycle(&g_group);
    assert(g_group.aborted_cycles == 0u);
    assert(g_group.failed_reads == 0u);
    assert(g_group.cycle_active == 0u);

    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    servo_group_readonly_abort_cycle(&g_group);
    servo_group_readonly_abort_cycle(&g_group); /* second call is a no-op */
    assert(g_group.aborted_cycles == 1u);
    assert(g_group.failed_reads == 1u);

    servo_group_readonly_abort_cycle(NULL);
}

static void test_abort_works_midway_through_the_group(void)
{
    /*
     * The interesting case is aborting after the cycle has advanced, because
     * that is the state a transmit timeout leaves behind.
     */
    setup_group(4u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);

    /* Consume the first servo as a failed read so current_index moves on. */
    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    servo_group_readonly_note_tx_failed(&g_group);
    assert(g_group.current_index == 1u);
    assert(g_group.cycle_active == 1u); /* note_tx_failed alone does not end it */

    servo_group_readonly_abort_cycle(&g_group);

    assert(g_group.cycle_active == 0u);
    assert(g_group.completed_cycles == 0u);
    assert(g_group.aborted_cycles == 1u);
    /* Both the failed servo and the aborted one are accounted for. */
    assert(g_group.failed_reads == 2u);

    /* Recoverable from here too. */
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    assert(g_group.current_index == 0u);
}

static void test_abort_from_a_waiting_transaction(void)
{
    /* The exact state a TX timeout leaves: transaction waiting for a status
     * packet that will never arrive. */
    setup_group(2u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    assert(g_group.transaction.state == SCS0009_TXN_WAIT_STATUS);

    servo_group_readonly_abort_cycle(&g_group);

    assert(g_group.transaction.state == SCS0009_TXN_IDLE);
    assert(g_group.cycle_active == 0u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);
}

static void test_note_tx_failed_still_advances_within_a_cycle(void)
{
    /*
     * The D2 fix must not change note_tx_failed(): a per-servo transmit
     * failure advances to the next servo and only ends the cycle once the
     * last one is done. Abort is for "cannot advance at all", not for this.
     */
    setup_group(3u);
    assert(servo_group_readonly_begin_cycle(&g_group) == 1);

    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    servo_group_readonly_note_tx_failed(&g_group);
    assert(g_group.current_index == 1u);
    assert(g_group.cycle_active == 1u);
    assert(g_group.aborted_cycles == 0u);

    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    servo_group_readonly_note_tx_failed(&g_group);
    assert(g_group.current_index == 2u);
    assert(g_group.cycle_active == 1u);

    assert(servo_group_readonly_prepare(&g_group, 0u, g_packet, sizeof(g_packet)) > 0u);
    servo_group_readonly_note_tx_failed(&g_group);
    /* Last servo: now the cycle ends by itself, the normal way. */
    assert(g_group.cycle_active == 0u);
    assert(g_group.completed_cycles == 1u);
    assert(g_group.aborted_cycles == 0u);
}

int main(void)
{
    test_begin_cycle_refuses_while_active();
    test_abort_clears_the_active_flag();
    test_next_cycle_recovers_after_abort();
    test_abort_is_idempotent_and_null_safe();
    test_abort_works_midway_through_the_group();
    test_abort_from_a_waiting_transaction();
    test_note_tx_failed_still_advances_within_a_cycle();

    puts("C servo group recovery tests passed");
    return 0;
}
