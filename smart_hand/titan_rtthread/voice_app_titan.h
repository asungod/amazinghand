#ifndef SMART_HAND_VOICE_APP_TITAN_H
#define SMART_HAND_VOICE_APP_TITAN_H

#include "voice_app.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * RT-Thread / FSP glue for the passive-integration voice state machine.
 *
 * voice_app.c holds the policy and is host-testable; this side owns the things
 * a host cannot have -- the real PDM ring, the front end, the classifier, and
 * one RT-Thread thread to drive poll() -- plus the static storage those need.
 *
 * STAGE 1: PASSIVE. The thread classifies and publishes into a read-only status
 * block. It calls no servo interface, writes no UART frame, changes no CRC,
 * ACK, timeout or gate, extends no MaixCAM2 protocol, and cannot start a
 * training session. Turning a keyword into a motion is a later, separately
 * reviewed change; nothing here is a step toward doing it implicitly.
 *
 * COMPILED IN OR OUT
 *
 *   VOICE_APP_ENABLE == 0 (the default)
 *     voice_app_titan.c compiles to a pair of accessors that report
 *     VOICE_STATE_DISABLED. No statics, no thread, no devices: the firmware is
 *     byte-for-byte the firmware it was before this file was added. The default
 *     is off so that merely adding the file to a build cannot change behaviour.
 *
 *   VOICE_APP_ENABLE == 1
 *     voice_app_titan_init() builds the pipeline and starts the thread.
 *     Define it from the build system (-DVOICE_APP_ENABLE=1) or in a
 *     board-specific config header.
 *
 * The switch is deliberately not "is the heap available" or any other
 * indirect condition: bring-up must be an explicit, reviewable decision.
 */

#ifndef VOICE_APP_ENABLE
#define VOICE_APP_ENABLE (0)
#endif

/*
 * 8 KB. The floor is not arbitrary: voice_kws_predict() keeps one
 * VOICE_MODEL_INPUT_COUNT (3920 byte) int8 feature vector on the stack, and the
 * rest of the call chain has to fit alongside it. The compile-time check below
 * refuses anything under 6 KB.
 *
 * The storage itself is a file-scope array, not an rt_thread_create() allocation
 * -- see voice_app_titan.c for why this one thread does not come out of the
 * heap.
 */
#define VOICE_APP_THREAD_STACK (8192U)
#define VOICE_APP_THREAD_STACK_MIN (6144U)

/*
 * Priority 22, i.e. LOWER priority than the existing sh_uart thread at 18 in
 * smart_hand/titan_rtthread/smart_hand_uart.c:750 (RT-Thread schedules the
 * numerically smallest priority first). Audio classification must never
 * preempt the command link: a late keyword is a missed keyword, a late UART
 * byte is a broken protocol.
 */
#define VOICE_APP_THREAD_PRIORITY (22U)
#define VOICE_APP_SH_UART_PRIORITY (18U)

/* Poll period. The analysis window is 1 s and the hop is 10 ms, so 10 ms is
 * the natural granularity; it is also short enough that a 25 ms PDM block
 * never waits long for the ring to be drained. */
#define VOICE_APP_THREAD_TICK (10U)

#define VOICE_APP_THREAD_NAME "v_kws"

#if VOICE_APP_THREAD_STACK < VOICE_APP_THREAD_STACK_MIN
#error "VOICE_APP_THREAD_STACK is below the 6 KB floor"
#endif

#if VOICE_APP_THREAD_PRIORITY <= VOICE_APP_SH_UART_PRIORITY
#error "the voice thread must be LOWER priority than sh_uart (larger number)"
#endif

/*
 * Build the pipeline and start the thread.
 *
 * Returns 0 on success (including "compiled out"), a negated rt_err_t when the
 * thread could not be created or started, or -RT_ERROR when the app could not
 * be configured. Calling it twice is a no-op.
 *
 * Nothing here opens the PDM block: voice_app_poll() does that on the thread,
 * so a dead microphone cannot block the caller.
 */
int voice_app_titan_init(void);

/* Stop the thread and release the app. Safe when never started. */
void voice_app_titan_deinit(void);

/*
 * Consistent snapshot of the read-only view, taken with interrupts masked so
 * the voice thread cannot publish into it halfway through the copy. This is the
 * only supported way to read the module's state from outside.
 */
void voice_app_titan_status(voice_app_status_t *out);

voice_state_t voice_app_titan_state(void);

/* The fingerprint of the voice_model_data linked into this build. */
uint32_t voice_app_titan_model_fingerprint(void);

#ifdef __cplusplus
}
#endif

#endif
