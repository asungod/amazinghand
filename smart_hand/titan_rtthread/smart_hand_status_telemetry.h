#ifndef SMART_HAND_STATUS_TELEMETRY_H
#define SMART_HAND_STATUS_TELEMETRY_H

#include "titan_trust_model.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Read-only telemetry frames that Titan sends TO MaixCAM2.
 *
 * This header carries two independent, additive encodings into the one frozen
 * wire container ($TYPE,SEQ,ARGS*CRC16\r\n, 16-bit sequence, 128-byte cap):
 *
 *   STATUS  v1  the existing link/vision/gate snapshot. Its field order,
 *               meanings and values are frozen and are NOT touched by the
 *               AITRUST work below.
 *   AITRUST v1  the TitanTrust-Tiny advisory classification. New in this
 *               round; no ACK, never retried, and never an input to any
 *               decision. Nothing here authorizes motion or starts training.
 *
 * Both are pure functions of a caller-filled struct: no RT-Thread, no FSP, no
 * device, no heap, so the whole encoding is exercisable on the host.
 */

#define SH_STATUS_VERSION 1u
#define SH_STATUS_ARG_COUNT 8u
#define SH_STATUS_FAULT_UNKNOWN 255u

#define SH_STATUS_SUBMIT_UNKNOWN 0u
#define SH_STATUS_SUBMIT_NOT_CONFIGURED 1u
#define SH_STATUS_SUBMIT_BLOCKED 2u
#define SH_STATUS_SUBMIT_SUBMITTED 3u

#define SH_STATUS_FLAG_LINK_ONLINE (1u << 0)
#define SH_STATUS_FLAG_HAVE_VISION (1u << 1)
#define SH_STATUS_FLAG_VISION_STALE (1u << 2)
#define SH_STATUS_FLAG_HAVE_LAST_RX (1u << 3)
#define SH_STATUS_FLAG_GATE_PRESENT (1u << 4)
#define SH_STATUS_FLAG_GATE_ARMED (1u << 5)
#define SH_STATUS_FLAG_GATE_FAULT (1u << 6)
#define SH_STATUS_FLAG_HAVE_ACTIONABLE (1u << 7)

typedef struct
{
    uint8_t link_online;
    uint8_t have_vision;
    uint8_t vision_stale;
    uint8_t have_last_rx;
    uint8_t gate_present;
    uint8_t gate_armed;
    uint8_t gate_fault;
    uint8_t have_actionable;
    uint16_t last_rx_seq;
    uint8_t action;
    uint8_t reason;
    uint8_t pose;
    uint8_t write_path_present;
    uint8_t write_observed_ok;
    uint8_t gate_blocked;
} smart_hand_status_input_t;

uint8_t smart_hand_status_derive_submit(const smart_hand_status_input_t *in);
int smart_hand_status_pack(const smart_hand_status_input_t *in, uint32_t args[SH_STATUS_ARG_COUNT]);

/* ------------------------------------------------------------------------- */
/* AITRUST v1 -- the frozen TitanTrust advisory frame.
 *
 * Wire contract (frozen before implementation, shared with the MaixCAM2 side):
 *
 *   args[0] version        always SH_AITRUST_VERSION
 *   args[1] ready          1 only when the advisory is about CURRENT vision
 *   args[2] class_id       titan_trust_class_t: 0 trusted, 1 uncertain, 2 anomalous
 *   args[3] vision_age_ms  age of the most recent vision payload Titan accepted
 *
 * NO ACK, NOT retried, and at most one frame per SH_AITRUST_PERIOD_MS.
 *
 * WHY ready IS A CONJUNCTION, AND WHY class_id IS STILL A CLASS WHEN IT IS 0
 *
 *   titan_trust_runtime_evaluate() keeps ready == 1 once a window has been
 *   classified, and it is NOT reset when the vision candidate expires -- so on
 *   its own it would report "ready" about vision that has already gone stale,
 *   which is exactly the "no valid vision frame" case that must read as
 *   未就绪. ready therefore means (the model had a full window) AND (the
 *   vision it describes is still current).
 *
 *   When ready == 0 the frame still carries one of the three class values,
 *   because the frozen contract has no fourth value and inventing one would
 *   desynchronise the receiver. Per that contract class_id is then MEANINGLESS
 *   and the page must show 未就绪.
 *
 *   WHAT ACTUALLY GOES ON THE WIRE WHEN ready == 0: the MODEL's own value,
 *   passed through unchanged -- NOT a fail-closed default. The runtime only
 *   seeds ANOMALOUS when it has no window at all; once a window exists its
 *   classification outlives the vision expiring, so a not-ready frame can
 *   legitimately carry TRUSTED (0). A consumer that ignores ready would then
 *   render green about vision Titan no longer has. Which value to authorise in
 *   that case is a PROTOCOL decision, not an implementation one -- the three
 *   options (gate strictly on ready / force a non-green class here / add a
 *   fourth value) are recorded in the delivery report and deliberately NOT
 *   chosen unilaterally in this file.
 *
 *   The clamp below is a separate, narrower thing: it only stops an
 *   out-of-range byte reaching a receiver whose field is 0/1/2, and it fails
 *   toward ANOMALOUS, never toward green.
 */
#define SH_AITRUST_VERSION 1u
#define SH_AITRUST_ARG_COUNT 4u
#define SH_AITRUST_PERIOD_MS 500u

/*
 * vision_age_ms is only ever the age of the newest VISION payload Titan
 * accepted; it is not an end-to-end latency and says nothing about accuracy.
 *
 * It has two sentinels and both are chosen so that neither can be misread as
 * fresh data:
 *
 *   SH_AITRUST_AGE_UNKNOWN      no VISION payload has EVER been accepted, so
 *                               there is no age to report. 0 would mean "just
 *                               arrived" and could render as current, so the
 *                               unknown case saturates upward instead.
 *   SH_AITRUST_AGE_SATURATE_MS  every other age is clamped here, which also
 *                               absorbs a non-monotonic clock: an age that
 *                               wraps to a huge unsigned value clamps to the
 *                               same ceiling as a genuinely old one rather
 *                               than aliasing back to a small, fresher-looking
 *                               number.
 */
#define SH_AITRUST_AGE_UNKNOWN 0xFFFFFFFFu
#define SH_AITRUST_AGE_SATURATE_MS 60000u

typedef struct
{
    uint8_t model_ready;      /* titan_trust_result_t.ready */
    uint8_t classification;   /* titan_trust_result_t.classification */
    uint8_t have_vision;      /* a vision candidate is fresh right now */
    uint8_t have_last_vision; /* a valid VISION payload has ever been accepted */
    uint32_t last_vision_ms;  /* when it arrived; ignored unless have_last_vision */
    uint32_t now_ms;
} smart_hand_aitrust_input_t;

/* Age of the newest accepted vision payload, with the policy above applied. */
uint32_t smart_hand_aitrust_vision_age_ms(const smart_hand_aitrust_input_t *in);

/* Fills exactly SH_AITRUST_ARG_COUNT args. Returns 0, or -1 on a NULL pointer. */
int smart_hand_aitrust_pack(const smart_hand_aitrust_input_t *in,
                            uint32_t args[SH_AITRUST_ARG_COUNT]);

/*
 * Send-side pacing, kept here rather than in the driver so the rate limit and
 * the failure policy are host-testable.
 *
 * The bookmark is written by note_attempt(), i.e. on EVERY attempt, successful
 * or not. That is what makes the 500 ms floor a floor on attempts: a failed or
 * refused write must not become a retry loop against the same polled TX that
 * carries ACK, STATUS and the motion link. A dropped telemetry frame is
 * acceptable; delaying an ACK is not -- and bounding that delay is exactly what
 * the floor and the no-retry rule are for. It does not make the write free: the
 * frame still occupies the wire, so the ACK latency it adds is a target
 * measurement, not a guarantee this module can make.
 *
 * seq advances only on a frame that actually went out, so every AITRUST
 * sequence the receiver sees is contiguous and a gap really is a lost frame.
 */
typedef struct
{
    uint32_t last_attempt_ms;
    uint16_t seq;
    uint32_t sent_frames;
    uint32_t failed_frames;
    uint8_t have_attempt;
} smart_hand_aitrust_link_t;

void smart_hand_aitrust_link_init(smart_hand_aitrust_link_t *link);

/* 1 when SH_AITRUST_PERIOD_MS has elapsed since the last attempt. */
uint8_t smart_hand_aitrust_due(const smart_hand_aitrust_link_t *link,
                               uint32_t now_ms);

/* Records an attempt and starts the next period. Call before writing. */
void smart_hand_aitrust_note_attempt(smart_hand_aitrust_link_t *link,
                                     uint32_t now_ms);

/* A whole frame reached the UART: advances seq and counts it. */
void smart_hand_aitrust_note_sent(smart_hand_aitrust_link_t *link);

/* The write failed or the frame could not be built: counted, never retried. */
void smart_hand_aitrust_note_failed(smart_hand_aitrust_link_t *link);

#ifdef __cplusplus
}
#endif

#endif
