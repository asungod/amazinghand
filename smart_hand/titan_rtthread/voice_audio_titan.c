#include "voice_audio_titan.h"

#include <rtthread.h>
#include <rtdevice.h>
#include <rthw.h>
#include <board.h>

#include <math.h>

#include "hal_data.h"

/*
 * See voice_audio_titan.h for the driver facts this file depends on.
 *
 * Interrupt discipline: the PDM data callback does nothing but copy samples
 * into the lock-free ring and bump counters. No features, no logging, no
 * inference -- the task book forbids that, and rt_kprintf is a blocking call
 * that would wreck the audio cadence.
 *
 * The FSP driver fills the caller's buffer linearly and fires PDM_EVENT_DATA
 * every `granularity` entries; the ISR-side handler below therefore has to
 * track its own position rather than assume the callback means "buffer full".
 * The vendor example gets this wrong (it treats a quarter-full buffer as
 * complete), which is why this is spelled out.
 */

/*
 * One second of audio per start. Buffer size must be a multiple of 4 bytes,
 * and buffer_size/4 must divide evenly by the callback granularity.
 */
#define VOICE_CAPTURE_SAMPLES (VOICE_SAMPLE_RATE_HZ)
#define VOICE_CAPTURE_BYTES (VOICE_CAPTURE_SAMPLES * (uint32_t)sizeof(uint32_t))

/*
 * Callback granularity in FIFO entries. 800 entries == 800 samples == 50 ms of
 * audio at 16 kHz.
 *
 * This value is not free to choose. R_PDM_Start rejects the call outright
 * unless it is a multiple of 1<<interrupt_threshold AND divides the buffer's
 * FIFO entry count:
 *
 *   ra/fsp/src/r_pdm/r_pdm.c:259  stages_per_interrupt = 1U << interrupt_threshold
 *   ra/fsp/src/r_pdm/r_pdm.c:266  FSP_ERROR_RETURN((0 == (number_of_data_to_callback
 *                                                    % stages_per_interrupt)),
 *                                                  FSP_ERR_INVALID_SIZE);
 *
 * The check is unconditional -- it is not gated by BSP_CFG_PARAM_CHECKING_ENABLE
 * -- so violating it means R_PDM_Start returns an error and capture never
 * starts, with no audio and no obvious symptom beyond every probe returning a
 * negative status. An earlier revision used 1000; since 1000 % 16 == 8, that
 * parameter failed the check on every single call, so capture never started at
 * all rather than starting intermittently.
 *
 * The static assertions below turn that run-time failure into a build error.
 */
#define VOICE_CALLBACK_GRANULARITY (800U)

/* FSP's own threshold constant, from ra/fsp/inc/instances/r_pdm.h. */
#define VOICE_PDM_STAGES_PER_INTERRUPT (1U << PDM_INTERRUPT_THRESHOLD_16)

_Static_assert((VOICE_CALLBACK_GRANULARITY % VOICE_PDM_STAGES_PER_INTERRUPT) == 0U,
               "R_PDM_Start rejects a callback granularity that is not a multiple "
               "of 1<<interrupt_threshold");
_Static_assert((VOICE_CAPTURE_SAMPLES % VOICE_CALLBACK_GRANULARITY) == 0U,
               "R_PDM_Start rejects a callback granularity that does not divide "
               "buffer_size/4");

static voice_ring_t g_voice_ring;
static int32_t g_capture_buffer[VOICE_CAPTURE_SAMPLES];
static voice_capture_stats_t g_stats;
/*
 * The interrupt's own cursor into g_capture_buffer. This is deliberately NOT
 * part of g_stats: reset_stats() clears g_stats, and an earlier revision
 * derived the cursor from g_stats.callbacks, so any mid-capture reset shifted
 * the interrupt's read position by (callbacks mod blocks) and left it there
 * for the rest of the session. Statistics and buffer positioning are separate
 * concerns and now use separate counters.
 */
static volatile uint32_t g_isr_block;
static volatile uint8_t g_running;
/*
 * Whether the PDM block is open, i.e. whether the hardware needs closing.
 *
 * start() and stop() key off this rather than g_running. g_running is only
 * published after R_PDM_Start() returns, but the data interrupt is already
 * live inside that call -- so keying off g_running left a window where the
 * hardware was running, g_running still read 0, and stop() returned without
 * stopping anything. g_pdm_open is set as soon as R_PDM_Open() succeeds, so
 * the window is closed.
 */
static volatile uint8_t g_pdm_open;
static uint64_t g_square_accumulator;
static int64_t g_sample_accumulator;
static uint32_t g_level_samples;

static void voice_account_sample(int16_t sample)
{
    /*
     * Widen before negating. In 16 bits, -(-32768) wraps back to -32768, so a
     * full-scale negative sample would compare as the smallest possible value
     * and never be recorded as a peak.
     */
    int32_t value = (int32_t)sample;

    if (value < 0)
    {
        value = -value;
    }
    if (value > g_stats.peak)
    {
        g_stats.peak = value;
    }

    /*
     * Accumulate in 64-bit so a 30 minute run cannot overflow: 16000*1800
     * samples of 32767^2 is about 3.1e16, which fits in int64 comfortably.
     */
    g_square_accumulator += (uint64_t)((int64_t)sample * (int64_t)sample);
    g_sample_accumulator += (int64_t)sample;
    g_level_samples += 1U;
}

void pdm_callback(pdm_callback_args_t *p_args)
{
    if (p_args == NULL)
    {
        return;
    }

    switch (p_args->event)
    {
        case PDM_EVENT_DATA:
        {
            static int16_t staging[VOICE_CALLBACK_GRANULARITY];
            uint32_t i;

            /*
             * The driver writes raw 32-bit FIFO words into g_capture_buffer.
             * In PDM_PCM_WIDTH_16_BITS_0_14 the sample is the low 16 bits.
             */
            /*
             * UNVERIFIED ON HARDWARE: this assumes the driver restarts filling
             * from the beginning of p_buffer once it reaches the end, so the
             * Nth callback sits at N*GRANULARITY modulo the buffer length.
             * ra/fsp/src/r_pdm/r_pdm.c shows p_read being set to p_buffer in
             * R_PDM_Start, but the wrap behaviour past rx_dest_samples is not
             * spelled out in the header. voice_audio_titan_probe() is what
             * settles it: if the assumption is wrong, the RMS and DC figures
             * will look like a repeating ramp rather than steady audio.
             */
            uint32_t base = ((g_isr_block * VOICE_CALLBACK_GRANULARITY) %
                             VOICE_CAPTURE_SAMPLES);

            for (i = 0U; i < VOICE_CALLBACK_GRANULARITY; ++i)
            {
                int16_t sample = (int16_t)(g_capture_buffer[base + i] & 0xFFFF);
                staging[i] = sample;
                voice_account_sample(sample);
            }

            g_stats.overrun_count +=
                voice_ring_push(&g_voice_ring, staging, VOICE_CALLBACK_GRANULARITY);
            g_stats.samples_captured += VOICE_CALLBACK_GRANULARITY;
            g_stats.callbacks += 1U;
            g_isr_block += 1U;
            break;
        }

        case PDM_EVENT_ERROR:
        {
            g_stats.error_count += 1U;
            g_stats.last_error = (uint32_t)p_args->error;
            voice_ring_note_error(&g_voice_ring, (uint32_t)p_args->error);
            break;
        }

        case PDM_EVENT_SOUND_DETECTION:
        default:
            break;
    }
}

int voice_audio_titan_start(void)
{
    fsp_err_t err;

    if (g_pdm_open != 0U)
    {
        return 0;
    }

    /*
     * reset_for_capture, not voice_ring_init: init memsets the whole ring
     * including read_index, which belongs to the consumer. A consumer
     * mid-read would then re-deliver audio it had already consumed.
     */
    voice_ring_reset_for_capture(&g_voice_ring);
    voice_audio_titan_reset_stats();

    /*
     * Phase the interrupt's cursor while the PDM block is still idle.
     *
     * This must happen BEFORE R_PDM_Start(), not after. That call enables the
     * data interrupt before it returns, so by the time it hands control back
     * the cursor may already have been advanced by one or more real callbacks.
     * Zeroing it afterwards would make the next callback replay a block that
     * was already delivered -- and on a restart the first callbacks would read
     * blocks left over from the previous session. Cold boot can look fine
     * because static initialisation happens to be zero, which is exactly what
     * makes this worth pinning down rather than reasoning about.
     *
     * g_running is also forced low here so a failed start cannot leave the
     * module advertised as running.
     */
    {
        rt_base_t level = rt_hw_interrupt_disable();
        g_isr_block = 0U;
        g_running = 0U;
        g_stats.running = 0U;
        rt_hw_interrupt_enable(level);
    }

    err = R_PDM_Open(&g_pdm0_ctrl, &g_pdm0_cfg);
    if (FSP_SUCCESS != err)
    {
        return -(int)err;
    }

    {
        rt_base_t level = rt_hw_interrupt_disable();
        g_pdm_open = 1U;
        rt_hw_interrupt_enable(level);
    }

    /* Let the PDM filter chain settle before the first data interrupt. */
    R_BSP_SoftwareDelay(PDM2_FILTER_SETTLING_TIME_US, BSP_DELAY_UNITS_MICROSECONDS);

    err = R_PDM_Start(&g_pdm0_ctrl,
                      g_capture_buffer,
                      VOICE_CAPTURE_BYTES,
                      VOICE_CALLBACK_GRANULARITY);
    if (FSP_SUCCESS != err)
    {
        /*
         * Close and clear g_pdm_open together. Leaving the flag set after a
         * failed start would make the module believe the hardware is still
         * open, so every later start() would return early and capture could
         * never begin. The stub suite caught exactly this.
         */
        R_PDM_Close(&g_pdm0_ctrl);
        {
            rt_base_t level = rt_hw_interrupt_disable();
            g_pdm_open = 0U;
            g_running = 0U;
            g_stats.running = 0U;
            rt_hw_interrupt_enable(level);
        }
        return -(int)err;
    }

    /*
     * Capture is genuinely live now. Publish the running flag, and do NOT
     * touch g_isr_block here: callbacks may already have advanced it, and
     * resetting it would desynchronise the block sequence.
     */
    {
        rt_base_t level = rt_hw_interrupt_disable();
        g_running = 1U;
        g_stats.running = 1U;
        rt_hw_interrupt_enable(level);
    }
    return 0;
}

void voice_audio_titan_stop(void)
{
    /*
     * Keyed off g_pdm_open, not g_running: between R_PDM_Start() entering and
     * returning, the interrupt is live while g_running is still 0, and a
     * g_running-keyed stop() would silently leave the hardware running.
     */
    if (g_pdm_open == 0U)
    {
        return;
    }

    (void)R_PDM_Stop(&g_pdm0_ctrl);
    (void)R_PDM_Close(&g_pdm0_ctrl);
    {
        rt_base_t level = rt_hw_interrupt_disable();
        g_pdm_open = 0U;
        g_running = 0U;
        g_stats.running = 0U;
        rt_hw_interrupt_enable(level);
    }
}

voice_ring_t *voice_audio_titan_ring(void)
{
    return &g_voice_ring;
}

/*
 * The masked window only snapshots. Everything expensive -- the uint64 to
 * float conversions (libgcc helpers on this part) and the divide/sqrt -- runs
 * after interrupts are back on, operating on a snapshot that was taken
 * atomically. The PDM interrupt and the servo bus therefore never wait on
 * floating point.
 *
 * Correctness note: the four values must be read in ONE masked region. Reading
 * the accumulator and the sample count in separate windows could pair a sum
 * from one moment with a count from another and return a mean that never
 * existed.
 */
void voice_audio_titan_stats(voice_capture_stats_t *out)
{
    uint64_t square_accumulator;
    int64_t sample_accumulator;
    uint32_t level_samples;
    rt_base_t level;

    if (out == NULL)
    {
        return;
    }

    level = rt_hw_interrupt_disable();
    *out = g_stats;
    square_accumulator = g_square_accumulator;
    sample_accumulator = g_sample_accumulator;
    level_samples = g_level_samples;
    rt_hw_interrupt_enable(level);

    out->rms = (level_samples > 0U)
                   ? sqrtf((float)square_accumulator / (float)level_samples)
                   : 0.0f;
    out->dc_offset = (level_samples > 0U)
                         ? ((float)sample_accumulator / (float)level_samples)
                         : 0.0f;
}

float voice_audio_titan_rms(void)
{
    uint64_t square_accumulator;
    uint32_t level_samples;
    rt_base_t level;

    level = rt_hw_interrupt_disable();
    square_accumulator = g_square_accumulator;
    level_samples = g_level_samples;
    rt_hw_interrupt_enable(level);

    return (level_samples > 0U)
               ? sqrtf((float)square_accumulator / (float)level_samples)
               : 0.0f;
}

void voice_audio_titan_reset_stats(void)
{
    rt_base_t level;

    level = rt_hw_interrupt_disable();
    rt_memset(&g_stats, 0, sizeof(g_stats));
    g_stats.running = g_running;
    g_square_accumulator = 0U;
    g_sample_accumulator = 0;
    g_level_samples = 0U;
    /*
     * Clear the ring's counters too. voice_ring_push bumps ring->overrun_count
     * while pdm_callback adds the same loss to g_stats.overrun_count, so
     * resetting only one side would leave two "overrun" figures that never
     * agree again.
     */
    voice_ring_reset_counters(&g_voice_ring);
    rt_hw_interrupt_enable(level);
}

int voice_audio_titan_probe(uint32_t duration_ms, voice_capture_stats_t *out)
{
    uint32_t start;
    int result;

    if (out == NULL)
    {
        return -1;
    }

    result = voice_audio_titan_start();
    if (result != 0)
    {
        return result;
    }

    voice_audio_titan_reset_stats();
    start = rt_tick_get();
    while (((rt_tick_get() - start) * 1000U / RT_TICK_PER_SECOND) < duration_ms)
    {
        rt_thread_mdelay(10);
    }

    voice_audio_titan_stats(out);

    /*
     * Leave capture running: the caller decides when to stop. The measured
     * sample count divided by the elapsed wall time is the only honest way to
     * establish the real sample rate, because the repo has no PDM clock
     * configuration to derive it from.
     */
    return 0;
}
