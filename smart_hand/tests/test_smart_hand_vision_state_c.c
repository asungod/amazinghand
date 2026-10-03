#include "smart_hand_vision_state.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

/* FIXTURE ONLY — never copy into production pose bank or calibration CSV. */
static void install_fixture_poses(smart_hand_vision_state_t *state)
{
    state->pose_bank.profiles[0].configured = 1u;
    state->pose_bank.profiles[1].configured = 1u;
    state->pose_bank.profiles[2].configured = 1u;
    for (size_t profile = 0u; profile < EIGHT_SERVO_POSE_PROFILE_COUNT; ++profile)
    {
        for (size_t index = 0u; index < EIGHT_SERVO_COUNT; ++index)
        {
            state->pose_bank.profiles[profile].targets[index] =
                (eight_servo_target_t){(uint8_t)(index + 1u),
                                       (int16_t)(12 - (int)profile)};
        }
    }
}

static grip_vision_payload_t make_payload(uint32_t class_id, uint32_t confidence)
{
    grip_vision_payload_t payload;
    payload.class_id = class_id;
    payload.center_x = 320u;
    payload.center_y = 240u;
    payload.width = 80u;
    payload.height = 120u;
    payload.confidence = confidence;
    return payload;
}

static void assert_not_actionable(const smart_hand_vision_state_t *state)
{
    assert(!state->have_actionable_target);
    assert(!state->have_targets);
    assert(state->targets[0].id == 0u);
    assert(state->targets[EIGHT_SERVO_COUNT - 1u].id == 0u);
}

int main(void)
{
    smart_hand_vision_state_t state;
    grip_vision_payload_t bottle = make_payload(39u, 90u);
    grip_vision_payload_t cup = make_payload(41u, 90u);
    grip_vision_payload_t remote = make_payload(65u, 90u);
    grip_vision_payload_t low_conf = make_payload(39u, 69u);
    grip_vision_payload_t unsupported = make_payload(1u, 99u);
    grip_vision_payload_t illegal = make_payload(39u, 90u);

    /* 1) init: all poses unconfigured, actionable=false */
    smart_hand_vision_state_init(&state);
    assert(state.initialized);
    assert(!state.pose_bank.profiles[0].configured);
    assert(!state.pose_bank.profiles[1].configured);
    assert(!state.pose_bank.profiles[2].configured);
    assert_not_actionable(&state);
    assert(!state.have_vision);

    /* 2) 39/41/65 map correctly but empty bank => NOT_CONFIGURED, not actionable */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 1000u);
    assert(state.have_vision);
    assert(state.last_decision.action == GRIP_ACTION_CYLINDRICAL);
    assert(state.last_decision.reason == GRIP_REASON_ACCEPTED);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NOT_CONFIGURED);
    assert_not_actionable(&state);

    smart_hand_vision_state_note_vision(&state, &cup, 70u, 1100u);
    assert(state.last_decision.action == GRIP_ACTION_POWER);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NOT_CONFIGURED);
    assert_not_actionable(&state);

    smart_hand_vision_state_note_vision(&state, &remote, 70u, 1200u);
    assert(state.last_decision.action == GRIP_ACTION_PRECISION);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NOT_CONFIGURED);
    assert_not_actionable(&state);

    /* 6 then 3/7: FIXTURE pose can prove OK only inside this test file */
    install_fixture_poses(&state);
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 2000u);
    assert(state.last_decision.action == GRIP_ACTION_CYLINDRICAL);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_OK);
    assert(state.have_actionable_target);
    assert(state.have_targets);
    assert(state.targets[0].id == 1u &&
           state.targets[EIGHT_SERVO_COUNT - 1u].id == 8u);

    /* 3) high-confidence unsupported => NO_ACTION, clears prior actionable */
    smart_hand_vision_state_note_vision(&state, &unsupported, 70u, 2100u);
    assert(state.last_decision.action == GRIP_ACTION_NONE);
    assert(state.last_decision.reason == GRIP_REASON_UNSUPPORTED_CLASS);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NO_ACTION);
    assert(state.have_vision);
    assert_not_actionable(&state);

    /* restore actionable then low confidence clears it */
    smart_hand_vision_state_note_vision(&state, &cup, 70u, 2200u);
    assert(state.have_actionable_target);
    assert(state.last_decision.action == GRIP_ACTION_POWER);

    /* 4) low confidence => NO_ACTION, cannot keep previous target */
    smart_hand_vision_state_note_vision(&state, &low_conf, 70u, 2300u);
    assert(state.last_decision.action == GRIP_ACTION_NONE);
    assert(state.last_decision.reason == GRIP_REASON_LOW_CONFIDENCE);
    assert_not_actionable(&state);

    /* 5) illegal payload fail closed */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 2400u);
    assert(state.have_actionable_target);
    illegal.width = 0u;
    smart_hand_vision_state_note_vision(&state, &illegal, 70u, 2500u);
    assert(state.last_decision.reason == GRIP_REASON_INVALID_PAYLOAD);
    assert(state.last_decision.action == GRIP_ACTION_NONE);
    assert_not_actionable(&state);

    /* null payload fail closed */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 2600u);
    assert(state.have_actionable_target);
    smart_hand_vision_state_note_vision(&state, NULL, 70u, 2700u);
    assert(!state.have_vision);
    assert_not_actionable(&state);

    /* 8) only PING-equivalent time advance must NOT refresh vision time:
     *    note bottle, then expire at +750 without a new note_vision. */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 3000u);
    assert(state.have_actionable_target);
    assert(state.last_vision_ms == 3000u);
    /* Simulated PING loop: call expire with advancing now, no note_vision. */
    smart_hand_vision_state_expire(&state, 3400u, 750u);
    assert(state.have_vision);
    assert(state.have_actionable_target);
    smart_hand_vision_state_expire(&state, 3750u, 750u);
    assert(!state.have_vision);
    assert_not_actionable(&state);

    /* 9) uint32_t age near top of range without overflow in the addends */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 0xFFFFFD00u);
    assert(state.have_actionable_target);
    smart_hand_vision_state_expire(&state, 0xFFFFFD00u + 749u, 750u);
    assert(state.have_vision);
    smart_hand_vision_state_expire(&state, 0xFFFFFD00u + 750u, 750u);
    assert(!state.have_vision);
    assert_not_actionable(&state);

    /* wrap across uint32 boundary: unsigned (now - last) remains correct */
    smart_hand_vision_state_note_vision(&state, &remote, 70u, 0xFFFFFE00u);
    assert(state.have_actionable_target);
    /* age = 0x200 = 512 < 750 */
    smart_hand_vision_state_expire(&state, 0x00000000u, 750u);
    assert(state.have_vision);
    /* age = 0x400 = 1024 >= 750 */
    smart_hand_vision_state_expire(&state, 0x00000200u, 750u);
    assert(!state.have_vision);
    assert_not_actionable(&state);

    /* 10) invalidate clears all */
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 5000u);
    assert(state.have_actionable_target);
    smart_hand_vision_state_invalidate(&state);
    assert(!state.have_vision);
    assert_not_actionable(&state);
    assert(state.last_decision.action == GRIP_ACTION_NONE);

    /* 11) null state / 0 timeout fail closed */
    smart_hand_vision_state_init(NULL); /* must not crash */
    smart_hand_vision_state_note_vision(NULL, &bottle, 70u, 1u);
    smart_hand_vision_state_expire(NULL, 1u, 750u);
    smart_hand_vision_state_invalidate(NULL);

    smart_hand_vision_state_init(&state);
    install_fixture_poses(&state);
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 6000u);
    assert(state.have_actionable_target);
    smart_hand_vision_state_expire(&state, 6001u, 0u); /* 0 timeout => clear */
    assert(!state.have_vision);
    assert_not_actionable(&state);

    /* Production-shaped init after FIXTURE test: re-init must wipe poses */
    smart_hand_vision_state_init(&state);
    assert(!state.pose_bank.profiles[0].configured);
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 7000u);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NOT_CONFIGURED);
    assert_not_actionable(&state);

    /* Explicit production config: validated close for bottle/cup only. */
    smart_hand_vision_state_configure_validated_right_hand(&state);
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 7100u);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_OK);
    assert(state.have_actionable_target);
    assert(state.targets[0].offset_from_center == 307);
    assert(state.targets[7].offset_from_center == 239);
    smart_hand_vision_state_note_vision(&state, &remote, 70u, 7200u);
    assert(state.last_pose_result == EIGHT_SERVO_POSE_NOT_CONFIGURED);
    assert_not_actionable(&state);

    /*
     * UART rule model (pure module): protocol-typed VISION with illegal business
     * payload must immediately invalidate prior candidate/actionable, without
     * waiting for 750 ms freshness timeout. Production uart calls invalidate()
     * on that path; this proves the clear semantics.
     */
    install_fixture_poses(&state);
    smart_hand_vision_state_note_vision(&state, &bottle, 70u, 8000u);
    assert(state.have_actionable_target);
    assert(state.last_vision_ms == 8000u);
    smart_hand_vision_state_invalidate(&state);
    assert(!state.have_vision);
    assert_not_actionable(&state);
    /* A later expire must not resurrect the cleared target. */
    smart_hand_vision_state_expire(&state, 9000u, 750u);
    assert(!state.have_vision);
    assert_not_actionable(&state);

    puts("smart_hand_vision_state C tests passed");
    return 0;
}
