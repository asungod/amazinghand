/*
 * Host tests for voice_app.c -- the passive-integration state machine.
 *
 * This file includes voice_app.h and nothing else. That is the point of the
 * module: voice_app.c has no RT-Thread, no FSP and no device reference, so its
 * whole decision policy can be driven here from a scripted voice_app_io_t
 * rather than from a board. tests/test_voice_app_titan_c.c covers the glue that
 * supplies the real table.
 *
 * The three rules under test are stated in voice_app.h; each has a case here
 * that fails if the rule is removed:
 *
 *   R1 window completeness  -> case 2   (and mutation 1)
 *   R2 overrun splice       -> cases 3, 8, 11 (and mutation 2)
 *   R3 no stale result      -> case 4   (and mutation 3)
 *
 * The scripted I/O model is deliberately able to lie in specific ways, because
 * the failures worth catching are the ones where the outside world returns a
 * plausible-looking answer that is subtly wrong:
 *
 *   - take can report a short window, the way voice_ring_take_window() does
 *     while the ring is still filling.
 *   - the overrun counter can move at a chosen *call number*, so the harness
 *     can place the gap between the two reads voice_app_step_capture() makes
 *     around the copy. A model that only moved the counter between polls would
 *     leave the mid-copy check untested.
 *   - infer can fail, or succeed with a decision that is not usable.
 */

#include "voice_app.h"

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* ------------------------------------------------------------------------- */
/* Check plumbing, same shape as the rest of the suite: every check is
 * recorded, failures are printed with their line, and the process exits
 * non-zero so the Python wrapper's returncode assertion still sees them. */

static uint32_t g_checks;
static uint32_t g_failures;

#define CHECK(cond)                                                        \
    do                                                                     \
    {                                                                      \
        g_checks += 1U;                                                    \
        if (!(cond))                                                       \
        {                                                                  \
            g_failures += 1U;                                              \
            printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
        }                                                                  \
    } while (0)

static void run_case(const char *slug, void (*fn)(void))
{
    uint32_t failures_before = g_failures;
    uint32_t checks_before = g_checks;

    fn();
    if (g_failures != failures_before)
    {
        printf("[case] %s: FAILED (%u failures, %u checks)\n",
               slug,
               (unsigned)(g_failures - failures_before),
               (unsigned)(g_checks - checks_before));
    }
    else
    {
        printf("[case] %s: ok (%u checks)\n",
               slug,
               (unsigned)(g_checks - checks_before));
    }
}

/* ------------------------------------------------------------------------- */
/* The scripted outside world. */

/*
 * One window buffer for the whole file. It is file scope on purpose: the
 * property under test is that the APP uses the caller's buffer rather than
 * anything of its own, and case 11 asserts the take was handed this exact
 * pointer. A 32 KB local would also be a test artefact rather than a
 * requirement.
 */
static int16_t g_window[VOICE_WINDOW_SAMPLES];

typedef struct
{
    /* capture */
    int start_result;      /* what capture_start returns */
    uint32_t start_calls;
    uint32_t stop_calls;
    uint8_t capture_open;

    /* window */
    uint32_t available;    /* samples take_window reports */
    uint32_t take_calls;
    const int16_t *last_take_out;
    uint32_t last_take_count;
    uint32_t take_count_mismatch;

    /* producer counters */
    uint32_t overrun;
    uint32_t accepted;
    uint32_t errors;
    uint32_t overrun_calls;

    /*
     * Overrun injection. When overrun_jump_at_call is non-zero, the counter
     * jumps by overrun_jump_by on exactly that call number. Call numbers are
     * per-poll: call 1 is the refresh at the top of step_capture, call 2 is the
     * re-read after the copy. Jumping on 2 models a gap that lands mid-copy.
     */
    uint32_t overrun_jump_at_call;
    uint32_t overrun_jump_by;

    /* inference */
    uint32_t infer_calls;
    int infer_result;
    int32_t infer_class;
    float infer_confidence;
    int32_t infer_score;
    uint32_t infer_ms;
    const int16_t *last_infer_samples;

    /* capture stats */
    uint32_t stats_calls;
    uint32_t stats_overrun;
    uint32_t stats_error_count;
    uint32_t stats_last_error;
    int32_t stats_peak;
    float stats_rms;
    float stats_dc;
} voice_fake_t;

static int fake_capture_start(void *ctx)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->start_calls += 1U;
    if (fake->start_result != 0)
    {
        return fake->start_result;
    }
    fake->capture_open = 1U;
    return 0;
}

static void fake_capture_stop(void *ctx)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->stop_calls += 1U;
    fake->capture_open = 0U;
}

/*
 * The scripted window source.
 *
 * It models the CONSUMING, all-or-nothing contract voice_app.h now states: a
 * whole window is either handed over and consumed, or nothing is handed over
 * and nothing is consumed. `available` is how many samples the source is
 * holding right now, and a successful take drains exactly that many.
 *
 * The source is a live microphone, so a successful take is followed by another
 * window arriving -- without that, a case that runs several cycles would be
 * modelling a source that was unplugged after the first one, which is not the
 * situation any of these cases is about. Starvation is expressed by `available`
 * being below a window, which is what case 2 does.
 *
 * The real ring's drain is not modelled here and is not meant to be: that is
 * covered against the actual voice_ring_t in test_voice_app_titan_c.c.
 */
static uint32_t fake_take_window(void *ctx, int16_t *out, uint32_t count)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->take_calls += 1U;
    fake->last_take_out = out;
    fake->last_take_count = count;

    if (count != (uint32_t)VOICE_WINDOW_SAMPLES)
    {
        fake->take_count_mismatch += 1U;
    }

    if (fake->available < count)
    {
        /* Short: nothing copied, nothing consumed, cursor unmoved. */
        return 0U;
    }

    /* Deterministic ramp, so a caller could tell windows apart if it wanted. */
    for (uint32_t i = 0U; i < count; ++i)
    {
        out[i] = (int16_t)(i & 0x7fff);
    }

    fake->available -= count;
    fake->available += (uint32_t)VOICE_WINDOW_SAMPLES;
    return count;
}

static uint32_t fake_accepted_samples(void *ctx)
{
    return ((voice_fake_t *)ctx)->accepted;
}

static uint32_t fake_overrun_count(void *ctx)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->overrun_calls += 1U;
    if ((fake->overrun_jump_at_call != 0U) &&
        (fake->overrun_calls == fake->overrun_jump_at_call))
    {
        fake->overrun += fake->overrun_jump_by;
    }
    return fake->overrun;
}

static uint32_t fake_error_count(void *ctx)
{
    return ((voice_fake_t *)ctx)->errors;
}

static void fake_capture_stats(void *ctx, voice_app_capture_stats_t *out)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->stats_calls += 1U;
    out->samples_captured = fake->accepted;
    out->error_count = fake->stats_error_count;
    out->overrun_count = fake->stats_overrun;
    out->last_error = fake->stats_last_error;
    out->peak = fake->stats_peak;
    out->rms = fake->stats_rms;
    out->dc_offset = fake->stats_dc;
    out->running = fake->capture_open;
}

static int fake_infer(void *ctx,
                      const int16_t *samples,
                      voice_app_decision_t *out)
{
    voice_fake_t *fake = (voice_fake_t *)ctx;

    fake->infer_calls += 1U;
    fake->last_infer_samples = samples;

    if (fake->infer_result != 0)
    {
        return fake->infer_result;
    }

    out->class_index = fake->infer_class;
    out->confidence = fake->infer_confidence;
    out->score = fake->infer_score;
    out->elapsed_ms = fake->infer_ms;
    return 0;
}

static const voice_app_io_t g_fake_io = {
    NULL,
    fake_capture_start,
    fake_capture_stop,
    fake_take_window,
    fake_accepted_samples,
    fake_overrun_count,
    fake_error_count,
    fake_capture_stats,
    fake_infer,
};

/* ------------------------------------------------------------------------- */
/* Fixture. */

typedef struct
{
    voice_app_t app;
    voice_fake_t fake;
    /*
     * The table is copied per fixture rather than shared, because the only
     * thing that varies between fixtures is ctx -- and the whole point of the
     * scripted model is that the module reaches the fake through it. A shared
     * const table with a NULL ctx would dereference NULL on the first callback.
     */
    voice_app_io_t io;
    voice_app_cfg_t cfg;
    voice_app_status_t status;
} fixture_t;

#define FAKE_FINGERPRINT (0xA17C0DE5U)

static void fixture_init(fixture_t *f)
{
    memset(f, 0, sizeof(*f));

    f->io = g_fake_io;
    f->io.ctx = &f->fake;

    f->fake.available = (uint32_t)VOICE_WINDOW_SAMPLES;
    f->fake.infer_class = 3;
    f->fake.infer_confidence = 0.75f;
    f->fake.infer_score = 41;
    f->fake.infer_ms = 42U;
    f->fake.stats_rms = 0.125f;
    f->fake.stats_peak = 4096;
    f->fake.stats_dc = -12.5f;

    f->cfg.io = &f->io;
    f->cfg.window_samples = g_window;
    f->cfg.model_fingerprint = FAKE_FINGERPRINT;

    voice_app_init(&f->app, &f->cfg);
}

/* Drive the machine to CAPTURING with a capture already open. */
static void fixture_open(fixture_t *f)
{
    CHECK(voice_app_start(&f->app) == 0);
    CHECK(voice_app_state(&f->app) == VOICE_STATE_INIT);
    voice_app_poll(&f->app);
    CHECK(voice_app_state(&f->app) == VOICE_STATE_CAPTURING);
}

/* One full clean cycle: CAPTURING -> INFERENCING -> RESULT -> CAPTURING. */
static void fixture_run_cycle(fixture_t *f)
{
    voice_app_poll(&f->app); /* CAPTURING  -> INFERENCING */
    voice_app_poll(&f->app); /* INFERENCING -> RESULT */
    voice_app_poll(&f->app); /* RESULT -> CAPTURING */
}

/* ------------------------------------------------------------------------- */
/* 1. The happy path. */

static void case_cold_start_reaches_result(void)
{
    fixture_t f;

    fixture_init(&f);

    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(voice_app_start(&f.app) == 0);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INIT);
    CHECK(f.fake.start_calls == 0U); /* opening is deferred to the poll */
    CHECK(f.fake.capture_open == 0U);

    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.start_calls == 1U);
    CHECK(f.fake.capture_open == 1U);
    CHECK(f.fake.stats_calls >= 1U); /* the init baseline reads health */

    /* INFERENCING is a real, observable state, not a transient one. */
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);
    CHECK(f.fake.infer_calls == 0U);

    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_RESULT);
    CHECK(f.fake.infer_calls == 1U);
    CHECK(f.fake.last_infer_samples == g_window);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.state == VOICE_STATE_RESULT);
    CHECK(f.status.result_valid == 1U);
    CHECK(f.status.result_generation == 1U);
    CHECK(f.status.last_class == 3);
    CHECK(f.status.last_confidence > 0.74f);
    CHECK(f.status.last_confidence < 0.76f);
    CHECK(f.status.last_score == 41);
    CHECK(f.status.last_inference_ms == 42U);
    CHECK(f.status.cycles_completed == 1U);
    CHECK(f.status.cycles_discarded == 0U);
    CHECK(f.status.cycles_failed == 0U);
    CHECK(f.status.samples_captured == (uint32_t)VOICE_WINDOW_SAMPLES);
    CHECK(f.status.samples_expected == (uint32_t)VOICE_WINDOW_SAMPLES);
    CHECK(f.status.model_fingerprint == FAKE_FINGERPRINT);
    CHECK(f.status.pdm_error_count == 0U);

    /* And the machine goes round again. */
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);

    fixture_run_cycle(&f);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_generation == 2U);
    CHECK(f.status.cycles_completed == 2U);
    CHECK(f.status.result_valid == 1U);
}

/* ------------------------------------------------------------------------- */
/* 2. R1 -- a short window is never inferred. */

static void case_short_window_is_not_inferred(void)
{
    fixture_t f;
    uint32_t i;

    fixture_init(&f);
    f.fake.available = (uint32_t)VOICE_WINDOW_SAMPLES - 1U;
    fixture_open(&f);

    for (i = 0U; i < 20U; ++i)
    {
        voice_app_poll(&f.app);
        CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    }

    voice_app_status(&f.app, &f.status);
    CHECK(f.fake.infer_calls == 0U);
    CHECK(f.status.result_valid == 0U);
    CHECK(f.status.result_generation == 0U);
    CHECK(f.status.cycles_completed == 0U);
    /*
     * Zero, not "just under a window": the take is all-or-nothing, so a source
     * that is one sample short hands over nothing at all. The old contract
     * copied the short range and reported its length, which is the shape that
     * let a partial, still-growing buffer look like a window.
     */
    CHECK(f.status.samples_captured == 0U);
    CHECK(f.status.samples_expected == (uint32_t)VOICE_WINDOW_SAMPLES);

    /* The guard must gate, not deadlock: one more sample unblocks it. */
    f.fake.available = (uint32_t)VOICE_WINDOW_SAMPLES;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);
}

/* ------------------------------------------------------------------------- */
/* 3. R2 -- an overrun abandons the cycle and quarantines a full window. */

static void case_overrun_discards_and_recovers(void)
{
    fixture_t f;

    fixture_init(&f);
    f.fake.accepted = 5000U; /* the ring already holds history at start-up */
    fixture_open(&f);
    CHECK(f.app.last_overrun == 0U);
    CHECK(f.app.accept_baseline == 5000U);

    /* The producer reports a gap. */
    f.fake.overrun = 4096U;
    f.fake.accepted = 6000U;
    voice_app_poll(&f.app);

    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.infer_calls == 0U);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.cycles_discarded == 1U);
    CHECK(f.status.result_generation == 0U);
    CHECK(f.status.overrun_count == 4096U);

    /* Re-polling with nothing new must not "clear" the quarantine. */
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.infer_calls == 0U);

    /* One sample short of a full clean window: still quarantined. */
    f.fake.accepted = 6000U + (uint32_t)VOICE_WINDOW_SAMPLES - 1U;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.infer_calls == 0U);

    /* Exactly a full window of newly accepted samples: recovered. */
    f.fake.accepted = 6000U + (uint32_t)VOICE_WINDOW_SAMPLES;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);

    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_RESULT);
    CHECK(f.fake.infer_calls == 1U);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.cycles_completed == 1U);
    CHECK(f.status.cycles_discarded == 1U);

    /* The counter is latched: the next window is not discarded again. */
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.cycles_discarded == 1U);
}

/* ------------------------------------------------------------------------- */
/* 4. R3 -- a failure never republishes the previous decision. */

static void case_failure_publishes_no_stale_result(void)
{
    fixture_t f;
    uint32_t generation_after_failure;

    fixture_init(&f);
    fixture_open(&f);
    f.fake.infer_class = 3;
    fixture_run_cycle(&f);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_valid == 1U);
    CHECK(f.status.result_generation == 1U);
    CHECK(f.status.last_class == 3);

    /* The model becomes unavailable. */
    f.fake.infer_result = -1;
    voice_app_poll(&f.app); /* CAPTURING  -> INFERENCING */
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);
    voice_app_poll(&f.app); /* INFERENCING -> MODEL_ERROR */
    CHECK(voice_app_state(&f.app) == VOICE_STATE_MODEL_ERROR);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_valid == 0U);
    CHECK(f.status.result_generation == 1U);
    CHECK(f.status.cycles_failed == 1U);
    CHECK(f.status.last_class == 3); /* kept for diagnosis only */

    /*
     * The load-bearing assertion: a reader that remembered generation 1 gets
     * generation 1 back, with result_valid clear, so it cannot mistake the old
     * class for a new decision.
     */
    generation_after_failure = f.status.result_generation;
    CHECK(generation_after_failure == 1U);
    CHECK(f.status.result_valid == 0U);

    /* Latched: polling does not quietly retry or republish. */
    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    voice_app_status(&f.app, &f.status);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_MODEL_ERROR);
    CHECK(f.status.result_generation == 1U);
    CHECK(f.status.result_valid == 0U);
    CHECK(f.fake.infer_calls == 2U);

    /* Recovery, and the next decision is distinguishable from the last one. */
    CHECK(voice_app_start(&f.app) == 0);
    f.fake.infer_result = 0;
    f.fake.infer_class = 5;
    f.fake.infer_confidence = 0.5f;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    fixture_run_cycle(&f);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_generation == 2U);
    CHECK(f.status.last_class == 5);
    CHECK(f.status.result_valid == 1U);
}

/* ------------------------------------------------------------------------- */
/* 5. R3 -- a decision that is not usable is a model error, not a result. */

static void case_unusable_decision_is_model_error(void)
{
    fixture_t f;

    /* Negative class index. */
    fixture_init(&f);
    fixture_open(&f);
    f.fake.infer_class = -1;
    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_MODEL_ERROR);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_valid == 0U);
    CHECK(f.status.result_generation == 0U);

    /* NaN confidence: the positive-assertion test has to reject it. */
    fixture_init(&f);
    fixture_open(&f);
    f.fake.infer_confidence = NAN;
    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_MODEL_ERROR);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_valid == 0U);

    /* Out-of-range confidence in the other direction. */
    fixture_init(&f);
    fixture_open(&f);
    f.fake.infer_confidence = 1.5f;
    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_MODEL_ERROR);
}

/* ------------------------------------------------------------------------- */
/* 6. Capture that will not open. */

static void case_capture_start_failure(void)
{
    fixture_t f;
    uint32_t i;

    for (i = 0U; i < 2U; ++i)
    {
        fixture_init(&f);
        /*
         * Both a plain negative return and an FSP-style negated fsp_err_t; the
         * module only promises "non-zero means failure".
         */
        f.fake.start_result = (i == 0U) ? -1 : (int)(-0x00000005);

        /* Not fixture_open(): that helper asserts a successful transition. */
        CHECK(voice_app_start(&f.app) == 0);
        CHECK(voice_app_state(&f.app) == VOICE_STATE_INIT);
        voice_app_poll(&f.app);

        CHECK(voice_app_state(&f.app) == VOICE_STATE_AUDIO_ERROR);
        CHECK(f.fake.start_calls == 1U);
        CHECK(f.fake.capture_open == 0U);

        voice_app_status(&f.app, &f.status);
        CHECK(f.status.cycles_failed == 1U);
        CHECK(f.status.result_valid == 0U);
        CHECK(f.status.result_generation == 0U);
    }

    /* Latched: no reopen storm from the thread's poll loop. */
    for (i = 0U; i < 100U; ++i)
    {
        voice_app_poll(&f.app);
    }
    CHECK(voice_app_state(&f.app) == VOICE_STATE_AUDIO_ERROR);
    CHECK(f.fake.start_calls == 1U);

    /* And the failure is recoverable when the device comes back. */
    f.fake.start_result = 0;
    CHECK(voice_app_start(&f.app) == 0);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.capture_open == 1U);
    CHECK(f.fake.start_calls == 2U);
}

/* ------------------------------------------------------------------------- */
/* 7. Stop and restart. */

static void case_stop_then_restart_recovers(void)
{
    fixture_t f;
    uint32_t i;

    fixture_init(&f);
    fixture_open(&f);
    fixture_run_cycle(&f);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_generation == 1U);
    CHECK(f.status.result_valid == 1U);

    voice_app_stop(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(f.fake.stop_calls == 1U);
    CHECK(f.fake.capture_open == 0U);

    voice_app_status(&f.app, &f.status);
    /* A stopped module has no current result. */
    CHECK(f.status.result_valid == 0U);
    CHECK(f.status.result_generation == 1U);

    for (i = 0U; i < 10U; ++i)
    {
        voice_app_poll(&f.app);
    }
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(f.fake.start_calls == 1U);

    /* Restart. */
    CHECK(voice_app_start(&f.app) == 0);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.start_calls == 2U);

    fixture_run_cycle(&f);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_generation == 2U); /* monotonic across a restart */
    CHECK(f.status.result_valid == 1U);
    CHECK(f.status.cycles_completed == 1U); /* per-run counters did reset */
    CHECK(f.app.result_generation == 2U);

    /* Stopping twice is harmless. */
    voice_app_stop(&f.app);
    voice_app_stop(&f.app);
    CHECK(f.fake.stop_calls == 2U); /* the second call had nothing to close */
}

/* ------------------------------------------------------------------------- */
/* 8. Compile-time / explicit disable. */

static void case_disabled_reports_disabled(void)
{
    fixture_t f;
    voice_app_cfg_t bad_cfg;

    fixture_init(&f);
    voice_app_disable(&f.app);

    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(voice_app_start(&f.app) == -1);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);

    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(f.fake.start_calls == 0U);
    CHECK(f.fake.take_calls == 0U);
    CHECK(f.fake.infer_calls == 0U);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.state == VOICE_STATE_DISABLED);
    CHECK(f.status.result_valid == 0U);
    CHECK(f.status.result_generation == 0U);

    /* A half-configured app must fail closed, not run with a NULL window. */
    memset(&bad_cfg, 0, sizeof(bad_cfg));
    bad_cfg.io = &g_fake_io;
    bad_cfg.window_samples = NULL;
    voice_app_init(&f.app, &bad_cfg);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(voice_app_start(&f.app) == -1);
    voice_app_poll(&f.app);
    CHECK(f.fake.start_calls == 0U);

    /* Same for a NULL io table. */
    bad_cfg.io = NULL;
    bad_cfg.window_samples = g_window;
    voice_app_init(&f.app, &bad_cfg);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_DISABLED);
    CHECK(voice_app_start(&f.app) == -1);

    /* And NULL arguments reach every entry point without faulting. */
    voice_app_init(NULL, &bad_cfg);
    voice_app_start(NULL);
    voice_app_stop(NULL);
    voice_app_disable(NULL);
    voice_app_poll(NULL);
    voice_app_status(NULL, &f.status);
    CHECK(f.status.state == VOICE_STATE_DISABLED);
    voice_app_status(&f.app, NULL);
    CHECK(voice_app_state(NULL) == VOICE_STATE_DISABLED);
    CHECK(strcmp(voice_app_state_name(VOICE_STATE_DISABLED), "disabled") == 0);
    CHECK(strcmp(voice_app_state_name(VOICE_STATE_MODEL_ERROR), "model_error") == 0);
    CHECK(voice_app_state_name((voice_state_t)99) != NULL);
}

/* ------------------------------------------------------------------------- */
/* 9. An overrun that lands DURING the copy. */

static void case_overrun_during_copy_is_caught(void)
{
    fixture_t f;

    fixture_init(&f);
    f.fake.accepted = 1000U;
    fixture_open(&f);

    /*
     * Jump on call 2 of the next poll, i.e. between the counter read taken
     * before the copy and the one taken after it. The window still looks full,
     * so a module that only checked the counter before the copy would classify
     * a spliced window.
     */
    f.fake.overrun = 0U;
    f.fake.overrun_calls = 0U;
    f.fake.overrun_jump_at_call = 2U;
    f.fake.overrun_jump_by = 512U;
    f.fake.accepted = 2000U;

    voice_app_poll(&f.app);

    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    CHECK(f.fake.infer_calls == 0U);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.cycles_discarded == 1U);
    CHECK(f.status.overrun_count == 512U);

    /* Disarm the injection; the module is still quarantined until it refills. */
    f.fake.overrun_jump_at_call = 0U;
    f.fake.accepted = 2000U + (uint32_t)VOICE_WINDOW_SAMPLES - 1U;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);

    f.fake.accepted = 2000U + (uint32_t)VOICE_WINDOW_SAMPLES;
    voice_app_poll(&f.app);
    CHECK(voice_app_state(&f.app) == VOICE_STATE_INFERENCING);
}

/* ------------------------------------------------------------------------- */
/* 10. Sustained overrun never reaches inference. */

static void case_sustained_overrun_never_infers(void)
{
    fixture_t f;
    uint32_t i;

    fixture_init(&f);
    fixture_open(&f);

    for (i = 0U; i < 50U; ++i)
    {
        f.fake.overrun += 160U;
        f.fake.accepted += 160U;
        voice_app_poll(&f.app);
        CHECK(voice_app_state(&f.app) == VOICE_STATE_CAPTURING);
    }

    CHECK(f.fake.infer_calls == 0U);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.result_generation == 0U);
    /* One discard episode, not fifty: the episode is not re-counted. */
    CHECK(f.status.cycles_discarded == 1U);
}

/* ------------------------------------------------------------------------- */
/* 11. The window the module classifies is the caller's buffer, sized right. */

static void case_window_buffer_and_sizing(void)
{
    fixture_t f;

    fixture_init(&f);
    fixture_open(&f);
    fixture_run_cycle(&f);

    /*
     * Exactly one take per CAPTURING step: the open and the inference do not
     * sample the ring, and RESULT does not either.
     */
    CHECK(f.fake.take_calls == 1U);
    CHECK(f.fake.take_count_mismatch == 0U);
    CHECK(f.fake.last_take_count == (uint32_t)VOICE_WINDOW_SAMPLES);
    CHECK(f.fake.last_take_out == g_window);
    CHECK(f.fake.last_infer_samples == g_window);
    /* The window the classifier saw is the one the take wrote into. */
    CHECK(g_window[0] == 0);
    CHECK(g_window[1] == 1);
}

/* ------------------------------------------------------------------------- */
/* 12. The evidence flags are never set by code, and health is mirrored. */

static void case_evidence_flags_and_health(void)
{
    fixture_t f;

    fixture_init(&f);
    fixture_open(&f);
    f.fake.errors = 3U;
    f.fake.stats_overrun = 4096U;
    f.fake.stats_last_error = 0x00000800U; /* PDM_ERROR_BUFFER_OVERWRITE */
    fixture_run_cycle(&f);

    voice_app_status(&f.app, &f.status);
    CHECK(f.status.field_accuracy_validated == 0U);
    CHECK(f.status.hardware_inference_validated == 0U);
    CHECK(f.status.pdm_error_count == 3U);
    CHECK(f.status.pdm_last_error == 0x00000800U);
    CHECK(f.status.dropped_samples == 4096U);
    CHECK(f.status.rms > 0.12f);
    CHECK(f.status.rms < 0.13f);
    CHECK(f.status.peak == 4096);
    CHECK(f.status.dc_offset < -12.4f);
    CHECK(f.status.dc_offset > -12.6f);
    CHECK(f.status.accepted_samples == 0U);

    /* A failure does not flip them either. */
    f.fake.infer_result = -1;
    voice_app_poll(&f.app);
    voice_app_poll(&f.app);
    voice_app_status(&f.app, &f.status);
    CHECK(f.status.state == VOICE_STATE_MODEL_ERROR);
    CHECK(f.status.field_accuracy_validated == 0U);
    CHECK(f.status.hardware_inference_validated == 0U);
}

/* ------------------------------------------------------------------------- */

int main(void)
{
    /*
     * Unbuffered: a mutation that walks off the end of the window buffer
     * faults instead of failing a check, and a block-buffered stdout would lose
     * the report with it. Unbuffered, the last case line still says where the
     * run stopped.
     */
    setvbuf(stdout, NULL, _IONBF, 0);

    run_case("1-cold-start-window-then-result",
             case_cold_start_reaches_result);
    run_case("2-short-window-is-not-inferred",
             case_short_window_is_not_inferred);
    run_case("3-overrun-discards-and-recovers",
             case_overrun_discards_and_recovers);
    run_case("4-inference-failure-publishes-no-stale-result",
             case_failure_publishes_no_stale_result);
    run_case("5-unusable-decision-is-model-error",
             case_unusable_decision_is_model_error);
    run_case("6-capture-start-failure-is-audio-error",
             case_capture_start_failure);
    run_case("7-stop-then-restart-recovers",
             case_stop_then_restart_recovers);
    run_case("8-disabled-reports-disabled",
             case_disabled_reports_disabled);
    run_case("9-overrun-during-copy-is-caught",
             case_overrun_during_copy_is_caught);
    run_case("10-sustained-overrun-never-infers",
             case_sustained_overrun_never_infers);
    run_case("11-window-buffer-is-the-callers",
             case_window_buffer_and_sizing);
    run_case("12-evidence-flags-and-health-mirror",
             case_evidence_flags_and_health);

    if (g_failures != 0U)
    {
        printf("C voice app tests FAILED: %u of %u checks failed\n",
               (unsigned)g_failures,
               (unsigned)g_checks);
        return 1;
    }

    printf("C voice app tests passed (%u checks)\n", (unsigned)g_checks);
    return 0;
}
