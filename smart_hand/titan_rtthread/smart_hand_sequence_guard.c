#include "smart_hand_sequence_guard.h"

#include <string.h>

void smart_hand_sequence_guard_init(smart_hand_sequence_guard_t *guard)
{
    if (guard == NULL)
    {
        return;
    }
    memset(guard, 0, sizeof(*guard));
    guard->initialized = 1u;
}

smart_hand_sequence_result_t smart_hand_sequence_guard_note(
    smart_hand_sequence_guard_t *guard,
    uint16_t sequence)
{
    uint16_t delta;

    if (guard == NULL || !guard->initialized)
    {
        return SMART_HAND_SEQ_OLD;
    }

    if (!guard->have_last)
    {
        guard->have_last = 1u;
        guard->last_accepted = sequence;
        ++guard->accepted_count;
        return SMART_HAND_SEQ_FIRST;
    }

    delta = (uint16_t)((sequence - guard->last_accepted) & 0xFFFFu);
    if (delta == 0u)
    {
        ++guard->duplicate_count;
        return SMART_HAND_SEQ_DUPLICATE;
    }
    if (delta >= 0x8000u)
    {
        ++guard->old_count;
        return SMART_HAND_SEQ_OLD;
    }

    guard->last_accepted = sequence;
    ++guard->accepted_count;
    if (delta == 1u)
    {
        return SMART_HAND_SEQ_IN_ORDER;
    }
    ++guard->gap_count;
    return SMART_HAND_SEQ_FORWARD_GAP;
}

void smart_hand_sequence_guard_reset(smart_hand_sequence_guard_t *guard)
{
    if (guard == NULL || !guard->initialized)
    {
        return;
    }
    guard->have_last = 0u;
    guard->last_accepted = 0u;
    /* Keep diagnostic counters across reset for sh_status lifetime stats. */
}

const char *smart_hand_sequence_result_name(smart_hand_sequence_result_t result)
{
    switch (result)
    {
    case SMART_HAND_SEQ_FIRST:
        return "FIRST";
    case SMART_HAND_SEQ_IN_ORDER:
        return "IN_ORDER";
    case SMART_HAND_SEQ_FORWARD_GAP:
        return "FORWARD_GAP";
    case SMART_HAND_SEQ_DUPLICATE:
        return "DUPLICATE";
    case SMART_HAND_SEQ_OLD:
        return "OLD";
    default:
        return "UNKNOWN";
    }
}
