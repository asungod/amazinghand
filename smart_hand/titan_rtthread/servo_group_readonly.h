#ifndef SERVO_GROUP_READONLY_H
#define SERVO_GROUP_READONLY_H

#include "scs0009_transaction.h"

#include <stddef.h>
#include <stdint.h>

#define SERVO_GROUP_READONLY_MAX_COUNT 8u

typedef struct
{
    uint8_t id;
    uint16_t position_raw;
    uint16_t speed_raw;
    uint16_t load_raw;
    uint8_t voltage_raw;
    uint8_t temperature_raw;
    uint8_t read_ok;
    uint32_t generation;
} servo_group_readonly_sample_t;

typedef struct
{
    scs0009_transaction_t transaction;
    servo_group_readonly_sample_t staged[SERVO_GROUP_READONLY_MAX_COUNT];
    uint8_t ids[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count;
    size_t current_index;
    uint32_t response_timeout_ms;
    uint32_t generation;
    uint8_t cycle_active;
    uint8_t cycle_complete;
    uint8_t cycle_valid;
    uint32_t successful_reads;
    uint32_t failed_reads;
    uint32_t completed_cycles;
    uint32_t invalid_cycles;
    /*
     * Cycles that were ended early because the bus could not make progress
     * (a request could not be prepared, or a transmit never completed).
     * Counted separately from invalid_cycles, which means "a cycle finished
     * but its data was not trustworthy". Keeping them apart matters: an
     * aborted cycle produced no data to judge at all.
     */
    uint32_t aborted_cycles;
} servo_group_readonly_t;

int servo_group_readonly_init(servo_group_readonly_t *group,
                              const uint8_t *ids,
                              size_t count,
                              uint32_t response_timeout_ms);
int servo_group_readonly_begin_cycle(servo_group_readonly_t *group);
size_t servo_group_readonly_prepare(servo_group_readonly_t *group,
                                    uint32_t now_ms,
                                    uint8_t *packet,
                                    size_t capacity);
void servo_group_readonly_note_tx_failed(servo_group_readonly_t *group);

/*
 * End the current cycle immediately without publishing anything.
 *
 * The cycle loop must never be left with cycle_active set while no progress
 * is possible: begin_cycle() refuses to start while cycle_active is set, so
 * a stuck flag silences the servo bus until reboot. Only completing (or
 * explicitly aborting) the cycle clears it.
 *
 * Use this when the group cannot advance at all. A per-servo transmit failure
 * is different and is handled by servo_group_readonly_note_tx_failed(), which
 * advances to the next servo and only ends the cycle once the last one is done.
 *
 * Staged data is invalidated, the transaction is reset, and cycle_active is
 * cleared. completed_cycles is NOT incremented (nothing completed) and
 * cycle_complete stays 0 so publish_cycle() will not run.
 */
void servo_group_readonly_abort_cycle(servo_group_readonly_t *group);
void servo_group_readonly_feed(servo_group_readonly_t *group,
                               uint8_t byte);
void servo_group_readonly_tick(servo_group_readonly_t *group,
                               uint32_t now_ms);
int servo_group_readonly_snapshot(
    const servo_group_readonly_t *group,
    servo_group_readonly_sample_t *samples,
    size_t capacity,
    size_t *sample_count);

#endif
