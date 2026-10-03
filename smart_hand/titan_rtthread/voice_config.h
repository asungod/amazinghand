#ifndef SMART_HAND_VOICE_CONFIG_H
#define SMART_HAND_VOICE_CONFIG_H

/*
 * Single source of truth for the Titan on-device keyword-spotting front end.
 *
 * smart_hand/titan_ai/voice/voice_features_ref.py mirrors every value in this
 * file. Changing one side without the other silently breaks the C/Python
 * feature contract, which is exactly what tests/test_voice_features.py checks.
 *
 * The sample rate below is a CONFIGURATION value, not a measurement. It comes
 * from the FSP configurator source, which is the authoritative definition of
 * what the PDM block was set up to produce:
 *
 *   D:/Micu/RTTWorkspace/titan_uart_test/configuration.xml
 *     module.driver.pdm.pdm_output_sampling_freq = 16000
 *     module.driver.pdm.pcm_width               = pcm_width_16bits_0_14
 *     module.driver.pdm.channel                 = 2
 *     module.driver.pdm.clock_div               = pdm_clock_div_2
 *     module.driver.pdm.sinc_filter_mode        = order_4
 *     module.driver.pdm.overwrite_error         = overwrite_error_enabled
 *
 * Whether the silicon actually delivers 16000 Hz has NOT been measured on
 * hardware and must not be claimed until voice_audio reports real sample
 * counts. See docs/TITAN_VOICE_RECON_2026-09-22.md.
 */

#define VOICE_SAMPLE_RATE_HZ (16000U)

/* 25 ms analysis window, 10 ms hop. */
#define VOICE_FRAME_LEN_MS (25U)
#define VOICE_FRAME_HOP_MS (10U)
#define VOICE_FRAME_LEN \
    ((VOICE_SAMPLE_RATE_HZ * VOICE_FRAME_LEN_MS) / 1000U) /* 400 */
#define VOICE_FRAME_HOP \
    ((VOICE_SAMPLE_RATE_HZ * VOICE_FRAME_HOP_MS) / 1000U) /* 160 */

/* 1.0 s of context per inference. */
#define VOICE_WINDOW_MS (1000U)
#define VOICE_WINDOW_SAMPLES \
    ((VOICE_SAMPLE_RATE_HZ * VOICE_WINDOW_MS) / 1000U) /* 16000 */

/* frames = floor((window - frame_len) / hop) + 1 */
#define VOICE_NUM_FRAMES                                        \
    (((VOICE_WINDOW_SAMPLES - VOICE_FRAME_LEN) / VOICE_FRAME_HOP) + 1U) /* 98 */

/* Next power of two >= VOICE_FRAME_LEN. */
#define VOICE_FFT_SIZE (512U)

#define VOICE_MEL_BANDS (40U)
#define VOICE_MEL_LOW_HZ (20.0f)
#define VOICE_MEL_HIGH_HZ (7600.0f)

#define VOICE_FEATURE_COUNT (VOICE_NUM_FRAMES * VOICE_MEL_BANDS) /* 3920 */

/*
 * Floor applied before log() so digital silence yields a finite, reproducible
 * value instead of -inf. Must be identical on both sides of the contract.
 */
#define VOICE_LOG_FLOOR (1.0e-6f)

/*
 * HTK mel conversion. The reference implementation uses the same two
 * constants; do not substitute the Slaney/auditory variant here.
 */
#define VOICE_MEL_HZ_PER_MEL (700.0f)
#define VOICE_MEL_SCALE (1127.0f)

#endif
