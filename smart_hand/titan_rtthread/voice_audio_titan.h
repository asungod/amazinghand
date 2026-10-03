#ifndef SMART_HAND_VOICE_AUDIO_TITAN_H
#define SMART_HAND_VOICE_AUDIO_TITAN_H

#include "voice_audio.h"
#include "voice_config.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Titan-side binding for the onboard PDM microphone.
 *
 * Facts this file is built on, all read out of the FSP driver rather than
 * assumed (see docs/TITAN_VOICE_RECON_2026-09-22.md for the full trail):
 *
 *   - ra/fsp/src/r_pdm/r_pdm.c:27   PDM_PRV_FIFO_SAMPLE_SIZE == sizeof(uint32_t),
 *                                   and one 32-bit FIFO entry carries exactly
 *                                   one PCM sample (PDDRRCHn.DAT[19:0]).
 *   - r_pdm.c:269-273               number_of_data_to_callback is the callback
 *                                   granularity in FIFO entries; it must be a
 *                                   multiple of 1<<interrupt_threshold and
 *                                   must divide buffer_size/4.
 *   - r_pdm.c:445-452               R_PDM_Read returns FSP_ERR_UNSUPPORTED, so
 *                                   polling is impossible. Audio can only be
 *                                   moved from the data interrupt.
 *   - r_pdm.c:848-878               pdm_dat_isr reads the FIFO count from
 *                                   PDDSR and copies entries on every
 *                                   interrupt, firing PDM_EVENT_DATA once
 *                                   rx_int_count reaches the configured
 *                                   granularity.
 *   - PDM_PCM_WIDTH_16_BITS_0_14    right-aligned {sign, D[14:0]}, so the
 *                                   sample is the low 16 bits of the word.
 *
 * NOT verified: the real sample rate. The repo contains no PDM clock source
 * configuration, and the configured SINCRNG/SINCDEC/CKDIV values are byte for
 * byte the chip's reset defaults, so the 16000 Hz in configuration.xml cannot
 * be taken as measured. voice_audio_titan_probe() exists to settle it on
 * hardware.
 */

/*
 * Read-only status block. This is what the firmware may expose; nothing here
 * feeds a servo decision. Names match the task book's stage D field list.
 */
typedef struct
{
    /*
     * Samples the microphone delivered, including any that the ring then
     * rejected -- this is what the sample-rate probe divides by elapsed time,
     * so it must count what was captured, not what survived buffering. Use
     * overrun_count (or the ring's own total_samples) for the latter.
     */
    uint32_t samples_captured;
    uint32_t callbacks;          /* PDM_EVENT_DATA count */
    uint32_t overrun_count;      /* samples rejected because the ring was full */
    uint32_t error_count;        /* PDM_EVENT_ERROR count */
    /*
     * uint32_t for the same reason as voice_ring_t::last_error: pdm_error_t
     * carries PDM_ERROR_BUFFER_OVERWRITE at bit 11, which a byte field would
     * truncate to 0 == PDM_ERROR_NONE.
     */
    uint32_t last_error;         /* last pdm_error_t seen */
    uint8_t running;
    /*
     * Magnitude, so it has to hold |-32768| == 32768. An int16_t field cannot
     * represent that: negating INT16_MIN in 16 bits wraps back to INT16_MIN,
     * which then compares as the smallest value rather than the largest, and
     * a full-scale negative sample would silently never register as a peak.
     */
    int32_t peak;
    float rms;                   /* sqrt of the mean square */
    float dc_offset;             /* running mean, exposes a PDM DC bias */
} voice_capture_stats_t;

/*
 * Open and start continuous capture. Returns 0 on success, negative on an FSP
 * error (the negated fsp_err_t). Safe to call once at start-up.
 */
int voice_audio_titan_start(void);

void voice_audio_titan_stop(void);

/*
 * The ring the data interrupt writes into. Never NULL after start.
 *
 * Deliberately NOT const. read_index in that struct belongs to the consumer,
 * and the consumer is the only thing that can free space in it; handing the
 * ring back read-only invited exactly the mistake that stalled capture, where
 * nothing advanced the cursor and the buffer filled up permanently.
 */
voice_ring_t *voice_audio_titan_ring(void);

/*
 * Snapshot the counters written by the PDM data interrupt.
 *
 * The interrupt updates g_stats continuously, so a plain struct copy can tear:
 * the caller may see samples_captured from after a callback paired with rms
 * accumulated before it. Both this and reset_stats() therefore run inside a
 * minimal critical section (interrupts masked) and return a consistent set.
 * The masked region is a snapshot only -- struct copy plus three scalar reads.
 * The uint64->float conversions, the divide and the square root all run after
 * interrupts are restored, so neither the PDM interrupt nor the servo bus ever
 * waits on floating point.
 *
 * A sequence lock would avoid masking entirely, but the writer here is an ISR
 * that can preempt the reader at any point, so the reader would have to retry
 * against a counter the ISR also updates; masking is simpler and provably
 * correct for a structure this small.
 */
void voice_audio_titan_stats(voice_capture_stats_t *out);

/* Root-mean-square of everything captured since the last reset. */
float voice_audio_titan_rms(void);

/* Zero the counters and accumulators. Also runs inside a critical section. */
void voice_audio_titan_reset_stats(void);

/*
 * Hardware probe for stage A evidence. Blocks for duration_ms while collecting,
 * then fills `out` with what was actually observed. Call with the servo bus
 * unpowered; this function never touches the servo path.
 *
 * Returns 0 on success, negative on an FSP error.
 */
int voice_audio_titan_probe(uint32_t duration_ms, voice_capture_stats_t *out);

#ifdef __cplusplus
}
#endif

#endif
