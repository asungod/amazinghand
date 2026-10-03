#ifndef SMART_HAND_SEQUENCE_GUARD_H
#define SMART_HAND_SEQUENCE_GUARD_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * 16-bit sequence anti-replay guard (host-testable, no RT-Thread/UART/heap).
 * Matches host MotionSafetyGate._sequence_is_newer() half-range rule:
 *   delta = (sequence - last_accepted) & 0xFFFF
 *   delta == 0           -> DUPLICATE
 *   0 < delta < 0x8000   -> newer (1 = IN_ORDER, >1 = FORWARD_GAP)
 *   delta >= 0x8000      -> OLD / ambiguous, reject
 */
typedef enum
{
    SMART_HAND_SEQ_FIRST = 0,
    SMART_HAND_SEQ_IN_ORDER,
    SMART_HAND_SEQ_FORWARD_GAP,
    SMART_HAND_SEQ_DUPLICATE,
    SMART_HAND_SEQ_OLD
} smart_hand_sequence_result_t;

typedef struct
{
    uint16_t last_accepted;
    uint8_t have_last;
    uint8_t initialized;
    uint32_t accepted_count;
    uint32_t gap_count;
    uint32_t duplicate_count;
    uint32_t old_count;
} smart_hand_sequence_guard_t;

void smart_hand_sequence_guard_init(smart_hand_sequence_guard_t *guard);

/* Only FIRST / IN_ORDER / FORWARD_GAP update last_accepted. */
smart_hand_sequence_result_t smart_hand_sequence_guard_note(
    smart_hand_sequence_guard_t *guard,
    uint16_t sequence);

void smart_hand_sequence_guard_reset(smart_hand_sequence_guard_t *guard);

const char *smart_hand_sequence_result_name(smart_hand_sequence_result_t result);

#ifdef __cplusplus
}
#endif

#endif
