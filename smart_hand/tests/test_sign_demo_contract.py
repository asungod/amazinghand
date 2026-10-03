"""Offline contract checks for the fixed Titan sign-sequence bank."""

import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UART_SOURCE = (PROJECT_ROOT / "titan_rtthread" / "smart_hand_uart.c").read_text(
    encoding="utf-8"
)
SERVO_SOURCE = (
    PROJECT_ROOT / "titan_rtthread" / "servo_bus_readonly_rt.c"
).read_text(encoding="utf-8")


class SignDemoContractTests(unittest.TestCase):
    def test_uart_accepts_only_fixed_three_field_sign_request(self):
        self.assertIn("SMART_HAND_SIGN_ARG_COUNT 3U", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_OPEN_PALM", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_FIST", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_V_SIGN", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_POINT", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_THUMBS_UP", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_L_SHAPE", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_OK_PINCH", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_HELLO_WORD", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_THANKS_WORD", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_HELP_SIGNAL", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_NO_WORD", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_ATTENTION_WORD", UART_SOURCE)
        self.assertIn("SERVO_SIGN_SEQUENCE_LIKE_WORD", UART_SOURCE)
        self.assertIn("case SHP_TYPE_SIGN:", UART_SOURCE)

    def test_sign_motion_uses_only_precompiled_bounded_targets(self):
        self.assertIn("g_servo_official_close", SERVO_SOURCE)
        self.assertIn("g_servo_official_open", SERVO_SOURCE)
        self.assertIn("g_servo_v_sign", SERVO_SOURCE)
        self.assertIn(
            "{452u, 690u, 332u, 570u, 758u, 264u, 690u, 332u}",
            SERVO_SOURCE,
        )
        self.assertIn("g_servo_point", SERVO_SOURCE)
        self.assertIn("g_servo_thumbs_up", SERVO_SOURCE)
        self.assertIn("g_servo_l_shape", SERVO_SOURCE)
        self.assertIn("g_servo_ok_pinch", SERVO_SOURCE)
        self.assertIn("g_servo_thanks_thumb_bend", SERVO_SOURCE)
        self.assertIn("g_servo_help_thumb_tucked", SERVO_SOURCE)
        self.assertIn("g_servo_no_side_a", SERVO_SOURCE)
        self.assertIn("g_servo_no_side_b", SERVO_SOURCE)
        self.assertIn("g_servo_attention_bend", SERVO_SOURCE)
        self.assertIn("hold_sign_duration", SERVO_SOURCE)
        self.assertIn("run_sign_demo_once", SERVO_SOURCE)
        self.assertNotIn("g_servo_sign_targets", SERVO_SOURCE)
        self.assertIn("target != g_servo_index_lateral_center", SERVO_SOURCE)
        self.assertIn("soft_min_raw", SERVO_SOURCE)
        self.assertIn("soft_max_raw", SERVO_SOURCE)

    def test_demo_speedup_keeps_step_and_soft_limit_guards(self):
        self.assertIn("SERVO_PAIR_COMMISSION_SPEED 80u", SERVO_SOURCE)
        self.assertIn("SERVO_GROUP_MOTION_SETTLE_MS 50u", SERVO_SOURCE)
        self.assertIn(".max_step_raw = 30u", SERVO_SOURCE)
        self.assertIn("target[index] < g_eight_servo_calibration[index].soft_min_raw", SERVO_SOURCE)

    def test_index_lateral_test_is_fixed_mailbox_only_and_recovers_open(self):
        self.assertIn("SERVO_INDEX_LATERAL_MAGIC 0x534D4C31u", SERVO_SOURCE)
        self.assertIn(
            "{392u, 630u, 332u, 690u, 332u, 690u, 332u, 690u}",
            SERVO_SOURCE,
        )
        self.assertIn(
            "{332u, 570u, 332u, 690u, 332u, 690u, 332u, 690u}",
            SERVO_SOURCE,
        )
        self.assertIn(
            "{452u, 690u, 332u, 690u, 332u, 690u, 332u, 690u}",
            SERVO_SOURCE,
        )
        test_body = SERVO_SOURCE.split(
            "static uint32_t run_index_lateral_test_once(void)", 1
        )[1].split("\n}\n\nstatic int decode_pair_commission_request", 1)[0]
        self.assertIn("g_servo_official_open", test_body)
        self.assertNotIn("g_sign_demo_pending_sequence_id", test_body)

    def test_cancel_is_bounded_and_recovers_to_official_open(self):
        self.assertIn("SERVO_SIGN_STATE_CANCELLING", SERVO_SOURCE)
        self.assertIn("SERVO_SIGN_RESULT_CANCEL_RECOVERY_FAILED", SERVO_SOURCE)
        self.assertIn("g_servo_official_open, &no_cancel", SERVO_SOURCE)

    def test_active_cancel_correlates_status_with_cancel_request(self):
        cancel = SERVO_SOURCE.split(
            "if (action == SERVO_SIGN_ACTION_CANCEL)", 1
        )[1].split(
            "if (action == SERVO_SIGN_ACTION_HOME && g_sign_demo_active)", 1
        )[0]
        active_cancel = cancel.split("if (g_sign_demo_active)", 1)[1].split(
            "else if (g_sign_demo_pending_action", 1
        )[0]
        normalized = " ".join(active_cancel.split())
        self.assertIn(
            "g_sign_demo_last_action = SERVO_SIGN_ACTION_CANCEL;", normalized
        )
        self.assertIn("g_sign_demo_sequence_id = sequence_id;", normalized)

    def test_active_home_always_requests_home_recovery(self):
        home = SERVO_SOURCE.split(
            "if (action == SERVO_SIGN_ACTION_HOME && g_sign_demo_active)", 1
        )[1].split("if (!g_ready || !g_eight_servo_gate.initialized)", 1)[0]
        normalized = " ".join(home.split())
        self.assertIn("g_sign_demo_home_requested = 1u;", normalized)
        self.assertNotIn("g_sign_demo_last_action == SERVO_SIGN_ACTION_START", normalized)

    def test_start_path_does_not_consult_vision_actionable_state(self):
        sign_case = UART_SOURCE.split("case SHP_TYPE_SIGN:", 1)[1].split(
            "case SHP_TYPE_TRAIN:", 1
        )[0]
        self.assertNotIn("have_actionable_target", sign_case)
        self.assertNotIn("last_pose_result", sign_case)
        self.assertIn("link_was_online", sign_case)

    def test_start_and_home_require_existing_online_link_but_cancel_does_not(self):
        sign_case = UART_SOURCE.split("case SHP_TYPE_SIGN:", 1)[1].split(
            "case SHP_TYPE_TRAIN:", 1
        )[0]
        normalized = " ".join(sign_case.split())
        self.assertIn(
            "if ((action == SERVO_SIGN_ACTION_START || action == "
            "SERVO_SIGN_ACTION_HOME) && !link_was_online)",
            normalized,
        )
        self.assertNotIn(
            "action == SERVO_SIGN_ACTION_CANCEL) && !link_was_online",
            normalized,
        )

    def test_home_cancel_or_link_loss_uses_uncancelled_open_recovery(self):
        home = SERVO_SOURCE.split("static uint32_t run_sign_home_once(void)", 1)[1].split(
            "\n}\n\nstatic void process_sign_demo_request", 1
        )[0]
        normalized = " ".join(home.split())
        self.assertIn("volatile uint8_t no_cancel = 0u", normalized)
        self.assertIn(
            "run_group_target_commission_ex( g_servo_official_open, &no_cancel)",
            normalized,
        )
        self.assertIn("SERVO_SIGN_RESULT_CANCELLED", normalized)
        self.assertIn("SERVO_SIGN_RESULT_CANCEL_RECOVERY_FAILED", normalized)
        self.assertIn("SERVO_SIGN_RESULT_HOME_FAILED", normalized)

    def test_train_request_is_busy_while_sign_active_or_pending(self):
        train_request = SERVO_SOURCE.split(
            "servo_rehab_request_result_t servo_bus_rehab_demo_request(void)",
            1,
        )[1].split("\n}\n\nint servo_bus_rehab_demo_get_status", 1)[0]
        normalized = " ".join(train_request.split())
        self.assertIn(
            "else if (g_rehab_demo_active || g_servo_pair_commission_request != 0u "
            "|| g_sign_demo_active || g_sign_demo_pending_action != 0u)",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
