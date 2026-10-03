"""One-command, hardware-free rehearsal of the single-finger control path.

This deliberately stops before any serial or servo API.  It proves that a
stable supported vision target reaches the execution state model, unsupported
targets are rejected, a link loss requests a safe stop, UART parser recovery
cases pass, and the unmeasured calibration file keeps physical motion blocked.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from execution_state_model import ExecutionStateMachine  # noqa: E402
from generate_uart_fault_corpus import build_cases, verify_cases  # noqa: E402
from grip_policy_model import NO_ACTION, decide_grip  # noqa: E402
from replay_vision import parse_observations, replay_observations  # noqa: E402
from servo_safety_model import load_calibrations  # noqa: E402


def _elapsed(now_ms, previous_ms):
    return now_ms - previous_ms


def run_rehearsal(project_root=PROJECT_ROOT):
    replay_path = project_root / "host" / "vision_replay_example.csv"
    calibration_path = project_root / "config" / "servo_calibration_template.csv"
    with replay_path.open("r", encoding="utf-8", newline="") as stream:
        observations = parse_observations(stream)
    replay = replay_observations(observations, output=None)

    decisions = [
        {"time_ms": time_ms, **decide_grip(payload)}
        for time_ms, payload in replay["sends"]
    ]
    accepted = [item for item in decisions if item["action"] != NO_ACTION]
    rejected = [item for item in decisions if item["action"] == NO_ACTION]
    if not accepted or not rejected:
        raise RuntimeError("replay must exercise accepted and rejected policies")

    execution = ExecutionStateMachine(target_timeout_ms=750)
    execution.set_link(True, 0)
    if not execution.arm(0):
        raise RuntimeError("execution model did not arm on an online link")
    first = accepted[0]
    if not execution.note_target(1, first["action"], first["time_ms"]):
        raise RuntimeError("accepted target did not enter execution model")
    if not execution.request_grasp(first["time_ms"] + 1, _elapsed):
        raise RuntimeError("fresh target did not start simulated grasp")
    execution.note_contact_stable(first["time_ms"] + 2)
    stop_result = execution.set_link(False, first["time_ms"] + 3)
    if stop_result != "safe_stop_required" or execution.state != "FAULT":
        raise RuntimeError("link loss did not fail safe during simulated motion")

    uart_failures = verify_cases(build_cases())
    if uart_failures:
        raise RuntimeError("UART fault corpus failed: {}".format(uart_failures))

    calibration_block_reason = None
    try:
        load_calibrations(calibration_path)
    except ValueError as exc:
        calibration_block_reason = str(exc)
    if calibration_block_reason is None:
        raise RuntimeError("template unexpectedly contains production calibration")

    return {
        "result": "PASS",
        "hardware_accessed": False,
        "vision": {
            "observations": len(observations),
            "transmissions": len(replay["sends"]),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "tracker": replay["tracker"].summary(),
        },
        "execution_failure_path": {
            "event": "link_loss_while_holding",
            "result": stop_result,
            "final_state": execution.state,
            "fault_reason": execution.fault_reason,
        },
        "uart_fault_cases": len(build_cases()),
        "physical_motion": {
            "authorized": False,
            "reason": calibration_block_reason,
            "calibration_file": str(calibration_path),
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_rehearsal()
    except (OSError, ValueError, RuntimeError) as exc:
        print("OFFLINE REHEARSAL FAILED:", exc, file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print("Evidence written to", output)
    print("OFFLINE SINGLE-FINGER REHEARSAL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
