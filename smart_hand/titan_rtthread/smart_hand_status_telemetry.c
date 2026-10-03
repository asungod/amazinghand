#include "smart_hand_status_telemetry.h"

#include "grip_pose_bank.h"

#include <stddef.h>

uint8_t smart_hand_status_derive_submit(const smart_hand_status_input_t *in)
{
    if (in == NULL)
    {
        return SH_STATUS_SUBMIT_UNKNOWN;
    }
    if (in->pose == (uint8_t)GRIP_POSE_NOT_CONFIGURED ||
        in->pose == (uint8_t)GRIP_POSE_INVALID_PROFILE)
    {
        return SH_STATUS_SUBMIT_NOT_CONFIGURED;
    }
    if (!in->write_path_present || !in->gate_present)
    {
        return SH_STATUS_SUBMIT_UNKNOWN;
    }
    if (in->gate_blocked || in->gate_fault)
    {
        return SH_STATUS_SUBMIT_BLOCKED;
    }
    if (in->write_observed_ok)
    {
        return SH_STATUS_SUBMIT_SUBMITTED;
    }
    return SH_STATUS_SUBMIT_UNKNOWN;
}

int smart_hand_status_pack(const smart_hand_status_input_t *in,
                           uint32_t args[SH_STATUS_ARG_COUNT])
{
    uint32_t flags;
    uint8_t submit;
    uint8_t have_actionable;

    if (in == NULL || args == NULL)
    {
        return -1;
    }

    submit = smart_hand_status_derive_submit(in);
    have_actionable = in->have_actionable;
    if (in->pose == (uint8_t)GRIP_POSE_NOT_CONFIGURED ||
        in->pose == (uint8_t)GRIP_POSE_INVALID_PROFILE)
    {
        have_actionable = 0u;
    }

    flags = 0u;
    if (in->link_online) flags |= SH_STATUS_FLAG_LINK_ONLINE;
    if (in->have_vision) flags |= SH_STATUS_FLAG_HAVE_VISION;
    if (in->vision_stale) flags |= SH_STATUS_FLAG_VISION_STALE;
    if (in->have_last_rx) flags |= SH_STATUS_FLAG_HAVE_LAST_RX;
    if (in->gate_present)
    {
        flags |= SH_STATUS_FLAG_GATE_PRESENT;
        if (in->gate_armed) flags |= SH_STATUS_FLAG_GATE_ARMED;
        if (in->gate_fault) flags |= SH_STATUS_FLAG_GATE_FAULT;
    }
    if (have_actionable) flags |= SH_STATUS_FLAG_HAVE_ACTIONABLE;

    args[0] = SH_STATUS_VERSION;
    args[1] = flags;
    args[2] = in->have_last_rx ? (uint32_t)in->last_rx_seq : 0u;
    args[3] = (uint32_t)in->action;
    args[4] = (uint32_t)in->reason;
    args[5] = (uint32_t)in->pose;
    args[6] = (uint32_t)submit;
    args[7] = in->gate_present ? 0u : (uint32_t)SH_STATUS_FAULT_UNKNOWN;
    return 0;
}

/* ------------------------------------------------------------------------- */
/* AITRUST v1. See the header for the wire contract and the reasoning behind
 * the ready conjunction and the two age sentinels. */

uint32_t smart_hand_aitrust_vision_age_ms(const smart_hand_aitrust_input_t *in)
{
    uint32_t age;

    if (in == NULL || in->have_last_vision == 0u)
    {
        return SH_AITRUST_AGE_UNKNOWN;
    }

    /*
     * Unsigned subtraction is wrap-safe for a monotonic millisecond clock. A
     * clock that steps backwards makes this a very large unsigned value, which
     * the clamp below turns into the same ceiling a genuinely old reading
     * gets -- never into a small, falsely fresh one.
     */
    age = in->now_ms - in->last_vision_ms;
    if (age > SH_AITRUST_AGE_SATURATE_MS)
    {
        return SH_AITRUST_AGE_SATURATE_MS;
    }
    return age;
}

int smart_hand_aitrust_pack(const smart_hand_aitrust_input_t *in,
                            uint32_t args[SH_AITRUST_ARG_COUNT])
{
    uint8_t ready;
    uint8_t class_id;

    if (in == NULL || args == NULL)
    {
        return -1;
    }

    /*
     * The conjunction is load-bearing, not belt-and-braces: the runtime keeps
     * model_ready at 1 after the vision candidate expires, so testing it alone
     * would advertise an advisory about vision Titan no longer has.
     */
    ready = (in->model_ready != 0u && in->have_vision != 0u) ? 1u : 0u;

    /*
     * Clamp rather than trust the caller's byte: the wire contract only has
     * three class values, and an out-of-range id would be a protocol error at
     * the receiver. ANOMALOUS is the fail-closed direction, so a bad value
     * degrades toward "do not trust this", never toward green.
     */
    class_id = in->classification;
    if (class_id > (uint8_t)TITAN_TRUST_ANOMALOUS)
    {
        class_id = (uint8_t)TITAN_TRUST_ANOMALOUS;
    }

    args[0] = SH_AITRUST_VERSION;
    args[1] = (uint32_t)ready;
    args[2] = (uint32_t)class_id;
    args[3] = smart_hand_aitrust_vision_age_ms(in);
    return 0;
}

void smart_hand_aitrust_link_init(smart_hand_aitrust_link_t *link)
{
    if (link == NULL)
    {
        return;
    }
    link->last_attempt_ms = 0u;
    link->seq = 0u;
    link->sent_frames = 0u;
    link->failed_frames = 0u;
    link->have_attempt = 0u;
}

uint8_t smart_hand_aitrust_due(const smart_hand_aitrust_link_t *link,
                               uint32_t now_ms)
{
    if (link == NULL)
    {
        return 0u;
    }
    if (link->have_attempt == 0u)
    {
        return 1u;
    }
    /* Unsigned subtraction is wrap-safe for a monotonic millisecond clock. */
    return ((now_ms - link->last_attempt_ms) >= SH_AITRUST_PERIOD_MS) ? 1u : 0u;
}

void smart_hand_aitrust_note_attempt(smart_hand_aitrust_link_t *link,
                                     uint32_t now_ms)
{
    if (link == NULL)
    {
        return;
    }
    link->last_attempt_ms = now_ms;
    link->have_attempt = 1u;
}

void smart_hand_aitrust_note_sent(smart_hand_aitrust_link_t *link)
{
    if (link == NULL)
    {
        return;
    }
    link->seq = (uint16_t)(link->seq + 1u);
    link->sent_frames += 1u;
}

void smart_hand_aitrust_note_failed(smart_hand_aitrust_link_t *link)
{
    if (link == NULL)
    {
        return;
    }
    /* The sequence deliberately does not move: it numbers frames that went out. */
    link->failed_frames += 1u;
}
