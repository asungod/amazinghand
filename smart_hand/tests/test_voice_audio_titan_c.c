/*
 * Host tests for voice_audio_titan.c -- the FSP PDM / RT-Thread adaptation
 * layer. Until now this file had zero host coverage: the existing
 * test_voice_audio_c.c only exercises the pure ring buffer in voice_audio.c,
 * so everything that talks to the FSP driver was untested off-target.
 *
 * That gap has already cost real time. VOICE_CALLBACK_GRANULARITY was 1000,
 * which is only a multiple of 8; R_PDM_Start divides it by
 * 1U << PDM_INTERRUPT_THRESHOLD_16 == 16 and returned FSP_ERR_INVALID_SIZE, so
 * capture never started at all -- and every test in the repo stayed green.
 *
 * This file is built to fail on exactly that class of problem, which shapes its
 * three load-bearing design choices:
 *
 *   1. The stub R_PDM_Start reproduces the FSP validation verbatim
 *      (ra/fsp/src/r_pdm/r_pdm.c:257-273), so an illegal granularity is
 *      rejected by the stub the same way the silicon rejects it. A permissive
 *      stub would have turned the 1000 bug into a passing test.
 *
 *   2. The buffer the driver fills is modelled as a function of POSITION:
 *      word i holds i / granularity. The module's ISR picks a position from its
 *      own cursor and copies the low 16 bits of each word, so the samples that
 *      reach the ring spell out which position was read -- a stale, replayed or
 *      skipped cursor shows up as a wrong id or as 800 samples that disagree.
 *
 *   3. Data interrupts are delivered while R_PDM_Start is still running, which
 *      is what the real driver does. The pre-P1 module zeroed its cursor after
 *      R_PDM_Start returned, which replayed the first block of every session;
 *      pdm_stub_pre_callbacks reproduces the window and
 *      pdm_stub_pre_callbacks_delivered proves the window was really entered.
 *
 * The stub headers in tests/stubs/ are found ahead of anything else because the
 * build line puts -I tests/stubs first.
 */

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * The stub headers are named after the real ones on purpose: the module under
 * test includes <rtthread.h>, <rthw.h> and <board.h>, and the build line puts
 * -I tests/stubs ahead of everything else so those names resolve to the hosts
 * stubs instead. This file includes them directly because it also *defines* the
 * symbols they declare.
 */
#include <rtthread.h>
#include <rthw.h>
#include <rtdevice.h>
#include <board.h>

#include "voice_audio_titan.h"

#include "hal_data.h"

/* ------------------------------------------------------------------------- */
/* Check plumbing.
 *
 * assert() would abort on the first failure, which is unhelpful when the job is
 * to characterise a mutation: one mutation should produce one legible report,
 * not a truncated one. Every check is recorded, printed when it fails, and the
 * process exits non-zero if anything failed -- so the Python wrapper's
 * returncode assertion still sees it.
 */

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

/* Same, but abandons the case: continuing past a failed start would report
 * noise from every later check instead of the one real defect. */
#define CHECK_OR_RETURN(cond)                                              \
    do                                                                     \
    {                                                                      \
        CHECK(cond);                                                       \
        if (!(cond))                                                       \
        {                                                                  \
            return;                                                        \
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
/* Stub implementations.
 *
 * The build line is
 *   gcc ... test_voice_audio_titan_c.c voice_audio_titan.c voice_audio.c -o exe
 * so nothing else can hold these definitions; the kernel and driver symbols the
 * module needs are all provided here.
 */

pdm_ctrl_t g_pdm0_ctrl;
pdm_cfg_t g_pdm0_cfg;

uint32_t pdm_stub_pre_callbacks;
uint32_t pdm_stub_pre_callbacks_delivered;
fsp_err_t pdm_stub_start_error;
uint32_t pdm_stub_autofill_markers;
int32_t *pdm_stub_buffer;
uint32_t pdm_stub_entries;
uint32_t pdm_stub_last_buffer_size;
uint32_t pdm_stub_last_granularity;
uint32_t pdm_stub_open_calls;
uint32_t pdm_stub_start_calls;
uint32_t pdm_stub_stop_calls;
uint32_t pdm_stub_close_calls;
uint32_t pdm_stub_is_open;
uint32_t pdm_stub_is_started;
uint32_t pdm_stub_refused_callbacks;
uint32_t pdm_stub_bsp_delay_calls;
uint32_t pdm_stub_bsp_delay_value;
uint32_t pdm_stub_bsp_delay_units;
void (*pdm_stub_callback_hook)(void);

static uint32_t g_irq_depth;
static rt_tick_t g_tick;
static uint32_t g_block_period_ms; /* ms of audio per data callback */
static uint32_t g_sim_block_ms;    /* ms accumulated since the last callback */

void pdm_stub_reset(void)
{
    pdm_stub_pre_callbacks = 0U;
    pdm_stub_pre_callbacks_delivered = 0U;
    pdm_stub_start_error = FSP_SUCCESS;
    pdm_stub_autofill_markers = 1U;
    pdm_stub_open_calls = 0U;
    pdm_stub_start_calls = 0U;
    pdm_stub_stop_calls = 0U;
    pdm_stub_close_calls = 0U;
    pdm_stub_is_open = 0U;
    pdm_stub_is_started = 0U;
    pdm_stub_refused_callbacks = 0U;
    pdm_stub_bsp_delay_calls = 0U;
    pdm_stub_bsp_delay_value = 0U;
    pdm_stub_bsp_delay_units = 0U;
    pdm_stub_callback_hook = NULL;

    g_irq_depth = 0U;
    g_tick = 0U;
    g_sim_block_ms = 0U;
}

uint32_t pdm_stub_irq_depth(void)
{
    return g_irq_depth;
}

void pdm_stub_fill_markers(void)
{
    uint32_t i;

    if ((pdm_stub_buffer == NULL) || (pdm_stub_last_granularity == 0U))
    {
        return;
    }

    /*
     * Word i == i / granularity. Every word of buffer block k therefore reads
     * back as k, so the id the module's ISR produces identifies the block it
     * chose, and a block that mixes two ids identifies a cursor that is not
     * block-aligned.
     */
    for (i = 0U; i < pdm_stub_entries; ++i)
    {
        pdm_stub_buffer[i] = (int32_t)(i / pdm_stub_last_granularity);
    }
}

static void pdm_stub_invoke(pdm_event_t event, pdm_error_t error)
{
    pdm_callback_args_t args;

    args.p_context = NULL;
    args.event = event;
    args.error = error;

    pdm_callback(&args);

    if (pdm_stub_callback_hook != NULL)
    {
        pdm_stub_callback_hook();
    }
}

void pdm_stub_fire_data(uint32_t blocks)
{
    uint32_t k;

    if (pdm_stub_is_started == 0U)
    {
        /* The real driver disables the data interrupt in R_PDM_Stop, so a
         * stopped block delivers nothing. Refusing here keeps a test from
         * "passing" with audio that the hardware could not have produced. */
        pdm_stub_refused_callbacks += 1U;
        return;
    }

    for (k = 0U; k < blocks; ++k)
    {
        pdm_stub_invoke(PDM_EVENT_DATA, PDM_ERROR_NONE);
    }
}

void pdm_stub_fire_event(pdm_event_t event, pdm_error_t error)
{
    if (pdm_stub_is_started == 0U)
    {
        pdm_stub_refused_callbacks += 1U;
        return;
    }

    pdm_stub_invoke(event, error);
}

/* ---- RT-Thread primitives ---- */

void *rt_memset(void *s, int c, rt_ubase_t count)
{
    return memset(s, c, (size_t)count);
}

rt_tick_t rt_tick_get(void)
{
    return g_tick;
}

/*
 * Time passing is what produces audio, so the stub advances a simulated clock
 * and delivers one PDM_EVENT_DATA every granularity/sample_rate milliseconds
 * (800 entries at 16 kHz == 50 ms). This is what makes
 * voice_audio_titan_probe() testable at all: its loop only delays, so without
 * this the probe would always report zero samples.
 */
void rt_thread_mdelay(rt_int32_t ms)
{
    uint32_t step = (ms > 0) ? (uint32_t)ms : 0U;

    g_tick += step;

    if ((pdm_stub_is_started != 0U) && (g_block_period_ms > 0U))
    {
        g_sim_block_ms += step;
        while (g_sim_block_ms >= g_block_period_ms)
        {
            g_sim_block_ms -= g_block_period_ms;
            pdm_stub_invoke(PDM_EVENT_DATA, PDM_ERROR_NONE);
        }
    }
}

rt_base_t rt_hw_interrupt_disable(void)
{
    rt_base_t level = (rt_base_t)g_irq_depth;

    g_irq_depth += 1U;
    return level;
}

void rt_hw_interrupt_enable(rt_base_t level)
{
    g_irq_depth = (uint32_t)level;
}

void R_BSP_SoftwareDelay(uint32_t delay, bsp_delay_units_t units)
{
    pdm_stub_bsp_delay_calls += 1U;
    pdm_stub_bsp_delay_value = delay;
    pdm_stub_bsp_delay_units = (uint32_t)units;
}

/* ---- FSP PDM driver ---- */

fsp_err_t R_PDM_Open(pdm_ctrl_t *p_ctrl, pdm_cfg_t const *p_cfg)
{
    pdm_stub_open_calls += 1U;

    if ((p_ctrl == NULL) || (p_cfg == NULL))
    {
        return FSP_ERR_ASSERTION;
    }
    if (pdm_stub_is_open != 0U)
    {
        return FSP_ERR_ALREADY_OPEN;
    }

    pdm_stub_is_open = 1U;
    return FSP_SUCCESS;
}

fsp_err_t R_PDM_Start(pdm_ctrl_t *p_ctrl,
                      void        *p_buffer,
                      size_t       buffer_size,
                      uint32_t     number_of_data_to_callback)
{
    uint32_t stages_per_interrupt = 1U << PDM_INTERRUPT_THRESHOLD_16;
    uint32_t entries;
    uint32_t k;

    pdm_stub_start_calls += 1U;

    if ((p_ctrl == NULL) || (p_buffer == NULL))
    {
        return FSP_ERR_ASSERTION;
    }
    if (pdm_stub_is_open == 0U)
    {
        return FSP_ERR_NOT_OPEN;
    }
    if (number_of_data_to_callback == 0U)
    {
        return FSP_ERR_INVALID_ARGUMENT;
    }

    /*
     * ra/fsp/src/r_pdm/r_pdm.c:257-273, in the driver's own order. This is the
     * check that the 1000-entry granularity failed, and the reason this stub
     * cannot be written as "store the pointer and return FSP_SUCCESS".
     */
    if ((((uintptr_t)p_buffer) & 0x03U) != 0U)
    {
        return FSP_ERR_INVALID_ALIGNMENT;
    }
    if ((number_of_data_to_callback % stages_per_interrupt) != 0U)
    {
        return FSP_ERR_INVALID_SIZE;
    }
    if ((buffer_size % sizeof(uint32_t)) != 0U)
    {
        return FSP_ERR_INVALID_SIZE;
    }
    entries = (uint32_t)(buffer_size / sizeof(uint32_t));
    if ((entries % number_of_data_to_callback) != 0U)
    {
        return FSP_ERR_INVALID_SIZE;
    }

    if (pdm_stub_start_error != FSP_SUCCESS)
    {
        return pdm_stub_start_error;
    }

    pdm_stub_last_buffer_size = (uint32_t)buffer_size;
    pdm_stub_last_granularity = number_of_data_to_callback;
    pdm_stub_buffer = (int32_t *)p_buffer;
    pdm_stub_entries = entries;
    pdm_stub_is_started = 1U;

    g_block_period_ms =
        (number_of_data_to_callback * 1000U) / VOICE_SAMPLE_RATE_HZ;
    g_sim_block_ms = 0U;

    if (pdm_stub_autofill_markers != 0U)
    {
        pdm_stub_fill_markers();
    }

    /*
     * The real driver writes p_rx_dest/p_read and enables the data interrupt
     * before it returns (r_pdm.c:287-300), so the first callbacks can arrive
     * while R_PDM_Start is still on the stack. Fire them here, after the buffer
     * is set up, exactly like the interrupt would.
     */
    for (k = 0U; k < pdm_stub_pre_callbacks; ++k)
    {
        pdm_stub_invoke(PDM_EVENT_DATA, PDM_ERROR_NONE);
        pdm_stub_pre_callbacks_delivered += 1U;
    }

    return FSP_SUCCESS;
}

fsp_err_t R_PDM_Stop(pdm_ctrl_t *p_ctrl)
{
    (void)p_ctrl; /* the stub keeps no per-channel state */

    pdm_stub_stop_calls += 1U;

    if (pdm_stub_is_open == 0U)
    {
        return FSP_ERR_NOT_OPEN;
    }

    pdm_stub_is_started = 0U;
    return FSP_SUCCESS;
}

fsp_err_t R_PDM_Close(pdm_ctrl_t *p_ctrl)
{
    (void)p_ctrl; /* the stub keeps no per-channel state */

    pdm_stub_close_calls += 1U;

    pdm_stub_is_open = 0U;
    pdm_stub_is_started = 0U;
    return FSP_SUCCESS;
}

/* ------------------------------------------------------------------------- */
/* Test-side helpers */

/* Bigger than any granularity the module may legally pass (800); the drain
 * checks the real one at run time rather than trusting this. */
#define TEST_BLOCK_MAX (1024U)

static int16_t g_block[TEST_BLOCK_MAX];
static uint32_t g_nonuniform_blocks;

static uint32_t lap_blocks(void)
{
    return (pdm_stub_last_granularity == 0U)
               ? 0U
               : (pdm_stub_entries / pdm_stub_last_granularity);
}

/*
 * Pull every complete block out of the ring and record the id each one carries.
 * A block whose 800 samples are not all identical means the ISR read across a
 * block boundary, which is counted and reported by the caller.
 */
static uint32_t drain_block_ids(uint32_t *ids, uint32_t max_ids)
{
    /* The test is the consumer here; the producer side is what is under test. */
    voice_ring_t *ring = (voice_ring_t *)voice_audio_titan_ring();
    uint32_t granularity = pdm_stub_last_granularity;
    uint32_t count = 0U;

    if (granularity == 0U)
    {
        return 0U;
    }

    while ((count < max_ids) && (voice_ring_available(ring) >= granularity))
    {
        uint32_t i;

        if (voice_ring_read(ring, g_block, granularity) != granularity)
        {
            break;
        }

        for (i = 1U; i < granularity; ++i)
        {
            if (g_block[i] != g_block[0])
            {
                g_nonuniform_blocks += 1U;
                break;
            }
        }

        ids[count] = (uint32_t)(uint16_t)g_block[0];
        count += 1U;
    }

    return count;
}

/*
 * The sequence the module must produce: callback k is buffer position
 * (k * granularity) % capture_samples, whose marker is k % lap. So the ids must
 * advance by exactly one each time, wrapping at lap, with no repeat inside a
 * lap and no gap. A replayed block, a skipped block, and a cursor left where a
 * previous session abandoned it all violate this one rule.
 *
 * `first` is the id of the first block in `ids`, so the same rule can be
 * applied to a run that starts mid-lap (an event, or a stats reset, must leave
 * the cursor exactly where it was).
 */
static void check_block_sequence(const uint32_t *ids,
                                 uint32_t        count,
                                 uint32_t        first,
                                 const char     *label)
{
    uint32_t lap = lap_blocks();
    uint32_t k;

    if (lap == 0U)
    {
        printf("  FAIL %s: no start observed, cannot evaluate the sequence\n",
               label);
        g_failures += 1U;
        return;
    }

    for (k = 0U; k < count; ++k)
    {
        uint32_t want = (first + k) % lap;

        g_checks += 1U;
        if (ids[k] != want)
        {
            g_failures += 1U;
            printf("  FAIL %s: block %u carried id %u, expected %u\n",
                   label,
                   (unsigned)k,
                   (unsigned)ids[k],
                   (unsigned)want);
        }
    }
}

static void snapshot(voice_capture_stats_t *out)
{
    memset(out, 0, sizeof(*out));
    voice_audio_titan_stats(out);
}

static void expect_full_drain(void)
{
    CHECK(voice_ring_available(voice_audio_titan_ring()) == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 1 -- cold start: the block sequence is contiguous from block 0. */

static void case_cold_start_is_contiguous(void)
{
    voice_capture_stats_t s;
    uint32_t ids[8];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    /* The ring handle is documented as never NULL after a start. */
    CHECK(voice_audio_titan_ring() != NULL);

    /*
     * What the module actually handed the driver. These are the values the FSP
     * divisibility rules constrain, so they are asserted here rather than
     * assumed: with granularity 1000 this whole file would still pass if the
     * stub were permissive, which is why the stub is not.
     */
    CHECK(pdm_stub_open_calls == 1U);
    CHECK(pdm_stub_start_calls == 1U);
    CHECK(pdm_stub_is_started == 1U);
    CHECK(pdm_stub_last_buffer_size == 64000U);
    CHECK(pdm_stub_entries == 16000U);
    CHECK(pdm_stub_last_granularity == 800U);
    CHECK((pdm_stub_last_granularity %
           (1U << PDM_INTERRUPT_THRESHOLD_16)) == 0U);
    CHECK((pdm_stub_entries % pdm_stub_last_granularity) == 0U);
    CHECK(lap_blocks() == 20U);

    /* The settling delay must be in microseconds, with the configured value. */
    CHECK(pdm_stub_bsp_delay_calls == 1U);
    CHECK(pdm_stub_bsp_delay_value == PDM2_FILTER_SETTLING_TIME_US);
    CHECK(pdm_stub_bsp_delay_units == (uint32_t)BSP_DELAY_UNITS_MICROSECONDS);

    snapshot(&s);
    CHECK(s.running == 1U);
    CHECK(s.samples_captured == 0U);
    CHECK(s.callbacks == 0U);

    pdm_stub_fire_data(5U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 5U);
    check_block_sequence(ids, count, 0U, "cold start");
    CHECK(g_nonuniform_blocks == 0U);
    expect_full_drain();

    snapshot(&s);
    CHECK(s.callbacks == 5U);
    CHECK(s.samples_captured == 5U * 800U);
    CHECK(s.overrun_count == 0U);
    CHECK(s.error_count == 0U);
    CHECK(s.running == 1U);

    /* Every critical section in the module must have been balanced. */
    CHECK(pdm_stub_irq_depth() == 0U);

    /* A second start while running must be a no-op, not a re-open. */
    CHECK(voice_audio_titan_start() == 0);
    CHECK(pdm_stub_open_calls == 1U);
    CHECK(pdm_stub_start_calls == 1U);
}

/* ------------------------------------------------------------------------- */
/* Case 2 -- stop, then restart: the sequence restarts at block 0 and the first
 * block of the new session is not replayed once the cursor is published. */

static void case_restart_does_not_replay_the_first_block(void)
{
    uint32_t ids[16];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    /*
     * A start always runs with the interrupt already live, so the restart below
     * gets one pre-return callback too. That is what makes this case able to
     * see a cursor published after R_PDM_Start returns: the callback consumes
     * block 0, and a cursor published afterwards would consume it again.
     */
    pdm_stub_pre_callbacks = 1U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);
    CHECK(pdm_stub_pre_callbacks_delivered == 1U);

    pdm_stub_fire_data(3U);
    count = drain_block_ids(ids, 16U);
    CHECK(count == 4U); /* one inside R_PDM_Start, three after it returned */
    check_block_sequence(ids, count, 0U, "session 1");

    voice_audio_titan_stop();
    CHECK(pdm_stub_stop_calls == 1U);
    CHECK(pdm_stub_close_calls == 1U);
    CHECK(pdm_stub_is_started == 0U);
    CHECK(pdm_stub_irq_depth() == 0U);

    /* The driver restarts filling at the beginning of the buffer, so the new
     * session's first block is position 0 again -- not wherever session 1 left
     * its cursor. */
    pdm_stub_pre_callbacks = 1U;
    CHECK_OR_RETURN(voice_audio_titan_start() == 0);
    CHECK(pdm_stub_pre_callbacks_delivered == 2U); /* 1 from session 1, 1 now */
    /* The restart goes through Open again, rather than assuming the block that
     * stop() closed is still usable. */
    CHECK(pdm_stub_open_calls == 2U);

    pdm_stub_fire_data(4U);
    count = drain_block_ids(ids, 16U);
    CHECK(count == 5U);
    check_block_sequence(ids, count, 0U, "session 2 restart");
    CHECK(g_nonuniform_blocks == 0U);
    expect_full_drain();
    CHECK(pdm_stub_irq_depth() == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 3 -- a failed R_PDM_Start must not be published as running, must close
 * the block, and must not poison the next start. */

static void case_failed_start_is_not_published_and_recovers(void)
{
    voice_capture_stats_t s;
    uint32_t ids[8];
    uint32_t count;
    int result;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_start_error = FSP_ERR_INVALID_SIZE;

    result = voice_audio_titan_start();
    CHECK(result == -(int)FSP_ERR_INVALID_SIZE);

    snapshot(&s);
    CHECK(s.running == 0U);
    CHECK(s.samples_captured == 0U);

    /* The module must close what it opened, or the next open fails with
     * FSP_ERR_ALREADY_OPEN on real hardware. */
    CHECK(pdm_stub_open_calls == 1U);
    CHECK(pdm_stub_close_calls == 1U);
    CHECK(pdm_stub_is_open == 0U);
    CHECK(pdm_stub_is_started == 0U);
    CHECK(pdm_stub_irq_depth() == 0U);

    /* Nothing may be deliverable from a block that never started. */
    pdm_stub_fire_data(3U);
    CHECK(pdm_stub_refused_callbacks == 1U);
    snapshot(&s);
    CHECK(s.running == 0U);
    CHECK(s.samples_captured == 0U);
    CHECK(s.error_count == 0U);
    CHECK(voice_ring_available(voice_audio_titan_ring()) == 0U);

    /* And a later, healthy start must behave exactly like a cold one. */
    pdm_stub_start_error = FSP_SUCCESS;
    pdm_stub_pre_callbacks = 0U;
    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    snapshot(&s);
    CHECK(s.running == 1U);

    pdm_stub_fire_data(3U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 3U);
    check_block_sequence(ids, count, 0U, "start after a failed start");
    CHECK(g_nonuniform_blocks == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 4 -- the P1 race: R_PDM_Start returns after the interrupt has already
 * delivered callbacks. The cursor must survive them, so nothing is replayed. */

static uint32_t g_hook_calls;
static uint32_t g_hook_running[16];

static void record_running_inside_callback(void)
{
    voice_capture_stats_t s;

    if (g_hook_calls < 16U)
    {
        voice_audio_titan_stats(&s);
        g_hook_running[g_hook_calls] = s.running;
    }
    g_hook_calls += 1U;
}

static void case_callbacks_before_start_returns(void)
{
    voice_capture_stats_t s;
    uint32_t ids[16];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 2U;

    g_hook_calls = 0U;
    memset(g_hook_running, 0xFF, sizeof(g_hook_running));
    pdm_stub_callback_hook = record_running_inside_callback;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    /* The race window was really entered: if this is zero the case is vacuous
     * and would pass against the old implementation. */
    CHECK(pdm_stub_pre_callbacks_delivered == 2U);
    CHECK(g_hook_calls == 2U);
    /* ... and it was entered before the module published itself as running,
     * which is why the cursor must be positioned before R_PDM_Start, not
     * after it. */
    CHECK(g_hook_running[0] == 0U);
    CHECK(g_hook_running[1] == 0U);

    snapshot(&s);
    CHECK(s.running == 1U);
    CHECK(s.callbacks == 2U);
    CHECK(s.samples_captured == 2U * 800U);

    pdm_stub_fire_data(5U);
    count = drain_block_ids(ids, 16U);
    CHECK(count == 7U);
    /* Old behaviour replayed ids 0 and 1 here (cursor re-zeroed after the
     * start), giving 0,1,0,1,2,3,4. */
    check_block_sequence(ids, count, 0U, "callbacks before start returned");
    CHECK(g_nonuniform_blocks == 0U);
    expect_full_drain();

    snapshot(&s);
    CHECK(s.callbacks == 7U);
    CHECK(s.samples_captured == 7U * 800U);
    CHECK(s.overrun_count == 0U);

    /* Callbacks delivered after the start must observe the published flag. */
    CHECK(g_hook_calls == 7U);
    CHECK(g_hook_running[6] == 1U);

    pdm_stub_callback_hook = NULL;
}

/* ------------------------------------------------------------------------- */
/* Case 5 -- the FSP granularity rules themselves. This is the stub's own
 * contract, and the reason a granularity regression cannot slip through: it
 * pins the exact divisibility checks R_PDM_Start applies. */

static void case_granularity_rules_match_the_driver(void)
{
    static int32_t buffer[16000];
    static uint8_t raw[64000U + 8U];

    pdm_stub_reset();

    CHECK(R_PDM_Open(&g_pdm0_ctrl, &g_pdm0_cfg) == FSP_SUCCESS);
    CHECK(pdm_stub_is_open == 1U);

    /* The historical regression: 1000 % 16 == 8, so the real driver returned
     * FSP_ERR_INVALID_SIZE and capture never started. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64000U, 1000U) != FSP_SUCCESS);
    CHECK(pdm_stub_is_started == 0U);
    CHECK(pdm_stub_last_granularity != 1000U);

    /* 8 entries is below one full set of 16 stages. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64000U, 8U) != FSP_SUCCESS);

    /* 1600 is legal: 1600 % 16 == 0 and 16000 % 1600 == 0. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64000U, 1600U) == FSP_SUCCESS);

    /* 2400 passes the multiple-of-16 rule but 16000 % 2400 == 1600, so the
     * entry count does not divide evenly. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64000U, 2400U) != FSP_SUCCESS);

    /* Buffer size must be a multiple of sizeof(uint32_t). */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64002U, 800U) != FSP_SUCCESS);

    /* The buffer must be 4-byte aligned. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, raw + 1U, 64000U, 800U) != FSP_SUCCESS);

    /* The pair the module actually uses must be one the driver accepts. */
    CHECK(R_PDM_Start(&g_pdm0_ctrl, buffer, 64000U, 800U) == FSP_SUCCESS);
    CHECK(pdm_stub_last_granularity == 800U);
    CHECK(pdm_stub_last_buffer_size == 64000U);

    CHECK(R_PDM_Close(&g_pdm0_ctrl) == FSP_SUCCESS);
    CHECK(pdm_stub_is_open == 0U);

    /* And the module's own start must still go through the same door. */
    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    CHECK(voice_audio_titan_start() == 0);
    CHECK((pdm_stub_last_granularity %
           (1U << PDM_INTERRUPT_THRESHOLD_16)) == 0U);
    CHECK((pdm_stub_entries % pdm_stub_last_granularity) == 0U);
    CHECK(pdm_stub_last_buffer_size % (uint32_t)sizeof(uint32_t) == 0U);
    voice_audio_titan_stop();
}

/* ------------------------------------------------------------------------- */
/* Case 6 -- error events: counted, reported in both the stats and the ring,
 * and harmless to the block cursor. */

static void case_error_events_are_counted_and_harmless(void)
{
    voice_capture_stats_t s;
    const voice_ring_t *ring;
    uint32_t ids[8];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    pdm_stub_fire_data(2U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 2U);

    /* Sound detection is not an error and must not move any counter. */
    pdm_stub_fire_event(PDM_EVENT_SOUND_DETECTION, PDM_ERROR_NONE);
    snapshot(&s);
    CHECK(s.error_count == 0U);
    CHECK(s.last_error == 0U);
    CHECK(s.callbacks == 2U);

    pdm_stub_fire_event(PDM_EVENT_ERROR, PDM_ERROR_OVERVOLTAGE_UPPER);
    snapshot(&s);
    CHECK(s.error_count == 1U);
    CHECK(s.last_error == (uint8_t)PDM_ERROR_OVERVOLTAGE_UPPER);

    ring = voice_audio_titan_ring();
    CHECK(ring->error_count == 1U);
    CHECK(ring->last_error == (uint8_t)PDM_ERROR_OVERVOLTAGE_UPPER);

    pdm_stub_fire_event(PDM_EVENT_ERROR, PDM_ERROR_OVERVOLTAGE_LOWER);
    snapshot(&s);
    CHECK(s.error_count == 2U);
    CHECK(s.last_error == (uint8_t)PDM_ERROR_OVERVOLTAGE_LOWER);
    CHECK(ring->error_count == 2U);
    CHECK(ring->last_error == (uint8_t)PDM_ERROR_OVERVOLTAGE_LOWER);

    /*
     * Both counters are bumped by different code paths (pdm_callback and
     * voice_ring_note_error) and are supposed to agree; voice_audio.c's
     * comments say so explicitly.
     *
     * Note: PDM_ERROR_BUFFER_OVERWRITE is (1UL << 11) == 0x800, and the
     * exposed last_error field is a uint8_t, so that code truncates to 0 and
     * cannot be told apart from "no error". The test therefore uses the two
     * overvoltage codes, which fit. The truncation is a real property of the
     * published field, not something asserted as correct here.
     */
    CHECK(s.error_count == ring->error_count);
    CHECK(s.last_error == ring->last_error);

    /* The cursor must be unaffected by a control event. */
    pdm_stub_fire_data(2U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 2U);
    check_block_sequence(ids, count, 2U, "blocks after error events");
    CHECK(g_nonuniform_blocks == 0U);
    CHECK(pdm_stub_irq_depth() == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 7 -- one second of audio: block 21 reads buffer position 0 again. */

static void case_one_second_buffer_wraps(void)
{
    voice_capture_stats_t s;
    uint32_t ids[32];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);
    CHECK(lap_blocks() == 20U); /* 16000 samples / 800 per callback */

    pdm_stub_fire_data(25U);
    count = drain_block_ids(ids, 32U);
    CHECK(count == 25U);
    check_block_sequence(ids, count, 0U, "one-second wrap");
    CHECK(g_nonuniform_blocks == 0U);

    /* The wrap in one line: the 21st callback reads buffer position 0 again. */
    CHECK(ids[0] == 0U);
    CHECK(ids[20] == 0U);
    CHECK(ids[19] == 19U);

    snapshot(&s);
    CHECK(s.callbacks == 25U);
    CHECK(s.samples_captured == 25U * 800U);
    CHECK(s.overrun_count == 0U); /* 20000 samples fit in the 32768 ring */
    CHECK(voice_ring_available(voice_audio_titan_ring()) == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 7b -- a full lap plus a block: the ring rejects the overflow whole, and
 * the two overrun counters (stats and ring) stay in agreement. */

static void case_ring_overrun_accounting_agrees(void)
{
    voice_capture_stats_t s;
    const voice_ring_t *ring;
    uint32_t ids[48];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    /* 41 blocks == 32800 samples; the 32768-sample ring holds 40 of them. */
    pdm_stub_fire_data(41U);

    snapshot(&s);
    ring = voice_audio_titan_ring();
    CHECK(s.callbacks == 41U);
    CHECK(s.samples_captured == 41U * 800U); /* every delivered sample */
    CHECK(s.overrun_count == 800U);          /* the one block the ring refused */
    CHECK(ring->total_samples == 40U * 800U);
    CHECK(ring->overrun_count == 800U);
    CHECK(s.overrun_count == ring->overrun_count);

    count = drain_block_ids(ids, 48U);
    CHECK(count == 40U);
    check_block_sequence(ids, count, 0U, "two laps with one block dropped");
    CHECK(g_nonuniform_blocks == 0U);
    CHECK(voice_ring_available(ring) == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 8 -- voice_audio_titan_probe(): blocks for duration_ms, reports what was
 * really captured, and leaves capture running. */

static void case_probe_smoke(void)
{
    voice_capture_stats_t out;
    uint32_t ids[8];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    memset(&out, 0xA5, sizeof(out));
    CHECK(voice_audio_titan_probe(100U, &out) == 0);

    /* 100 ms of audio at one block per 50 ms is exactly two blocks. The
     * simulated cadence is the stub's, so this is deterministic rather than
     * timing dependent. */
    CHECK(out.samples_captured == 1600U);
    CHECK(out.callbacks == 2U);
    CHECK(out.running == 1U);
    CHECK(out.error_count == 0U);
    CHECK(out.overrun_count == 0U);

    /* What the probe reports must be what the ring actually holds. */
    CHECK(voice_ring_available(voice_audio_titan_ring()) == out.samples_captured);

    count = drain_block_ids(ids, 8U);
    CHECK(count == 2U);
    check_block_sequence(ids, count, 0U, "probe");
    CHECK(g_nonuniform_blocks == 0U);

    /* The probe deliberately leaves capture running for the caller. */
    voice_audio_titan_stop();
    CHECK(pdm_stub_stop_calls == 1U);
    CHECK(pdm_stub_close_calls == 1U);
    CHECK(pdm_stub_is_started == 0U);

    /* A second stop must be inert: nothing is open to stop or close. */
    voice_audio_titan_stop();
    CHECK(pdm_stub_stop_calls == 1U);
    CHECK(pdm_stub_close_calls == 1U);

    /* A NULL out is rejected without touching the driver. */
    pdm_stub_reset();
    CHECK(voice_audio_titan_probe(10U, NULL) == -1);
    CHECK(pdm_stub_start_calls == 0U);
    CHECK(pdm_stub_irq_depth() == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 9 -- the stats snapshot is self consistent with the samples that were
 * captured, including the silent-input case. */

static void case_stats_match_the_captured_samples(void)
{
    voice_capture_stats_t s;
    uint32_t ids[8];
    uint32_t count;
    uint32_t i;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    /* Three blocks carry ids 0, 1, 2 -> 800 samples each of 0, 1 and 2. */
    pdm_stub_fire_data(3U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 3U);

    snapshot(&s);
    CHECK(s.callbacks == 3U);
    CHECK(s.samples_captured == 2400U);
    CHECK(s.peak == 2);
    /* mean = (0 + 800 + 1600) / 2400 = 1 */
    CHECK(fabsf(s.dc_offset - 1.0f) < 1.0e-6f);
    /* mean square = (0 + 800*1 + 800*4) / 2400 = 5/3 */
    CHECK(fabsf(s.rms - sqrtf(5.0f / 3.0f)) < 1.0e-5f);
    /* voice_audio_titan_rms() reads the same accumulators. */
    CHECK(fabsf(voice_audio_titan_rms() - s.rms) < 1.0e-6f);

    /* Now silence: the whole buffer zeroed, counters reset, two blocks read. */
    for (i = 0U; i < pdm_stub_entries; ++i)
    {
        pdm_stub_buffer[i] = 0;
    }
    pdm_stub_autofill_markers = 0U;
    voice_audio_titan_reset_stats();

    pdm_stub_fire_data(2U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 2U);
    CHECK(ids[0] == 0U);
    CHECK(ids[1] == 0U);

    snapshot(&s);
    CHECK(s.samples_captured == 1600U);
    CHECK(s.callbacks == 2U);
    CHECK(s.rms == 0.0f);
    CHECK(s.dc_offset == 0.0f);
    CHECK(s.peak == 0);
    CHECK(s.error_count == 0U);
    CHECK(voice_audio_titan_rms() == 0.0f);

    /* The size of the captured window must be consistent with the counters. */
    CHECK(s.samples_captured == s.callbacks * 800U);

    /* NULL handling must not fault, and must not move any counter. */
    voice_audio_titan_stats(NULL);
    pdm_callback(NULL);
    snapshot(&s);
    CHECK(s.callbacks == 2U);
    CHECK(s.samples_captured == 1600U);
    CHECK(pdm_stub_irq_depth() == 0U);
}

/* ------------------------------------------------------------------------- */
/* Case 10 -- resetting the statistics mid-capture must not move the interrupt's
 * cursor. An earlier revision derived the cursor from g_stats.callbacks, so a
 * reset rewound the ISR by (callbacks mod blocks) and replayed audio. */

static void case_reset_stats_does_not_move_the_cursor(void)
{
    voice_capture_stats_t s;
    const voice_ring_t *ring;
    uint32_t ids[8];
    uint32_t count;

    voice_audio_titan_stop();
    pdm_stub_reset();
    pdm_stub_autofill_markers = 1U;
    pdm_stub_pre_callbacks = 0U;

    CHECK_OR_RETURN(voice_audio_titan_start() == 0);

    pdm_stub_fire_data(3U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 3U);
    check_block_sequence(ids, count, 0U, "before the reset");

    voice_audio_titan_reset_stats();

    snapshot(&s);
    CHECK(s.samples_captured == 0U);
    CHECK(s.callbacks == 0U);
    CHECK(s.peak == 0);
    /* The module is still capturing, and the snapshot must say so. */
    CHECK(s.running == 1U);
    CHECK(voice_audio_titan_rms() == 0.0f);

    pdm_stub_fire_data(2U);
    count = drain_block_ids(ids, 8U);
    CHECK(count == 2U);
    /* Ids 3 and 4: the capture continues where it was, it does not rewind to
     * block 0. Checking contiguity alone would not catch this, because a rewind
     * would restart the sequence at a valid-looking 0, 1. */
    CHECK(ids[0] == 3U);
    CHECK(ids[1] == 4U);
    check_block_sequence(ids, count, 3U, "after the reset");

    snapshot(&s);
    CHECK(s.samples_captured == 1600U);
    CHECK(s.callbacks == 2U);

    /* The ring's own counters are reset with the stats, so the two views of the
     * loss figure cannot drift apart. */
    ring = voice_audio_titan_ring();
    CHECK(ring->error_count == s.error_count);
    CHECK(ring->overrun_count == s.overrun_count);
    CHECK(ring->total_samples == 5U * 800U); /* reset does not discard audio */
    CHECK(pdm_stub_irq_depth() == 0U);
}

/* ------------------------------------------------------------------------- */

int main(void)
{
    /*
     * Unbuffered: a mutation that reads past the end of the capture buffer
     * faults rather than failing a check, and with a block-buffered stdout the
     * report would be lost with it. Unbuffered, the last case line printed
     * still says where the run stopped.
     */
    setvbuf(stdout, NULL, _IONBF, 0);

    run_case("1-cold-start-contiguous",
             case_cold_start_is_contiguous);
    run_case("2-restart-no-first-block-replay",
             case_restart_does_not_replay_the_first_block);
    run_case("3-failed-start-not-running-and-recovers",
             case_failed_start_is_not_published_and_recovers);
    run_case("4-callbacks-before-start-returns",
             case_callbacks_before_start_returns);
    run_case("5-fsp-granularity-rules",
             case_granularity_rules_match_the_driver);
    run_case("6-error-events-counted",
             case_error_events_are_counted_and_harmless);
    run_case("7-one-second-wrap",
             case_one_second_buffer_wraps);
    run_case("7b-ring-overrun-accounting",
             case_ring_overrun_accounting_agrees);
    run_case("8-probe-smoke",
             case_probe_smoke);
    run_case("9-stats-match-samples",
             case_stats_match_the_captured_samples);
    run_case("10-reset-stats-keeps-the-cursor",
             case_reset_stats_does_not_move_the_cursor);

    if (g_failures != 0U)
    {
        printf("C voice audio titan tests FAILED: %u of %u checks failed\n",
               (unsigned)g_failures,
               (unsigned)g_checks);
        return 1;
    }

    printf("C voice audio titan tests passed (%u checks)\n", (unsigned)g_checks);
    return 0;
}
