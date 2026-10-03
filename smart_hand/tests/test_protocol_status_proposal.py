"""Offline draft codec for the frozen Titan STATUS v1 snapshot.

Does not modify maixcam2/protocol.py or Titan C. The production encoder is
used only as the existing ASCII/$/CRC framing layer, which already allows
TYPE=STATUS with at most eight arguments.

hardware_accessed must stay false.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from protocol import StreamParser, decode_frame, encode_frame  # noqa: E402


STATUS_VERSION = 1
STATUS_ARG_COUNT = 8

FLAG_LINK_ONLINE = 1 << 0
FLAG_HAVE_VISION = 1 << 1
FLAG_VISION_STALE = 1 << 2
FLAG_HAVE_LAST_RX = 1 << 3
FLAG_GATE_PRESENT = 1 << 4
FLAG_GATE_ARMED = 1 << 5
FLAG_GATE_FAULT = 1 << 6
FLAG_HAVE_ACTIONABLE = 1 << 7

ACTION_NONE = 0
ACTION_CYLINDRICAL = 1
ACTION_POWER = 2
ACTION_PRECISION = 3

REASON_ACCEPTED = 0
REASON_INVALID_PAYLOAD = 1
REASON_INVALID_CONFIGURATION = 2
REASON_LOW_CONFIDENCE = 3
REASON_UNSUPPORTED_CLASS = 4

POSE_OK = 0
POSE_NO_ACTION = 1
POSE_NOT_CONFIGURED = 2
POSE_INVALID_PROFILE = 3

SUBMIT_UNKNOWN = 0
SUBMIT_NOT_CONFIGURED = 1
SUBMIT_BLOCKED = 2
SUBMIT_SUBMITTED = 3

FAULT_NONE = 0
FAULT_UNKNOWN = 255

UNKNOWN_SNAPSHOT = {
    "ver": None,
    "flags": 0,
    "link_online": None,
    "have_vision": None,
    "vision_stale": None,
    "have_last_rx": False,
    "gate_present": None,
    "gate_armed": None,
    "gate_fault": None,
    "have_actionable": None,
    "last_rx_seq": None,
    "action": None,
    "reason": None,
    "pose": None,
    "submit": SUBMIT_UNKNOWN,
    "fault": FAULT_UNKNOWN,
    "tx_seq": None,
}


def derive_submit(pose, gate_present, gate_blocked, write_observed_ok):
    if pose in (POSE_NOT_CONFIGURED, POSE_INVALID_PROFILE):
        return SUBMIT_NOT_CONFIGURED
    if not gate_present:
        return SUBMIT_UNKNOWN
    if gate_blocked:
        return SUBMIT_BLOCKED
    if write_observed_ok:
        return SUBMIT_SUBMITTED
    return SUBMIT_UNKNOWN


def pack_flags(
    *,
    link_online,
    have_vision,
    vision_stale,
    have_last_rx,
    gate_present=False,
    gate_armed=False,
    gate_fault=False,
    have_actionable=False,
):
    flags = 0
    if link_online:
        flags |= FLAG_LINK_ONLINE
    if have_vision:
        flags |= FLAG_HAVE_VISION
    if vision_stale:
        flags |= FLAG_VISION_STALE
    if have_last_rx:
        flags |= FLAG_HAVE_LAST_RX
    if gate_present:
        flags |= FLAG_GATE_PRESENT
        if gate_armed:
            flags |= FLAG_GATE_ARMED
        if gate_fault:
            flags |= FLAG_GATE_FAULT
    if have_actionable:
        flags |= FLAG_HAVE_ACTIONABLE
    return flags


def encode_status(tx_seq, args):
    if len(args) != STATUS_ARG_COUNT:
        raise ValueError("STATUS must have exactly 8 arguments")
    return encode_frame("STATUS", tx_seq, *args)


def decode_status_frame(frame):
    message = decode_frame(frame)
    return interpret_status(message)


def interpret_status(message):
    if message["type"] != "STATUS":
        raise ValueError("not a STATUS frame")
    args = message["args"]
    if len(args) != STATUS_ARG_COUNT:
        raise ValueError("STATUS argument count must be 8")
    ver, flags, last_rx_seq, action, reason, pose, submit, fault = args
    if ver != STATUS_VERSION:
        raise ValueError("unsupported STATUS version")
    if flags > 0xFFFF:
        raise ValueError("flags out of range")
    if last_rx_seq > 0xFFFF:
        raise ValueError("last_rx_seq out of range")
    if action not in (0, 1, 2, 3):
        raise ValueError("action out of range")
    if reason not in (0, 1, 2, 3, 4):
        raise ValueError("reason out of range")
    if pose not in (0, 1, 2, 3):
        raise ValueError("pose out of range")
    if submit not in (0, 1, 2, 3):
        raise ValueError("submit out of range")
    if fault != FAULT_UNKNOWN and not 0 <= fault <= 12:
        raise ValueError("fault out of range")

    gate_present = bool(flags & FLAG_GATE_PRESENT)
    snapshot = {
        "ver": ver,
        "flags": flags,
        "link_online": bool(flags & FLAG_LINK_ONLINE),
        "have_vision": bool(flags & FLAG_HAVE_VISION),
        "vision_stale": bool(flags & FLAG_VISION_STALE),
        "have_last_rx": bool(flags & FLAG_HAVE_LAST_RX),
        "gate_present": gate_present,
        "gate_armed": None if not gate_present else bool(flags & FLAG_GATE_ARMED),
        "gate_fault": None if not gate_present else bool(flags & FLAG_GATE_FAULT),
        "have_actionable": bool(flags & FLAG_HAVE_ACTIONABLE),
        "last_rx_seq": last_rx_seq if flags & FLAG_HAVE_LAST_RX else None,
        "action": action,
        "reason": reason,
        "pose": pose,
        "submit": submit,
        "fault": fault if gate_present else FAULT_UNKNOWN,
        "tx_seq": message["seq"],
    }
    if not gate_present and submit == SUBMIT_SUBMITTED:
        raise ValueError("SUBMITTED is illegal without a servo write path")
    if pose in (POSE_NOT_CONFIGURED, POSE_INVALID_PROFILE):
        if submit != SUBMIT_NOT_CONFIGURED:
            raise ValueError("unconfigured pose must report submit=NOT_CONFIGURED")
        if snapshot["have_actionable"]:
            raise ValueError("unconfigured pose cannot be actionable")
    return snapshot


def apply_status(snapshot, frame):
    """Update authority snapshot only from a well-formed v1 STATUS."""
    try:
        return decode_status_frame(frame)
    except ValueError:
        return snapshot


class StatusProposalWireTest(unittest.TestCase):
    def test_frozen_status_has_exactly_eight_args(self):
        flags = pack_flags(
            link_online=True,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
        )
        args = [1, flags, 7, ACTION_CYLINDRICAL, REASON_ACCEPTED,
                POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN]
        frame = encode_status(10, args)
        message = decode_frame(frame)
        self.assertEqual(message["type"], "STATUS")
        self.assertEqual(message["seq"], 10)
        self.assertEqual(len(message["args"]), 8)
        self.assertEqual(message["args"], args)
        self.assertTrue(frame.startswith(b"$STATUS,10,"))
        self.assertTrue(frame.endswith(b"\r\n"))
        self.assertIn(b"*", frame)

    def test_seven_or_nine_args_are_illegal(self):
        with self.assertRaises(ValueError):
            encode_status(1, [1, 11, 7, 1, 0, 2, 1])
        # Production encode_frame() refuses >8 args at the wire layer.
        # Nine-arg STATUS is checked on the already-decoded message dict.
        nine = [1, 11, 7, 1, 0, 2, 1, 255, 0]
        with self.assertRaises(ValueError):
            interpret_status({"type": "STATUS", "seq": 1, "args": nine})

    def test_crc_covers_body_between_dollar_and_star(self):
        frame = encode_status(
            3,
            [1, 11, 4, ACTION_NONE, REASON_LOW_CONFIDENCE,
             POSE_NO_ACTION, SUBMIT_UNKNOWN, FAULT_UNKNOWN],
        )
        star = frame.rfind(b"*")
        body = frame[1:star]
        from protocol import crc16_ccitt

        self.assertEqual(
            int(frame[star + 1 : star + 5], 16),
            crc16_ccitt(body),
        )
        self.assertNotIn(b"$", body)
        self.assertNotIn(b"*", body)


class StatusProposalScenarioTest(unittest.TestCase):
    def test_normal_accepted_but_pose_not_configured(self):
        flags = pack_flags(
            link_online=True,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
            have_actionable=False,
        )
        self.assertEqual(flags, 11)
        args = [
            1,
            flags,
            7,
            ACTION_CYLINDRICAL,
            REASON_ACCEPTED,
            POSE_NOT_CONFIGURED,
            derive_submit(POSE_NOT_CONFIGURED, False, False, False),
            FAULT_UNKNOWN,
        ]
        snap = decode_status_frame(encode_status(10, args))
        self.assertEqual(snap["action"], ACTION_CYLINDRICAL)
        self.assertEqual(snap["reason"], REASON_ACCEPTED)
        self.assertEqual(snap["pose"], POSE_NOT_CONFIGURED)
        self.assertEqual(snap["submit"], SUBMIT_NOT_CONFIGURED)
        self.assertFalse(snap["have_actionable"])
        self.assertIsNone(snap["gate_armed"])
        self.assertEqual(snap["fault"], FAULT_UNKNOWN)
        self.assertEqual(snap["last_rx_seq"], 7)

    def test_pose_not_configured_rejects_submitted_claim(self):
        flags = pack_flags(
            link_online=True,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
        )
        illegal = [
            1, flags, 7, ACTION_POWER, REASON_ACCEPTED,
            POSE_NOT_CONFIGURED, SUBMIT_SUBMITTED, FAULT_UNKNOWN,
        ]
        with self.assertRaises(ValueError):
            interpret_status({"type": "STATUS", "seq": 1, "args": illegal})

    def test_low_confidence_is_rejected_not_submitted(self):
        flags = pack_flags(
            link_online=True,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
        )
        submit = derive_submit(POSE_NO_ACTION, False, False, False)
        self.assertEqual(submit, SUBMIT_UNKNOWN)
        snap = decode_status_frame(
            encode_status(
                11,
                [1, flags, 8, ACTION_NONE, REASON_LOW_CONFIDENCE,
                 POSE_NO_ACTION, submit, FAULT_UNKNOWN],
            )
        )
        self.assertEqual(snap["reason"], REASON_LOW_CONFIDENCE)
        self.assertEqual(snap["action"], ACTION_NONE)
        self.assertEqual(snap["pose"], POSE_NO_ACTION)
        self.assertEqual(snap["submit"], SUBMIT_UNKNOWN)
        self.assertNotEqual(snap["submit"], SUBMIT_SUBMITTED)

    def test_vision_stale_clears_candidate_and_keeps_sticky_flag(self):
        flags = pack_flags(
            link_online=True,
            have_vision=False,
            vision_stale=True,
            have_last_rx=True,
        )
        self.assertEqual(flags, 13)
        snap = decode_status_frame(
            encode_status(
                12,
                [1, flags, 8, ACTION_NONE, REASON_INVALID_PAYLOAD,
                 POSE_NO_ACTION, SUBMIT_UNKNOWN, FAULT_UNKNOWN],
            )
        )
        self.assertTrue(snap["vision_stale"])
        self.assertFalse(snap["have_vision"])
        self.assertTrue(snap["link_online"])
        self.assertEqual(snap["submit"], SUBMIT_UNKNOWN)
        self.assertFalse(snap["have_actionable"])

    def test_crc_error_is_dropped_and_snapshot_unchanged(self):
        good = encode_status(
            20,
            [1, 11, 4, ACTION_CYLINDRICAL, REASON_ACCEPTED,
             POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
        )
        snapshot = decode_status_frame(good)
        broken = bytearray(good)
        body_index = 3
        broken[body_index] ^= 0x01
        parser = StreamParser()
        recovered = parser.feed(bytes(broken) + good)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["type"], "STATUS")
        self.assertEqual(apply_status(snapshot, bytes(broken)), snapshot)
        self.assertEqual(apply_status(snapshot, good)["last_rx_seq"], 4)

    def test_duplicate_inbound_sequence_does_not_advance_last_rx(self):
        accepted = decode_status_frame(
            encode_status(
                30,
                [1, 11, 4, ACTION_PRECISION, REASON_ACCEPTED,
                 POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
            )
        )
        self.assertEqual(accepted["last_rx_seq"], 4)
        # Titan would ACK 0 on duplicate inbound seq=4 and keep last_accepted=4.
        after_dup = decode_status_frame(
            encode_status(
                31,
                [1, 11, 4, ACTION_PRECISION, REASON_ACCEPTED,
                 POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
            )
        )
        self.assertEqual(after_dup["last_rx_seq"], 4)
        self.assertEqual(after_dup["tx_seq"], 31)
        self.assertNotEqual(after_dup["tx_seq"], after_dup["last_rx_seq"])

    def test_old_peer_ack_is_unchanged_and_not_a_status(self):
        frame = encode_frame("ACK", 5, 0)
        message = decode_frame(frame)
        self.assertEqual(message, {"type": "ACK", "seq": 5, "args": [0]})
        with self.assertRaises(ValueError):
            interpret_status(message)

    def test_missing_status_keeps_authority_unknown_not_local_intent(self):
        snapshot = dict(UNKNOWN_SNAPSHOT)
        local_intent_action = ACTION_CYLINDRICAL
        self.assertEqual(snapshot["submit"], SUBMIT_UNKNOWN)
        self.assertIsNone(snapshot["action"])
        self.assertNotEqual(snapshot["action"], local_intent_action)
        self.assertIsNone(snapshot["pose"])

    def test_current_firmware_cannot_claim_submitted(self):
        self.assertEqual(
            derive_submit(POSE_NOT_CONFIGURED, False, False, False),
            SUBMIT_NOT_CONFIGURED,
        )
        self.assertEqual(
            derive_submit(POSE_NO_ACTION, False, False, False),
            SUBMIT_UNKNOWN,
        )
        self.assertEqual(
            derive_submit(POSE_OK, False, False, True),
            SUBMIT_UNKNOWN,
        )
        with self.assertRaises(ValueError):
            interpret_status(
                {
                    "type": "STATUS",
                    "seq": 1,
                    "args": [
                        1,
                        pack_flags(
                            link_online=True,
                            have_vision=True,
                            vision_stale=False,
                            have_last_rx=True,
                        ),
                        1,
                        ACTION_CYLINDRICAL,
                        REASON_ACCEPTED,
                        POSE_OK,
                        SUBMIT_SUBMITTED,
                        FAULT_NONE,
                    ],
                }
            )


class ProductionMaixStatusPathTest(unittest.TestCase):
    def test_production_decoder_matches_frozen_eight_args(self):
        from status_snapshot import (
            authority_display_line,
            interpret_status as prod_interpret,
        )

        flags = pack_flags(
            link_online=True,
            have_vision=True,
            vision_stale=False,
            have_last_rx=True,
        )
        frame = encode_status(
            10,
            [1, flags, 7, ACTION_CYLINDRICAL, REASON_ACCEPTED,
             POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
        )
        snap = prod_interpret(decode_frame(frame))
        self.assertEqual(snap["submit"], SUBMIT_NOT_CONFIGURED)
        self.assertIsNone(snap["gate_armed"])
        self.assertEqual(snap["fault"], FAULT_UNKNOWN)
        compact = authority_display_line(snap)
        self.assertLessEqual(len(compact), 48)
        self.assertNotIn("reason=", compact)

    def test_main_handle_message_does_not_count_status_as_ack(self):
        sys.path.insert(0, str(PROJECT_ROOT / "tests"))
        from test_maix_main import load_main_module
        from link_monitor import AckMonitor

        module, fake_time = load_main_module(iterations=0)
        monitor = AckMonitor(1000)
        monitor.record(10, "PING", 0)
        authority = {"snapshot": None}
        frame = encode_status(
            99,
            [1, 11, 7, ACTION_CYLINDRICAL, REASON_ACCEPTED,
             POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
        )
        message = decode_frame(frame)
        module.handle_message(message, monitor, 50, authority)
        self.assertEqual(monitor.acked, 0)
        self.assertEqual(monitor.rejected, 0)
        self.assertEqual(len(monitor.pending), 1)
        self.assertEqual(authority["snapshot"]["tx_seq"], 99)
        self.assertIn("NOT_CONFIGURED", module.authority_status_line(authority["snapshot"]))

    def test_authority_snapshot_expires_without_new_status(self):
        sys.path.insert(0, str(PROJECT_ROOT / "tests"))
        from test_maix_main import load_main_module
        from link_monitor import AckMonitor

        module, _ = load_main_module(iterations=0)
        monitor = AckMonitor(1000)
        authority = {
            "snapshot": dict(module.UNKNOWN_SNAPSHOT),
            "last_status_ms": None,
        }
        frame = encode_status(
            99,
            [1, 11, 7, ACTION_CYLINDRICAL, REASON_ACCEPTED,
             POSE_NOT_CONFIGURED, SUBMIT_NOT_CONFIGURED, FAULT_UNKNOWN],
        )
        module.handle_message(decode_frame(frame), monitor, 0, authority)
        self.assertEqual(authority["last_status_ms"], 0)
        self.assertEqual(authority["snapshot"]["tx_seq"], 99)

        self.assertFalse(module.expire_authority_snapshot(authority, 1499))
        self.assertEqual(authority["snapshot"]["tx_seq"], 99)

        self.assertTrue(module.expire_authority_snapshot(authority, 1500))
        self.assertIsNone(authority["snapshot"]["ver"])
        self.assertIsNone(authority["last_status_ms"])


if __name__ == "__main__":
    unittest.main()
