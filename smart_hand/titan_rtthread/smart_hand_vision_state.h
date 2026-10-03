#ifndef SMART_HAND_VISION_STATE_H
#define SMART_HAND_VISION_STATE_H

#include "grip_policy.h"
#include "eight_servo_pose_bank.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Host-testable vision decision state for Titan.
 * No RT-Thread, UART, GPIO, filesystem, or heap.
 *
 * Layers (kept separate):
 *   1) protocol payload validity (caller)
 *   2) grip_policy acceptance
 *   3) eight-servo pose-bank availability
 */
typedef struct
{
    eight_servo_pose_bank_t pose_bank;
    grip_decision_t last_decision;
    eight_servo_pose_result_t last_pose_result;
    eight_servo_target_t targets[EIGHT_SERVO_COUNT];
    uint32_t last_vision_ms;
    uint8_t have_vision;
    uint8_t have_actionable_target;
    uint8_t have_targets;
    uint8_t initialized;
} smart_hand_vision_state_t;

void smart_hand_vision_state_init(smart_hand_vision_state_t *state);

/* Install only poses already validated on the assembled right hand. */
void smart_hand_vision_state_configure_validated_right_hand(
    smart_hand_vision_state_t *state);

/* Apply a protocol-valid VISION payload. Rejects clear prior actionable targets. */
void smart_hand_vision_state_note_vision(smart_hand_vision_state_t *state,
                                         const grip_vision_payload_t *payload,
                                         uint8_t minimum_confidence,
                                         uint32_t now_ms);

/*
 * Expire vision freshness using unsigned uint32_t age (wrap-safe).
 * timeout_ms == 0 fail-closes (clears vision).
 * PING must NOT call this with a refreshed vision timestamp.
 */
void smart_hand_vision_state_expire(smart_hand_vision_state_t *state,
                                    uint32_t now_ms,
                                    uint32_t timeout_ms);

/* Link offline or explicit clear: drop candidate, actionable, and targets. */
void smart_hand_vision_state_invalidate(smart_hand_vision_state_t *state);

#ifdef __cplusplus
}
#endif

#endif
