#ifndef SMART_HAND_VOICE_AUDIO_H
#define SMART_HAND_VOICE_AUDIO_H

#include "voice_config.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Lock-free single-producer / single-consumer PCM ring buffer.
 * No RT-Thread, UART, GPIO, filesystem, or heap: the caller owns the struct.
 *
 * Producer: the PDM data callback. It must only move samples and bump
 * counters -- no feature extraction, formatting, or inference in interrupt
 * context. voice_ring_push is written to be safe there.
 *
 * Consumer: the low-priority voice thread, which takes a window of
 * VOICE_WINDOW_SAMPLES and runs the front end outside interrupt context. It
 * must CONSUME the window it classifies -- see voice_ring_take_window().
 *
 * The FSP binding lives in voice_audio_titan.c; this file stays host-testable.
 */

/* Power of two covering 2.05 s at 16 kHz. */
#define VOICE_RING_CAPACITY (32768U)
#define VOICE_RING_MASK (VOICE_RING_CAPACITY - 1U)

typedef struct
{
    int16_t samples[VOICE_RING_CAPACITY];
    volatile uint32_t write_index;  /* advanced by the producer only */
    volatile uint32_t read_index;   /* advanced by the consumer only */
    volatile uint32_t overrun_count;
    volatile uint32_t error_count;
    volatile uint32_t total_samples; /* monotonic, wrap-safe */
    /*
     * uint32_t, not uint8_t: pdm_error_t is a bitmask whose most important
     * member, PDM_ERROR_BUFFER_OVERWRITE, is (1UL << 11). Stored in a byte it
     * truncates to 0, which is exactly PDM_ERROR_NONE -- the buffer-overwrite
     * error would be indistinguishable from "no error at all".
     */
    volatile uint32_t last_error;
} voice_ring_t;

/*
 * Bring-up reset. Clears the whole structure, INCLUDING read_index.
 * Only valid before any consumer exists; a consumer holding a snapshot of
 * read_index would be corrupted by this. Capture start/stop use
 * voice_ring_reset_for_capture() instead.
 */
void voice_ring_init(voice_ring_t *ring);

/*
 * Control-path reset used when (re)starting capture.
 *
 * Producer-owned state is discarded and the ring is made to look empty, but
 * read_index is NOT written: it belongs to the consumer, and zeroing it
 * underneath a consumer that is mid-read would make it re-deliver audio that
 * was already consumed. Emptiness is expressed by moving write_index up to
 * read_index instead, which preserves the "write - read" invariant.
 *
 * Only call this while no producer can be pushing (the PDM block is idle).
 *
 * It DOES clear total_samples, overrun_count, error_count and last_error --
 * total_samples is documented on the struct as monotonic, which holds between
 * resets but not across a capture restart.
 */
void voice_ring_reset_for_capture(voice_ring_t *ring);

/*
 * Producer side. Appends count samples.
 *
 * Ownership: read_index belongs to the consumer and this function never
 * writes it. An earlier revision advanced read_index to make room, which is
 * not a legal single-producer/single-consumer operation -- it silently
 * rewrote audio the consumer was still reading.
 *
 * Overflow is fail-closed: when the ring lacks room for the whole block the
 * block is rejected and the unread audio is left untouched, rather than
 * evicting the oldest samples underneath the consumer. Callers must treat a
 * non-zero return as a gap in the stream, not as a retryable condition.
 *
 * Returns the number of samples NOT accepted (0 when the whole block landed).
 * A rejected block is added to overrun_count. total_samples counts only
 * accepted samples.
 */
uint32_t voice_ring_push(voice_ring_t *ring,
                         const int16_t *samples,
                         uint32_t count);

/* Samples currently readable. */
uint32_t voice_ring_available(const voice_ring_t *ring);

/*
 * Consumer side. Copies up to max_count readable samples in chronological
 * order and advances read_index past them. Returns the number copied.
 *
 * This is a streaming drain, not a window source: it consumes whatever is
 * there, so a caller that needs exactly VOICE_WINDOW_SAMPLES adjacent samples
 * wants voice_ring_take_window() instead.
 */
uint32_t voice_ring_read(voice_ring_t *ring, int16_t *out, uint32_t max_count);

/*
 * Consumer side. Copies exactly `count` chronologically contiguous samples
 * starting at the consumer cursor and advances read_index past them, or copies
 * nothing and leaves the cursor alone.
 *
 * Returns `count` when a whole window was available and has been consumed, and
 * 0 otherwise. There is no partial success: 0 means "not yet", not "here is
 * less", so a caller waiting for a window must return and try again rather than
 * classify what it got.
 *
 * WHY THIS MUST CONSUME, AND WHY voice_ring_peek_latest IS NOT ENOUGH
 *
 *   read_index belongs to the consumer. A non-consuming read never moves it, so
 *   nothing ever frees space: the producer's fail-closed overflow path refuses
 *   every block once the ring is full, total_samples stops advancing, and any
 *   policy that waits for a fresh window before inferring again can never be
 *   satisfied. Consuming the window is what makes continuous capture possible
 *   at all -- it is not an optimisation.
 *
 * OWNERSHIP AND WINDOW BOUNDS
 *
 *   write_index is read once, at the top, and never re-read. Everything below
 *   is bounded by that one snapshot, so a producer that appends while the copy
 *   is in progress cannot extend the window underneath it.
 *
 *   voice_ring_push() writes only to [write_index, write_index + count) and
 *   only when that range fits in the free space, so it can never write into
 *   [read_index, write_index) -- the range this function copies. On overflow it
 *   fails closed and stores nothing. That is what makes the window immutable
 *   for the duration of the copy rather than merely usually immutable.
 *
 *   The window therefore holds `count` samples that are adjacent in time, and
 *   it stays adjacent across a wrap: indexing goes through VOICE_RING_MASK per
 *   sample and the ring is circular, so sample i and sample i+1 are consecutive
 *   in time even when i+1 is a lower index than i.
 *
 *   read_index is published with a single 32-bit store AFTER the copy, so the
 *   producer never sees room that has not actually been freed. A stale
 *   read_index only makes it see less room, and it fails closed.
 *
 *   Only one thread may call this. It is the consumer cursor's sole owner, the
 *   same rule voice_ring_read() carries.
 */
uint32_t voice_ring_take_window(voice_ring_t *ring, int16_t *out, uint32_t count);

/*
 * Consumer side, NON-CONSUMING PREVIEW. Copies up to count samples in
 * chronological order without moving read_index, and returns how many were
 * copied.
 *
 * PREVIEW, NOT ACQUISITION. This function answers "what does the audio in the
 * buffer look like right now". It frees no space and advances no cursor, so a
 * caller that uses it as its only window source will fill the ring and stall
 * capture permanently -- which is exactly the defect that parked the state
 * machine in CAPTURING on hardware. The function that hands a window to the
 * inference path is voice_ring_take_window(): it consumes, and it is
 * all-or-nothing. Use this one for diagnostics, level checks and tests.
 *
 * When fewer than count samples are available the copy starts at the oldest
 * readable sample rather than the newest, so a caller waiting for a full
 * window MUST check the return value: a short return means the buffer has not
 * filled yet and the data is the whole readable range, not the most recent
 * count samples. voice_ring_take_window() deliberately does not share that
 * quirk -- it reports 0 and copies nothing rather than a partial window.
 */
uint32_t voice_ring_peek_latest(const voice_ring_t *ring,
                                int16_t *out,
                                uint32_t count);

/* Producer side. Records one PDM error interrupt. Cheap enough for an ISR. */
void voice_ring_note_error(voice_ring_t *ring, uint32_t error_code);

void voice_ring_reset_counters(voice_ring_t *ring);

#ifdef __cplusplus
}
#endif

#endif
