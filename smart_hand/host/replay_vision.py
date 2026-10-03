"""Replay timestamped vision payloads through the production target tracker."""

import argparse
import csv
import io
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from target_tracker import TargetTracker, VisionScheduler  # noqa: E402


REQUIRED_COLUMNS = (
    "time_ms",
    "class_id",
    "center_x",
    "center_y",
    "width",
    "height",
    "confidence",
)
UINT32_MAX = 0xFFFFFFFF


def _integer(row, name, line_number):
    try:
        return int(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "line {}: {} must be an integer".format(line_number, name)
        ) from exc


def parse_observations(stream):
    reader = csv.DictReader(stream)
    missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or ())]
    if missing:
        raise ValueError("missing CSV columns: {}".format(", ".join(missing)))

    observations = []
    previous_time_ms = None
    for line_number, row in enumerate(reader, start=2):
        time_ms = _integer(row, "time_ms", line_number)
        if time_ms < 0:
            raise ValueError("line {}: time_ms must not be negative".format(line_number))
        if previous_time_ms is not None and time_ms < previous_time_ms:
            raise ValueError("line {}: timestamps must be nondecreasing".format(line_number))
        previous_time_ms = time_ms

        class_text = (row.get("class_id") or "").strip()
        if not class_text or class_text.upper() == "NONE":
            payload = None
        else:
            payload = (
                _integer(row, "class_id", line_number),
                _integer(row, "center_x", line_number),
                _integer(row, "center_y", line_number),
                _integer(row, "width", line_number),
                _integer(row, "height", line_number),
                _integer(row, "confidence", line_number),
            )
            class_id, center_x, center_y, width, height, confidence = payload
            if not (
                0 <= class_id <= 65535
                and 0 <= center_x <= UINT32_MAX
                and 0 <= center_y <= UINT32_MAX
                and 0 < width <= UINT32_MAX
                and 0 < height <= UINT32_MAX
                and 0 <= confidence <= 100
            ):
                raise ValueError("line {}: payload is out of range".format(line_number))
        observations.append((time_ms, payload))
    if not observations:
        raise ValueError("CSV contains no observations")
    return observations


def parse_probe_log(stream):
    rows = []
    for line in stream:
        marker = line.find("REPLAY,")
        if marker < 0:
            continue
        row = line[marker + len("REPLAY,") :].strip()
        if row.startswith("time_ms,"):
            continue
        if row:
            rows.append(row)
    if not rows:
        raise ValueError("probe log contains no REPLAY rows")
    csv_text = ",".join(REQUIRED_COLUMNS) + "\n" + "\n".join(rows) + "\n"
    return parse_observations(io.StringIO(csv_text))


def replay_observations(
    observations,
    stable_frames=3,
    stale_timeout_ms=750,
    match_iou=0.2,
    send_interval_ms=500,
    output=print,
):
    tracker = TargetTracker(stable_frames, stale_timeout_ms, match_iou)
    scheduler = VisionScheduler(tracker, 0, send_interval_ms)
    events = []
    sends = []

    def elapsed_ms(now_ms, previous_ms):
        return now_ms - previous_ms

    for time_ms, payload in observations:
        before = (tracker.acquired, tracker.switches, tracker.lost)
        scheduler.observe(payload, time_ms, elapsed_ms)
        after = (tracker.acquired, tracker.switches, tracker.lost)
        for index, name in enumerate(("acquired", "switch", "lost")):
            if after[index] > before[index]:
                event = (time_ms, name, tracker.active)
                events.append(event)
                if output is not None:
                    output("{}ms target {}: {}".format(time_ms, name, tracker.active))

        send_payload = scheduler.take_send_payload(time_ms, elapsed_ms)
        if send_payload is not None:
            sends.append((time_ms, send_payload))
            if output is not None:
                output("{}ms VISION: {}".format(time_ms, send_payload))

    if output is not None:
        output(
            "Replay summary: observations={} sends={} {}".format(
                len(observations), len(sends), tracker.summary()
            )
        )
    return {"tracker": tracker, "events": events, "sends": sends}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--probe-log",
        action="store_true",
        help="extract REPLAY-prefixed rows from mixed yolo_probe console output",
    )
    parser.add_argument("--stable-frames", type=int, default=3)
    parser.add_argument("--stale-timeout-ms", type=int, default=750)
    parser.add_argument("--match-iou", type=float, default=0.2)
    parser.add_argument("--send-interval-ms", type=int, default=500)
    args = parser.parse_args()

    try:
        with args.input.open("r", encoding="utf-8-sig", newline="") as stream:
            if args.probe_log:
                observations = parse_probe_log(stream)
            else:
                observations = parse_observations(stream)
        replay_observations(
            observations,
            stable_frames=args.stable_frames,
            stale_timeout_ms=args.stale_timeout_ms,
            match_iou=args.match_iou,
            send_interval_ms=args.send_interval_ms,
        )
    except (OSError, ValueError) as exc:
        print("Vision replay failed:", exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
