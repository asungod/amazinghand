#ifndef SMART_HAND_TESTS_STUBS_HAL_DATA_H
#define SMART_HAND_TESTS_STUBS_HAL_DATA_H

/*
 * Host stub for the FSP-generated ra_gen/hal_data.h, plus the control surface
 * the PDM tests drive it with.
 *
 * Two things live here and they have different rules.
 *
 * 1. The driver surface. Types, constants and prototypes are copied from the
 *    real FSP headers so the module under test compiles unchanged:
 *
 *      ra/fsp/inc/api/r_pdm_api.h      pdm_event_t, pdm_error_t,
 *                                      pdm_callback_args_t
 *      ra/fsp/inc/instances/r_pdm.h    PDM_INTERRUPT_THRESHOLD_16 == 4
 *      ra_gen/hal_data.h               PDM2_FILTER_SETTLING_TIME_US, g_pdm0_*
 *
 *    R_PDM_Read is deliberately NOT declared. r_pdm.c:445 makes it return
 *    FSP_ERR_UNSUPPORTED, so polling is impossible and the module must never
 *    call it; leaving the symbol out turns "it never calls R_PDM_Read" into a
 *    link error rather than a comment, which is the intent.
 *
 * 2. The control surface (the pdm_stub_* symbols). This is test scaffolding,
 *    not a model of the driver: the implementations live in
 *    tests/test_voice_audio_titan_c.c.
 *
 * What the stub models about the real driver, and why each part is load
 * bearing:
 *
 *   - R_PDM_Start runs the SAME validation as ra/fsp/src/r_pdm/r_pdm.c:257-273
 *     (alignment, granularity multiple of 1<<interrupt_threshold, buffer size a
 *     multiple of 4, entry count a multiple of the granularity). Without that
 *     check a stub would accept any granularity and the historical 1000-vs-16
 *     regression -- R_PDM_Start returning an error so capture never starts --
 *     would pass every test in this file.
 *
 *   - The words the driver writes into the caller's buffer are modelled as a
 *     function of buffer POSITION: word i holds i / granularity. Since the
 *     module's ISR picks a position from its own cursor and copies the low 16
 *     bits of each word, the samples that land in the ring spell out which
 *     position the ISR read. A cursor error therefore shows up as a duplicate,
 *     a skip, or a block whose 800 samples disagree with each other.
 *
 *   - Data interrupts fire while R_PDM_Start is still running, which is what
 *     the real driver does (r_pdm.c enables the interrupt before returning).
 *     pdm_stub_pre_callbacks controls how many, and
 *     pdm_stub_pre_callbacks_delivered proves afterwards that they were really
 *     delivered -- a race test that never entered the race is worthless.
 */

#include <stddef.h>
#include <stdint.h>

#include "voice_config.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------------- */
/* FSP error codes. Values are the stub's own; only "== FSP_SUCCESS" and the
 * non-zero-ness of the rest are relied on. The module returns -(int)err, so
 * every failure code must stay non-zero and positive.
 */
typedef int32_t fsp_err_t;

#define FSP_SUCCESS               (0)
#define FSP_ERR_ASSERTION         (1)
#define FSP_ERR_INVALID_ARGUMENT  (2)
#define FSP_ERR_NOT_OPEN          (3)
#define FSP_ERR_ALREADY_OPEN      (4)
#define FSP_ERR_INVALID_SIZE      (5)
#define FSP_ERR_INVALID_ALIGNMENT (6)

/* ------------------------------------------------------------------------- */
/* PDM driver surface, copied from ra/fsp/inc/api/r_pdm_api.h. */

typedef enum e_pdm_event
{
    PDM_EVENT_IDLE = 0,
    PDM_EVENT_DATA,
    PDM_EVENT_SOUND_DETECTION,
    PDM_EVENT_ERROR
} pdm_event_t;

typedef enum e_pdm_error
{
    PDM_ERROR_NONE              = 0,
    PDM_ERROR_SHORT_CIRCUIT     = (1UL << 0),
    PDM_ERROR_OVERVOLTAGE_LOWER = (1UL << 1),
    PDM_ERROR_OVERVOLTAGE_UPPER = (1UL << 2),
    PDM_ERROR_BUFFER_OVERWRITE  = (1UL << 11)
} pdm_error_t;

typedef struct st_pdm_callback_args
{
    void       *p_context;
    pdm_event_t event;
    pdm_error_t error;
} pdm_callback_args_t;

/* The stub has no registers; the control block only has to exist. */
typedef struct
{
    uint32_t reserved;
} pdm_ctrl_t;

typedef struct
{
    uint32_t reserved;
} pdm_cfg_t;

extern pdm_ctrl_t g_pdm0_ctrl;
extern pdm_cfg_t  g_pdm0_cfg;

/*
 * 1U << PDM_INTERRUPT_THRESHOLD_16 == 16 FIFO entries per interrupt, which is
 * the value R_PDM_Start divides the callback granularity by. Defined as 4 in
 * ra/fsp/inc/instances/r_pdm.h; a stub that got this wrong would wave through
 * exactly the granularity bug this file exists to catch.
 */
#define PDM_INTERRUPT_THRESHOLD_16 (4U)

/* ra_gen/hal_data.h:82. */
#define PDM2_FILTER_SETTLING_TIME_US (1662U)

fsp_err_t R_PDM_Open(pdm_ctrl_t *p_ctrl, pdm_cfg_t const *p_cfg);

fsp_err_t R_PDM_Start(pdm_ctrl_t *p_ctrl,
                      void       *p_buffer,
                      size_t      buffer_size,
                      uint32_t    number_of_data_to_callback);

fsp_err_t R_PDM_Stop(pdm_ctrl_t *p_ctrl);

fsp_err_t R_PDM_Close(pdm_ctrl_t *p_ctrl);

/* Defined by the module under test (voice_audio_titan.c). */
void pdm_callback(pdm_callback_args_t *p_args);

/* ------------------------------------------------------------------------- */
/* Test control surface. Implemented in tests/test_voice_audio_titan_c.c. */

/* Number of PDM_EVENT_DATA callbacks R_PDM_Start delivers before returning. */
extern uint32_t pdm_stub_pre_callbacks;

/* How many of those actually ran. If a race test leaves this at zero it never
 * entered the window it claims to cover. */
extern uint32_t pdm_stub_pre_callbacks_delivered;

/* Non-zero: make R_PDM_Start fail with this code, before it starts anything. */
extern fsp_err_t pdm_stub_start_error;

/* Non-zero (default): fill the caller's buffer with position markers on start. */
extern uint32_t pdm_stub_autofill_markers;

/* The buffer R_PDM_Start was handed, and its length in 32-bit entries. */
extern int32_t *pdm_stub_buffer;
extern uint32_t pdm_stub_entries;

/* Observations of the last accepted R_PDM_Start. */
extern uint32_t pdm_stub_last_buffer_size;
extern uint32_t pdm_stub_last_granularity;

/* Call accounting. */
extern uint32_t pdm_stub_open_calls;
extern uint32_t pdm_stub_start_calls;
extern uint32_t pdm_stub_stop_calls;
extern uint32_t pdm_stub_close_calls;
extern uint32_t pdm_stub_is_open;
extern uint32_t pdm_stub_is_started;

/* Callbacks the test asked for while the block was not started. The real
 * driver disables the data interrupt in R_PDM_Stop, so the stub refuses them
 * too instead of quietly delivering audio from a stopped microphone. */
extern uint32_t pdm_stub_refused_callbacks;

/* R_BSP_SoftwareDelay observations. */
extern uint32_t pdm_stub_bsp_delay_calls;
extern uint32_t pdm_stub_bsp_delay_value;
extern uint32_t pdm_stub_bsp_delay_units;

/* Called right after each pdm_callback() the stub invokes. Lets a test record
 * what the module looked like from inside the callback. May be NULL. */
extern void (*pdm_stub_callback_hook)(void);

/* Clear per-test state. The last_* observations and the buffer pointer are
 * deliberately kept: they belong to the previous start, which the next start
 * overwrites anyway, and the drain helper needs the granularity to size its
 * reads. */
void pdm_stub_reset(void);

/* Rewrite the whole saved buffer as position markers (word i == i / granularity)
 * without starting anything. No-op when no buffer has been seen yet. */
void pdm_stub_fill_markers(void);

/* Deliver `blocks` PDM_EVENT_DATA callbacks. No-op (counted in
 * pdm_stub_refused_callbacks) while the block is not started. */
void pdm_stub_fire_data(uint32_t blocks);

/* Deliver one non-data event. */
void pdm_stub_fire_event(pdm_event_t event, pdm_error_t error);

/* Interrupt-mask nesting depth. Must be zero whenever the module is not inside
 * one of its own critical sections. */
uint32_t pdm_stub_irq_depth(void);

#ifdef __cplusplus
}
#endif

#endif
