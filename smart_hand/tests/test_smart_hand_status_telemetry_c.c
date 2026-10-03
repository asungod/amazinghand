#include "smart_hand_status_telemetry.h"

#include "grip_policy.h"
#include "grip_pose_bank.h"
#include "smart_hand_protocol.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static smart_hand_status_input_t base_input(void)
{
    smart_hand_status_input_t in;
    memset(&in, 0, sizeof(in));
    in.link_online = 1u;
    in.have_vision = 1u;
    in.have_last_rx = 1u;
    in.last_rx_seq = 7u;
    in.action = (uint8_t)GRIP_ACTION_CYLINDRICAL;
    in.reason = (uint8_t)GRIP_REASON_ACCEPTED;
    in.pose = (uint8_t)GRIP_POSE_NOT_CONFIGURED;
    in.gate_present = 0u;
    in.write_path_present = 0u;
    return in;
}

int main(void)
{
    uint32_t args[SH_STATUS_ARG_COUNT];
    smart_hand_status_input_t in = base_input();

    assert(smart_hand_status_pack(&in, args) == 0);
    assert(args[0] == 1u);
    assert(args[1] == 11u);
    assert(args[2] == 7u);
    assert(args[3] == (uint32_t)GRIP_ACTION_CYLINDRICAL);
    assert(args[4] == (uint32_t)GRIP_REASON_ACCEPTED);
    assert(args[5] == (uint32_t)GRIP_POSE_NOT_CONFIGURED);
    assert(args[6] == SH_STATUS_SUBMIT_NOT_CONFIGURED);
    assert(args[7] == SH_STATUS_FAULT_UNKNOWN);
    assert(args[6] != SH_STATUS_SUBMIT_SUBMITTED);

    in.pose = (uint8_t)GRIP_POSE_NO_ACTION;
    in.action = (uint8_t)GRIP_ACTION_NONE;
    in.reason = (uint8_t)GRIP_REASON_LOW_CONFIDENCE;
    in.last_rx_seq = 8u;
    assert(smart_hand_status_pack(&in, args) == 0);
    assert(args[4] == (uint32_t)GRIP_REASON_LOW_CONFIDENCE);
    assert(args[6] == SH_STATUS_SUBMIT_UNKNOWN);

    in = base_input();
    in.have_vision = 0u;
    in.vision_stale = 1u;
    in.action = (uint8_t)GRIP_ACTION_NONE;
    in.reason = (uint8_t)GRIP_REASON_INVALID_PAYLOAD;
    in.pose = (uint8_t)GRIP_POSE_NO_ACTION;
    in.last_rx_seq = 8u;
    assert(smart_hand_status_pack(&in, args) == 0);
    assert(args[1] == 13u);
    assert(args[6] == SH_STATUS_SUBMIT_UNKNOWN);

    in = base_input();
    in.pose = (uint8_t)GRIP_POSE_OK;
    in.write_path_present = 0u;
    in.write_observed_ok = 1u;
    assert(smart_hand_status_derive_submit(&in) == SH_STATUS_SUBMIT_UNKNOWN);
    assert(smart_hand_status_pack(&in, args) == 0);
    assert(args[6] == SH_STATUS_SUBMIT_UNKNOWN);
    assert(args[7] == SH_STATUS_FAULT_UNKNOWN);

    in.have_actionable = 1u;
    in.pose = (uint8_t)GRIP_POSE_NOT_CONFIGURED;
    assert(smart_hand_status_pack(&in, args) == 0);
    assert((args[1] & SH_STATUS_FLAG_HAVE_ACTIONABLE) == 0u);

    assert(smart_hand_status_pack(NULL, args) == -1);

    /* --------------------------------------------------------------------- */
    /* STATUS v1 is frozen. The literal below is the entire frame including its
     * CRC16, so reordering a field, adding a flag bit or bumping the version
     * breaks this test rather than silently changing what MaixCAM2 receives. */

    in = base_input();
    assert(smart_hand_status_pack(&in, args) == 0);
    {
        char frame[SHP_MAX_FRAME_SIZE];
        int length = shp_encode(frame, sizeof(frame), "STATUS", 3u, args,
                                SH_STATUS_ARG_COUNT);
        assert(length > 0);
        assert(strcmp(frame, "$STATUS,3,1,11,7,1,0,2,1,255*D0A0\r\n") == 0);
    }

    /* --------------------------------------------------------------------- */
    /* AITRUST v1: the TitanTrust advisory frame. */

    {
        smart_hand_aitrust_input_t ai;
        smart_hand_aitrust_link_t link;
        uint32_t aiargs[SH_AITRUST_ARG_COUNT];
        char frame[SHP_MAX_FRAME_SIZE];
        int length;

        /* Ready: a classified window whose vision is still current. */
        memset(&ai, 0, sizeof(ai));
        ai.model_ready = 1u;
        ai.classification = (uint8_t)TITAN_TRUST_TRUSTED;
        ai.have_vision = 1u;
        ai.have_last_vision = 1u;
        ai.last_vision_ms = 1000u;
        ai.now_ms = 1250u;
        assert(smart_hand_aitrust_vision_age_ms(&ai) == 250u);
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[0] == SH_AITRUST_VERSION);
        assert(aiargs[1] == 1u);
        assert(aiargs[2] == (uint32_t)TITAN_TRUST_TRUSTED);
        assert(aiargs[3] == 250u);

        length = shp_encode(frame, sizeof(frame), "AITRUST", 0u, aiargs,
                            SH_AITRUST_ARG_COUNT);
        assert(length > 0);
        assert(strcmp(frame, "$AITRUST,0,1,1,0,250*0497\r\n") == 0);
        /* The checksum in that literal must be the one this project's own CRC
         * produces over the body, and one changed byte must not match it. */
        assert(shp_crc16_ccitt((const uint8_t *)"AITRUST,0,1,1,0,250", 19u) ==
               0x0497u);
        assert(shp_crc16_ccitt((const uint8_t *)"AITRUST,0,1,1,0,251", 19u) !=
               0x0497u);

        /* Worst case on the wire: the largest 16-bit sequence paired with the
         * saturated unknown age. It has to fit the frozen 128-byte frame cap
         * with room to spare, so a future field cannot silently overflow it. */
        {
            uint32_t worst[SH_AITRUST_ARG_COUNT];

            worst[0] = SH_AITRUST_VERSION;
            worst[1] = 1u;
            worst[2] = (uint32_t)TITAN_TRUST_ANOMALOUS;
            worst[3] = SH_AITRUST_AGE_UNKNOWN;
            length = shp_encode(frame, sizeof(frame), "AITRUST", 0xFFFFu, worst,
                                SH_AITRUST_ARG_COUNT);
            assert(length > 0);
            assert((size_t)length < (size_t)SHP_MAX_FRAME_SIZE);
            assert(strcmp(frame, "$AITRUST,65535,1,1,2,4294967295*574D\r\n") == 0);
        }

        /* No VISION payload has EVER been accepted. The model still has a
         * window, but there is no age to report, and 0 would read as "just
         * arrived" -- so the age saturates upward and ready reads 0 (未就绪).
         * class_id is carried through unchanged and is meaningless in this
         * frame: the frozen contract has no fourth value, and fabricating one
         * (or clamping to ANOMALOUS) would be inventing a class. */
        memset(&ai, 0, sizeof(ai));
        ai.model_ready = 1u;
        ai.classification = (uint8_t)TITAN_TRUST_TRUSTED;
        ai.have_vision = 0u;
        ai.have_last_vision = 0u;
        ai.now_ms = 5000u;
        assert(smart_hand_aitrust_vision_age_ms(&ai) == SH_AITRUST_AGE_UNKNOWN);
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[1] == 0u);
        assert(aiargs[2] == (uint32_t)TITAN_TRUST_TRUSTED);
        assert(aiargs[3] == SH_AITRUST_AGE_UNKNOWN);

        /* Vision expired. This is the case model_ready alone gets wrong: the
         * runtime keeps ready at 1 after the candidate expires, so the frame
         * must go not-ready on have_vision and the age must keep counting from
         * the last payload that really arrived. */
        ai.model_ready = 1u;
        ai.classification = (uint8_t)TITAN_TRUST_TRUSTED;
        ai.have_vision = 0u;
        ai.have_last_vision = 1u;
        ai.last_vision_ms = 1000u;
        ai.now_ms = 3000u;
        assert(smart_hand_aitrust_vision_age_ms(&ai) == 2000u);
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[1] == 0u);
        assert(aiargs[3] == 2000u);

        /*
         * Both halves of the ready conjunction must be load-bearing ON THEIR
         * OWN, so each is exercised against a true other half. The vision-
         * expired case above already pins have_vision (model_ready == 1,
         * have_vision == 0 -> not ready); this one pins model_ready, which an
         * earlier revision of this test left unconstrained because its only
         * "model not ready" case also had have_vision == 0 -- dropping
         * model_ready from the conjunction left the suite green.
         */
        ai.have_vision = 1u;
        ai.have_last_vision = 1u;
        ai.last_vision_ms = 1000u;
        ai.now_ms = 1000u;
        ai.classification = (uint8_t)TITAN_TRUST_TRUSTED;
        ai.model_ready = 0u; /* vision fresh, but no classified window yet */
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[1] == 0u);

        /* And the one case that may read ready: both halves true. */
        ai.model_ready = 1u;
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[1] == 1u);

        /* Age saturation, and a clock that steps backwards. Neither may alias
         * into a small, fresher-looking age. */
        ai.have_vision = 1u;
        ai.model_ready = 1u;
        ai.now_ms = 1000u + SH_AITRUST_AGE_SATURATE_MS + 1u;
        assert(smart_hand_aitrust_vision_age_ms(&ai) ==
               SH_AITRUST_AGE_SATURATE_MS);
        ai.now_ms = 999u; /* one ms BEFORE last_vision_ms */
        assert(smart_hand_aitrust_vision_age_ms(&ai) ==
               SH_AITRUST_AGE_SATURATE_MS);

        /* A corrupt class byte must not reach the wire. The clamp fails
         * closed: a bad value degrades toward "do not trust this". */
        ai.classification = 250u;
        assert(smart_hand_aitrust_pack(&ai, aiargs) == 0);
        assert(aiargs[2] == (uint32_t)TITAN_TRUST_ANOMALOUS);

        /* Pacing: the floor is on ATTEMPTS, so a failed write cannot become a
         * retry loop against the UART that carries ACK and the motion link. */
        smart_hand_aitrust_link_init(&link);
        assert(smart_hand_aitrust_due(&link, 0u) == 1u); /* nothing sent yet */
        assert(link.seq == 0u);

        smart_hand_aitrust_note_attempt(&link, 10000u);
        assert(smart_hand_aitrust_due(&link, 10000u) == 0u);
        assert(smart_hand_aitrust_due(&link, 10499u) == 0u); /* 499 ms: too soon */
        assert(smart_hand_aitrust_due(&link, 10500u) == 1u); /* 500 ms: due */

        /*
         * The floor is written as an unsigned difference precisely so it
         * survives the 32-bit millisecond clock wrapping (about 49.7 days of
         * uptime). A natural rewrite -- now_ms >= last + PERIOD -- sails
         * through the two assertions above and then reports "due" on every
         * tick after a wrap, which would put the frame back on the 50 ms loop
         * the floor exists to keep it off. Pin the wrap itself.
         */
        smart_hand_aitrust_link_init(&link);
        smart_hand_aitrust_note_attempt(&link, 0xFFFFFFF0u);
        assert(smart_hand_aitrust_due(&link, 0xFFFFFFF0u) == 0u);
        assert(smart_hand_aitrust_due(&link, 0xFFFFFFFFu) == 0u); /* +15 ms */
        assert(smart_hand_aitrust_due(&link, 0x000001E3u) == 0u); /* +499 ms, post-wrap */
        assert(smart_hand_aitrust_due(&link, 0x000001E4u) == 1u); /* +500 ms, post-wrap */

        /* A frame that went out advances the sequence; the peer can then treat
         * a gap as a genuinely lost frame. */
        smart_hand_aitrust_note_sent(&link);
        assert(link.seq == 1u);
        assert(link.sent_frames == 1u);
        assert(link.failed_frames == 0u);

        /* A failed write is only counted: same sequence, and the next attempt
         * still waits the full period. */
        smart_hand_aitrust_note_attempt(&link, 20000u);
        smart_hand_aitrust_note_failed(&link);
        assert(link.failed_frames == 1u);
        assert(link.sent_frames == 1u);
        assert(link.seq == 1u);
        assert(smart_hand_aitrust_due(&link, 20499u) == 0u);
        assert(smart_hand_aitrust_due(&link, 20500u) == 1u);

        /* NULL handling: no crash, and no frame claimed to be due. Both
         * pointer arguments are checked -- the args guard was previously
         * unexercised, so removing it left the suite green. */
        assert(smart_hand_aitrust_pack(NULL, aiargs) == -1);
        assert(smart_hand_aitrust_pack(&ai, NULL) == -1);
        assert(smart_hand_aitrust_vision_age_ms(NULL) == SH_AITRUST_AGE_UNKNOWN);
        assert(smart_hand_aitrust_due(NULL, 0u) == 0u);
        smart_hand_aitrust_link_init(NULL);
        smart_hand_aitrust_note_attempt(NULL, 0u);
        smart_hand_aitrust_note_sent(NULL);
        smart_hand_aitrust_note_failed(NULL);
    }

    printf("smart_hand_status_telemetry C tests passed (STATUS v1 + AITRUST v1)\n");
    return 0;
}
