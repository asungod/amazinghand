#ifndef SMART_HAND_VOICE_APP_H
#define SMART_HAND_VOICE_APP_H

#include "voice_config.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Passive-integration state machine for the Titan onboard keyword spotter.
 *
 * This file is deliberately free of RT-Thread, FSP, UART, GPIO, filesystem and
 * heap. Everything it needs from the outside world arrives through the
 * function-pointer table in voice_app_io_t, which is what lets the whole
 * decision policy below be exercised on the host with fakes instead of a
 * board. voice_app_titan.c supplies the real table; test_voice_app_c.c
 * supplies a scripted one.
 *
 * STAGE 1 SCOPE -- what this module is allowed to do
 *
 *   It captures, it classifies, and it publishes a decision into a read-only
 *   status block. It does not move a servo, it does not send a UART frame, and
 *   it does not start a training session. There is no output path from here to
 *   the mechanical hand in this stage; the only consumer is whatever polls
 *   voice_app_status(). Wiring a keyword to a motion is a later, separately
 *   reviewed change.
 *
 * THE THREE RULES THE STATE MACHINE ENFORCES
 *
 *   R1  A window is only inferred when the capture layer really handed back a
 *       whole VOICE_WINDOW_SAMPLES. take_window() is all-or-nothing, so a short
 *       return means the buffer has not filled yet; inferring on it would
 *       classify a fraction of a second of audio padded up to a window. The
 *       return value is checked, and a short read leaves the state in
 *       CAPTURING.
 *
 *   R2  An overrun invalidates the splice, not just the sample. When the ring
 *       rejects a block it leaves the older samples in place, so the newest
 *       VOICE_WINDOW_SAMPLES can silently span a wall-clock gap: audio from
 *       before the gap and audio from after it, laid end to end as if they were
 *       contiguous. That is worse for the front end than either half alone.
 *       So a growing overrun_count abandons the current cycle and the machine
 *       then waits for a full window's worth of NEW accepted samples before it
 *       will infer again -- see voice_app_step_capture() for why that interval
 *       is sufficient rather than merely plausible.
 *
 *   R3  A failure never leaves a stale decision looking current. Every
 *       published result carries a monotonically increasing generation number,
 *       and result_valid is cleared the instant anything goes wrong. A reader
 *       that saw generation 7 keeps seeing generation 7 while the module is in
 *       MODEL_ERROR, so it can tell "no new result" from "the same result
 *       again". The last class and confidence stay in the block for
 *       diagnostics, but they are marked stale, not republished.
 *
 *   None of these paths block, sleep, or retry in a loop. A failure parks the
 *   state machine in AUDIO_ERROR or MODEL_ERROR and poll() becomes a no-op
 *   until voice_app_start() is called again; the thread stays alive and every
 *   other module keeps running.
 */

typedef enum
{
    VOICE_STATE_DISABLED = 0, /* compiled out, or explicitly stopped: not running */
    VOICE_STATE_INIT,         /* a start was requested; capture is being opened */
    VOICE_STATE_CAPTURING,    /* accumulating a complete window */
    VOICE_STATE_INFERENCING,  /* running the front end and the network */
    VOICE_STATE_RESULT,       /* a fresh result is published */
    VOICE_STATE_AUDIO_ERROR,  /* capture would not open, or the PDM path failed */
    VOICE_STATE_MODEL_ERROR   /* inference is not available */
} voice_state_t;

/* ------------------------------------------------------------------------- */
/* The injected outside world.
 *
 * Six accessors and two actions; nothing here knows about FSP, RT-Thread, or
 * any specific microphone. Functions are mandatory unless the comment says
 * otherwise, and none of them may block: the capture accessors are called from
 * the voice thread between PDM interrupts, and the sampled-data ones are reads.
 */

/*
 * Signal health as the capture layer reports it. Field-for-field a mirror of
 * voice_capture_stats_t (voice_audio_titan.h), redeclared here because that
 * header pulls in the FSP types and this one must stay host-buildable.
 */
typedef struct
{
    uint32_t samples_captured; /* samples the PDM delivered, before buffering */
    uint32_t error_count;      /* PDM error interrupts */
    uint32_t overrun_count;    /* samples the ring refused because it was full */
    uint32_t last_error;       /* last pdm_error_t bitmask */
    int32_t peak;              /* magnitude, so INT16_MIN fits */
    float rms;
    float dc_offset;
    uint8_t running;
} voice_app_capture_stats_t;

/*
 * One inference outcome. class_index is the argmax over the logits,
 * confidence its dequantised probability, score the raw int8 logit. A negative
 * class_index, a confidence outside [0, 1] (including NaN), or a non-zero
 * return from infer() are all treated as an unavailable model, never as a
 * decision.
 */
typedef struct
{
    int32_t class_index;
    float confidence;
    int32_t score;
    uint32_t elapsed_ms;
} voice_app_decision_t;

/*
 * The whole outside world, as one table. `ctx` is passed back to every entry
 * point unchanged, so a caller can point the same functions at different rings.
 */
typedef struct
{
    void *ctx;

    /* Open/close continuous capture. start returns 0 on success, <0 on error. */
    int (*capture_start)(void *ctx);
    void (*capture_stop)(void *ctx);

    /*
     * Consuming copy of the OLDEST `count` samples. Returns `count` when a
     * whole window was available -- and has then advanced the consumer cursor
     * past exactly those samples -- or 0 when it was not, leaving the cursor
     * untouched so the next call sees the same, still-filling window.
     *
     * This MUST consume. A non-consuming read leaves the consumer cursor where
     * it was, and the ring then fills and stays full: the producer's fail-closed
     * overflow path refuses every later block, accepted_samples stops advancing,
     * and the R2 quarantine below can never be satisfied. Releasing the window
     * is what makes continuous capture possible at all.
     *
     * The `count` samples must be adjacent in time. A caller may not pad, and
     * may not treat a short return as a partial window.
     */
    uint32_t (*take_window)(void *ctx, int16_t *out, uint32_t count);

    /* Producer-side monotonic count of samples ACCEPTED into the buffer. */
    uint32_t (*accepted_samples)(void *ctx);

    /* Producer-side counters. overrun_count must be monotonic between resets. */
    uint32_t (*overrun_count)(void *ctx);
    uint32_t (*error_count)(void *ctx);

    /* Snapshot of signal health. Optional; skipped when NULL. */
    void (*capture_stats)(void *ctx, voice_app_capture_stats_t *out);

    /*
     * Run the front end and the network over exactly VOICE_WINDOW_SAMPLES
     * samples and fill `out`. Returns 0 on success, non-zero when the model is
     * unavailable.
     */
    int (*infer)(void *ctx, const int16_t *samples, voice_app_decision_t *out);
} voice_app_io_t;

/* ------------------------------------------------------------------------- */
/* Read-only view of the module. This is the only thing a consumer may read. */

typedef struct
{
    voice_state_t state;

    /* Capture accounting. */
    uint32_t samples_captured;  /* actual: what the last peek returned */
    uint32_t samples_expected;  /* expected: VOICE_WINDOW_SAMPLES */
    uint32_t accepted_samples;  /* producer monotonic count, as last read */

    /* PDM health. */
    uint32_t pdm_error_count;
    uint32_t pdm_last_error;
    uint32_t overrun_count;   /* ring overrun counter (blocks refused) */
    uint32_t dropped_samples; /* samples refused by the ring, from the capture layer */

    /* Signal. */
    float rms;
    int32_t peak;
    float dc_offset;

    /* Last published decision. Only meaningful when result_valid is 1. */
    uint32_t last_inference_ms;
    int32_t last_class;
    float last_confidence;
    int32_t last_score;

    /*
     * Staleness discriminator. result_generation increments ONLY when a new
     * decision is published, so a reader that remembers the generation it last
     * acted on can tell a repeat read of the same result from a new one.
     * result_valid is cleared on every failure and on stop.
     */
    uint32_t result_generation;
    uint8_t result_valid;

    /* Cycle accounting. */
    uint32_t cycles_completed;  /* results published */
    uint32_t cycles_discarded;  /* windows abandoned because of an overrun */
    uint32_t cycles_failed;     /* capture or model failures */

    /* Identifies the voice_model_data currently linked in. */
    uint32_t model_fingerprint;

    /*
     * Both are 0, and no code path in this repository makes them anything
     * else: voice_app_init() zeroes them and voice_app_status() reads them
     * straight back out. They exist so that the flow which turns a claim into
     * evidence -- labelled audio scored on the target, and then an inference
     * actually run on the RA8 -- has somewhere to record it. Neither has
     * happened, so both are 0, and no accuracy figure may be quoted from this
     * build until they are not. tests/test_voice_app.py greps voice_app.c to
     * keep it that way.
     */
    uint8_t field_accuracy_validated;
    uint8_t hardware_inference_validated;
} voice_app_status_t;

/* ------------------------------------------------------------------------- */
/* Configuration and state. Caller-owned and statically allocatable: nothing
 * here is ever allocated from the heap, and voice_app_t stays small because
 * the audio window and the classifier live with the caller.
 */

typedef struct
{
    const voice_app_io_t *io;

    /*
     * Scratch for one window. Must hold VOICE_WINDOW_SAMPLES samples and must
     * outlive the app. Kept in the caller's static storage on purpose: 32 KB on
     * an 8 KB thread stack would not end well.
     */
    int16_t *window_samples;

    /* Reported verbatim in the status block. */
    uint32_t model_fingerprint;
} voice_app_cfg_t;

typedef struct
{
    const voice_app_io_t *io;
    int16_t *window_samples;
    uint32_t model_fingerprint;

    voice_state_t state;
    uint8_t enabled; /* 1 unless compiled out or explicitly disabled */
    uint8_t started; /* a start has been requested and not yet stopped */

    uint32_t samples_captured;
    uint32_t accepted_samples;

    uint32_t overrun_count;
    uint32_t error_count;
    uint32_t last_error;
    uint32_t dropped_samples;

    /*
     * Discard window state. When the ring reports a fresh overrun the machine
     * records the producer's accepted count and refuses to infer until that
     * count has advanced by a whole window, guaranteeing the samples it
     * classifies were all accepted after the gap.
     */
    uint8_t discarding;
    uint32_t accept_baseline;
    uint32_t last_overrun;

    uint32_t result_generation;
    uint8_t result_valid;
    int32_t last_class;
    float last_confidence;
    int32_t last_score;
    uint32_t last_inference_ms;

    float rms;
    int32_t peak;
    float dc_offset;

    uint32_t cycles_completed;
    uint32_t cycles_discarded;
    uint32_t cycles_failed;

    /*
     * Evidence flags. Nothing in this module ever writes them: they are zeroed
     * by voice_app_init() and read straight back out by voice_app_status().
     * They are only ever set by a human edit that follows real evidence --
     * field_accuracy_validated once labelled audio has been scored on the
     * target, hardware_inference_validated once an inference has actually run
     * on the RA8 silicon. Neither has happened.
     */
    uint8_t field_accuracy_validated;
    uint8_t hardware_inference_validated;
} voice_app_t;

/* ------------------------------------------------------------------------- */
/* API. None of these block, allocate, or touch a device directly. */

/*
 * Bind a configured app to its I/O table. Leaves it in DISABLED with no
 * capture open; voice_app_start() is what actually turns it on.
 *
 * A NULL app, NULL cfg, NULL io table or NULL window buffer leaves the app
 * disabled rather than half-configured -- a miswired build fails closed.
 */
void voice_app_init(voice_app_t *app, const voice_app_cfg_t *cfg);

/*
 * Request capture. Drops any running capture first, so this doubles as the
 * recovery path out of AUDIO_ERROR / MODEL_ERROR and the restart path after
 * voice_app_stop(). Returns 0 when the request was accepted, -1 when the app is
 * disabled or unconfigured (state stays DISABLED). The device is opened on the
 * next poll, not here.
 */
int voice_app_start(voice_app_t *app);

/*
 * Close capture and park in DISABLED. The last decision is invalidated: a
 * stopped module has no current result. voice_app_start() brings it back.
 */
void voice_app_stop(voice_app_t *app);

/* Permanently park in DISABLED until voice_app_init() runs again. */
void voice_app_disable(voice_app_t *app);

/*
 * One non-blocking step. Exactly one state transition per call, so
 * INFERENCING is an observable state rather than a transient one. Call it from
 * a loop; it never sleeps.
 */
void voice_app_poll(voice_app_t *app);

/* Consistent copy of the read-only view. Safe to call from another thread. */
void voice_app_status(const voice_app_t *app, voice_app_status_t *out);

voice_state_t voice_app_state(const voice_app_t *app);

/* Stable lowercase name for logs and tests. Never NULL. */
const char *voice_app_state_name(voice_state_t state);

#ifdef __cplusplus
}
#endif

#endif
