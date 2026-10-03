#include "voice_audio.h"

#include <string.h>

void voice_ring_init(voice_ring_t *ring)
{
    if (ring == NULL)
    {
        return;
    }
    memset(ring, 0, sizeof(*ring));
}

void voice_ring_reset_for_capture(voice_ring_t *ring)
{
    uint32_t read;

    if (ring == NULL)
    {
        return;
    }

    /*
     * Read read_index once, then publish it as the new write_index. That makes
     * the ring look empty without the producer writing a consumer-owned field.
     * Setting write_index to 0 instead would make "write - read" wrap to a
     * huge value whenever read_index was non-zero.
     */
    read = ring->read_index;
    ring->write_index = read;
    ring->total_samples = 0U;
    ring->overrun_count = 0U;
    ring->error_count = 0U;
    ring->last_error = 0U;
}

uint32_t voice_ring_push(voice_ring_t *ring,
                         const int16_t *samples,
                         uint32_t count)
{
    uint32_t write;
    uint32_t read;
    uint32_t pending;
    uint32_t i;

    if ((ring == NULL) || (samples == NULL) || (count == 0U))
    {
        return 0U;
    }

    /* A block larger than the whole buffer can never be accepted. */
    if (count > VOICE_RING_CAPACITY)
    {
        ring->overrun_count += count;
        return count;
    }

    write = ring->write_index;
    read = ring->read_index; /* read-only here; the consumer owns it */
    pending = write - read;  /* wrap-safe unsigned distance */

    if ((pending + count) > VOICE_RING_CAPACITY)
    {
        /*
         * Fail closed. Reject the whole block and leave every unread sample
         * where the consumer expects it. A partially written block would
         * splice two non-adjacent moments of audio together, which is worse
         * for the front end than a clean gap the caller can see.
         */
        ring->overrun_count += count;
        return count;
    }

    for (i = 0U; i < count; ++i)
    {
        ring->samples[(write + i) & VOICE_RING_MASK] = samples[i];
    }

    /*
     * Publish only after the samples are visible. On Cortex-M a single 32-bit
     * store is atomic, so the consumer never observes a half-written index.
     * read_index is deliberately untouched.
     */
    ring->write_index = write + count;
    ring->total_samples += count;

    return 0U;
}

uint32_t voice_ring_available(const voice_ring_t *ring)
{
    if (ring == NULL)
    {
        return 0U;
    }
    return ring->write_index - ring->read_index;
}

uint32_t voice_ring_read(voice_ring_t *ring, int16_t *out, uint32_t max_count)
{
    uint32_t read;
    uint32_t pending;
    uint32_t take;
    uint32_t i;

    if ((ring == NULL) || (out == NULL) || (max_count == 0U))
    {
        return 0U;
    }

    read = ring->read_index;
    pending = ring->write_index - read;
    take = (pending < max_count) ? pending : max_count;

    for (i = 0U; i < take; ++i)
    {
        out[i] = ring->samples[(read + i) & VOICE_RING_MASK];
    }

    ring->read_index = read + take;
    return take;
}

uint32_t voice_ring_peek_latest(const voice_ring_t *ring,
                                int16_t *out,
                                uint32_t count)
{
    uint32_t write;
    uint32_t available;
    uint32_t take;
    uint32_t start;
    uint32_t i;

    if ((ring == NULL) || (out == NULL) || (count == 0U))
    {
        return 0U;
    }

    write = ring->write_index;
    available = write - ring->read_index;
    take = (available < count) ? available : count;

    /*
     * The caller asked for the newest `count` samples. When fewer exist, the
     * request is satisfied from the oldest available end so callers can detect
     * a still-filling buffer by the short return value.
     */
    start = write - take;

    for (i = 0U; i < take; ++i)
    {
        out[i] = ring->samples[(start + i) & VOICE_RING_MASK];
    }
    return take;
}

uint32_t voice_ring_take_window(voice_ring_t *ring,
                                int16_t *out,
                                uint32_t count)
{
    uint32_t write;
    uint32_t read;
    uint32_t i;

    if ((ring == NULL) || (out == NULL) || (count == 0U) ||
        (count > VOICE_RING_CAPACITY))
    {
        return 0U;
    }

    /*
     * Latch both cursors once. write_index is loaded BEFORE read_index so the
     * pending figure can only ever be an underestimate -- a producer that
     * advances write_index between the two loads makes us wait one poll longer
     * rather than hand back samples that were not there yet.
     *
     * Neither value is re-read below: the copy is bounded entirely by these two
     * snapshots, which is what stops a producer appending mid-copy from
     * extending the window underneath us.
     */
    write = ring->write_index;
    read = ring->read_index;

    if ((write - read) < count)
    {
        /*
         * Not a whole window yet. Leave the cursor exactly where it is: the
         * samples already buffered are the beginning of the window we will
         * classify once the rest arrives.
         */
        return 0U;
    }

    for (i = 0U; i < count; ++i)
    {
        out[i] = ring->samples[(read + i) & VOICE_RING_MASK];
    }

    /*
     * Published after the copy, in one 32-bit store. The producer only ever
     * reads this field, so a stale value costs it room -- which fails closed --
     * and never a sample it has not written.
     */
    ring->read_index = read + count;
    return count;
}

void voice_ring_note_error(voice_ring_t *ring, uint32_t error_code)
{
    if (ring == NULL)
    {
        return;
    }
    ring->error_count += 1U;
    ring->last_error = error_code;
}

void voice_ring_reset_counters(voice_ring_t *ring)
{
    if (ring == NULL)
    {
        return;
    }
    ring->overrun_count = 0U;
    ring->error_count = 0U;
    ring->last_error = 0U;
}
