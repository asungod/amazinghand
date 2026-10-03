#include "smart_hand_vision_state.h"

#include <string.h>

static void clear_actionable(smart_hand_vision_state_t *state)
{
    state->have_actionable_target = 0u;
    state->have_targets = 0u;
    memset(state->targets, 0, sizeof(state->targets));
}

static void clear_vision_candidate(smart_hand_vision_state_t *state)
{
    state->have_vision = 0u;
    state->last_vision_ms = 0u;
    state->last_decision.action = GRIP_ACTION_NONE;
    state->last_decision.reason = GRIP_REASON_INVALID_PAYLOAD;
    state->last_decision.class_id = 0u;
    state->last_pose_result = EIGHT_SERVO_POSE_NO_ACTION;
    clear_actionable(state);
}

void smart_hand_vision_state_init(smart_hand_vision_state_t *state)
{
    if (state == NULL)
    {
        return;
    }
    memset(state, 0, sizeof(*state));
    eight_servo_pose_bank_init(&state->pose_bank);
    state->last_decision.action = GRIP_ACTION_NONE;
    state->last_decision.reason = GRIP_REASON_INVALID_PAYLOAD;
    state->last_pose_result = EIGHT_SERVO_POSE_NO_ACTION;
    state->initialized = 1u;
}

void smart_hand_vision_state_configure_validated_right_hand(
    smart_hand_vision_state_t *state)
{
    static const int16_t close_offsets[EIGHT_SERVO_COUNT] = {
        307, 307, 307, 307, 307, 307, 239, 239
    };
    size_t profile_index;
    size_t servo_index;

    if (state == NULL || !state->initialized)
    {
        return;
    }

    /* Cylindrical and power currently share the hardware-validated close. */
    for (profile_index = 0u; profile_index < 2u; ++profile_index)
    {
        state->pose_bank.profiles[profile_index].configured = 1u;
        for (servo_index = 0u; servo_index < EIGHT_SERVO_COUNT;
             ++servo_index)
        {
            state->pose_bank.profiles[profile_index].targets[servo_index].id =
                (uint8_t)(servo_index + 1u);
            state->pose_bank.profiles[profile_index]
                .targets[servo_index].offset_from_center =
                close_offsets[servo_index];
        }
    }
    /* Precision remains fail-closed until a real thumb/index pose is tested. */
    state->pose_bank.profiles[2].configured = 0u;
}

void smart_hand_vision_state_note_vision(smart_hand_vision_state_t *state,
                                         const grip_vision_payload_t *payload,
                                         uint8_t minimum_confidence,
                                         uint32_t now_ms)
{
    grip_decision_t decision;
    eight_servo_pose_result_t pose_result;
    eight_servo_target_t resolved[EIGHT_SERVO_COUNT];

    if (state == NULL || !state->initialized)
    {
        return;
    }
    if (payload == NULL)
    {
        clear_vision_candidate(state);
        return;
    }

    decision = grip_policy_decide(payload, minimum_confidence);
    state->last_decision = decision;
    state->have_vision = 1u;
    state->last_vision_ms = now_ms;

    pose_result = eight_servo_pose_bank_resolve(
        &state->pose_bank, &decision, resolved);
    state->last_pose_result = pose_result;

    if (decision.reason != GRIP_REASON_ACCEPTED ||
        decision.action == GRIP_ACTION_NONE ||
        pose_result != EIGHT_SERVO_POSE_OK)
    {
        /* Reject paths must not keep a previous actionable target. */
        clear_actionable(state);
        return;
    }

    memcpy(state->targets, resolved, sizeof(state->targets));
    state->have_targets = 1u;
    state->have_actionable_target = 1u;
}

void smart_hand_vision_state_expire(smart_hand_vision_state_t *state,
                                    uint32_t now_ms,
                                    uint32_t timeout_ms)
{
    uint32_t age_ms;

    if (state == NULL || !state->initialized)
    {
        return;
    }
    if (timeout_ms == 0u)
    {
        clear_vision_candidate(state);
        return;
    }
    if (!state->have_vision)
    {
        return;
    }

    /* Unsigned subtraction is wrap-safe for monotonic millisecond clocks. */
    age_ms = now_ms - state->last_vision_ms;
    if (age_ms >= timeout_ms)
    {
        clear_vision_candidate(state);
    }
}

void smart_hand_vision_state_invalidate(smart_hand_vision_state_t *state)
{
    if (state == NULL || !state->initialized)
    {
        return;
    }
    clear_vision_candidate(state);
}
