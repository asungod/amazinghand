/*
 * Host tests for voice_app_titan.c -- the RT-Thread glue.
 *
 * test_voice_app_c.c covers the decision policy against a scripted I/O table.
 * This file covers the things that only exist once the module is wired to a
 * kernel and a real pipeline, and which a policy test cannot see:
 *
 *   1. What was handed to the kernel. The voice thread's priority, stack size
 *      and name are arguments to rt_thread_init(), not fields of any state the
 *      module keeps, so nothing but a recording stub can check them. Priority
 *      is the load-bearing one: it has to be BELOW sh_uart's 18 or the command
 *      link starves when the classifier is busy.
 *
 *   2. That the pipeline composes. Here the real voice_frontend_window() and
 *      the real voice_kws_predict() run over a real voice_ring_t, driven by the
 *      module's own thread entry, and the assertion is on the status block that
 *      comes out the far end. The engine itself is checked against TFLite by
 *      test_voice_kws.py; what is new here is that it is reachable through the
 *      glue at all.
 *
 *   3. That "compiled out" really is inert. The same source is built a second
 *      time with VOICE_APP_ENABLE=0 and asserts that no thread, no device and
 *      no ring access happen at all.
 *
 *   4. That capture keeps running. Cases 7-10 drive the ring the way the PDM
 *      callback does -- one callback-sized block at a time, with a poll between
 *      blocks -- and assert on the ring itself as well as on the status block:
 *      how many samples were accepted, whether the overrun counter moved, and
 *      the ORDER of the samples in a window that crosses the ring's wrap.
 *      Case 7 is the regression test for the defect this file previously could
 *      not see: the glue asked for a window through a non-consuming read, so
 *      nothing ever advanced read_index, the 32,768-sample ring filled after
 *      32,000 accepted samples, and every later block was refused. Pushing one
 *      window and stopping -- all the earlier cases do -- never reaches that
 *      state. tests/test_voice_app.py restores the old call and requires case 7
 *      to go red.
 *
 * The file is built twice by tests/test_voice_app.py, once per switch setting,
 * which is why main() and the case list are behind the same #if.
 *
 * NOT covered here, and not pretended otherwise: the FSP PDM binding. The
 * voice_audio_titan_* functions below are stubs, so a fault in
 * voice_audio_titan.c will not show up in this file. That binding has its own
 * driver model in tests/stubs/ + test_voice_audio_titan_c.c and is out of scope
 * for the glue.
 */

#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <rthw.h>
#include <rtthread.h>

#include "voice_app_titan.h"
#include "voice_audio_titan.h"

#if VOICE_APP_ENABLE
#include "voice_kws.h"
#include "voice_model_data.h"
#endif

/* ------------------------------------------------------------------------- */
/* Check plumbing. */

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
/* Kernel stub, shared by both builds so the disabled build can still prove
 * that nothing called it. */

voice_thread_recorder_t g_voice_thread_recorder;

static uint32_t g_irq_depth;
static uint32_t g_irq_max_depth;
static uint32_t g_irq_unbalanced;

rt_base_t rt_hw_interrupt_disable(void)
{
    g_irq_depth += 1U;
    if (g_irq_depth > g_irq_max_depth)
    {
        g_irq_max_depth = g_irq_depth;
    }
    return (rt_base_t)g_irq_depth;
}

void rt_hw_interrupt_enable(rt_base_t level)
{
    (void)level;
    if (g_irq_depth == 0U)
    {
        g_irq_unbalanced += 1U;
        return;
    }
    g_irq_depth -= 1U;
}

rt_err_t rt_thread_init(struct rt_thread *thread,
                        const char *name,
                        void (*entry)(void *parameter),
                        void *parameter,
                        void *stack_start,
                        rt_uint32_t stack_size,
                        rt_uint8_t priority,
                        rt_uint32_t tick)
{
    g_voice_thread_recorder.init_calls += 1U;
    g_voice_thread_recorder.entry = entry;
    g_voice_thread_recorder.parameter = parameter;
    g_voice_thread_recorder.stack_start = stack_start;
    g_voice_thread_recorder.stack_size = stack_size;
    g_voice_thread_recorder.priority = priority;
    g_voice_thread_recorder.tick = tick;
    memset(g_voice_thread_recorder.name, 0,
           sizeof(g_voice_thread_recorder.name));
    if (name != NULL)
    {
        strncpy(g_voice_thread_recorder.name, name,
                sizeof(g_voice_thread_recorder.name) - 1U);
    }

    if (thread == NULL)
    {
        return -RT_ERROR;
    }

    thread->entry = entry;
    thread->parameter = parameter;
    thread->stack_start = stack_start;
    thread->stack_size = stack_size;
    thread->priority = priority;
    thread->tick = tick;
    return RT_EOK;
}

rt_err_t rt_thread_detach(rt_thread_t thread)
{
    (void)thread;
    g_voice_thread_recorder.detach_calls += 1U;
    return RT_EOK;
}

rt_err_t rt_thread_startup(rt_thread_t thread)
{
    (void)thread;
    g_voice_thread_recorder.startup_calls += 1U;
    return RT_EOK;
}

/* The real escape hatch; see drive_thread() below. */
static jmp_buf g_thread_escape;
static uint32_t g_sleep_limit = 1U;
static uint32_t g_sleep_calls;

#if VOICE_APP_ENABLE
static uint32_t g_entry_returned;
#endif

rt_err_t rt_thread_mdelay(rt_int32_t ms)
{
    g_voice_thread_recorder.sleep_calls += 1U;
    g_voice_thread_recorder.last_sleep_ms = (uint32_t)ms;

    g_sleep_calls += 1U;
    if (g_sleep_calls >= g_sleep_limit)
    {
        longjmp(g_thread_escape, 1);
    }
    return RT_EOK;
}

rt_tick_t rt_tick_get(void)
{
    return (rt_tick_t)g_voice_thread_recorder.sleep_calls;
}

rt_tick_t rt_tick_get_millisecond(void)
{
    /* RT_TICK_PER_SECOND is 1000 in this stub, so ticks are milliseconds. */
    return (rt_tick_t)g_voice_thread_recorder.sleep_calls;
}

int rt_kprintf(const char *fmt, ...)
{
    /* The module logs one bring-up line; keep it out of the parsed output. */
    (void)fmt;
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Capture stub.
 *
 * voice_audio_titan.c itself is NOT linked here; it needs the FSP driver. The
 * ring underneath is the real voice_ring_t from voice_audio.c, so
 * peek/push/overrun semantics are genuine even though the PDM binding is not.
 */

static voice_ring_t g_ring;
static uint32_t g_capture_start_calls;
static uint32_t g_capture_stop_calls;
static int g_capture_start_result;
static voice_capture_stats_t g_stats_stub;

int voice_audio_titan_start(void)
{
    g_capture_start_calls += 1U;
    if (g_capture_start_result != 0)
    {
        return g_capture_start_result;
    }
    voice_ring_reset_for_capture(&g_ring);
    g_stats_stub.running = 1U;
    return 0;
}

void voice_audio_titan_stop(void)
{
    g_capture_stop_calls += 1U;
    g_stats_stub.running = 0U;
}

voice_ring_t *voice_audio_titan_ring(void)
{
    return &g_ring;
}

void voice_audio_titan_stats(voice_capture_stats_t *out)
{
    if (out == NULL)
    {
        return;
    }
    *out = g_stats_stub;
}

#if VOICE_APP_ENABLE

/* ------------------------------------------------------------------------- */
/* Driving the module's own thread entry.
 *
 * The entry is for(;;){ poll(); mdelay(); }, so the host cannot simply call it.
 * rt_thread_mdelay() longjmps out after a chosen number of iterations, which
 * runs the module's real loop body and then unwinds back here.
 */

static void drive_thread(uint32_t iterations)
{
    g_sleep_limit = (iterations == 0U) ? 1U : iterations;
    g_sleep_calls = 0U;

    if (setjmp(g_thread_escape) == 0)
    {
        g_voice_thread_recorder.entry(g_voice_thread_recorder.parameter);
        g_entry_returned = 1U;
    }
}

/* A 200 Hz triangle at 16 kHz. Any non-degenerate signal will do; this one has
 * energy spread over several mel bands, so the front end is not fed silence. */
static void fill_window(void)
{
    static int16_t block[VOICE_WINDOW_SAMPLES];
    uint32_t i;

    for (i = 0U; i < (uint32_t)VOICE_WINDOW_SAMPLES; ++i)
    {
        uint32_t phase = i % 80U;
        int32_t value = (phase < 40U) ? ((int32_t)phase * 200)
                                      : ((int32_t)(80U - phase) * 200);
        block[i] = (int16_t)(value - 4000);
    }

    CHECK(voice_ring_push(&g_ring, block, (uint32_t)VOICE_WINDOW_SAMPLES) == 0U);
}

static void fixture_reset(void)
{
    memset(&g_voice_thread_recorder, 0, sizeof(g_voice_thread_recorder));
    voice_ring_init(&g_ring);
    memset(&g_stats_stub, 0, sizeof(g_stats_stub));
    g_capture_start_calls = 0U;
    g_capture_stop_calls = 0U;
    g_capture_start_result = 0;
    g_irq_depth = 0U;
    g_irq_max_depth = 0U;
    g_irq_unbalanced = 0U;
    g_entry_returned = 0U;

    /* detach state does not survive a fresh init; undo the previous fixture. */
    voice_app_titan_deinit();
    memset(&g_voice_thread_recorder, 0, sizeof(g_voice_thread_recorder));
    g_irq_depth = 0U;
    g_irq_unbalanced = 0U;
}

/* init + run the entry until capture is open. */
static void fixture_up(void)
{
    CHECK(voice_app_titan_init() == 0);
    drive_thread(1U);
    CHECK(g_capture_start_calls == 1U);
}

/* ------------------------------------------------------------------------- */
/* 1. What the module handed the kernel. */

static void case_thread_parameters(void)
{
    fixture_reset();
    CHECK(voice_app_titan_init() == 0);

    CHECK(g_voice_thread_recorder.init_calls == 1U);
    CHECK(g_voice_thread_recorder.startup_calls == 1U);

    /*
     * The priority requirement, asserted against the constant rather than a
     * literal, AND against sh_uart's 18, because the relationship is the
     * actual requirement: RT-Thread runs the smallest priority number first,
     * so the voice thread must be strictly larger than the command thread's.
     */
    CHECK(g_voice_thread_recorder.priority == VOICE_APP_THREAD_PRIORITY);
    CHECK(g_voice_thread_recorder.priority > VOICE_APP_SH_UART_PRIORITY);
    CHECK(g_voice_thread_recorder.priority > 18U);

    CHECK(g_voice_thread_recorder.stack_size == VOICE_APP_THREAD_STACK);
    CHECK(g_voice_thread_recorder.stack_size >= 6144U);
    CHECK(g_voice_thread_recorder.stack_size == 8192U);

    CHECK(strcmp(g_voice_thread_recorder.name, VOICE_APP_THREAD_NAME) == 0);
    CHECK(strcmp(g_voice_thread_recorder.name, "v_kws") == 0);

    CHECK(g_voice_thread_recorder.tick == VOICE_APP_THREAD_TICK);
    CHECK(g_voice_thread_recorder.tick == 10U);

    /* A statically provided stack: not NULL, and aligned like rt_ubase_t. */
    CHECK(g_voice_thread_recorder.stack_start != NULL);
    CHECK(((uintptr_t)g_voice_thread_recorder.stack_start % sizeof(rt_ubase_t))
          == 0U);
    CHECK(g_voice_thread_recorder.entry != NULL);
    CHECK(g_entry_returned == 0U);

    /* A second init is a no-op, not a second thread. */
    CHECK(voice_app_titan_init() == 0);
    CHECK(g_voice_thread_recorder.init_calls == 1U);
    CHECK(g_voice_thread_recorder.startup_calls == 1U);

    voice_app_titan_deinit();
    CHECK(g_voice_thread_recorder.detach_calls == 1U);
    CHECK(voice_app_titan_state() == VOICE_STATE_DISABLED);
    CHECK(g_capture_stop_calls == 1U);
    CHECK(voice_app_titan_init() == 0); /* deinit is recoverable */
    CHECK(g_voice_thread_recorder.init_calls == 2U);
    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 2. The thread really drives the state machine. */

static void case_thread_opens_capture_and_polls(void)
{
    voice_app_status_t status;

    fixture_reset();
    fixture_up();

    /* Opening is deferred to the poll, which runs on the thread. */
    CHECK(g_voice_thread_recorder.init_calls == 1U);
    CHECK(g_capture_start_calls == 1U);
    CHECK(g_stats_stub.running == 1U);

    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_CAPTURING);
    CHECK(status.result_valid == 0U);
    CHECK(status.result_generation == 0U);
    CHECK(status.samples_expected == (uint32_t)VOICE_WINDOW_SAMPLES);
    /* The ring is empty, so the module must not have inferred. */
    CHECK(status.samples_captured < (uint32_t)VOICE_WINDOW_SAMPLES);

    /* Ten more ticks with an empty ring: still no result. */
    drive_thread(10U);
    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_CAPTURING);
    CHECK(status.result_generation == 0U);
    CHECK(voice_app_titan_state() == VOICE_STATE_CAPTURING);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 3. End to end through the real front end and the real network. */

static void case_real_window_publishes_a_result(void)
{
    voice_app_status_t status;
    uint32_t fingerprint_first;

    fixture_reset();
    fixture_up();

    fill_window();
    CHECK(g_ring.total_samples == (uint32_t)VOICE_WINDOW_SAMPLES);

    /*
     * Two ticks: one takes CAPTURING -> INFERENCING, the next runs the network
     * and lands in RESULT. (A third would already be back in CAPTURING, which
     * is why the count is exact rather than "a few".)
     */
    drive_thread(2U);

    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_RESULT);
    CHECK(status.result_valid == 1U);
    CHECK(status.result_generation == 1U);
    CHECK(status.cycles_completed == 1U);
    CHECK(status.cycles_discarded == 0U);
    CHECK(status.cycles_failed == 0U);
    CHECK(status.samples_captured == (uint32_t)VOICE_WINDOW_SAMPLES);

    /* The class is a real argmax over the exported model's logits. */
    CHECK(status.last_class >= 0);
    CHECK(status.last_class < (int32_t)VOICE_MODEL_CLASS_COUNT);
    CHECK(status.last_confidence >= 0.0f);
    CHECK(status.last_confidence <= 1.0f);

    /*
     * Timing is reported, but only as "a number was produced": the host runs
     * the model at -O0 with no relation to the RA8 clock, and quoting a host
     * number as an inference budget is exactly the kind of claim this project
     * keeps having to retract.
     */
    CHECK(status.last_inference_ms < 60000U);

    /* Evidence flags stay zero. */
    CHECK(status.field_accuracy_validated == 0U);
    CHECK(status.hardware_inference_validated == 0U);

    /* The model identity is real: non-zero and stable. */
    fingerprint_first = voice_app_titan_model_fingerprint();
    CHECK(fingerprint_first != 0U);
    CHECK(fingerprint_first == voice_app_titan_model_fingerprint());
    CHECK(status.model_fingerprint == fingerprint_first);
    /* ... and not the bare FNV-1a offset basis, i.e. it hashed something. */
    CHECK(fingerprint_first != 2166136261UL);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 4. A ring overrun stops the module publishing, through the real ring. */

static void case_overrun_blocks_publication(void)
{
    voice_app_status_t status;
    static int16_t block[VOICE_WINDOW_SAMPLES];

    fixture_reset();
    fixture_up();

    fill_window();

    /*
     * Exactly three ticks, so the machine is parked in CAPTURING when the
     * overrun below lands. One more tick would leave it in INFERENCING, and the
     * window for that cycle was already copied out of the ring -- an overrun
     * after the copy cannot contaminate it, so the module would (correctly)
     * publish, and this case would be testing nothing.
     */
    drive_thread(3U);
    voice_app_titan_status(&status);
    CHECK(status.result_generation == 1U);
    CHECK(status.state == VOICE_STATE_CAPTURING);

    /*
     * A genuine refused push: voice_ring_push() rejects a block larger than the
     * whole buffer and charges it to overrun_count. That is the same fail-closed
     * path the PDM callback hits when the consumer falls behind.
     */
    CHECK(voice_ring_push(&g_ring, block, VOICE_RING_CAPACITY + 1U) ==
          VOICE_RING_CAPACITY + 1U);
    CHECK(g_ring.overrun_count > 0U);

    drive_thread(4U);
    voice_app_titan_status(&status);
    CHECK(status.result_generation == 1U); /* nothing new was published */
    CHECK(status.cycles_discarded >= 1U);
    CHECK(status.overrun_count > 0U);

    /* Recovery needs a full window of newly accepted samples, not just time. */
    fill_window();
    drive_thread(4U);
    voice_app_titan_status(&status);
    CHECK(status.result_generation == 2U);
    CHECK(status.result_valid == 1U);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 5. The snapshot accessors leave the interrupt mask balanced. */

static void case_snapshot_is_balanced(void)
{
    voice_app_status_t status;

    fixture_reset();
    fixture_up();

    CHECK(g_irq_depth == 0U);
    voice_app_titan_status(&status);
    CHECK(g_irq_depth == 0U);
    CHECK(voice_app_titan_state() == VOICE_STATE_CAPTURING);
    CHECK(g_irq_depth == 0U);

    for (int i = 0; i < 50; ++i)
    {
        voice_app_titan_status(&status);
        (void)voice_app_titan_state();
    }
    CHECK(g_irq_depth == 0U);
    CHECK(g_irq_max_depth >= 1U); /* the snapshot really did mask */
    CHECK(g_irq_unbalanced == 0U);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 6. A capture that will not open is reported, not retried, not fatal. */

static void case_capture_start_failure_is_survivable(void)
{
    voice_app_status_t status;
    uint32_t i;

    fixture_reset();
    g_capture_start_result = -3; /* a negated fsp_err_t */

    CHECK(voice_app_titan_init() == 0);
    drive_thread(4U);

    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_AUDIO_ERROR);
    CHECK(status.cycles_failed == 1U);
    CHECK(status.result_valid == 0U);
    CHECK(g_capture_start_calls == 1U);

    /* The thread keeps ticking; it does not spin on the dead device. */
    for (i = 0U; i < 20U; ++i)
    {
        drive_thread(1U);
    }
    CHECK(g_capture_start_calls == 1U);
    CHECK(voice_app_titan_state() == VOICE_STATE_AUDIO_ERROR);

    /* Everything else in the process is untouched, and deinit still works. */
    voice_app_titan_deinit();
    CHECK(voice_app_titan_state() == VOICE_STATE_DISABLED);
}

/* ------------------------------------------------------------------------- */
/* 7. Sustained capture: the consumer must keep making room.
 *
 * This is the case that fails on the pre-fix implementation, and it exists for
 * that reason. Everything above pushes one window and stops, which is why the
 * ring never had a chance to fill and the defect survived the host suite.
 */

/*
 * A producer that behaves like the PDM callback: fixed-size blocks, fed one at
 * a time with a poll between them.
 *
 * The samples are a ramp over the ABSOLUTE stream index, so a consumer can tell
 * where in the stream a window came from. A window stitched from the wrong place
 * is then visible as wrong contents rather than merely suspicious, which is the
 * only way to test wrap ordering and gap splicing from the outside.
 */
static int16_t ramp_sample(uint32_t index)
{
    return (int16_t)((index * 37U) & 0x7ffU);
}

/* Returns how many samples the ring REFUSED, exactly like voice_ring_push. */
static uint32_t push_ramp(uint32_t first_index, uint32_t count)
{
    static int16_t block[VOICE_RING_CAPACITY];
    uint32_t i;

    CHECK(count <= (uint32_t)VOICE_RING_CAPACITY);

    for (i = 0U; i < count; ++i)
    {
        block[i] = ramp_sample(first_index + i);
    }
    return voice_ring_push(&g_ring, block, count);
}

static void case_sustained_windows_keep_the_ring_draining(void)
{
    voice_app_status_t status;
    uint32_t produced = 0U;
    uint32_t i;

    fixture_reset();
    fixture_up();

    /*
     * 120 blocks of 800 is 96,000 samples -- six windows' worth -- offered one
     * callback-sized block at a time with a single poll between blocks, which
     * is what the PDM interrupt does to this module on hardware.
     *
     * THIS FAILS ON THE PRE-FIX IMPLEMENTATION. voice_io_peek_window() used to
     * map to the non-consuming voice_ring_peek_latest(), so read_index never
     * moved: the 32,768-sample ring accepted 32,000 samples and refused every
     * block after that. On that implementation total_samples stops at 32,000 and
     * overrun_count climbs, so the assertions below are precisely the difference
     * between the defect and the fix. Reproduced mechanically by the mutation
     * suite in tests/test_voice_app.py, which restores the old call and requires
     * this case to go red.
     */
    for (i = 0U; i < 120U; ++i)
    {
        CHECK(push_ramp(produced, 800U) == 0U);
        produced += 800U;
        drive_thread(1U);
    }

    /* Every block was accepted: the consumer freed room for all of them. */
    CHECK(g_ring.total_samples == 96000U);
    CHECK(g_ring.overrun_count == 0U);
    CHECK(g_ring.write_index - g_ring.read_index <= (uint32_t)VOICE_RING_CAPACITY);

    voice_app_titan_status(&status);
    CHECK(status.overrun_count == 0U);
    CHECK(status.dropped_samples == 0U);
    /* Six windows offered, five completed by the time the loop ends. */
    CHECK(status.result_generation >= 5U);
    CHECK(status.cycles_discarded == 0U);
    CHECK(status.cycles_failed == 0U);
    CHECK(status.state != VOICE_STATE_AUDIO_ERROR);
    CHECK(status.state != VOICE_STATE_MODEL_ERROR);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 8. A window that crosses the ring's wrap boundary is still in order. */

static void case_window_spans_a_ring_wrap_in_order(void)
{
    static int16_t out[VOICE_WINDOW_SAMPLES];
    uint32_t first_mismatch;
    uint32_t i;

    fixture_reset();
    voice_ring_init(&g_ring);

    /*
     * Land the consumer cursor 1,768 samples short of the end of the ring, so
     * the window below has to cross index 0. No app is involved: this is the
     * ring contract the glue is built on, tested where it can be pinned down
     * exactly rather than through three layers of state machine.
     */
    CHECK(push_ramp(0U, 31000U) == 0U);
    CHECK(voice_ring_take_window(&g_ring, out, 31000U) == 31000U);
    CHECK(g_ring.read_index == 31000U);

    /* 20,000 more: 1,768 land before the wrap, 18,232 after it. */
    CHECK(push_ramp(31000U, 20000U) == 0U);

    CHECK(voice_ring_take_window(&g_ring, out, 16000U) == 16000U);

    /*
     * Sample for sample against the stream. A window copied from the wrong end,
     * or restarted at the wrap, would still be 16,000 samples long-and-wrong --
     * the length is not the property under test, the order is.
     */
    first_mismatch = (uint32_t)VOICE_WINDOW_SAMPLES;
    for (i = 0U; i < (uint32_t)VOICE_WINDOW_SAMPLES; ++i)
    {
        if (out[i] != ramp_sample(31000U + i))
        {
            first_mismatch = i;
            break;
        }
    }
    CHECK(first_mismatch == (uint32_t)VOICE_WINDOW_SAMPLES);
    CHECK(g_ring.read_index == 47000U);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 9. The producer cannot write into a window the consumer is reading.
 *
 * The host is cooperative, so a pre-empting producer cannot be interleaved into
 * the middle of voice_ring_take_window() here, and this case does not pretend
 * otherwise. What it checks is the invariant that makes the concurrency safe in
 * the first place: the producer only ever appends ahead of write_index and
 * refuses outright when the block does not fit, so the half-open range
 * [read_index, write_index) is immutable for as long as it is unread.
 */

static void case_producer_cannot_overwrite_an_unread_window(void)
{
    static int16_t first[VOICE_WINDOW_SAMPLES];
    static int16_t second[VOICE_WINDOW_SAMPLES];
    static int16_t filler[VOICE_RING_CAPACITY];
    static int16_t tail[VOICE_RING_CAPACITY - 32000U];
    uint32_t first_mismatch;
    uint32_t i;

    fixture_reset();
    voice_ring_init(&g_ring);

    /* A full ring, then a window taken from its oldest end. */
    CHECK(push_ramp(0U, (uint32_t)VOICE_RING_CAPACITY) == 0U);
    CHECK(g_ring.total_samples == (uint32_t)VOICE_RING_CAPACITY);
    CHECK(voice_ring_take_window(&g_ring, first, 16000U) == 16000U);
    CHECK(first[0] == ramp_sample(0U));
    CHECK(first[15999] == ramp_sample(15999U));

    /*
     * A block that cannot possibly fit is refused WHOLE. It must not evict the
     * unread samples underneath the consumer: those are the next window, and
     * rewriting them would splice two different moments of audio together
     * silently, which is worse than a gap the caller can see.
     */
    CHECK(voice_ring_push(&g_ring, filler, (uint32_t)VOICE_RING_CAPACITY + 1U) ==
          (uint32_t)VOICE_RING_CAPACITY + 1U);
    CHECK(g_ring.overrun_count == (uint32_t)VOICE_RING_CAPACITY + 1U);

    /* The very next window is the NEXT 16,000 samples of the same stream. */
    CHECK(voice_ring_take_window(&g_ring, second, 16000U) == 16000U);
    CHECK(second[0] == ramp_sample(16000U));
    CHECK(second[15999] == ramp_sample(31999U));

    /*
     * And the ordinary fail-closed path, where the block is legal in size but
     * there is no room for it: the 768 samples still unread must survive, in
     * order, for the consumer that has not asked for them yet.
     */
    CHECK(g_ring.write_index - g_ring.read_index == 768U);
    CHECK(voice_ring_push(&g_ring, filler, (uint32_t)VOICE_RING_CAPACITY) ==
          (uint32_t)VOICE_RING_CAPACITY);

    CHECK(voice_ring_take_window(&g_ring, tail, 768U) == 768U);
    first_mismatch = 768U;
    for (i = 0U; i < 768U; ++i)
    {
        if (tail[i] != ramp_sample(32000U + i))
        {
            first_mismatch = i;
            break;
        }
    }
    CHECK(first_mismatch == 768U);
    /* Consuming the remainder empties the ring again: nothing was lost. */
    CHECK(voice_ring_available(&g_ring) == 0U);

    voice_app_titan_deinit();
}

/* ------------------------------------------------------------------------- */
/* 10. Inference longer than a window: keep going, then recover from a real gap.
 *
 * Taking the window out of the ring before classifying it is what makes this
 * survivable. The consumed window is no longer occupying space while the
 * network runs, so a whole second window can arrive during inference without
 * the producer running out of room.
 */

static void case_inference_longer_than_a_window_recovers(void)
{
    voice_app_status_t status;
    uint32_t produced = 0U;
    uint32_t generation_before;

    fixture_reset();
    fixture_up();

    /* Window 1 is taken on the CAPTURING poll and leaves the ring immediately. */
    CHECK(push_ramp(produced, (uint32_t)VOICE_WINDOW_SAMPLES) == 0U);
    produced += (uint32_t)VOICE_WINDOW_SAMPLES;
    drive_thread(1U);
    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_INFERENCING);

    /* A whole window arrives while the network is running. */
    CHECK(push_ramp(produced, (uint32_t)VOICE_WINDOW_SAMPLES) == 0U);
    produced += (uint32_t)VOICE_WINDOW_SAMPLES;

    drive_thread(1U);
    voice_app_titan_status(&status);
    CHECK(status.result_generation == 1U);

    drive_thread(2U); /* RESULT -> CAPTURING -> take -> INFERENCING */
    drive_thread(1U); /* -> RESULT */
    voice_app_titan_status(&status);
    CHECK(status.result_generation == 2U);
    CHECK(status.overrun_count == 0U);
    CHECK(status.state != VOICE_STATE_AUDIO_ERROR);

    generation_before = status.result_generation;

    /*
     * Now a genuinely over-long inference: a whole ring capacity arrives with
     * nothing consuming it, and the block after that has nowhere to go. The
     * producer refuses it, so the newest window would be audio from before the
     * gap laid end to end with audio from after it. R2 exists to refuse exactly
     * that, and it must refuse it here rather than publish a spliced window.
     */
    CHECK(push_ramp(produced, (uint32_t)VOICE_RING_CAPACITY) == 0U);
    produced += (uint32_t)VOICE_RING_CAPACITY;
    CHECK(push_ramp(produced, 800U) == 800U); /* refused: no room */
    produced += 800U;

    drive_thread(2U);
    voice_app_titan_status(&status);
    CHECK(status.overrun_count > 0U);
    CHECK(status.cycles_discarded >= 1U);
    CHECK(status.result_generation == generation_before);

    /* Recovery needs a whole window of newly ACCEPTED samples, not just time. */
    CHECK(push_ramp(produced, (uint32_t)VOICE_WINDOW_SAMPLES) == 0U);
    produced += (uint32_t)VOICE_WINDOW_SAMPLES;
    drive_thread(3U);
    voice_app_titan_status(&status);
    CHECK(status.result_generation > generation_before);
    CHECK(status.result_valid == 1U);
    CHECK(status.state != VOICE_STATE_AUDIO_ERROR);
    CHECK(status.state != VOICE_STATE_MODEL_ERROR);

    voice_app_titan_deinit();
}

#endif /* VOICE_APP_ENABLE */

/* ------------------------------------------------------------------------- */
/* The compiled-out build: same source, VOICE_APP_ENABLE=0. */

#if !VOICE_APP_ENABLE

static void case_compiled_out_is_inert(void)
{
    voice_app_status_t status;

    g_voice_thread_recorder.init_calls = 0U;
    g_voice_thread_recorder.startup_calls = 0U;
    g_voice_thread_recorder.detach_calls = 0U;
    g_capture_start_calls = 0U;

    CHECK(voice_app_titan_init() == 0);
    voice_app_titan_deinit();

    CHECK(g_voice_thread_recorder.init_calls == 0U);
    CHECK(g_voice_thread_recorder.startup_calls == 0U);
    CHECK(g_capture_start_calls == 0U);

    CHECK(voice_app_titan_state() == VOICE_STATE_DISABLED);

    memset(&status, 0xAA, sizeof(status));
    voice_app_titan_status(&status);
    CHECK(status.state == VOICE_STATE_DISABLED);
    CHECK(status.result_valid == 0U);
    CHECK(status.result_generation == 0U);
    CHECK(status.model_fingerprint == 0U);
    CHECK(status.field_accuracy_validated == 0U);
    CHECK(status.hardware_inference_validated == 0U);
    CHECK(status.samples_expected == (uint32_t)VOICE_WINDOW_SAMPLES);

    CHECK(voice_app_titan_model_fingerprint() == 0U);
}

#endif /* !VOICE_APP_ENABLE */

/* ------------------------------------------------------------------------- */

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);

#if VOICE_APP_ENABLE
    run_case("1-thread-parameters-match-the-requirement",
             case_thread_parameters);
    run_case("2-thread-opens-capture-and-polls",
             case_thread_opens_capture_and_polls);
    run_case("3-real-window-publishes-a-result",
             case_real_window_publishes_a_result);
    run_case("4-ring-overrun-blocks-publication",
             case_overrun_blocks_publication);
    run_case("5-snapshot-leaves-the-interrupt-mask-balanced",
             case_snapshot_is_balanced);
    run_case("6-capture-start-failure-is-survivable",
             case_capture_start_failure_is_survivable);
    run_case("7-sustained-windows-keep-the-ring-draining",
             case_sustained_windows_keep_the_ring_draining);
    run_case("8-window-spans-a-ring-wrap-in-order",
             case_window_spans_a_ring_wrap_in_order);
    run_case("9-producer-cannot-overwrite-an-unread-window",
             case_producer_cannot_overwrite_an_unread_window);
    run_case("10-inference-longer-than-a-window-recovers",
             case_inference_longer_than_a_window_recovers);
#else
    run_case("0-compiled-out-is-inert", case_compiled_out_is_inert);
#endif

    if (g_failures != 0U)
    {
        printf("C voice app titan tests FAILED: %u of %u checks failed\n",
               (unsigned)g_failures,
               (unsigned)g_checks);
        return 1;
    }

    printf("C voice app titan tests passed (%u checks)\n", (unsigned)g_checks);
    return 0;
}
