#include <rtdevice.h>
#include <rtthread.h>

#include "grip_policy.h"
#include "smart_hand_protocol.h"
#include "servo_bus_readonly_rt.h"
#include "smart_hand_sequence_guard.h"
#include "smart_hand_status_telemetry.h"
#include "smart_hand_vision_state.h"
#include "titan_trust_runtime.h"

#ifndef SMART_HAND_UART_NAME
#define SMART_HAND_UART_NAME "uart2"
#endif

#define SMART_HAND_RX_THREAD_STACK 2048
#define SMART_HAND_LINK_TIMEOUT_MS 1500
/* Communication freshness only — not a mechanical parameter. */
#define SMART_HAND_VISION_STALE_MS 750U
#define SMART_HAND_STATUS_PERIOD_MS 250U
#define SMART_HAND_CLASS_ID_MAX 65535U
#define SMART_HAND_COORDINATE_MAX 65535U
#define SMART_HAND_MIN_CONFIDENCE GRIP_POLICY_DEFAULT_MIN_CONFIDENCE
#define SMART_HAND_TRAIN_MODE_REHAB 1U
#define SMART_HAND_TRAINSTAT_VERSION 1U
#define SMART_HAND_TRAINSTAT_ARG_COUNT 5U
#define SMART_HAND_SIGN_VERSION 1U
#define SMART_HAND_SIGN_ARG_COUNT 3U
#define SMART_HAND_SIGNSTAT_ARG_COUNT 7U
#define SMART_HAND_ACK_INVALID_PAYLOAD 1U
#define SMART_HAND_ACK_UNSUPPORTED_TYPE 2U
#define SMART_HAND_ACK_BLOCKED 3U
#define SMART_HAND_ACK_BUSY 4U

typedef struct
{
    uint32_t valid_frames;
    uint32_t invalid_frames;
    uint32_t invalid_payloads;
    uint32_t sequence_gaps;
    uint32_t duplicate_frames;
    uint32_t old_frames;
    uint32_t tx_failures;
    uint32_t offline_events;
    uint32_t policy_rejected;
    uint32_t pose_unavailable;
    uint32_t vision_expired;
    uint32_t train_accepted;
    uint32_t train_blocked;
    uint32_t train_busy;
    uint32_t sign_accepted;
    uint32_t sign_blocked;
    uint32_t sign_busy;
} smart_hand_stats_t;

static rt_device_t g_uart;
static struct rt_semaphore g_rx_sem;
static rt_tick_t g_last_valid_tick;
static rt_tick_t g_last_status_tick;
static rt_bool_t g_link_online;
static uint8_t g_vision_stale;
static uint16_t g_status_seq;
static uint16_t g_train_status_seq;
static uint16_t g_train_request_seq;
static uint8_t g_train_report_active;
static uint8_t g_train_last_state;
static uint32_t g_train_last_result;
static uint32_t g_train_last_completed_count;
static uint16_t g_sign_status_seq;
static uint16_t g_sign_request_seq;
static uint8_t g_sign_report_active;
static uint8_t g_sign_last_state;
static uint32_t g_sign_last_result;
static uint32_t g_sign_last_sequence_id;
static uint32_t g_sign_last_completed_count;
static uint8_t g_sign_last_action;
static smart_hand_stats_t g_stats;
static smart_hand_vision_state_t g_vision_state;
static smart_hand_sequence_guard_t g_sequence_guard;
static titan_trust_runtime_t g_titan_trust_runtime;
static titan_trust_result_t g_titan_trust_result;
static uint32_t g_titan_trust_last_gap_count;
static uint8_t g_titan_trust_have_report;
static smart_hand_aitrust_link_t g_aitrust_link;
/*
 * When a VISION payload was last really accepted, and whether one ever was.
 * Kept separately from g_vision_state because that state clears its own
 * last_vision_ms the moment the candidate expires, and the AITRUST age has to
 * keep counting from the last real payload rather than restart from zero.
 */
static uint8_t g_vision_seen;
static uint32_t g_vision_last_seen_ms;

static uint32_t now_ms(void)
{
    return (uint32_t)(((uint64_t)rt_tick_get() * 1000ULL) /
                      (uint64_t)RT_TICK_PER_SECOND);
}

static const char *pose_result_name(eight_servo_pose_result_t result)
{
    switch (result)
    {
    case EIGHT_SERVO_POSE_OK:
        return "OK";
    case EIGHT_SERVO_POSE_NO_ACTION:
        return "NO_ACTION";
    case EIGHT_SERVO_POSE_NOT_CONFIGURED:
        return "NOT_CONFIGURED";
    case EIGHT_SERVO_POSE_INVALID_PROFILE:
        return "INVALID_PROFILE";
    default:
        return "UNKNOWN";
    }
}

static rt_err_t uart_rx_indicate(rt_device_t device, rt_size_t size)
{
    (void)device;
    (void)size;
    rt_sem_release(&g_rx_sem);
    return RT_EOK;
}

static int send_message(const char *type,
                        uint16_t sequence,
                        const uint32_t *args,
                        uint8_t arg_count)
{
    char frame[SHP_MAX_FRAME_SIZE];
    int length = shp_encode(frame, sizeof(frame), type, sequence, args, arg_count);
    rt_size_t written;

    if (length <= 0)
    {
        ++g_stats.tx_failures;
        return -RT_ERROR;
    }
    written = rt_device_write(g_uart, 0, frame, (rt_size_t)length);
    if (written != (rt_size_t)length)
    {
        ++g_stats.tx_failures;
        return -RT_ERROR;
    }
    return RT_EOK;
}

static void send_ack(uint16_t sequence, uint32_t status)
{
    (void)send_message("ACK", sequence, &status, 1);
}

static void send_status(void)
{
    uint32_t args[SH_STATUS_ARG_COUNT];
    smart_hand_status_input_t input;

    rt_memset(&input, 0, sizeof(input));
    input.link_online = g_link_online ? 1u : 0u;
    input.have_vision = g_vision_state.have_vision;
    input.vision_stale = g_vision_stale;
    input.have_last_rx = g_sequence_guard.have_last;
    input.last_rx_seq = g_sequence_guard.last_accepted;
    input.action = (uint8_t)g_vision_state.last_decision.action;
    input.reason = (uint8_t)g_vision_state.last_decision.reason;
    input.pose = (uint8_t)g_vision_state.last_pose_result;
    input.have_actionable = g_vision_state.have_actionable_target;
    input.gate_present = servo_bus_safety_gate_present() ? 1u : 0u;
    input.gate_armed = servo_bus_safety_gate_armed() ? 1u : 0u;
    input.gate_fault =
        servo_bus_safety_gate_fault_latched() ? 1u : 0u;
    /* Calibration is live, but visual intent still has no production writer. */
    input.write_path_present = 0u;

    if (smart_hand_status_pack(&input, args) != 0)
    {
        return;
    }
    if (send_message("STATUS", g_status_seq, args, SH_STATUS_ARG_COUNT) == RT_EOK)
    {
        g_status_seq = (uint16_t)(g_status_seq + 1u);
        g_last_status_tick = rt_tick_get();
    }
}

/* Defined below, next to the runtime it drives; declared here because
 * send_aitrust() re-evaluates immediately before it packs a frame. */
static void update_titan_trust(uint32_t current_ms, uint8_t force_log);

/*
 * AITRUST v1, Titan -> MaixCAM2, read-only advisory telemetry.
 *
 * Encoded by smart_hand_aitrust_pack() (host-tested); this function only
 * supplies the inputs and drives the write.
 *
 * WHAT IS GUARANTEED: no ACK is expected, nothing is retried, there is no queue
 * behind it, and at most one frame is attempted per SH_AITRUST_PERIOD_MS --
 * booked on the ATTEMPT, so a failing write cannot turn into a retry loop. A
 * refused or failed write costs one telemetry frame and nothing else.
 *
 * WHAT IS NOT GUARANTEED, AND MUST BE MEASURED: this runs on the sh_uart thread
 * and writes through the SAME polled TX as ACK and STATUS (config.tx_bufsz = 0),
 * so the ~38-byte frame occupies the wire for roughly 3.3 ms at 115200. That is
 * time an ACK or a STATUS cannot use, and it lands on the thread that also
 * parses inbound frames. It is bounded and it is not a retry storm, but it is
 * NOT zero: the resulting ACK latency is a target-measurement item, not
 * something this code can assert.
 *
 * The classification is produced by update_titan_trust() and is only READ here
 * -- nothing on this path can authorize motion, start a training session or
 * reach the safety gate.
 */
static void send_aitrust(void)
{
    smart_hand_aitrust_input_t input;
    uint32_t args[SH_AITRUST_ARG_COUNT];
    uint32_t current_ms = now_ms();

    if (!smart_hand_aitrust_due(&g_aitrust_link, current_ms))
    {
        return;
    }

    /*
     * Book the attempt before writing so the 500 ms floor holds on attempts,
     * not just on successes. A failed write that left the bookmark alone would
     * be retried on the next 50 ms tick, which is the retry loop this design
     * exists to avoid.
     */
    smart_hand_aitrust_note_attempt(&g_aitrust_link, current_ms);

    /* Re-evaluate against this instant: the age feature keeps growing while
     * vision is quiet, so a result cached from the last VISION frame would
     * report a staler world than the one being described. */
    update_titan_trust(current_ms, 0u);

    rt_memset(&input, 0, sizeof(input));
    input.model_ready = g_titan_trust_result.ready;
    input.classification = (uint8_t)g_titan_trust_result.classification;
    input.have_vision = g_vision_state.have_vision;
    input.have_last_vision = g_vision_seen;
    input.last_vision_ms = g_vision_last_seen_ms;
    input.now_ms = current_ms;

    if (smart_hand_aitrust_pack(&input, args) != 0)
    {
        smart_hand_aitrust_note_failed(&g_aitrust_link);
        return;
    }

    if (send_message("AITRUST", g_aitrust_link.seq, args,
                     SH_AITRUST_ARG_COUNT) == RT_EOK)
    {
        smart_hand_aitrust_note_sent(&g_aitrust_link);
        return;
    }
    smart_hand_aitrust_note_failed(&g_aitrust_link);
}

static void send_train_status(uint8_t force)
{
    uint32_t args[SMART_HAND_TRAINSTAT_ARG_COUNT];
    servo_rehab_status_t status;

    if (!g_train_report_active ||
        !servo_bus_rehab_demo_get_status(&status))
    {
        return;
    }
    if (!force && g_train_last_state == (uint8_t)status.state &&
        g_train_last_result == status.result_code &&
        g_train_last_completed_count == status.completed_count)
    {
        return;
    }

    args[0] = SMART_HAND_TRAINSTAT_VERSION;
    args[1] = g_train_request_seq;
    args[2] = (uint32_t)status.state;
    args[3] = status.result_code;
    args[4] = status.completed_count;
    if (send_message("TRAINSTAT", g_train_status_seq, args,
                     SMART_HAND_TRAINSTAT_ARG_COUNT) != RT_EOK)
    {
        return;
    }
    g_train_status_seq = (uint16_t)(g_train_status_seq + 1u);
    g_train_last_state = (uint8_t)status.state;
    g_train_last_result = status.result_code;
    g_train_last_completed_count = status.completed_count;
    if (status.state == SERVO_REHAB_STATE_SUCCEEDED ||
        status.state == SERVO_REHAB_STATE_FAILED)
    {
        g_train_report_active = 0u;
    }
}

/*
 * SIGNSTAT is progress telemetry, not an acceptance ACK.  The ACK emitted
 * for SIGN=START/CANCEL/HOME only says that the fixed request was accepted
 * into the Titan mailbox.  SIGNSTAT then reports the servo-owned state until
 * the bounded sequence reaches a terminal state.
 *
 * args: version, request_uart_seq, sequence_id, state, result,
 *       completed_count, last_action (all unsigned decimal fields).
 */
static void send_sign_status(uint8_t force)
{
    uint32_t args[SMART_HAND_SIGNSTAT_ARG_COUNT];
    servo_sign_status_t status;

    if (!g_sign_report_active || !servo_bus_sign_demo_get_status(&status))
    {
        return;
    }
    if (!force && g_sign_last_state == (uint8_t)status.state &&
        g_sign_last_result == (uint32_t)status.result_code &&
        g_sign_last_sequence_id == status.sequence_id &&
        g_sign_last_completed_count == status.completed_count &&
        g_sign_last_action == (uint8_t)status.last_action)
    {
        return;
    }

    args[0] = SMART_HAND_SIGN_VERSION;
    args[1] = g_sign_request_seq;
    args[2] = status.sequence_id;
    args[3] = (uint32_t)status.state;
    args[4] = (uint32_t)status.result_code;
    args[5] = status.completed_count;
    args[6] = (uint32_t)status.last_action;
    if (send_message("SIGNSTAT", g_sign_status_seq, args,
                     SMART_HAND_SIGNSTAT_ARG_COUNT) != RT_EOK)
    {
        return;
    }
    g_sign_status_seq = (uint16_t)(g_sign_status_seq + 1u);
    g_sign_last_state = (uint8_t)status.state;
    g_sign_last_result = (uint32_t)status.result_code;
    g_sign_last_sequence_id = status.sequence_id;
    g_sign_last_completed_count = status.completed_count;
    g_sign_last_action = (uint8_t)status.last_action;
    if (status.state == SERVO_SIGN_STATE_COMPLETED ||
        status.state == SERVO_SIGN_STATE_CANCELLED ||
        status.state == SERVO_SIGN_STATE_FAILED)
    {
        g_sign_report_active = 0u;
    }
}

static void mark_link_alive(void)
{
    g_last_valid_tick = rt_tick_get();
    ++g_stats.valid_frames;
    if (!g_link_online)
    {
        g_link_online = RT_TRUE;
        rt_kprintf("smart_hand: vision link ONLINE\n");
    }
}

static rt_bool_t vision_payload_valid(const shp_message_t *message)
{
    if (message->arg_count != 6U) return RT_FALSE;
    if (message->args[0] > SMART_HAND_CLASS_ID_MAX) return RT_FALSE;
    if (message->args[1] > SMART_HAND_COORDINATE_MAX) return RT_FALSE;
    if (message->args[2] > SMART_HAND_COORDINATE_MAX) return RT_FALSE;
    if (message->args[3] == 0U || message->args[3] > SMART_HAND_COORDINATE_MAX) return RT_FALSE;
    if (message->args[4] == 0U || message->args[4] > SMART_HAND_COORDINATE_MAX) return RT_FALSE;
    if (message->args[5] > 100U) return RT_FALSE;
    return RT_TRUE;
}

static rt_bool_t sign_payload_valid(const shp_message_t *message)
{
    if (message->arg_count != SMART_HAND_SIGN_ARG_COUNT ||
        message->args[0] != SMART_HAND_SIGN_VERSION ||
        (message->args[1] != SERVO_SIGN_ACTION_START &&
         message->args[1] != SERVO_SIGN_ACTION_CANCEL &&
         message->args[1] != SERVO_SIGN_ACTION_HOME) ||
        (message->args[2] != SERVO_SIGN_SEQUENCE_OPEN_PALM &&
         message->args[2] != SERVO_SIGN_SEQUENCE_FIST &&
         message->args[2] != SERVO_SIGN_SEQUENCE_V_SIGN &&
         message->args[2] != SERVO_SIGN_SEQUENCE_POINT &&
         message->args[2] != SERVO_SIGN_SEQUENCE_THUMBS_UP &&
         message->args[2] != SERVO_SIGN_SEQUENCE_L_SHAPE &&
         message->args[2] != SERVO_SIGN_SEQUENCE_OK_PINCH &&
         message->args[2] != SERVO_SIGN_SEQUENCE_HELLO_WORD &&
         message->args[2] != SERVO_SIGN_SEQUENCE_THANKS_WORD &&
         message->args[2] != SERVO_SIGN_SEQUENCE_HELP_SIGNAL &&
         message->args[2] != SERVO_SIGN_SEQUENCE_NO_WORD &&
         message->args[2] != SERVO_SIGN_SEQUENCE_ATTENTION_WORD &&
         message->args[2] != SERVO_SIGN_SEQUENCE_LIKE_WORD))
    {
        return RT_FALSE;
    }
    return RT_TRUE;
}

static void note_policy_and_pose_stats(void)
{
    if (g_vision_state.last_decision.reason != GRIP_REASON_ACCEPTED ||
        g_vision_state.last_decision.action == GRIP_ACTION_NONE)
    {
        ++g_stats.policy_rejected;
    }
    else if (g_vision_state.last_pose_result != EIGHT_SERVO_POSE_OK)
    {
        ++g_stats.pose_unavailable;
    }
}

static void update_titan_trust(uint32_t current_ms, uint8_t force_log)
{
    titan_trust_class_t previous = g_titan_trust_result.classification;
    uint8_t previous_ready = g_titan_trust_result.ready;

    titan_trust_runtime_evaluate(&g_titan_trust_runtime,
                                 current_ms,
                                 &g_titan_trust_result);
    if (force_log || !g_titan_trust_have_report ||
        previous != g_titan_trust_result.classification ||
        previous_ready != g_titan_trust_result.ready)
    {
        rt_kprintf("TITAN_AI advisory=1 ready=%u state=%s controls_servo=0\n",
                   (unsigned)g_titan_trust_result.ready,
                   titan_trust_class_name(
                       g_titan_trust_result.classification));
        g_titan_trust_have_report = 1u;
    }
}

/*
 * Returns 1 if the frame may refresh link/vision business state.
 * DUPLICATE/OLD: ACK=0 but do not refresh link, vision, or freshness.
 */
static int accept_sequence_for_business(uint16_t sequence)
{
    smart_hand_sequence_result_t seq_result =
        smart_hand_sequence_guard_note(&g_sequence_guard, sequence);

    switch (seq_result)
    {
    case SMART_HAND_SEQ_FIRST:
    case SMART_HAND_SEQ_IN_ORDER:
        return 1;
    case SMART_HAND_SEQ_FORWARD_GAP:
        ++g_stats.sequence_gaps;
        return 1;
    case SMART_HAND_SEQ_DUPLICATE:
        ++g_stats.duplicate_frames;
        titan_trust_runtime_note_duplicate_or_old(&g_titan_trust_runtime);
        rt_kprintf("smart_hand: ignored_duplicate seq=%u\n", (unsigned)sequence);
        return 0;
    case SMART_HAND_SEQ_OLD:
    default:
        ++g_stats.old_frames;
        titan_trust_runtime_note_duplicate_or_old(&g_titan_trust_runtime);
        rt_kprintf("smart_hand: ignored_old seq=%u\n", (unsigned)sequence);
        return 0;
    }
}

static void handle_message(const shp_message_t *message)
{
    uint32_t status = 0;

    switch (message->type)
    {
    case SHP_TYPE_PING:
        if (message->arg_count != 0U)
        {
            status = 1;
            ++g_stats.invalid_payloads;
            send_ack(message->sequence, status);
            send_status();
            break;
        }
        if (!accept_sequence_for_business(message->sequence))
        {
            /* Idempotent ignore: ACK 0, no link/vision refresh. */
            send_ack(message->sequence, 0);
            send_status();
            break;
        }
        mark_link_alive();
        send_ack(message->sequence, 0);
        send_status();
        break;

    case SHP_TYPE_VISION:
        if (!vision_payload_valid(message))
        {
            /*
             * Protocol type is VISION but business payload illegal:
             * clear prior candidate immediately; do not refresh link/seq/vision time.
             */
            smart_hand_vision_state_invalidate(&g_vision_state);
            status = 1;
            ++g_stats.invalid_payloads;
            titan_trust_runtime_note_invalid(&g_titan_trust_runtime);
            rt_kprintf("smart_hand: invalid VISION payload; vision candidate cleared\n");
            send_ack(message->sequence, status);
            send_status();
            break;
        }
        if (!accept_sequence_for_business(message->sequence))
        {
            send_ack(message->sequence, 0);
            send_status();
            break;
        }
        {
            grip_vision_payload_t payload;

            mark_link_alive();
            g_vision_stale = 0u;
            payload.class_id = message->args[0];
            payload.center_x = message->args[1];
            payload.center_y = message->args[2];
            payload.width = message->args[3];
            payload.height = message->args[4];
            payload.confidence = message->args[5];

            smart_hand_vision_state_note_vision(&g_vision_state,
                                                &payload,
                                                (uint8_t)SMART_HAND_MIN_CONFIDENCE,
                                                now_ms());
            /* Remember the last payload that really arrived. The vision state
             * drops its own timestamp when the candidate expires, so AITRUST
             * has to keep its own copy or the reported age would restart. */
            g_vision_seen = 1u;
            g_vision_last_seen_ms = now_ms();
            note_policy_and_pose_stats();
            titan_trust_runtime_note_valid(
                &g_titan_trust_runtime,
                &payload,
                (uint16_t)(g_stats.sequence_gaps -
                           g_titan_trust_last_gap_count),
                now_ms());
            g_titan_trust_last_gap_count = g_stats.sequence_gaps;
            update_titan_trust(now_ms(), 0u);

            rt_kprintf(
                "VISION seq=%u class=%lu conf=%lu action=%s reason=%s pose=%s actionable=%u\n",
                (unsigned)message->sequence,
                (unsigned long)payload.class_id,
                (unsigned long)payload.confidence,
                grip_policy_action_name(g_vision_state.last_decision.action),
                grip_policy_reason_name(g_vision_state.last_decision.reason),
                pose_result_name(g_vision_state.last_pose_result),
                (unsigned)g_vision_state.have_actionable_target);
            send_ack(message->sequence, 0);
            send_status();
        }
        break;

    case SHP_TYPE_SIGN:
        if (!sign_payload_valid(message))
        {
            ++g_stats.invalid_payloads;
            send_ack(message->sequence, SMART_HAND_ACK_INVALID_PAYLOAD);
            send_status();
            break;
        }
        if (!accept_sequence_for_business(message->sequence))
        {
            send_ack(message->sequence, 0u);
            send_status();
            break;
        }
        {
            servo_sign_action_t action =
                (servo_sign_action_t)message->args[1];
            servo_sign_request_result_t request_result;
            rt_bool_t link_was_online = g_link_online;

            /* START and HOME must be preceded by a live transport heartbeat.
             * The SIGN frame itself is not allowed to bootstrap that gate;
             * CANCEL remains idempotent and is accepted while offline. */
            if ((action == SERVO_SIGN_ACTION_START ||
                 action == SERVO_SIGN_ACTION_HOME) && !link_was_online)
            {
                ++g_stats.sign_blocked;
                send_ack(message->sequence, SMART_HAND_ACK_BLOCKED);
                send_status();
                break;
            }

            mark_link_alive();
            request_result = servo_bus_sign_demo_request(
                action, message->args[2]);
            if (request_result == SERVO_SIGN_REQUEST_ACCEPTED)
            {
                ++g_stats.sign_accepted;
                g_sign_request_seq = message->sequence;
                g_sign_report_active = 1u;
                g_sign_last_state = 0xffu;
                g_sign_last_result = 0xffffffffu;
                g_sign_last_sequence_id = 0xffffffffu;
                g_sign_last_completed_count = 0xffffffffu;
                g_sign_last_action = 0xffu;
                /* ACK=0 means queued only; completion is SIGNSTAT. */
                send_ack(message->sequence, 0u);
                send_sign_status(1u);
            }
            else if (request_result == SERVO_SIGN_REQUEST_BUSY)
            {
                ++g_stats.sign_busy;
                send_ack(message->sequence, SMART_HAND_ACK_BUSY);
            }
            else
            {
                ++g_stats.sign_blocked;
                send_ack(message->sequence, SMART_HAND_ACK_BLOCKED);
            }
            send_status();
        }
        break;

    case SHP_TYPE_TRAIN:
        if (message->arg_count != 1U ||
            message->args[0] != SMART_HAND_TRAIN_MODE_REHAB)
        {
            ++g_stats.invalid_payloads;
            send_ack(message->sequence, SMART_HAND_ACK_INVALID_PAYLOAD);
            send_status();
            break;
        }
        if (!accept_sequence_for_business(message->sequence))
        {
            send_ack(message->sequence, 0u);
            send_status();
            break;
        }
        mark_link_alive();
        if (!g_link_online || g_vision_stale ||
            !g_vision_state.have_vision ||
            !g_vision_state.have_actionable_target ||
            g_vision_state.last_pose_result != EIGHT_SERVO_POSE_OK ||
            !servo_bus_safety_gate_present() ||
            servo_bus_safety_gate_fault_latched())
        {
            ++g_stats.train_blocked;
            rt_kprintf("TRAIN blocked: fresh actionable target/servo gate unavailable\n");
            send_ack(message->sequence, SMART_HAND_ACK_BLOCKED);
            send_status();
            break;
        }
        {
            servo_rehab_request_result_t request_result =
                servo_bus_rehab_demo_request();
            if (request_result == SERVO_REHAB_REQUEST_ACCEPTED)
            {
                ++g_stats.train_accepted;
                g_train_request_seq = message->sequence;
                g_train_report_active = 1u;
                g_train_last_state = 0xffu;
                rt_kprintf("TRAIN accepted: rehabilitation repetition queued\n");
                send_ack(message->sequence, 0u);
                send_train_status(1u);
            }
            else if (request_result == SERVO_REHAB_REQUEST_BUSY)
            {
                ++g_stats.train_busy;
                send_ack(message->sequence, SMART_HAND_ACK_BUSY);
            }
            else
            {
                ++g_stats.train_blocked;
                send_ack(message->sequence, SMART_HAND_ACK_BLOCKED);
            }
            send_status();
        }
        break;

    default:
        send_ack(message->sequence, SMART_HAND_ACK_UNSUPPORTED_TYPE);
        send_status();
        break;
    }
}

static void check_vision_expiry(void)
{
    uint8_t had_vision = g_vision_state.have_vision;

    smart_hand_vision_state_expire(&g_vision_state, now_ms(), SMART_HAND_VISION_STALE_MS);
    if (had_vision && !g_vision_state.have_vision)
    {
        ++g_stats.vision_expired;
        g_vision_stale = 1u;
        update_titan_trust(now_ms(), 1u);
        rt_kprintf("smart_hand: VISION_STALE; cleared candidate/actionable\n");
        send_status();
    }
}

static void rx_thread_entry(void *parameter)
{
    shp_parser_t parser;
    shp_message_t message;
    uint8_t byte;

    (void)parameter;
    shp_parser_init(&parser);

    while (1)
    {
        while (rt_device_read(g_uart, 0, &byte, 1) == 1)
        {
            int result = shp_parser_feed(&parser, byte, &message);
            if (result == 1)
            {
                handle_message(&message);
            }
            else if (result < 0)
            {
                ++g_stats.invalid_frames;
                titan_trust_runtime_note_invalid(&g_titan_trust_runtime);
                rt_kprintf("smart_hand: dropped invalid frame\n");
            }
        }

        check_vision_expiry();
        send_train_status(0u);
        send_sign_status(0u);

        if (g_link_online &&
            (rt_tick_get() - g_last_valid_tick) >
                rt_tick_from_millisecond(SMART_HAND_LINK_TIMEOUT_MS))
        {
            g_link_online = RT_FALSE;
            ++g_stats.offline_events;
            g_vision_stale = 1u;
            smart_hand_vision_state_invalidate(&g_vision_state);
            smart_hand_sequence_guard_reset(&g_sequence_guard);
            /* A link loss must not leave a sign sequence moving.  The servo
             * worker samples this cancellation at its next bounded step and
             * attempts the verified official_open recovery target. */
            (void)servo_bus_sign_demo_request(
                SERVO_SIGN_ACTION_CANCEL, SERVO_SIGN_SEQUENCE_HELLO);
            rt_kprintf("smart_hand: VISION_OFFLINE; cleared vision; sequence baseline reset\n");
            send_sign_status(0u);
            send_status();
        }

        if ((rt_tick_get() - g_last_status_tick) >
            rt_tick_from_millisecond(SMART_HAND_STATUS_PERIOD_MS))
        {
            send_status();
        }

        /* Self-gated to one frame per SH_AITRUST_PERIOD_MS, so this is a
         * couple of comparisons on the ticks where it is not due. */
        send_aitrust();

        rt_sem_take(&g_rx_sem, rt_tick_from_millisecond(50));
    }
}

static int smart_hand_comm_init(void)
{
    struct serial_configure config = RT_SERIAL_CONFIG_DEFAULT;
    rt_thread_t thread;
    rt_err_t result;

    g_uart = rt_device_find(SMART_HAND_UART_NAME);
    if (g_uart == RT_NULL)
    {
        rt_kprintf("smart_hand: device %s not found; run list_device and update SMART_HAND_UART_NAME\n",
                   SMART_HAND_UART_NAME);
        return -RT_ERROR;
    }

    config.baud_rate = BAUD_RATE_115200;
    config.data_bits = DATA_BITS_8;
    config.stop_bits = STOP_BITS_1;
    config.parity = PARITY_NONE;
    /*
     * Force RT-Thread serial v2 to use its polling TX path.  The Titan
     * RA8P1 driver does not implement completion for buffered transmit,
     * so a non-zero TX buffer would block forever on the first ACK.
     */
    config.tx_bufsz = 0;
    result = rt_device_control(g_uart, RT_DEVICE_CTRL_CONFIG, &config);
    if (result != RT_EOK)
    {
        rt_kprintf("smart_hand: failed to configure %s (%d)\n",
                   SMART_HAND_UART_NAME,
                   result);
        return result;
    }

    result = rt_sem_init(&g_rx_sem, "shrx", 0, RT_IPC_FLAG_FIFO);
    if (result != RT_EOK) return result;
    result = rt_device_set_rx_indicate(g_uart, uart_rx_indicate);
    if (result != RT_EOK)
    {
        rt_sem_detach(&g_rx_sem);
        return result;
    }
    result = rt_device_open(g_uart, RT_DEVICE_OFLAG_RDWR | RT_DEVICE_FLAG_INT_RX);
    if (result != RT_EOK)
    {
        rt_kprintf("smart_hand: failed to open %s (%d)\n",
                   SMART_HAND_UART_NAME,
                   result);
        rt_sem_detach(&g_rx_sem);
        return result;
    }

    g_last_valid_tick = rt_tick_get();
    g_last_status_tick = g_last_valid_tick;
    g_link_online = RT_FALSE;
    g_vision_stale = 0u;
    g_status_seq = 0u;
    g_train_status_seq = 0u;
    g_train_request_seq = 0u;
    g_train_report_active = 0u;
    g_train_last_state = 0xffu;
    g_train_last_result = 0u;
    g_train_last_completed_count = 0u;
    g_sign_status_seq = 0u;
    g_sign_request_seq = 0u;
    g_sign_report_active = 0u;
    g_sign_last_state = 0xffu;
    g_sign_last_result = 0u;
    g_sign_last_sequence_id = 0u;
    g_sign_last_completed_count = 0u;
    g_sign_last_action = 0u;
    rt_memset(&g_stats, 0, sizeof(g_stats));
    smart_hand_vision_state_init(&g_vision_state);
    smart_hand_vision_state_configure_validated_right_hand(&g_vision_state);
    smart_hand_sequence_guard_init(&g_sequence_guard);
    titan_trust_runtime_init(&g_titan_trust_runtime);
    rt_memset(&g_titan_trust_result, 0, sizeof(g_titan_trust_result));
    g_titan_trust_result.classification = TITAN_TRUST_ANOMALOUS;
    g_titan_trust_last_gap_count = 0u;
    g_titan_trust_have_report = 0u;
    smart_hand_aitrust_link_init(&g_aitrust_link);
    /* No vision payload has been accepted yet: AITRUST must report the age as
     * unknown rather than as fresh. */
    g_vision_seen = 0u;
    g_vision_last_seen_ms = 0u;

    thread = rt_thread_create("sh_uart",
                              rx_thread_entry,
                              RT_NULL,
                              SMART_HAND_RX_THREAD_STACK,
                              18,
                              10);
    if (thread == RT_NULL)
    {
        rt_device_close(g_uart);
        rt_sem_detach(&g_rx_sem);
        return -RT_ENOMEM;
    }
    result = rt_thread_startup(thread);
    if (result != RT_EOK)
    {
        rt_thread_delete(thread);
        rt_device_close(g_uart);
        rt_sem_detach(&g_rx_sem);
        return result;
    }

    rt_kprintf("smart_hand: listening on %s at 115200 (validated poses; motion requires explicit TRAIN)\n",
               SMART_HAND_UART_NAME);
    return RT_EOK;
}
INIT_APP_EXPORT(smart_hand_comm_init);

static void sh_status(void)
{
    rt_tick_t age_ticks = rt_tick_get() - g_last_valid_tick;
    unsigned long age_ms = (unsigned long)
        (((uint64_t)age_ticks * 1000ULL) / (uint64_t)RT_TICK_PER_SECOND);
    uint32_t vision_age_ms = 0u;

    if (g_vision_state.have_vision)
    {
        vision_age_ms = now_ms() - g_vision_state.last_vision_ms;
    }

    rt_kprintf("smart_hand link=%s age_ms=%lu uart=%s\n",
               g_link_online ? "ONLINE" : "OFFLINE",
               age_ms,
               SMART_HAND_UART_NAME);
    rt_kprintf("frames valid=%lu invalid=%lu payload=%lu gaps=%lu duplicates=%lu old=%lu tx_fail=%lu offline=%lu\n",
               (unsigned long)g_stats.valid_frames,
               (unsigned long)g_stats.invalid_frames,
               (unsigned long)g_stats.invalid_payloads,
               (unsigned long)g_stats.sequence_gaps,
               (unsigned long)g_stats.duplicate_frames,
               (unsigned long)g_stats.old_frames,
               (unsigned long)g_stats.tx_failures,
               (unsigned long)g_stats.offline_events);
    rt_kprintf("sequence have_last=%u last_accepted=%u gaps=%lu duplicates=%lu old=%lu\n",
               (unsigned)g_sequence_guard.have_last,
               (unsigned)g_sequence_guard.last_accepted,
               (unsigned long)g_sequence_guard.gap_count,
               (unsigned long)g_sequence_guard.duplicate_count,
               (unsigned long)g_sequence_guard.old_count);
    rt_kprintf("decision policy_rejected=%lu pose_unavailable=%lu vision_expired=%lu\n",
               (unsigned long)g_stats.policy_rejected,
               (unsigned long)g_stats.pose_unavailable,
               (unsigned long)g_stats.vision_expired);
    rt_kprintf("training accepted=%lu blocked=%lu busy=%lu\n",
               (unsigned long)g_stats.train_accepted,
               (unsigned long)g_stats.train_blocked,
               (unsigned long)g_stats.train_busy);
    {
        servo_sign_status_t sign_status;
        if (servo_bus_sign_demo_get_status(&sign_status))
        {
            rt_kprintf("sign accepted=%lu blocked=%lu busy=%lu state=%u result=%u seq_id=%lu completed=%lu\n",
                       (unsigned long)g_stats.sign_accepted,
                       (unsigned long)g_stats.sign_blocked,
                       (unsigned long)g_stats.sign_busy,
                       (unsigned)sign_status.state,
                       (unsigned)sign_status.result_code,
                       (unsigned long)sign_status.sequence_id,
                       (unsigned long)sign_status.completed_count);
        }
    }
    rt_kprintf("vision present=%u age_ms=%lu action=%s reason=%s pose=%s actionable=%u\n",
               (unsigned)g_vision_state.have_vision,
               (unsigned long)vision_age_ms,
               grip_policy_action_name(g_vision_state.last_decision.action),
               grip_policy_reason_name(g_vision_state.last_decision.reason),
               pose_result_name(g_vision_state.last_pose_result),
               (unsigned)g_vision_state.have_actionable_target);
    update_titan_trust(now_ms(), 0u);
    rt_kprintf("titan_ai advisory=1 ready=%u state=%s controls_servo=0\n",
               (unsigned)g_titan_trust_result.ready,
               titan_trust_class_name(g_titan_trust_result.classification));
}
MSH_CMD_EXPORT(sh_status, show smart hand UART link diagnostics);
