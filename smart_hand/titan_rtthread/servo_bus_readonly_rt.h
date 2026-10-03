#ifndef SERVO_BUS_READONLY_RT_H
#define SERVO_BUS_READONLY_RT_H

#include "servo_group_readonly.h"

#include <stddef.h>
#include <stdint.h>

#define SERVO_SIGN_SEQUENCE_OPEN_PALM 1u
#define SERVO_SIGN_SEQUENCE_FIST 2u
#define SERVO_SIGN_SEQUENCE_V_SIGN 3u
#define SERVO_SIGN_SEQUENCE_POINT 4u
#define SERVO_SIGN_SEQUENCE_THUMBS_UP 5u
#define SERVO_SIGN_SEQUENCE_L_SHAPE 6u
#define SERVO_SIGN_SEQUENCE_OK_PINCH 7u
#define SERVO_SIGN_SEQUENCE_HELLO_WORD 8u
#define SERVO_SIGN_SEQUENCE_THANKS_WORD 9u
#define SERVO_SIGN_SEQUENCE_HELP_SIGNAL 10u
#define SERVO_SIGN_SEQUENCE_NO_WORD 11u
#define SERVO_SIGN_SEQUENCE_ATTENTION_WORD 12u
#define SERVO_SIGN_SEQUENCE_LIKE_WORD 13u
/* Compatibility name retained for the already validated first recipe. */
#define SERVO_SIGN_SEQUENCE_HELLO SERVO_SIGN_SEQUENCE_OPEN_PALM

typedef enum
{
    SERVO_REHAB_REQUEST_ACCEPTED = 0,
    SERVO_REHAB_REQUEST_NOT_READY = 1,
    SERVO_REHAB_REQUEST_FAULT = 2,
    SERVO_REHAB_REQUEST_BUSY = 3
} servo_rehab_request_result_t;

typedef enum
{
    SERVO_REHAB_STATE_IDLE = 0,
    SERVO_REHAB_STATE_QUEUED = 1,
    SERVO_REHAB_STATE_RUNNING = 2,
    SERVO_REHAB_STATE_SUCCEEDED = 3,
    SERVO_REHAB_STATE_FAILED = 4
} servo_rehab_state_t;

typedef struct
{
    servo_rehab_state_t state;
    uint32_t result_code;
    uint32_t completed_count;
} servo_rehab_status_t;

int servo_bus_readonly_is_ready(void);
int servo_bus_safety_gate_present(void);
int servo_bus_safety_gate_armed(void);
int servo_bus_safety_gate_fault_latched(void);
servo_rehab_request_result_t servo_bus_rehab_demo_request(void);
int servo_bus_rehab_demo_get_status(servo_rehab_status_t *status);
int servo_bus_readonly_get_snapshot(servo_group_readonly_sample_t *samples,
                                    size_t capacity,
                                    size_t *sample_count);

/*
 * Sign-demo requests are intentionally a separate mailbox from TRAIN.  The
 * UART side submits only an action and a fixed, validated sequence id; raw
 * servo positions never cross this API boundary.
 */
typedef enum
{
    SERVO_SIGN_ACTION_START = 1,
    SERVO_SIGN_ACTION_CANCEL = 2,
    SERVO_SIGN_ACTION_HOME = 3
} servo_sign_action_t;

typedef enum
{
    SERVO_SIGN_REQUEST_ACCEPTED = 0,
    SERVO_SIGN_REQUEST_NOT_READY = 1,
    SERVO_SIGN_REQUEST_FAULT = 2,
    SERVO_SIGN_REQUEST_BUSY = 3,
    SERVO_SIGN_REQUEST_UNSUPPORTED = 4
} servo_sign_request_result_t;

typedef enum
{
    SERVO_SIGN_STATE_IDLE = 0,
    SERVO_SIGN_STATE_QUEUED = 1,
    SERVO_SIGN_STATE_RUNNING = 2,
    /* A running target operation is bounded but not interruptible at the
     * individual UART packet boundary.  CANCEL therefore enters this state
     * until the current bounded step exits and recovery is attempted. */
    SERVO_SIGN_STATE_CANCELLING = 3,
    SERVO_SIGN_STATE_HOMING = 4,
    SERVO_SIGN_STATE_COMPLETED = 5,
    SERVO_SIGN_STATE_CANCELLED = 6,
    SERVO_SIGN_STATE_FAILED = 7
} servo_sign_state_t;

typedef enum
{
    SERVO_SIGN_RESULT_NONE = 0,
    SERVO_SIGN_RESULT_SUCCEEDED = 1,
    SERVO_SIGN_RESULT_MOTION_FAILED = 2,
    SERVO_SIGN_RESULT_CANCELLED = 3,
    SERVO_SIGN_RESULT_CANCEL_RECOVERY_FAILED = 4,
    SERVO_SIGN_RESULT_HOME_FAILED = 5
} servo_sign_result_t;

typedef struct
{
    servo_sign_state_t state;
    servo_sign_result_t result_code;
    uint32_t sequence_id;
    uint32_t completed_count;
    servo_sign_action_t last_action;
} servo_sign_status_t;

servo_sign_request_result_t servo_bus_sign_demo_request(
    servo_sign_action_t action,
    uint32_t sequence_id);
int servo_bus_sign_demo_get_status(servo_sign_status_t *status);

#endif
