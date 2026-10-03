"""Unit tests for offline no-servo UART acceptance toolkit."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from no_servo_uart_acceptance import (  # noqa: E402
    LINK_TIMEOUT_MS,
    VISION_STALE_MS,
    SequenceGuard,
    TitanAcceptor,
    builtin_scenarios,
    extract_frames_from_text,
    run_all_builtin,
    run_events,
    score_scenario,
    static_uart_no_servo_write_proof,
)
from protocol import encode_frame  # noqa: E402


class SequenceGuardTests(unittest.TestCase):
    def test_first_in_order_dup_old_gap_rollover(self):
        g = SequenceGuard()
        self.assertEqual(g.note(10), "FIRST")
        self.assertEqual(g.note(11), "IN_ORDER")
        self.assertEqual(g.note(11), "DUPLICATE")
        self.assertEqual(g.note(10), "OLD")
        self.assertEqual(g.note(15), "FORWARD_GAP")
        g = SequenceGuard()
        self.assertEqual(g.note(65535), "FIRST")
        self.assertEqual(g.note(0), "IN_ORDER")
        g = SequenceGuard()
        self.assertEqual(g.note(0), "FIRST")
        self.assertEqual(g.note(65535), "OLD")
        g = SequenceGuard()
        self.assertEqual(g.note(0), "FIRST")
        self.assertEqual(g.note(0x8000), "OLD")


class AcceptorPathTests(unittest.TestCase):
    def test_all_builtin_scenarios_pass(self):
        report = run_all_builtin()
        self.assertTrue(report["all_passed"], json.dumps(report, ensure_ascii=False, indent=2))
        self.assertFalse(report["hardware_accessed"])
        self.assertFalse(report["serial_opened"])
        self.assertGreaterEqual(report["scenarios_total"], 8)

    def test_ping_does_not_refresh_vision_time(self):
        events = [
            {"kind": "frame", "now_ms": 1000, "type": "VISION", "seq": 1,
             "args": [39, 320, 240, 80, 120, 90]},
            {"kind": "frame", "now_ms": 1100, "type": "PING", "seq": 2, "args": []},
            {"kind": "time", "now_ms": 1000 + VISION_STALE_MS - 1},
        ]
        titan, _ = run_events(events)
        self.assertTrue(titan.vision.have_vision)
        self.assertEqual(titan.vision.last_vision_ms, 1000)
        titan.tick(1000 + VISION_STALE_MS)
        self.assertFalse(titan.vision.have_vision)

    def test_duplicate_does_not_change_last_vision_ms(self):
        # Stay inside VISION_STALE_MS so expiry does not mask the dup behavior.
        events = [
            {"kind": "frame", "now_ms": 50, "type": "VISION", "seq": 3,
             "args": [39, 320, 240, 80, 120, 90]},
            {"kind": "frame", "now_ms": 200, "type": "VISION", "seq": 3,
             "args": [41, 320, 240, 80, 120, 90]},
        ]
        titan, _ = run_events(events)
        self.assertEqual(titan.vision.last_vision_ms, 50)
        self.assertEqual(titan.vision.last_class_id, 39)
        self.assertGreaterEqual(titan.stats.ignored_duplicate, 1)

    def test_invalid_payload_ack1_and_clear(self):
        events = [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1,
             "args": [39, 320, 240, 80, 120, 90]},
            {"kind": "frame", "now_ms": 5, "type": "VISION", "seq": 2,
             "args": [39, 320, 240, 0, 120, 90]},
        ]
        titan, acks = run_events(events)
        self.assertEqual(acks[-1]["args"], [1])
        self.assertFalse(titan.vision.have_vision)
        self.assertFalse(titan.vision.have_actionable)

    def test_empty_pose_never_actionable_for_supported_class(self):
        events = [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1,
             "args": [39, 320, 240, 80, 120, 95]},
        ]
        titan, _ = run_events(events)
        self.assertEqual(titan.vision.last_action, "CYLINDRICAL_GRASP")
        self.assertEqual(titan.vision.last_pose, "NOT_CONFIGURED")
        self.assertFalse(titan.vision.have_actionable)

    def test_offline_resets_sequence_baseline(self):
        events = [
            {"kind": "frame", "now_ms": 0, "type": "PING", "seq": 50, "args": []},
            {"kind": "time", "now_ms": LINK_TIMEOUT_MS},
            {"kind": "frame", "now_ms": LINK_TIMEOUT_MS + 1, "type": "PING", "seq": 1, "args": []},
        ]
        titan, _ = run_events(events)
        self.assertGreaterEqual(titan.stats.offline_events, 1)
        self.assertEqual(titan.seq.last_accepted, 1)
        self.assertTrue(titan.link_online)


class LogAndStaticProofTests(unittest.TestCase):
    def test_extract_frames_from_mixed_log(self):
        ping = encode_frame("PING", 7).decode("ascii")
        vision = encode_frame("VISION", 8, 39, 1, 2, 3, 4, 90).decode("ascii")
        text = "boot\n" + ping + "noise\n" + vision + "tail\n"
        blob = extract_frames_from_text(text)
        self.assertIn(b"$PING,7*", blob)
        self.assertIn(b"$VISION,8,", blob)

    def test_uart_c_has_no_servo_write_tokens(self):
        path = PROJECT_ROOT / "titan_rtthread" / "smart_hand_uart.c"
        proof = static_uart_no_servo_write_proof(path)
        self.assertTrue(proof["ok"], proof)

    def test_cli_all_scenarios_exit_zero(self):
        import no_servo_uart_acceptance as mod

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.json"
            code = mod.main(["--json-out", str(out), "--prove-no-servo-write"])
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(report["all_passed"])
            self.assertTrue(report["no_servo_write_proof"]["ok"])
            self.assertFalse(report["hardware_accessed"])


class BuiltinInventoryTests(unittest.TestCase):
    def test_expected_scenario_names_present(self):
        names = set(builtin_scenarios())
        for required in (
            "ping_link_only",
            "class_mapping_empty_pose",
            "reject_low_and_unsupported",
            "invalid_vision_clears",
            "duplicate_and_old",
            "stale_with_ping",
            "offline_resets_sequence",
            "rollover_65535_to_0",
        ):
            self.assertIn(required, names)


if __name__ == "__main__":
    unittest.main()
