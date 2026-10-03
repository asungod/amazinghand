/*
 * Passive-integration state machine for the Titan onboard keyword spotter.
 *
 * Zero RT-Thread, zero FSP, zero heap, zero blocking. Everything the machine
 * needs from the outside arrives through voice_app_io_t; see voice_app.h for
 * the three rules (R1 window completeness, R2 overrun splice rejection, R3 no
 * stale result) that the code below exists to enforce.
 *
 * The module never actuates anything. It has no servo include, no UART write,
 * and no path to the mechanical hand; the only thing it produces is a
 * generation-numbered decision in a read-only status block.
 */

#include "voice_app.h"

#include <string.h>

/* ------------------------------------------------------------------------- */
/* Small helpers. */

static void voice_app_invalidate_result(voice_app_t *app)
{
    /*
     * Cleared, not republished. last_class / last_confidence stay put for
     * diagnostics, but result_valid drops and result_generation does NOT move,
     * so a reader that already saw generation N still sees N. There is no
     * window in which a failure makes the previous decision look new.
     */
    app->result_valid = 0U;
}

static void voice_app_enter_failure(voice_app_t *app, voice_state_t state)
{
    voice_app_invalidate_result(app);
    app->cycles_failed += 1U;
    app->state = state;
}

static void voice_app_refresh_health(voice_app_t *app)
{
    const voice_app_io_t *io = app->io;

    if (io == NULL)
    {
        return;
    }

    if (io->accepted_samples != NULL)
    {
        app->accepted_samples = io->accepted_samples(io->ctx);
    }

    if (io->overrun_count != NULL)
    {
        app->overrun_count = io->overrun_count(io->ctx);
    }

    if (io->error_count != NULL)
    {
        app->error_count = io->error_count(io->ctx);
    }

    if (io->capture_stats != NULL)
    {
        voice_app_capture_stats_t stats;

        memset(&stats, 0, sizeof(stats));
        io->capture_stats(io->ctx, &stats);

        app->dropped_samples = stats.overrun_count;
        app->last_error = stats.last_error;
        app->rms = stats.rms;
        app->peak = stats.peak;
        app->dc_offset = stats.dc_offset;

        /* Only a fallback: a ring counter is fresher than the stats snapshot. */
        if (io->error_count == NULL)
        {
            app->error_count = stats.error_count;
        }
    }
}

/* ------------------------------------------------------------------------- */
/* State handlers. */

static void voice_app_step_init(voice_app_t *app)
{
    if (app->started == 0U)
    {
        app->state = VOICE_STATE_DISABLED;
        return;
    }

    if ((app->io == NULL) || (app->io->capture_start == NULL))
    {
        voice_app_enter_failure(app, VOICE_STATE_AUDIO_ERROR);
        return;
    }

    if (app->io->capture_start(app->io->ctx) != 0)
    {
        voice_app_enter_failure(app, VOICE_STATE_AUDIO_ERROR);
        return;
    }

    /*
     * Baseline the producer counters against whatever the freshly opened
     * capture reports, so a ring that starts life with a non-zero overrun
     * counter (or one that was reset by the open itself) does not read as a
     * mid-flight overrun on the first capture poll.
     */
    voice_app_refresh_health(app);
    app->last_overrun = app->overrun_count;
    app->accept_baseline = app->accepted_samples;
    app->discarding = 0U;
    app->state = VOICE_STATE_CAPTURING;
}

static void voice_app_step_capture(voice_app_t *app)
{
    const voice_app_io_t *io = app->io;
    uint32_t available;
    uint32_t overrun_before;
    uint32_t overrun_after;

    if ((io == NULL) || (io->take_window == NULL))
    {
        voice_app_enter_failure(app, VOICE_STATE_AUDIO_ERROR);
        return;
    }

    voice_app_refresh_health(app);
    overrun_before = app->overrun_count;

    /*
     * Consumes the window when it succeeds. That is what keeps the ring from
     * staying full: the producer's fail-closed overflow path refuses blocks
     * while there is no room, so a consumer that never released anything would
     * stall accepted_samples permanently and the quarantine below could never
     * be satisfied. The cycle this poll starts owns the window it just took.
     */
    available = io->take_window(io->ctx, app->window_samples,
                               (uint32_t)VOICE_WINDOW_SAMPLES);
    app->samples_captured = available;

    /*
     * Re-read the producer counters after the copy. An overrun that lands
     * *during* the copy is exactly the case the caller cannot see from the
     * return value alone: the take still reports a full window, but the samples
     * on either side of the gap came from different moments. Checking only
     * before the copy would publish that window as clean.
     */
    if (io->overrun_count != NULL)
    {
        app->overrun_count = io->overrun_count(io->ctx);
    }

    if (io->accepted_samples != NULL)
    {
        app->accepted_samples = io->accepted_samples(io->ctx);
    }

    overrun_after = app->overrun_count;

    /*
     * R2. Any movement of the overrun counter -- across the copy, or since the
     * last time this function looked -- means the newest window may be two
     * non-adjacent stretches of audio spliced together. Abandon the cycle and
     * do not infer.
     */
    if ((overrun_after != overrun_before) ||
        (overrun_after != app->last_overrun))
    {
        app->last_overrun = overrun_after;

        if (app->discarding == 0U)
        {
            app->discarding = 1U;
            app->cycles_discarded += 1U;
        }

        /*
         * Re-arm on every observation, not just the first. A second gap while
         * we are already waiting means the window we were waiting for is
         * contaminated too, so the full-window quarantine below has to start
         * again from here.
         */
        app->accept_baseline = app->accepted_samples;
        return;
    }

    if (app->discarding != 0U)
    {
        /*
         * Quarantine. Ring pushes are fail-closed: a refused block is not
         * stored at all, so a window that overlaps the gap mixes pre-gap and
         * post-gap samples. Requiring VOICE_WINDOW_SAMPLES of *newly accepted*
         * samples puts the whole window strictly after the gap.
         *
         * accepted_samples is sampled no earlier than the moment the overrun
         * was observed, and the gap happened at or before that moment, so
         * (accepted - baseline) >= WINDOW guarantees at least WINDOW accepted
         * samples lie after the gap -- which is precisely the window peek will
         * hand back. The test can therefore be an exact bound rather than a
         * guess, and it errs toward waiting, never toward inferring early.
         */
        if ((app->accepted_samples - app->accept_baseline) <
            (uint32_t)VOICE_WINDOW_SAMPLES)
        {
            return;
        }
        app->discarding = 0U;
    }

    /*
     * R1. take_window() is all-or-nothing: it either consumed a whole window or
     * consumed nothing and left the cursor where it was. So a short return is
     * not a truncated recent window -- it is a buffer that has not filled yet.
     * Inferring on it would classify a fraction of a second of audio padded up
     * to a window. Stay in CAPTURING and try again.
     */
    if (available < (uint32_t)VOICE_WINDOW_SAMPLES)
    {
        return;
    }

    app->state = VOICE_STATE_INFERENCING;
}

static void voice_app_step_inference(voice_app_t *app)
{
    const voice_app_io_t *io = app->io;
    voice_app_decision_t decision;

    decision.class_index = -1;
    decision.confidence = 0.0f;
    decision.score = 0;
    decision.elapsed_ms = 0U;

    if ((io == NULL) || (io->infer == NULL))
    {
        voice_app_enter_failure(app, VOICE_STATE_MODEL_ERROR);
        return;
    }

    if (io->infer(io->ctx, app->window_samples, &decision) != 0)
    {
        voice_app_enter_failure(app, VOICE_STATE_MODEL_ERROR);
        return;
    }

    /*
     * A decision has to look like a decision. The confidence test is written
     * as a positive assertion so a NaN fails it rather than slipping through a
     * pair of `<` comparisons.
     */
    if ((decision.class_index < 0) ||
        !((decision.confidence >= 0.0f) && (decision.confidence <= 1.0f)))
    {
        voice_app_enter_failure(app, VOICE_STATE_MODEL_ERROR);
        return;
    }

    /* The only place a decision is ever published. */
    app->last_class = decision.class_index;
    app->last_confidence = decision.confidence;
    app->last_score = decision.score;
    app->last_inference_ms = decision.elapsed_ms;
    app->result_generation += 1U;
    app->result_valid = 1U;
    app->cycles_completed += 1U;
    app->state = VOICE_STATE_RESULT;
}

/* ------------------------------------------------------------------------- */
/* Public API. */

void voice_app_init(voice_app_t *app, const voice_app_cfg_t *cfg)
{
    if (app == NULL)
    {
        return;
    }

    memset(app, 0, sizeof(*app));
    app->state = VOICE_STATE_DISABLED;
    app->last_class = -1;

    if ((cfg == NULL) || (cfg->io == NULL) || (cfg->window_samples == NULL))
    {
        /* Misconfigured build: fail closed rather than half-alive. */
        return;
    }

    app->io = cfg->io;
    app->window_samples = cfg->window_samples;
    app->model_fingerprint = cfg->model_fingerprint;
    app->enabled = 1U;
}

int voice_app_start(voice_app_t *app)
{
    if ((app == NULL) || (app->enabled == 0U))
    {
        return -1;
    }

    if (app->started != 0U)
    {
        voice_app_stop(app);
    }

    app->samples_captured = 0U;
    app->accepted_samples = 0U;
    app->overrun_count = 0U;
    app->error_count = 0U;
    app->last_error = 0U;
    app->dropped_samples = 0U;
    app->discarding = 0U;
    app->accept_baseline = 0U;
    app->last_overrun = 0U;
    app->rms = 0.0f;
    app->peak = 0;
    app->dc_offset = 0.0f;
    app->last_inference_ms = 0U;
    app->last_class = -1;
    app->last_confidence = 0.0f;
    app->last_score = 0;
    app->cycles_completed = 0U;
    app->cycles_discarded = 0U;
    app->cycles_failed = 0U;

    /*
     * result_generation is deliberately NOT reset. It is the reader's only
     * way to tell one decision from the next, so it has to be monotonic for
     * the whole life of the app -- reusing generation 1 after a restart would
     * make a stale read from before the restart indistinguishable from a
     * fresh one.
     */
    voice_app_invalidate_result(app);

    app->started = 1U;
    app->state = VOICE_STATE_INIT;
    return 0;
}

void voice_app_stop(voice_app_t *app)
{
    if (app == NULL)
    {
        return;
    }

    if ((app->started != 0U) && (app->io != NULL) &&
        (app->io->capture_stop != NULL))
    {
        app->io->capture_stop(app->io->ctx);
    }

    app->started = 0U;
    app->discarding = 0U;
    app->samples_captured = 0U;
    voice_app_invalidate_result(app);
    app->state = VOICE_STATE_DISABLED;
}

void voice_app_disable(voice_app_t *app)
{
    if (app == NULL)
    {
        return;
    }

    voice_app_stop(app);
    app->enabled = 0U;
    app->state = VOICE_STATE_DISABLED;
}

void voice_app_poll(voice_app_t *app)
{
    if (app == NULL)
    {
        return;
    }

    if (app->enabled == 0U)
    {
        return;
    }

    switch (app->state)
    {
        case VOICE_STATE_INIT:
            voice_app_step_init(app);
            break;

        case VOICE_STATE_CAPTURING:
            voice_app_step_capture(app);
            break;

        case VOICE_STATE_INFERENCING:
            voice_app_step_inference(app);
            break;

        case VOICE_STATE_RESULT:
            /* The result has been visible for a full poll; go round again. */
            app->state = VOICE_STATE_CAPTURING;
            break;

        case VOICE_STATE_DISABLED:
        case VOICE_STATE_AUDIO_ERROR:
        case VOICE_STATE_MODEL_ERROR:
        default:
            /*
             * Latched. Audio and model errors are not retried in a loop: a
             * dead microphone would otherwise be re-opened forever inside the
             * voice thread. voice_app_start() is the recovery path, and every
             * other module keeps running meanwhile.
             */
            break;
    }
}

void voice_app_status(const voice_app_t *app, voice_app_status_t *out)
{
    if (out == NULL)
    {
        return;
    }

    memset(out, 0, sizeof(*out));
    out->samples_expected = (uint32_t)VOICE_WINDOW_SAMPLES;
    out->last_class = -1;

    if (app == NULL)
    {
        out->state = VOICE_STATE_DISABLED;
        return;
    }

    out->state = app->state;
    out->samples_captured = app->samples_captured;
    out->accepted_samples = app->accepted_samples;
    out->pdm_error_count = app->error_count;
    out->pdm_last_error = app->last_error;
    out->overrun_count = app->overrun_count;
    out->dropped_samples = app->dropped_samples;
    out->rms = app->rms;
    out->peak = app->peak;
    out->dc_offset = app->dc_offset;
    out->last_inference_ms = app->last_inference_ms;
    out->last_class = app->last_class;
    out->last_confidence = app->last_confidence;
    out->last_score = app->last_score;
    out->result_generation = app->result_generation;
    out->result_valid = app->result_valid;
    out->cycles_completed = app->cycles_completed;
    out->cycles_discarded = app->cycles_discarded;
    out->cycles_failed = app->cycles_failed;
    out->model_fingerprint = app->model_fingerprint;

    /*
     * Both flags are reported as they are stored, and nothing in this module
     * ever stores anything but zero. They exist to be flipped by a human once
     * -- and only once -- real evidence exists: field_accuracy_validated after
     * labelled audio has been scored on the target, hardware_inference_
     * validated after an inference has actually run on the RA8 silicon. No
     * such evidence exists today, so both stay 0.
     */
    out->field_accuracy_validated = app->field_accuracy_validated;
    out->hardware_inference_validated = app->hardware_inference_validated;
}

voice_state_t voice_app_state(const voice_app_t *app)
{
    if (app == NULL)
    {
        return VOICE_STATE_DISABLED;
    }
    return app->state;
}

const char *voice_app_state_name(voice_state_t state)
{
    switch (state)
    {
        case VOICE_STATE_DISABLED:
            return "disabled";
        case VOICE_STATE_INIT:
            return "init";
        case VOICE_STATE_CAPTURING:
            return "capturing";
        case VOICE_STATE_INFERENCING:
            return "inferencing";
        case VOICE_STATE_RESULT:
            return "result";
        case VOICE_STATE_AUDIO_ERROR:
            return "audio_error";
        case VOICE_STATE_MODEL_ERROR:
            return "model_error";
        default:
            return "unknown";
    }
}
