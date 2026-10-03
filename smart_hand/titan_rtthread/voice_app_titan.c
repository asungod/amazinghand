/*
 * RT-Thread / FSP glue for the passive-integration voice state machine.
 *
 * See voice_app_titan.h for the stage-1 boundary and the compile-time switch.
 * This file supplies the real voice_app_io_t, the static storage the pipeline
 * needs, and the one thread that drives voice_app_poll().
 *
 * WHAT THIS FILE DELIBERATELY DOES NOT DO
 *
 *   - No servo call of any kind, direct or indirect. No include of
 *     servo_bus_readonly_rt.h, smart_hand_uart.h, eight_servo_safety_gate.h or
 *     anything else on the motion path.
 *   - No UART write, and no change to any frame, CRC, ACK, timeout or gate.
 *   - No extension of the MaixCAM2 protocol.
 *   - No "keyword starts a training session" path.
 *
 * The only thing it produces is a generation-numbered decision in a read-only
 * status block that something else may choose to read. In this stage nothing
 * does.
 */

#include "voice_app_titan.h"

/*
 * Outside the switch on purpose. The compiled-out branch below uses NULL, and
 * the only other provider (string.h) sits inside the enabled branch -- so
 * VOICE_APP_ENABLE=0 had never actually been built for the target. It failed
 * with "'NULL' undeclared" the first time the ARM build ran with the voice
 * thread disabled. The host test for the compiled-out build did not catch it
 * because that test's own includes happen to bring NULL in.
 */
#include <stddef.h>

#if VOICE_APP_ENABLE

#include <string.h>

#include <rtthread.h>
#include <rthw.h>

#include "voice_audio_titan.h"
#include "voice_features.h"
#include "voice_kws.h"
#include "voice_model_data.h"

/* ------------------------------------------------------------------------- */
/* Static storage.
 *
 * All of it is file scope and all of it lands in .bss. voice_kws_t alone is
 * 62,727 B, and the window is another 32 KB; putting any of it on the thread
 * stack would not fit in the 8 KB the thread is given (and would not fit in a
 * Cortex-M85 stack at all). The thread's own stack is a static array for the
 * same reason -- this one thread must not come out of the RT-Thread heap.
 */

static voice_frontend_t g_frontend;   /* 48,868 B */
static voice_kws_t g_kws;             /* 62,728 B */
static float g_logmel[VOICE_FEATURE_COUNT];        /* 15,680 B */
static int16_t g_window[VOICE_WINDOW_SAMPLES];     /* 32,000 B */
static voice_app_t g_app;

static struct rt_thread g_thread;
static rt_ubase_t g_thread_stack[VOICE_APP_THREAD_STACK / sizeof(rt_ubase_t)];

static uint8_t g_ready;

/* ------------------------------------------------------------------------- */
/* The real I/O table. */

static int voice_io_capture_start(void *ctx)
{
    (void)ctx;
    /* 0 on success, the negated fsp_err_t otherwise; voice_app.c only needs
     * "zero or not". */
    return voice_audio_titan_start();
}

static void voice_io_capture_stop(void *ctx)
{
    (void)ctx;
    voice_audio_titan_stop();
}

static uint32_t voice_io_take_window(void *ctx, int16_t *out, uint32_t count)
{
    voice_ring_t *ring = voice_audio_titan_ring();

    (void)ctx;

    if (ring == NULL)
    {
        return 0U;
    }

    /*
     * Consuming, and that is the whole point.
     *
     * The original defect lived exactly here: this mapped to the non-consuming
     * voice_ring_peek_latest() -- whose old comment even explained that the
     * same window is read by several polls -- so no code path ever advanced
     * read_index. VOICE_RING_CAPACITY is 32,768 and the PDM callback offers
     * 800 samples at a time, so 32,000 were accepted and every later block was
     * then refused by the ring's fail-closed overflow path. total_samples
     * stopped advancing, and because R2's quarantine waits for a whole window
     * of newly ACCEPTED samples, the machine could never leave CAPTURING again.
     *
     * The old reasoning for peeking was that a consuming read would tear the
     * window across two laps of the poll loop. That is true of a streaming
     * drain, and it is why voice_ring_take_window() is not one: it either
     * returns a whole window and consumes exactly it, or returns nothing and
     * consumes nothing.
     */
    return voice_ring_take_window(ring, out, count);
}

static uint32_t voice_io_accepted_samples(void *ctx)
{
    const voice_ring_t *ring = voice_audio_titan_ring();

    (void)ctx;
    return (ring == NULL) ? 0U : ring->total_samples;
}

static uint32_t voice_io_overrun_count(void *ctx)
{
    const voice_ring_t *ring = voice_audio_titan_ring();

    (void)ctx;
    return (ring == NULL) ? 0U : ring->overrun_count;
}

static uint32_t voice_io_error_count(void *ctx)
{
    const voice_ring_t *ring = voice_audio_titan_ring();

    (void)ctx;
    return (ring == NULL) ? 0U : ring->error_count;
}

static void voice_io_capture_stats(void *ctx, voice_app_capture_stats_t *out)
{
    voice_capture_stats_t stats;

    (void)ctx;

    if (out == NULL)
    {
        return;
    }

    voice_audio_titan_stats(&stats);

    out->samples_captured = stats.samples_captured;
    out->error_count = stats.error_count;
    out->overrun_count = stats.overrun_count;
    out->last_error = stats.last_error;
    out->peak = stats.peak;
    out->rms = stats.rms;
    out->dc_offset = stats.dc_offset;
    out->running = stats.running;
}

/*
 * The whole inference pipeline, behind one call: 1 s of int16 PCM in, one
 * decision out. This is the only place the front end and the classifier are
 * invoked, and it runs on the voice thread -- never in an interrupt. The PDM
 * callback only moves samples (voice_audio_titan.c), so nothing here can
 * lengthen the interrupt's critical path.
 */
static int voice_io_infer(void *ctx,
                          const int16_t *samples,
                          voice_app_decision_t *out)
{
    int klass = -1;
    float confidence = 0.0f;
    rt_tick_t start;

    (void)ctx;

    if ((samples == NULL) || (out == NULL))
    {
        return -1;
    }

    start = rt_tick_get_millisecond();

    voice_frontend_window(&g_frontend, samples, g_logmel);

    if (voice_kws_predict(&g_kws, g_logmel, &klass, &confidence) != 0)
    {
        return -1;
    }

    if ((klass < 0) || (klass >= (int)VOICE_MODEL_CLASS_COUNT))
    {
        return -1;
    }

    out->class_index = (int32_t)klass;
    out->confidence = confidence;
    out->score = (int32_t)g_kws.logits[klass];
    /* rt_tick_get_millisecond() is exact here: RT_TICK_PER_SECOND is 1000. */
    out->elapsed_ms = (uint32_t)(rt_tick_get_millisecond() - start);
    return 0;
}

static const voice_app_io_t g_io = {
    NULL,
    voice_io_capture_start,
    voice_io_capture_stop,
    voice_io_take_window,
    voice_io_accepted_samples,
    voice_io_overrun_count,
    voice_io_error_count,
    voice_io_capture_stats,
    voice_io_infer,
};

/* ------------------------------------------------------------------------- */
/* Model identity.
 *
 * The status block has to say which voice_model_data is linked in, and a bare
 * "the model" is not an answer once a re-export is one script away. FNV-1a
 * over every weight blob, mixed with the model's shape, gives a value that
 * changes when the network changes and costs one pass over ~14 KB at start-up.
 */

static uint32_t voice_hash_bytes(uint32_t hash, const int8_t *data, uint32_t count)
{
    uint32_t i;

    for (i = 0U; i < count; ++i)
    {
        hash ^= (uint32_t)(uint8_t)data[i];
        hash *= 16777619UL;
    }
    return hash;
}

static uint32_t voice_hash_u32(uint32_t hash, uint32_t value)
{
    uint32_t i;

    for (i = 0U; i < 4U; ++i)
    {
        hash ^= (value >> (8U * i)) & 0xffU;
        hash *= 16777619UL;
    }
    return hash;
}

static uint32_t voice_model_fingerprint(void)
{
    /*
     * The layer-3 and layer-6 pooling layers carry no weights, so the six
     * arrays below are every learnable parameter in the exported model.
     */
    static const int8_t *const weights[] = {
        g_voice_model_t0_w, g_voice_model_t1_w, g_voice_model_t2_w,
        g_voice_model_t4_w, g_voice_model_t5_w, g_voice_model_t7_w,
    };
    static const uint32_t lengths[] = {
        (uint32_t)VOICE_MODEL_L0_WEIGHT_COUNT,
        (uint32_t)VOICE_MODEL_L1_WEIGHT_COUNT,
        (uint32_t)VOICE_MODEL_L2_WEIGHT_COUNT,
        (uint32_t)VOICE_MODEL_L4_WEIGHT_COUNT,
        (uint32_t)VOICE_MODEL_L5_WEIGHT_COUNT,
        (uint32_t)VOICE_MODEL_L7_WEIGHT_COUNT,
    };

    uint32_t hash = 2166136261UL;
    uint32_t i;

    for (i = 0U; i < (uint32_t)(sizeof(weights) / sizeof(weights[0])); ++i)
    {
        hash = voice_hash_bytes(hash, weights[i], lengths[i]);
    }

    /* Same weights in a differently shaped model are a different model. */
    hash = voice_hash_u32(hash, (uint32_t)VOICE_MODEL_LAYER_COUNT);
    hash = voice_hash_u32(hash, (uint32_t)VOICE_MODEL_CLASS_COUNT);
    hash = voice_hash_u32(hash, (uint32_t)VOICE_MODEL_INPUT_COUNT);
    hash = voice_hash_u32(hash, (uint32_t)VOICE_MODEL_L0_IN_ZP);
    return hash;
}

/* ------------------------------------------------------------------------- */
/* Thread. */

static void voice_app_thread_entry(void *parameter)
{
    (void)parameter;

    for (;;)
    {
        /*
         * One state transition per tick. poll() never sleeps and never waits
         * on a device; a failure parks the machine in an error state, where
         * poll() becomes a no-op and this loop stays a cheap 10 ms tick.
         */
        voice_app_poll(&g_app);
        rt_thread_mdelay((rt_int32_t)VOICE_APP_THREAD_TICK);
    }
}

/* ------------------------------------------------------------------------- */
/* Public API. */

int voice_app_titan_init(void)
{
    voice_app_cfg_t cfg;
    rt_err_t result;

    if (g_ready != 0U)
    {
        return 0;
    }

    memset(&cfg, 0, sizeof(cfg));
    cfg.io = &g_io;
    cfg.window_samples = g_window;
    cfg.model_fingerprint = voice_model_fingerprint();

    voice_app_init(&g_app, &cfg);
    voice_frontend_init(&g_frontend);
    voice_kws_init(&g_kws);

    result = rt_thread_init(&g_thread,
                            VOICE_APP_THREAD_NAME,
                            voice_app_thread_entry,
                            RT_NULL,
                            g_thread_stack,
                            (rt_uint32_t)sizeof(g_thread_stack),
                            (rt_uint8_t)VOICE_APP_THREAD_PRIORITY,
                            (rt_uint32_t)VOICE_APP_THREAD_TICK);
    if (result != RT_EOK)
    {
        voice_app_disable(&g_app);
        return (int)result;
    }

    /*
     * Start the state machine before the thread that drives it, so the thread
     * cannot observe a half-started app. The device itself is opened on the
     * thread, inside poll(), not here.
     */
    if (voice_app_start(&g_app) != 0)
    {
        (void)rt_thread_detach(&g_thread);
        return -(int)RT_ERROR;
    }

    result = rt_thread_startup(&g_thread);
    if (result != RT_EOK)
    {
        voice_app_stop(&g_app);
        (void)rt_thread_detach(&g_thread);
        return (int)result;
    }

    g_ready = 1U;

    rt_kprintf("voice: passive integration up (thread %s, prio %u, stack %u B, "
               "model %08x); results are published, never actuated\n",
               VOICE_APP_THREAD_NAME,
               (unsigned)VOICE_APP_THREAD_PRIORITY,
               (unsigned)VOICE_APP_THREAD_STACK,
               (unsigned)voice_model_fingerprint());
    return 0;
}

void voice_app_titan_deinit(void)
{
    if (g_ready == 0U)
    {
        return;
    }

    g_ready = 0U;

    /* Close the device before the thread that owns it stops being scheduled. */
    voice_app_stop(&g_app);
    (void)rt_thread_detach(&g_thread);
}

void voice_app_titan_status(voice_app_status_t *out)
{
    rt_base_t level;

    if (out == NULL)
    {
        return;
    }

    /*
     * The voice thread publishes into g_app from its own context, so a plain
     * copy from another thread can catch a half-updated decision: a new
     * result_generation paired with the previous class. Masking interrupts
     * stops that on a single-core Cortex-M, where the scheduler is entered
     * from PendSV and cannot run while they are off. The section is one struct
     * copy and touches no device, no lock and no heap.
     */
    level = rt_hw_interrupt_disable();
    voice_app_status(&g_app, out);
    rt_hw_interrupt_enable(level);
}

voice_state_t voice_app_titan_state(void)
{
    rt_base_t level;
    voice_state_t state;

    /* Read under the same mask as the full snapshot: app->state is written by
     * the voice thread, and a torn read of an enum is still a wrong answer. */
    level = rt_hw_interrupt_disable();
    state = voice_app_state(&g_app);
    rt_hw_interrupt_enable(level);
    return state;
}

uint32_t voice_app_titan_model_fingerprint(void)
{
    return g_app.model_fingerprint;
}

/*
 * Bring the pipeline up from the application init phase, the same way
 * servo_bus_readonly_init() and smart_hand_comm_init() are started.
 *
 * This line must sit INSIDE the VOICE_APP_ENABLE branch. Placed after the
 * #else it would be compiled only into the disabled build -- where the stub
 * reports DISABLED and there is nothing to start -- leaving the enabled build
 * with no call site, so --gc-sections discards voice_app_titan.o entirely and
 * the image is byte-identical to a build with no voice support at all.
 *
 * rt_components_init() ignores the return value, and init only creates the
 * thread and binds devices, so a capture failure inside the thread cannot
 * hold up the rest of the boot.
 */
INIT_APP_EXPORT(voice_app_titan_init);

#else /* !VOICE_APP_ENABLE */

/*
 * Compiled out. No statics, no thread, no device references -- the translation
 * unit is a handful of accessors, and the firmware is what it was before this
 * file existed.
 */

int voice_app_titan_init(void)
{
    return 0;
}

void voice_app_titan_deinit(void)
{
}

void voice_app_titan_status(voice_app_status_t *out)
{
    /* A NULL app is the honest answer: nothing is bound and nothing runs. */
    voice_app_status(NULL, out);
}

voice_state_t voice_app_titan_state(void)
{
    return VOICE_STATE_DISABLED;
}

uint32_t voice_app_titan_model_fingerprint(void)
{
    return 0U;
}

#endif /* VOICE_APP_ENABLE */
