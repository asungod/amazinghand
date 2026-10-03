#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "voice_audio.h"

/*
 * Host-side checks for the PCM ring buffer.
 *
 * The interesting cases are the ones that only show up on hardware after a
 * few minutes of audio: index wrap-around, a consumer that falls behind, and
 * a push larger than the buffer.
 */

static voice_ring_t g_ring;
static int16_t g_scratch[VOICE_RING_CAPACITY];

static int16_t sample_at(uint32_t index)
{
    /* A value that depends on position, so misordering is detectable. */
    return (int16_t)((index * 7U) ^ 0x5A5AU);
}

static void fill_expected(int16_t *out, uint32_t from, uint32_t count)
{
    uint32_t i;
    for (i = 0U; i < count; ++i)
    {
        out[i] = sample_at(from + i);
    }
}

static void push_range(uint32_t from, uint32_t count)
{
    uint32_t i;
    for (i = 0U; i < count; ++i)
    {
        g_scratch[i] = sample_at(from + i);
    }
    (void)voice_ring_push(&g_ring, g_scratch, count);
}

static void test_empty_ring(void)
{
    voice_ring_init(&g_ring);
    assert(voice_ring_available(&g_ring) == 0U);
    assert(voice_ring_peek_latest(&g_ring, g_scratch, 10U) == 0U);
    assert(voice_ring_read(&g_ring, g_scratch, 10U) == 0U);
    assert(g_ring.write_index == 0U);
    assert(g_ring.overrun_count == 0U);
}

static void test_push_then_peek_and_read(void)
{
    int16_t expected[64];

    voice_ring_init(&g_ring);
    push_range(0U, 100U);
    assert(voice_ring_available(&g_ring) == 100U);
    assert(g_ring.total_samples == 100U);

    /* peek_latest returns the newest N, in chronological order */
    assert(voice_ring_peek_latest(&g_ring, g_scratch, 10U) == 10U);
    fill_expected(expected, 90U, 10U);
    assert(memcmp(g_scratch, expected, 10U * sizeof(int16_t)) == 0);

    /* peeking must not consume */
    assert(voice_ring_available(&g_ring) == 100U);

    /* read consumes from the oldest end, in order */
    assert(voice_ring_read(&g_ring, g_scratch, 50U) == 50U);
    fill_expected(expected, 0U, 50U);
    assert(memcmp(g_scratch, expected, 50U * sizeof(int16_t)) == 0);
    assert(voice_ring_available(&g_ring) == 50U);
}

static void test_peek_while_filling(void)
{
    voice_ring_init(&g_ring);
    push_range(0U, 5U);
    /* Fewer samples than requested: copy what exists and report the shortfall. */
    assert(voice_ring_peek_latest(&g_ring, g_scratch, 10U) == 5U);
    assert(g_scratch[0] == sample_at(0U));
    assert(g_scratch[4] == sample_at(4U));
}

static void test_ring_wrap_integrity(void)
{
    /*
     * Walk the write and read indices past the capacity boundary several
     * times, checking that every sample survives in order. This is the case
     * a mask-based ring buffer usually gets wrong.
     */
    uint32_t produced = 0U;
    uint32_t consumed = 0U;
    uint32_t round;

    voice_ring_init(&g_ring);

    for (round = 0U; round < 40U; ++round)
    {
        uint32_t chunk = 3000U;
        int16_t expected[3000];
        uint32_t got;
        uint32_t i;

        push_range(produced, chunk);
        produced += chunk;

        /* Take everything back out and verify order. */
        while (consumed < produced)
        {
            uint32_t want = produced - consumed;
            if (want > chunk)
            {
                want = chunk;
            }
            got = voice_ring_read(&g_ring, g_scratch, want);
            assert(got == want);
            fill_expected(expected, consumed, want);
            for (i = 0U; i < want; ++i)
            {
                assert(g_scratch[i] == expected[i]);
            }
            consumed += want;
        }
    }

    assert(consumed == produced);
    assert(voice_ring_available(&g_ring) == 0U);
    assert(g_ring.overrun_count == 0U);
}

static void test_producer_never_touches_read_index(void)
{
    /*
     * read_index is consumer-owned. A producer that advances it to make room
     * is rewriting audio the consumer is still reading, which is not a legal
     * single-producer/single-consumer operation.
     */
    uint32_t before;
    uint32_t after;
    uint32_t round;

    voice_ring_init(&g_ring);

    /* Consume part of the stream, then hammer the producer while it is full. */
    push_range(0U, VOICE_RING_CAPACITY);
    assert(voice_ring_read(&g_ring, g_scratch, 1000U) == 1000U);

    for (round = 0U; round < 50U; ++round)
    {
        before = g_ring.read_index;
        (void)voice_ring_push(&g_ring, g_scratch, 500U);
        after = g_ring.read_index;
        assert(before == after);
    }
}

static void test_overflow_fails_closed_and_preserves_unread(void)
{
    int16_t expected[32];
    static int16_t big[VOICE_RING_CAPACITY + 555U];
    uint32_t i;

    voice_ring_init(&g_ring);

    /* Fill exactly to capacity: no loss. */
    push_range(0U, VOICE_RING_CAPACITY);
    assert(voice_ring_available(&g_ring) == VOICE_RING_CAPACITY);
    assert(g_ring.overrun_count == 0U);
    assert(g_ring.total_samples == VOICE_RING_CAPACITY);

    /*
     * Push 100 more with nobody reading. The block must be rejected whole:
     * overrun_count records the loss, nothing is written, and every unread
     * sample stays exactly where the consumer left it.
     */
    assert(voice_ring_push(&g_ring, g_scratch, 100U) == 100U);
    assert(g_ring.overrun_count == 100U);
    assert(voice_ring_available(&g_ring) == VOICE_RING_CAPACITY);
    assert(g_ring.total_samples == VOICE_RING_CAPACITY);

    /* The oldest sample is still the original first sample, not an evicted one. */
    assert(voice_ring_read(&g_ring, g_scratch, 1U) == 1U);
    assert(g_scratch[0] == sample_at(0U));

    /* One sample has been consumed, so the tail is indices CAPACITY-32..CAPACITY-1. */
    assert(voice_ring_peek_latest(&g_ring, g_scratch, 32U) == 32U);
    fill_expected(expected, VOICE_RING_CAPACITY - 32U, 32U);
    assert(memcmp(g_scratch, expected, sizeof(expected)) == 0);

    /* Draining then refilling must restore normal operation. */
    while (voice_ring_read(&g_ring, g_scratch, 4096U) > 0U)
    {
    }
    assert(voice_ring_available(&g_ring) == 0U);
    assert(voice_ring_push(&g_ring, g_scratch, 64U) == 0U);
    assert(voice_ring_available(&g_ring) == 64U);

    /* A block larger than the whole buffer is rejected, not truncated. */
    voice_ring_init(&g_ring);
    for (i = 0U; i < (VOICE_RING_CAPACITY + 555U); ++i)
    {
        big[i] = sample_at(i);
    }
    assert(voice_ring_push(&g_ring, big, VOICE_RING_CAPACITY + 555U) ==
           VOICE_RING_CAPACITY + 555U);
    assert(voice_ring_available(&g_ring) == 0U);
    assert(g_ring.overrun_count == VOICE_RING_CAPACITY + 555U);
}


static void test_absurd_push_cannot_wrap_the_capacity_check(void)
{
    /*
     * The count > VOICE_RING_CAPACITY guard is load bearing, not a courtesy.
     * Without it, `pending + count` wraps in uint32 arithmetic:
     *
     *     pending = 100, count = 0xFFFFFFF0  ->  sum = 84  <=  CAPACITY
     *
     * so the capacity check passes, the reject branch is skipped, and the
     * copy loop runs ~4.3 billion iterations writing through the mask. The
     * guard is the only thing standing between the ring and that. Removing it
     * used to leave every other test in this file green, so this case exists
     * specifically to fail when the guard goes away.
     */
    uint32_t read_before;
    uint32_t write_before;
    uint32_t total_before;

    voice_ring_init(&g_ring);
    push_range(0U, 100U);

    read_before = g_ring.read_index;
    write_before = g_ring.write_index;
    total_before = g_ring.total_samples;

    assert(voice_ring_push(&g_ring, g_scratch, 0xFFFFFFF0U) == 0xFFFFFFF0U);

    /* Rejected whole: nothing written, nothing consumed, nothing published. */
    assert(g_ring.write_index == write_before);
    assert(g_ring.read_index == read_before);
    assert(g_ring.total_samples == total_before);
    assert(voice_ring_available(&g_ring) == 100U);
    assert(g_ring.overrun_count == 0xFFFFFFF0U);

    /* The 100 samples already buffered are still intact and in order. */
    assert(voice_ring_read(&g_ring, g_scratch, 100U) == 100U);
    {
        uint32_t i;
        for (i = 0U; i < 100U; ++i)
        {
            assert(g_scratch[i] == sample_at(i));
        }
    }

    /* The same guard is what keeps read_index untouched on this path. */
    voice_ring_init(&g_ring);
    push_range(0U, 50U);
    read_before = g_ring.read_index;
    (void)voice_ring_push(&g_ring, g_scratch, VOICE_RING_CAPACITY + 1U);
    assert(g_ring.read_index == read_before);
}


static void test_capture_reset_never_touches_read_index(void)
{
    /*
     * Capture start/stop uses voice_ring_reset_for_capture(), not
     * voice_ring_init(). init memsets the whole ring including read_index,
     * which the consumer owns; doing that while a consumer is mid-read would
     * make it re-deliver audio it had already consumed.
     */
    uint32_t read_before;
    uint32_t i;

    voice_ring_init(&g_ring);
    push_range(0U, 1000U);
    assert(voice_ring_read(&g_ring, g_scratch, 400U) == 400U);

    read_before = g_ring.read_index;
    assert(read_before != 0U); /* the field really is non-zero, or this proves nothing */

    voice_ring_reset_for_capture(&g_ring);

    assert(g_ring.read_index == read_before);      /* consumer-owned: untouched */
    assert(voice_ring_available(&g_ring) == 0U);   /* but the ring looks empty */
    assert(g_ring.total_samples == 0U);
    assert(g_ring.overrun_count == 0U);

    /* Still usable afterwards, and in order. */
    push_range(5000U, 64U);
    assert(voice_ring_available(&g_ring) == 64U);
    assert(voice_ring_read(&g_ring, g_scratch, 64U) == 64U);
    for (i = 0U; i < 64U; ++i)
    {
        assert(g_scratch[i] == sample_at(5000U + i));
    }

    /* Bring-up init still resets everything, as its contract says. */
    voice_ring_init(&g_ring);
    assert(g_ring.read_index == 0U);
    assert(voice_ring_available(&g_ring) == 0U);
}

static uint32_t stress_random(uint32_t *state)
{
    *state = (*state) * 1664525U + 1013904223U;
    return *state >> 8;
}

static void test_interleaved_producer_consumer_stress(void)
{
    /*
     * Drive the ring the way the firmware does: a producer appending bursts
     * while a consumer drains, in an order neither side controls. A shadow
     * FIFO records what the consumer is entitled to see, and every read is
     * checked against it sample by sample.
     */
    /* Circular too: at most VOICE_RING_CAPACITY entries are ever live, so
     * twice that is provably enough and the run can be arbitrarily long. */
    static int16_t shadow[VOICE_RING_CAPACITY * 2];
    const uint32_t shadow_mask = (VOICE_RING_CAPACITY * 2U) - 1U;
    uint32_t shadow_head = 0U; /* next index to be consumed */
    uint32_t shadow_tail = 0U; /* next index to be produced  */
    uint32_t next_sample = 0U;
    uint32_t random_state = 0xC0FFEEU;
    uint32_t accepted = 0U;
    uint32_t rejected = 0U;
    uint32_t consumed = 0U;
    uint32_t step;

    voice_ring_init(&g_ring);

    for (step = 0U; step < 20000U; ++step)
    {
        uint32_t action = stress_random(&random_state) % 100U;

        if (action < 55U)
        {
            /* Producer burst. */
            uint32_t count = (stress_random(&random_state) % 900U) + 1U;
            uint32_t i;
            uint32_t room = VOICE_RING_CAPACITY - voice_ring_available(&g_ring);
            uint32_t dropped;

            for (i = 0U; i < count; ++i)
            {
                g_scratch[i] = sample_at(next_sample + i);
            }
            dropped = voice_ring_push(&g_ring, g_scratch, count);

            if (count > room)
            {
                /* Must be rejected whole: nothing appended to the shadow. */
                assert(dropped == count);
                rejected += count;
            }
            else
            {
                assert(dropped == 0U);
                for (i = 0U; i < count; ++i)
                {
                    shadow[shadow_tail & shadow_mask] = g_scratch[i];
                    shadow_tail += 1U;
                }
                accepted += count;
            }
            next_sample += count;
        }
        else
        {
            /* Consumer drain. */
            uint32_t want = (stress_random(&random_state) % 700U) + 1U;
            uint32_t pending = shadow_tail - shadow_head;
            uint32_t take = (pending < want) ? pending : want;
            uint32_t got;
            uint32_t i;

            got = voice_ring_read(&g_ring, g_scratch, take);
            assert(got == take);
            for (i = 0U; i < take; ++i)
            {
                /* Every consumed sample must be the one the producer sent. */
                assert(g_scratch[i] == shadow[(shadow_head + i) & shadow_mask]);
            }
            shadow_head += take;
            consumed += take;

            assert(voice_ring_available(&g_ring) == (shadow_tail - shadow_head));
        }
    }

    /* Conservation: accepted == consumed + still buffered. */
    assert(accepted == consumed + voice_ring_available(&g_ring));
    assert(g_ring.overrun_count == rejected);
    assert(g_ring.total_samples == accepted);
    assert(rejected > 0U); /* the stress run must actually exercise overflow */
    printf("  stress: accepted=%u consumed=%u rejected=%u\n",
           (unsigned)accepted, (unsigned)consumed, (unsigned)rejected);
}

static void test_error_counters(void)
{
    voice_ring_init(&g_ring);
    assert(g_ring.error_count == 0U);
    voice_ring_note_error(&g_ring, 0x2AU);
    voice_ring_note_error(&g_ring, 0x2AU);
    assert(g_ring.error_count == 2U);
    assert(g_ring.last_error == 0x2AU);

    /*
     * The field must be wide enough for the FSP error bitmask. The one that
     * matters most in practice, PDM_ERROR_BUFFER_OVERWRITE, is (1UL << 11);
     * stored in a byte it would truncate to 0, i.e. exactly PDM_ERROR_NONE,
     * and the error this project explicitly enables would never be visible.
     * Regression guard for a uint8_t field that shipped once.
     */
    voice_ring_reset_counters(&g_ring);
    voice_ring_note_error(&g_ring, 1UL << 11);
    assert(g_ring.error_count == 1U);
    assert(g_ring.last_error == (1UL << 11));
    assert(g_ring.last_error != 0U);   /* 0 would mean PDM_ERROR_NONE */
    assert(g_ring.last_error != (uint32_t)(uint8_t)(1UL << 11));

    g_ring.overrun_count = 7U;
    voice_ring_reset_counters(&g_ring);
    assert(g_ring.error_count == 0U);
    assert(g_ring.overrun_count == 0U);
    assert(g_ring.last_error == 0U);
    /* Resetting counters must not disturb buffered audio or indices. */
    assert(g_ring.write_index == 0U);
}

static void test_null_safety(void)
{
    voice_ring_init(&g_ring);
    assert(voice_ring_push(NULL, g_scratch, 1U) == 0U);
    assert(voice_ring_push(&g_ring, NULL, 1U) == 0U);
    assert(voice_ring_push(&g_ring, g_scratch, 0U) == 0U);
    assert(voice_ring_available(NULL) == 0U);
    assert(voice_ring_read(NULL, g_scratch, 1U) == 0U);
    assert(voice_ring_peek_latest(NULL, g_scratch, 1U) == 0U);
    voice_ring_note_error(NULL, 1U);
    voice_ring_reset_counters(NULL);
    voice_ring_init(NULL);
}

int main(void)
{
    test_empty_ring();
    test_push_then_peek_and_read();
    test_peek_while_filling();
    test_ring_wrap_integrity();
    test_producer_never_touches_read_index();
    test_overflow_fails_closed_and_preserves_unread();
    test_absurd_push_cannot_wrap_the_capacity_check();
    test_capture_reset_never_touches_read_index();
    test_interleaved_producer_consumer_stress();
    test_error_counters();
    test_null_safety();

    puts("C voice audio tests passed");
    return 0;
}
