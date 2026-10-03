"""Evaluate target-tracking parameter combinations against one replay log."""

import argparse
import csv
import itertools
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from replay_vision import (  # noqa: E402
    parse_observations,
    parse_probe_log,
    replay_observations,
)


OUTPUT_FIELDS = (
    "stable_frames",
    "stale_timeout_ms",
    "match_iou",
    "send_interval_ms",
    "first_acquire_ms",
    "first_vision_ms",
    "acquired",
    "switches",
    "lost",
    "sends",
    "active_end",
)


def parse_number_list(text, value_type, name, minimum, maximum=None):
    values = []
    for item in text.split(","):
        try:
            value = value_type(item.strip())
        except ValueError as exc:
            raise ValueError("{} contains an invalid value".format(name)) from exc
        if value < minimum or (maximum is not None and value > maximum):
            raise ValueError("{} contains an out-of-range value".format(name))
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError("{} must not be empty".format(name))
    return values


def sweep_observations(
    observations,
    stable_frames_values,
    stale_timeout_values,
    match_iou_values,
    send_interval_values,
):
    rows = []
    combinations = itertools.product(
        stable_frames_values,
        stale_timeout_values,
        match_iou_values,
        send_interval_values,
    )
    for stable_frames, stale_timeout_ms, match_iou, send_interval_ms in combinations:
        result = replay_observations(
            observations,
            stable_frames=stable_frames,
            stale_timeout_ms=stale_timeout_ms,
            match_iou=match_iou,
            send_interval_ms=send_interval_ms,
            output=None,
        )
        tracker = result["tracker"]
        first_acquire_ms = next(
            (time_ms for time_ms, name, _ in result["events"] if name == "acquired"),
            -1,
        )
        first_vision_ms = result["sends"][0][0] if result["sends"] else -1
        rows.append(
            {
                "stable_frames": stable_frames,
                "stale_timeout_ms": stale_timeout_ms,
                "match_iou": match_iou,
                "send_interval_ms": send_interval_ms,
                "first_acquire_ms": first_acquire_ms,
                "first_vision_ms": first_vision_ms,
                "acquired": tracker.acquired,
                "switches": tracker.switches,
                "lost": tracker.lost,
                "sends": len(result["sends"]),
                "active_end": 1 if tracker.active is not None else 0,
            }
        )
    return rows


def write_rows(rows, stream):
    writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--probe-log", action="store_true")
    parser.add_argument("--stable-frames", default="2,3,4")
    parser.add_argument("--stale-timeout-ms", default="500,750,1000")
    parser.add_argument("--match-iou", default="0.1,0.2,0.3")
    parser.add_argument("--send-interval-ms", default="250,500")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        stable_frames_values = parse_number_list(
            args.stable_frames, int, "stable_frames", 1
        )
        stale_timeout_values = parse_number_list(
            args.stale_timeout_ms, int, "stale_timeout_ms", 1
        )
        match_iou_values = parse_number_list(
            args.match_iou, float, "match_iou", 0.0, 1.0
        )
        send_interval_values = parse_number_list(
            args.send_interval_ms, int, "send_interval_ms", 1
        )
        with args.input.open("r", encoding="utf-8-sig", newline="") as stream:
            observations = (
                parse_probe_log(stream) if args.probe_log else parse_observations(stream)
            )
        rows = sweep_observations(
            observations,
            stable_frames_values,
            stale_timeout_values,
            match_iou_values,
            send_interval_values,
        )
        if args.output is None:
            write_rows(rows, sys.stdout)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8", newline="") as stream:
                write_rows(rows, stream)
            print("Wrote {} parameter combinations to {}".format(len(rows), args.output))
    except (OSError, ValueError) as exc:
        print("Vision parameter sweep failed:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
