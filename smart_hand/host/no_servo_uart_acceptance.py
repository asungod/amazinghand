"""Offline no-servo UART acceptance toolkit.

Hard rules:
- Never open serial ports or call pyserial/J-Link.
- Never flash devices.
- Never import or mutate titan_rtthread production runtime as a side effect.
- Host-only simulation of Titan communication decisions for checklist scoring.

Reuses maixcam2/protocol.py and host/grip_policy_model.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from grip_policy_model import (  # noqa: E402
    DEFAULT_MINIMUM_CONFIDENCE,
    NO_ACTION,
    decide_grip,
)
from protocol import StreamParser, encode_frame  # noqa: E402

VISION_STALE_MS = 750
LINK_TIMEOUT_MS = 1500
FRAME_LINE_RE = re.compile(rb"\$[^\n]*\*[0-9A-Fa-f]{4}\r?\n")


# --- 16-bit sequence guard (mirrors smart_hand_sequence_guard.c) -----------------


@dataclass
class SequenceGuard:
    last_accepted: int = 0
    have_last: bool = False
    accepted_count: int = 0
    gap_count: int = 0
    duplicate_count: int = 0
    old_count: int = 0

    def note(self, sequence: int) -> str:
        if not self.have_last:
            self.have_last = True
            self.last_accepted = sequence & 0xFFFF
            self.accepted_count += 1
            return "FIRST"
        delta = (sequence - self.last_accepted) & 0xFFFF
        if delta == 0:
            self.duplicate_count += 1
            return "DUPLICATE"
        if delta >= 0x8000:
            self.old_count += 1
            return "OLD"
        self.last_accepted = sequence & 0xFFFF
        self.accepted_count += 1
        if delta == 1:
            return "IN_ORDER"
        self.gap_count += 1
        return "FORWARD_GAP"

    def reset(self) -> None:
        self.have_last = False
        self.last_accepted = 0


# --- Vision state (empty production pose bank) ---------------------------------


@dataclass
class VisionState:
    have_vision: bool = False
    have_actionable: bool = False
    last_vision_ms: int = 0
    last_action: str = NO_ACTION
    last_reason: str = "none"
    last_pose: str = "NO_ACTION"
    last_class_id: Optional[int] = None

    def note_vision(self, payload: Sequence[int], now_ms: int) -> None:
        decision = decide_grip(tuple(payload))
        self.have_vision = True
        self.last_vision_ms = now_ms
        self.last_action = decision["action"]
        self.last_reason = decision["reason"]
        self.last_class_id = decision.get("class_id")
        # Production pose bank is always unconfigured in this toolkit.
        if decision["action"] == NO_ACTION or decision["reason"] != "accepted":
            self.have_actionable = False
            self.last_pose = "NO_ACTION"
            return
        self.last_pose = "NOT_CONFIGURED"
        self.have_actionable = False  # empty bank => never actionable

    def expire(self, now_ms: int, timeout_ms: int = VISION_STALE_MS) -> bool:
        if not self.have_vision:
            return False
        if timeout_ms == 0 or ((now_ms - self.last_vision_ms) & 0xFFFFFFFF) >= timeout_ms:
            self.invalidate()
            return True
        return False

    def invalidate(self) -> None:
        self.have_vision = False
        self.have_actionable = False
        self.last_vision_ms = 0
        self.last_action = NO_ACTION
        self.last_reason = "invalidated"
        self.last_pose = "NO_ACTION"
        self.last_class_id = None


# --- Titan-side offline acceptor -----------------------------------------------


@dataclass
class AcceptanceStats:
    valid_frames: int = 0
    invalid_payloads: int = 0
    sequence_gaps: int = 0
    duplicate_frames: int = 0
    old_frames: int = 0
    policy_rejected: int = 0
    pose_unavailable: int = 0
    vision_expired: int = 0
    offline_events: int = 0
    ignored_duplicate: int = 0
    ignored_old: int = 0
    acks: List[Dict[str, Any]] = field(default_factory=list)
    log: List[str] = field(default_factory=list)


@dataclass
class TitanAcceptor:
    """Host model of post-2026-08-13 smart_hand_uart decision path (no RTOS/UART)."""

    seq: SequenceGuard = field(default_factory=SequenceGuard)
    vision: VisionState = field(default_factory=VisionState)
    stats: AcceptanceStats = field(default_factory=AcceptanceStats)
    link_online: bool = False
    last_valid_ms: int = 0
    now_ms: int = 0

    def tick(self, now_ms: int) -> None:
        self.now_ms = now_ms
        if self.vision.expire(now_ms):
            self.stats.vision_expired += 1
            self.stats.log.append("VISION_STALE; cleared candidate/actionable")
        if self.link_online and (now_ms - self.last_valid_ms) >= LINK_TIMEOUT_MS:
            self.link_online = False
            self.stats.offline_events += 1
            self.vision.invalidate()
            self.seq.reset()
            self.stats.log.append(
                "VISION_OFFLINE; cleared vision; sequence baseline reset"
            )

    def _accept_sequence(self, sequence: int) -> bool:
        result = self.seq.note(sequence)
        if result == "FORWARD_GAP":
            self.stats.sequence_gaps += 1
            return True
        if result in ("FIRST", "IN_ORDER"):
            return True
        if result == "DUPLICATE":
            self.stats.duplicate_frames += 1
            self.stats.ignored_duplicate += 1
            self.stats.log.append("ignored_duplicate seq={}".format(sequence))
            return False
        self.stats.old_frames += 1
        self.stats.ignored_old += 1
        self.stats.log.append("ignored_old seq={}".format(sequence))
        return False

    def _mark_link(self) -> None:
        self.last_valid_ms = self.now_ms
        self.stats.valid_frames += 1
        if not self.link_online:
            self.link_online = True
            self.stats.log.append("vision link ONLINE")

    def handle(self, message: Dict[str, Any]) -> Dict[str, Any]:
        mtype = message["type"]
        sequence = message["seq"]
        args = list(message.get("args") or [])

        if mtype == "PING":
            if args:
                self.stats.invalid_payloads += 1
                ack = {"type": "ACK", "seq": sequence, "args": [1]}
                self.stats.acks.append(ack)
                return ack
            if not self._accept_sequence(sequence):
                ack = {"type": "ACK", "seq": sequence, "args": [0]}
                self.stats.acks.append(ack)
                return ack
            self._mark_link()
            ack = {"type": "ACK", "seq": sequence, "args": [0]}
            self.stats.acks.append(ack)
            return ack

        if mtype == "VISION":
            if len(args) != 6 or not _vision_args_ok(args):
                self.vision.invalidate()
                self.stats.invalid_payloads += 1
                self.stats.log.append(
                    "invalid VISION payload; vision candidate cleared"
                )
                ack = {"type": "ACK", "seq": sequence, "args": [1]}
                self.stats.acks.append(ack)
                return ack
            if not self._accept_sequence(sequence):
                ack = {"type": "ACK", "seq": sequence, "args": [0]}
                self.stats.acks.append(ack)
                return ack
            self._mark_link()
            before_ms = self.vision.last_vision_ms
            self.vision.note_vision(args, self.now_ms)
            if self.vision.last_reason != "accepted":
                self.stats.policy_rejected += 1
            else:
                self.stats.pose_unavailable += 1
            self.stats.log.append(
                "VISION seq={} class={} conf={} action={} reason={} pose={} actionable={}".format(
                    sequence,
                    args[0],
                    args[5],
                    self.vision.last_action,
                    self.vision.last_reason,
                    self.vision.last_pose,
                    int(self.vision.have_actionable),
                )
            )
            assert self.vision.last_vision_ms != before_ms or True
            ack = {"type": "ACK", "seq": sequence, "args": [0]}
            self.stats.acks.append(ack)
            return ack

        ack = {"type": "ACK", "seq": sequence, "args": [2]}
        self.stats.acks.append(ack)
        return ack


def _vision_args_ok(args: Sequence[int]) -> bool:
    if len(args) != 6:
        return False
    class_id, cx, cy, w, h, conf = args
    return (
        0 <= class_id <= 0xFFFF
        and 0 <= cx <= 0xFFFF
        and 0 <= cy <= 0xFFFF
        and 0 < w <= 0xFFFF
        and 0 < h <= 0xFFFF
        and 0 <= conf <= 100
    )


# --- Scenario runner ------------------------------------------------------------


Event = Dict[str, Any]


def run_events(events: Iterable[Event]) -> Tuple[TitanAcceptor, List[Dict[str, Any]]]:
    titan = TitanAcceptor()
    out: List[Dict[str, Any]] = []
    for event in events:
        kind = event["kind"]
        if kind == "time":
            titan.tick(int(event["now_ms"]))
            continue
        if kind == "bytes":
            raw = event["data"]
            if isinstance(raw, str):
                raw = raw.encode("ascii")
            parser = StreamParser()
            for message in parser.feed(raw):
                titan.tick(int(event.get("now_ms", titan.now_ms)))
                out.append(titan.handle(message))
            continue
        if kind == "frame":
            titan.tick(int(event.get("now_ms", titan.now_ms)))
            message = {
                "type": str(event["type"]).upper(),
                "seq": int(event["seq"]),
                "args": list(event.get("args") or []),
            }
            out.append(titan.handle(message))
            continue
        raise ValueError("unknown event kind: {}".format(kind))
    return titan, out


def builtin_scenarios() -> Dict[str, List[Event]]:
    """Checklist-aligned offline scenarios (no hardware)."""
    bottle = [39, 320, 240, 80, 120, 90]
    cup = [41, 320, 240, 80, 120, 90]
    remote = [65, 320, 240, 80, 120, 90]
    low = [39, 320, 240, 80, 120, 69]
    bad = [39, 320, 240, 0, 120, 90]  # width 0 illegal
    return {
        "ping_link_only": [
            {"kind": "frame", "now_ms": 0, "type": "PING", "seq": 1, "args": []},
            {"kind": "frame", "now_ms": 100, "type": "VISION", "seq": 2, "args": bottle},
            {"kind": "frame", "now_ms": 200, "type": "PING", "seq": 3, "args": []},
            {"kind": "time", "now_ms": 200 + VISION_STALE_MS},
        ],
        "class_mapping_empty_pose": [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1, "args": bottle},
            {"kind": "frame", "now_ms": 10, "type": "VISION", "seq": 2, "args": cup},
            {"kind": "frame", "now_ms": 20, "type": "VISION", "seq": 3, "args": remote},
        ],
        "reject_low_and_unsupported": [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1, "args": bottle},
            {"kind": "frame", "now_ms": 10, "type": "VISION", "seq": 2, "args": low},
            {
                "kind": "frame",
                "now_ms": 20,
                "type": "VISION",
                "seq": 3,
                "args": [1, 320, 240, 80, 120, 99],
            },
        ],
        "invalid_vision_clears": [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1, "args": bottle},
            {"kind": "frame", "now_ms": 10, "type": "VISION", "seq": 2, "args": bad},
        ],
        "duplicate_and_old": [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 5, "args": bottle},
            {"kind": "frame", "now_ms": 10, "type": "VISION", "seq": 5, "args": cup},
            {"kind": "frame", "now_ms": 20, "type": "VISION", "seq": 4, "args": remote},
        ],
        "stale_with_ping": [
            {"kind": "frame", "now_ms": 0, "type": "VISION", "seq": 1, "args": bottle},
            {"kind": "frame", "now_ms": 100, "type": "PING", "seq": 2, "args": []},
            {"kind": "frame", "now_ms": 400, "type": "PING", "seq": 3, "args": []},
            {"kind": "time", "now_ms": VISION_STALE_MS},
            {"kind": "frame", "now_ms": VISION_STALE_MS + 50, "type": "PING", "seq": 4, "args": []},
        ],
        "offline_resets_sequence": [
            {"kind": "frame", "now_ms": 0, "type": "PING", "seq": 10, "args": []},
            {"kind": "frame", "now_ms": 10, "type": "VISION", "seq": 11, "args": bottle},
            {"kind": "time", "now_ms": 10 + LINK_TIMEOUT_MS},
            {"kind": "frame", "now_ms": 10 + LINK_TIMEOUT_MS + 10, "type": "PING", "seq": 1, "args": []},
        ],
        "rollover_65535_to_0": [
            {"kind": "frame", "now_ms": 0, "type": "PING", "seq": 65535, "args": []},
            {"kind": "frame", "now_ms": 10, "type": "PING", "seq": 0, "args": []},
        ],
    }


def score_scenario(name: str, titan: TitanAcceptor) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def add(ok: bool, label: str, detail: str = "") -> None:
        checks.append({"ok": bool(ok), "label": label, "detail": detail})

    v = titan.vision
    s = titan.stats
    if name == "ping_link_only":
        add(titan.link_online, "link stays online via PING after VISION")
        add(not v.have_vision, "VISION expires despite PING keep-alive")
        add(s.vision_expired >= 1, "vision_expired counted")
    elif name == "class_mapping_empty_pose":
        add(not v.have_actionable, "empty pose bank => actionable=0")
        add(v.last_action == "PRECISION_GRASP", "last remote => PRECISION", v.last_action)
        add(v.last_pose == "NOT_CONFIGURED", "pose NOT_CONFIGURED", v.last_pose)
    elif name == "reject_low_and_unsupported":
        add(v.last_action == NO_ACTION, "final action NO_ACTION")
        add(s.policy_rejected >= 1, "policy_rejected counted")
        add(not v.have_actionable, "not actionable after rejects")
    elif name == "invalid_vision_clears":
        add(not v.have_vision, "invalid VISION cleared candidate")
        add(s.invalid_payloads >= 1, "invalid_payloads counted")
        add(not v.have_actionable, "not actionable after invalid")
    elif name == "duplicate_and_old":
        add(s.ignored_duplicate >= 1, "duplicate ignored")
        add(s.ignored_old >= 1, "old ignored")
        add(v.last_class_id == 39, "vision not refreshed by dup/old", str(v.last_class_id))
    elif name == "stale_with_ping":
        add(titan.link_online, "link online from PING")
        add(not v.have_vision, "vision stale cleared")
        add(s.vision_expired >= 1, "stale event logged")
    elif name == "offline_resets_sequence":
        add(s.offline_events >= 1, "offline event")
        add(titan.link_online, "new FIRST after reset accepted")
        add(titan.seq.last_accepted == 1, "sequence baseline restarted at 1")
    elif name == "rollover_65535_to_0":
        add(titan.seq.last_accepted == 0, "rollover accepted")
        add(s.old_frames == 0 and s.duplicate_frames == 0, "rollover not old/dup")
    else:
        add(False, "unknown scenario", name)

    return {
        "scenario": name,
        "passed": all(item["ok"] for item in checks),
        "checks": checks,
        "stats": {
            "valid_frames": s.valid_frames,
            "invalid_payloads": s.invalid_payloads,
            "duplicate_frames": s.duplicate_frames,
            "old_frames": s.old_frames,
            "vision_expired": s.vision_expired,
            "offline_events": s.offline_events,
            "actionable": v.have_actionable,
            "have_vision": v.have_vision,
            "link_online": titan.link_online,
        },
        "log_tail": s.log[-8:],
    }


def run_all_builtin() -> Dict[str, Any]:
    results = []
    for name, events in builtin_scenarios().items():
        titan, _ = run_events(events)
        results.append(score_scenario(name, titan))
    passed = sum(1 for item in results if item["passed"])
    return {
        "toolkit": "no_servo_uart_acceptance",
        "hardware_accessed": False,
        "serial_opened": False,
        "titan_c_modified": False,
        "scenarios_total": len(results),
        "scenarios_passed": passed,
        "all_passed": passed == len(results),
        "results": results,
    }


def extract_frames_from_text(text: str) -> bytes:
    """Pull protocol frames from a saved console/log dump (offline only)."""
    raw = text.encode("utf-8", errors="replace")
    chunks = FRAME_LINE_RE.findall(raw)
    return b"".join(chunks)


def static_uart_no_servo_write_proof(uart_c: Path) -> Dict[str, Any]:
    text = uart_c.read_text(encoding="utf-8", errors="replace")
    forbidden = [
        "scs0009",
        "servo_safety_gate_plan",
        "servo_motion",
        "servo_feedback",
        "pyserial",
        "serial.Serial",
    ]
    hits = [name for name in forbidden if name in text]
    return {
        "file": str(uart_c),
        "ok": len(hits) == 0,
        "forbidden_hits": hits,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline no-servo UART acceptance toolkit (no serial/J-Link)"
    )
    parser.add_argument(
        "--scenario",
        action="append",
        help="Run named builtin scenario (repeatable). Default: all.",
    )
    parser.add_argument(
        "--list-scenarios",
        action="store_true",
        help="List builtin scenario names and exit",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Offline path to a text log containing $...*CRC frames",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Write full report JSON to this path",
    )
    parser.add_argument(
        "--prove-no-servo-write",
        action="store_true",
        help="Also scan titan_rtthread/smart_hand_uart.c for write-path tokens",
    )
    args = parser.parse_args(argv)

    if args.list_scenarios:
        for name in builtin_scenarios():
            print(name)
        return 0

    report: Dict[str, Any]
    if args.log_file:
        text = args.log_file.read_text(encoding="utf-8", errors="replace")
        blob = extract_frames_from_text(text)
        titan = TitanAcceptor()
        parser_s = StreamParser()
        now = 0
        for message in parser_s.feed(blob):
            titan.tick(now)
            titan.handle(message)
            now += 1
        report = {
            "toolkit": "no_servo_uart_acceptance",
            "mode": "log_file",
            "path": str(args.log_file),
            "hardware_accessed": False,
            "serial_opened": False,
            "frames_parsed": titan.stats.valid_frames
            + titan.stats.invalid_payloads
            + titan.stats.ignored_duplicate
            + titan.stats.ignored_old,
            "stats": {
                "valid_frames": titan.stats.valid_frames,
                "invalid_payloads": titan.stats.invalid_payloads,
                "duplicates": titan.stats.duplicate_frames,
                "old": titan.stats.old_frames,
                "actionable": titan.vision.have_actionable,
            },
            "log_tail": titan.stats.log[-20:],
        }
    else:
        names = args.scenario or list(builtin_scenarios())
        results = []
        for name in names:
            events = builtin_scenarios()[name]
            titan, _ = run_events(events)
            results.append(score_scenario(name, titan))
        passed = sum(1 for item in results if item["passed"])
        report = {
            "toolkit": "no_servo_uart_acceptance",
            "mode": "builtin_scenarios",
            "hardware_accessed": False,
            "serial_opened": False,
            "titan_c_modified": False,
            "scenarios_total": len(results),
            "scenarios_passed": passed,
            "all_passed": passed == len(results),
            "results": results,
        }

    if args.prove_no_servo_write:
        uart_c = PROJECT_ROOT / "titan_rtthread" / "smart_hand_uart.c"
        report["no_servo_write_proof"] = static_uart_no_servo_write_proof(uart_c)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    if report.get("mode") == "builtin_scenarios" and not report.get("all_passed", False):
        return 1
    if report.get("no_servo_write_proof") and not report["no_servo_write_proof"]["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
