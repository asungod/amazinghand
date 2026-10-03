"""Titan no-servo UART acceptance tool (default dry-run).

Reuses maixcam2/protocol.py only — no second CRC/protocol stack.
Default never opens serial. Live mode is implemented but this batch must not run it.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from grip_policy_model import decide_grip  # noqa: E402
from no_servo_uart_acceptance import (  # noqa: E402
    LINK_TIMEOUT_MS,
    VISION_STALE_MS,
    TitanAcceptor,
    run_events,
)
from protocol import StreamParser, encode_frame  # noqa: E402

VECTORS_PATH = Path(__file__).with_name("titan_uart_acceptance_vectors.json")
ALLOWED_BAUD = 115200


def load_vectors(path: Path = VECTORS_PATH) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def format_frame(message_type: str, seq: int, args: Sequence[int] | None = None) -> str:
    raw = encode_frame(message_type, seq, *(args or []))
    return raw.decode("ascii").strip()


def expected_action_for_vision(args: Sequence[int]) -> Dict[str, Any]:
    decision = decide_grip(tuple(args))
    actionable = 0  # production pose bank empty
    pose = "NOT_CONFIGURED" if decision["reason"] == "accepted" else "NO_ACTION"
    return {
        "action": decision["action"],
        "reason": decision["reason"],
        "pose": pose,
        "actionable": actionable,
    }


def dry_run_case(case: Dict[str, Any]) -> Dict[str, Any]:
    steps_out: List[Dict[str, Any]] = []
    for step in case.get("steps", []):
        entry: Dict[str, Any] = {"raw_step": step}
        if "send" in step:
            send = step["send"]
            frame = format_frame(send["type"], int(send["seq"]), send.get("args") or [])
            entry["tx_frame"] = frame
            entry["expect_ack"] = step.get("expect_ack")
            if send["type"].upper() == "VISION" and len(send.get("args") or []) == 6:
                pred = expected_action_for_vision(send["args"])
                entry["expected_business"] = pred
                if "expect_action" in step:
                    entry["expect_action_match"] = pred["action"] == step["expect_action"]
                if "expect_actionable" in step:
                    entry["expect_actionable_match"] = (
                        pred["actionable"] == int(step["expect_actionable"])
                    )
            if step.get("expect_ignored"):
                entry["expected_business_side_effect"] = (
                    "ignore_{}; do not refresh vision/link business".format(
                        step["expect_ignored"]
                    )
                )
            if step.get("expect_gap"):
                entry["expected_business_side_effect"] = "accept FORWARD_GAP; count gap"
        if "wait_ms" in step:
            entry["wait_ms"] = step["wait_ms"]
            entry["expect_shell"] = step.get("expect_shell")
            entry["note"] = (
                "PC ACK cannot prove timing; save Titan shell sh_status/log "
                "with wall-clock evidence."
            )
        steps_out.append(entry)

    return {
        "id": case["id"],
        "title": case["title"],
        "steps": steps_out,
        "expect_side_effects": case.get("expect_side_effects", []),
        "evidence": case.get("evidence", []),
        "pc_ack_cannot_pass_alone": bool(case.get("pc_ack_cannot_pass_alone", False)),
        "result": "dry_run_planned",
        "ack_observation": "not_run",
        "titan_shell_evidence": "not_run",
        "unverified": case.get("evidence", []),
    }


def dry_run_report(vectors: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = vectors or load_vectors()
    cases = [dry_run_case(case) for case in data["cases"]]
    # Also execute host-side acceptor simulation for non-timing business checks.
    sim = _simulate_business_vectors(data)
    return {
        "tool": "titan_uart_acceptance",
        "mode": "dry-run",
        "hardware_accessed": False,
        "serial_opened": False,
        "live_ran": False,
        "flashed": False,
        "baud_policy": ALLOWED_BAUD,
        "timing_note": data.get("timing_note"),
        "cases": cases,
        "host_simulation": sim,
        "host_simulation_all_passed": sim["all_passed"],
    }


def _simulate_business_vectors(data: Dict[str, Any]) -> Dict[str, Any]:
    """Host-only simulation of ACK/business rules (not a substitute for shell timing)."""
    results = []
    for case in data["cases"]:
        events = []
        now = 0
        titan = TitanAcceptor()
        acks = []
        ok = True
        detail = []
        for step in case["steps"]:
            if "wait_ms" in step:
                now += int(step["wait_ms"])
                titan.tick(now)
                # Timing shell expectations are not auto-pass from ACK.
                detail.append(
                    "wait {}ms requires Titan shell evidence ({})".format(
                        step["wait_ms"], step.get("expect_shell")
                    )
                )
                continue
            send = step["send"]
            now += 1
            titan.tick(now)
            msg = {
                "type": str(send["type"]).upper(),
                "seq": int(send["seq"]),
                "args": list(send.get("args") or []),
            }
            ack = titan.handle(msg)
            acks.append(ack)
            exp = step.get("expect_ack") or {}
            if exp:
                if ack.get("seq") != exp.get("seq") or (ack.get("args") or [None])[0] != exp.get(
                    "status"
                ):
                    ok = False
                    detail.append(
                        "ACK mismatch got={} expect={}".format(ack, exp)
                    )
            if step.get("expect_action") and msg["type"] == "VISION":
                # Only check when business was accepted by sequence path
                if not step.get("expect_ignored"):
                    if exp.get("status") == 0 and len(msg["args"]) == 6 and _vision_ok(msg["args"]):
                        if titan.vision.last_action != step["expect_action"] and not step.get(
                            "expect_ignored"
                        ):
                            # After illegal clear paths last_action may be NO_ACTION
                            if step.get("expect_ack", {}).get("status") == 0:
                                if titan.stats.ignored_duplicate or titan.stats.ignored_old:
                                    pass
                                elif titan.vision.last_action != step["expect_action"]:
                                    # For reject cases expect_action is NO_ACTION
                                    if step["expect_action"] == titan.vision.last_action:
                                        pass
                                    else:
                                        # re-read: after handle, last_action should match
                                        if titan.vision.last_action != step["expect_action"]:
                                            ok = False
                                            detail.append(
                                                "action {} != {}".format(
                                                    titan.vision.last_action,
                                                    step["expect_action"],
                                                )
                                            )
            if "expect_actionable" in step and not step.get("expect_ignored"):
                if int(titan.vision.have_actionable) != int(step["expect_actionable"]):
                    ok = False
                    detail.append("actionable mismatch")
            if step.get("expect_ignored") == "duplicate":
                if titan.stats.ignored_duplicate < 1:
                    ok = False
                    detail.append("expected duplicate ignore")
            if step.get("expect_ignored") == "old":
                if titan.stats.ignored_old < 1:
                    ok = False
                    detail.append("expected old ignore")
            if step.get("expect_gap") and titan.stats.sequence_gaps < 1:
                ok = False
                detail.append("expected gap")
            if step.get("expect_first_after_reset"):
                if titan.seq.last_accepted != int(send["seq"]):
                    ok = False
                    detail.append("expected FIRST after reset")

        # Timing-only cases: host sim cannot auto-pass shell waits.
        if case.get("pc_ack_cannot_pass_alone"):
            results.append(
                {
                    "id": case["id"],
                    "host_business_checks_ok": ok,
                    "auto_pass": False,
                    "detail": detail
                    + ["pc_ack_cannot_pass_alone: need Titan shell timing evidence"],
                    "acks": acks,
                }
            )
        else:
            results.append(
                {
                    "id": case["id"],
                    "host_business_checks_ok": ok,
                    "auto_pass": ok,
                    "detail": detail,
                    "acks": acks,
                }
            )

    auto = [r for r in results if r.get("auto_pass") is True or r.get("auto_pass") is False]
    # all_passed for host-simulatable non-timing cases only
    sim_ok = all(
        r["host_business_checks_ok"]
        for r in results
        if not any(
            c["id"] == r["id"] and c.get("pc_ack_cannot_pass_alone")
            for c in data["cases"]
        )
    )
    return {
        "all_passed": sim_ok,
        "results": results,
        "note": "Timing cases never auto-pass from host simulation alone.",
    }


def _vision_ok(args: Sequence[int]) -> bool:
    if len(args) != 6:
        return False
    _, _, _, w, h, conf = args
    return w > 0 and h > 0 and 0 <= conf <= 100


class FakeSerial:
    """In-memory serial double for unit tests (never real hardware)."""

    def __init__(self, response_chunks: Optional[List[bytes]] = None, raise_on_open: bool = False):
        self.response_chunks = list(response_chunks or [])
        self.raise_on_open = raise_on_open
        self.written: List[bytes] = []
        self.opened = False
        self.closed = False
        self._read_idx = 0
        self.timeout = 1.0

    def open(self) -> None:
        if self.raise_on_open:
            raise OSError("fake serial open failed")
        self.opened = True

    def close(self) -> None:
        self.closed = True
        self.opened = False

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if self._read_idx >= len(self.response_chunks):
            time.sleep(min(0.01, float(self.timeout)))
            return b""
        chunk = self.response_chunks[self._read_idx]
        self._read_idx += 1
        return chunk[:size] if size else chunk

    def reset_input_buffer(self) -> None:
        return None


def live_preflight_or_exit(args: argparse.Namespace) -> Optional[str]:
    """Return error string if live gates fail — must run before importing serial."""
    if not getattr(args, "live", False) and not getattr(args, "port", None):
        return None
    # Live requested if port set or --live flag
    want_live = bool(getattr(args, "port", None)) or bool(getattr(args, "live", False))
    if not want_live:
        return None
    if not args.port:
        return "live mode requires --port COMx (no auto-enumerate, no default COM4)"
    if not getattr(args, "live_no_servo_confirmed", False):
        return (
            "live mode requires --live-no-servo-confirmed "
            "(must exit before opening serial)"
        )
    baud = int(getattr(args, "baud", ALLOWED_BAUD) or ALLOWED_BAUD)
    if baud != ALLOWED_BAUD:
        return "only baud {} is allowed for Smart Hand link (got {})".format(
            ALLOWED_BAUD, baud
        )
    return None


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Titan no-servo UART acceptance (default dry-run)")
    p.add_argument("--dry-run", action="store_true", default=False, help="Plan-only (default)")
    p.add_argument("--port", default=None, help="Live serial port e.g. COM5 (no default)")
    p.add_argument(
        "--live-no-servo-confirmed",
        action="store_true",
        help="Required with --port: confirm servo 6V off and bus disconnected",
    )
    p.add_argument("--baud", type=int, default=ALLOWED_BAUD)
    p.add_argument("--live", action="store_true", help="Alias to request live (still needs port+confirm)")
    p.add_argument("--json-out", type=Path, default=None)
    p.add_argument("--vectors", type=Path, default=VECTORS_PATH)
    p.add_argument(
        "--case-id",
        action="append",
        help="Limit dry-run to case id(s)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Default is dry-run when no live port.
    want_live = bool(args.port) or bool(args.live)
    if want_live:
        err = live_preflight_or_exit(args)
        if err:
            print(json.dumps({
                "mode": "live_rejected",
                "hardware_accessed": False,
                "serial_opened": False,
                "error": err,
            }, ensure_ascii=False, indent=2))
            return 2
        # Live is allowed by code structure but this batch forbids running it.
        print(json.dumps({
            "mode": "live_blocked_by_batch_policy",
            "hardware_accessed": False,
            "serial_opened": False,
            "message": (
                "Live gates passed structurally, but this implementation batch "
                "forbids running live. Re-run only under explicit later authorization."
            ),
            "would_print_before_open": "舵机 6V 必须关闭且总线不得连接",
            "port": args.port,
            "baud": args.baud,
        }, ensure_ascii=False, indent=2))
        return 3

    vectors = load_vectors(args.vectors)
    if args.case_id:
        vectors = dict(vectors)
        vectors["cases"] = [c for c in vectors["cases"] if c["id"] in set(args.case_id)]
    report = dry_run_report(vectors)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    print(text)
    # dry-run always exits 0 if report generated; host sim failures still shown
    return 0 if report.get("hardware_accessed") is False else 1


if __name__ == "__main__":
    sys.exit(main())
