#include "smart_hand_sequence_guard.h"

#include <assert.h>
#include <stdio.h>

int main(void)
{
    smart_hand_sequence_guard_t guard;

    smart_hand_sequence_guard_init(NULL);
    assert(smart_hand_sequence_guard_note(NULL, 1u) == SMART_HAND_SEQ_OLD);

    smart_hand_sequence_guard_init(&guard);
    assert(!guard.have_last);

    /* First frame */
    assert(smart_hand_sequence_guard_note(&guard, 10u) == SMART_HAND_SEQ_FIRST);
    assert(guard.have_last && guard.last_accepted == 10u);
    assert(guard.accepted_count == 1u);

    /* In order */
    assert(smart_hand_sequence_guard_note(&guard, 11u) == SMART_HAND_SEQ_IN_ORDER);
    assert(guard.last_accepted == 11u);

    /* Duplicate */
    assert(smart_hand_sequence_guard_note(&guard, 11u) == SMART_HAND_SEQ_DUPLICATE);
    assert(guard.last_accepted == 11u);
    assert(guard.duplicate_count == 1u);

    /* Old / backward */
    assert(smart_hand_sequence_guard_note(&guard, 10u) == SMART_HAND_SEQ_OLD);
    assert(guard.last_accepted == 11u);
    assert(guard.old_count == 1u);

    /* Forward gap */
    assert(smart_hand_sequence_guard_note(&guard, 15u) == SMART_HAND_SEQ_FORWARD_GAP);
    assert(guard.last_accepted == 15u);
    assert(guard.gap_count == 1u);

    /* 65535 -> 0 rollover accepted as in-order */
    smart_hand_sequence_guard_init(&guard);
    assert(smart_hand_sequence_guard_note(&guard, 65535u) == SMART_HAND_SEQ_FIRST);
    assert(smart_hand_sequence_guard_note(&guard, 0u) == SMART_HAND_SEQ_IN_ORDER);
    assert(guard.last_accepted == 0u);

    /* 0 -> 65535 is old (half-range reverse) */
    smart_hand_sequence_guard_init(&guard);
    assert(smart_hand_sequence_guard_note(&guard, 0u) == SMART_HAND_SEQ_FIRST);
    assert(smart_hand_sequence_guard_note(&guard, 65535u) == SMART_HAND_SEQ_OLD);
    assert(guard.last_accepted == 0u);

    /* delta == 0x8000 fail closed as OLD */
    smart_hand_sequence_guard_init(&guard);
    assert(smart_hand_sequence_guard_note(&guard, 0u) == SMART_HAND_SEQ_FIRST);
    assert(smart_hand_sequence_guard_note(&guard, 0x8000u) == SMART_HAND_SEQ_OLD);
    assert(guard.last_accepted == 0u);

    /* delta 0x7FFF is still newer (forward gap) */
    assert(smart_hand_sequence_guard_note(&guard, 0x7FFFu) == SMART_HAND_SEQ_FORWARD_GAP);
    assert(guard.last_accepted == 0x7FFFu);

    /* Reset allows low sequence as FIRST again */
    smart_hand_sequence_guard_reset(&guard);
    assert(!guard.have_last);
    assert(smart_hand_sequence_guard_note(&guard, 1u) == SMART_HAND_SEQ_FIRST);
    assert(guard.last_accepted == 1u);

    /* Continuous stream after reset */
    assert(smart_hand_sequence_guard_note(&guard, 2u) == SMART_HAND_SEQ_IN_ORDER);
    assert(smart_hand_sequence_guard_note(&guard, 2u) == SMART_HAND_SEQ_DUPLICATE);

    puts("smart_hand_sequence_guard C tests passed");
    return 0;
}
