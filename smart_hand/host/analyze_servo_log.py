"""Validate a single-finger CSV log and create a dependency-free HTML report."""

import argparse
import csv
import html
import json
from pathlib import Path


SERVO_FIELDS = {
    index: {
        "role": "servo{}_role".format(index),
        "target": "servo{}_target_raw".format(index),
        "position": "servo{}_position_raw".format(index),
        "speed": "servo{}_speed_raw".format(index),
        "load": "servo{}_load_raw".format(index),
        "voltage": "servo{}_voltage_raw".format(index),
        "temperature": "servo{}_temperature_raw".format(index),
        "read_ok": "servo{}_read_ok".format(index),
        "age": "servo{}_data_age_ms".format(index),
    }
    for index in (1, 2)
}

REQUIRED_FIELDS = {
    "session_id",
    "trial_id",
    "sample_seq",
    "time_ms",
    *(field for fields in SERVO_FIELDS.values() for field in fields.values()),
}


def _parse_int(value, field, row_number, allow_blank=False):
    value = value.strip()
    if not value and allow_blank:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise ValueError("row {} field {} must be an integer".format(row_number, field)) from error


def read_log(path):
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        missing = sorted(REQUIRED_FIELDS.difference(reader.fieldnames))
        if missing:
            raise ValueError("CSV missing required fields: {}".format(", ".join(missing)))

        rows = []
        previous_time = None
        previous_sequence = None
        session_id = None
        trial_id = None
        for row_number, raw in enumerate(reader, start=2):
            time_ms = _parse_int(raw["time_ms"], "time_ms", row_number)
            sample_seq = _parse_int(raw["sample_seq"], "sample_seq", row_number)
            if time_ms < 0 or sample_seq < 0:
                raise ValueError("row {} time and sequence must be non-negative".format(row_number))
            if previous_time is not None and time_ms < previous_time:
                raise ValueError("row {} time_ms decreased".format(row_number))
            if previous_sequence is not None and sample_seq <= previous_sequence:
                raise ValueError("row {} sample_seq is not strictly increasing".format(row_number))

            current_session = raw["session_id"].strip()
            current_trial = raw["trial_id"].strip()
            if not current_session or not current_trial:
                raise ValueError("row {} session_id and trial_id are required".format(row_number))
            if session_id is None:
                session_id, trial_id = current_session, current_trial
            elif current_session != session_id or current_trial != trial_id:
                raise ValueError("one log file must contain exactly one session_id/trial_id")

            parsed = dict(raw)
            parsed["time_ms"] = time_ms
            parsed["sample_seq"] = sample_seq
            for fields in SERVO_FIELDS.values():
                read_ok = _parse_int(raw[fields["read_ok"]], fields["read_ok"], row_number)
                if read_ok not in (0, 1):
                    raise ValueError("row {} read_ok must be 0 or 1".format(row_number))
                parsed[fields["read_ok"]] = read_ok
                parsed[fields["age"]] = _parse_int(
                    raw[fields["age"]], fields["age"], row_number, allow_blank=not read_ok
                )
                for key in ("target", "position", "speed", "load", "voltage", "temperature"):
                    field = fields[key]
                    parsed[field] = _parse_int(raw[field], field, row_number, allow_blank=True)
                if read_ok == 0:
                    feedback = ("position", "speed", "load", "voltage", "temperature")
                    if any(parsed[fields[key]] is not None for key in feedback):
                        raise ValueError(
                            "row {} failed read must not contain fresh feedback values".format(row_number)
                        )
            rows.append(parsed)
            previous_time = time_ms
            previous_sequence = sample_seq

    if not rows:
        raise ValueError("CSV contains no samples")
    return rows


def _range(values):
    values = [value for value in values if value is not None]
    return {"minimum": min(values), "maximum": max(values)} if values else None


def analyze(rows):
    duration_ms = rows[-1]["time_ms"] - rows[0]["time_ms"]
    intervals = [
        current["time_ms"] - previous["time_ms"]
        for previous, current in zip(rows, rows[1:])
    ]
    result = {
        "session_id": rows[0]["session_id"],
        "trial_id": rows[0]["trial_id"],
        "samples": len(rows),
        "duration_ms": duration_ms,
        "mean_interval_ms": (sum(intervals) / len(intervals)) if intervals else None,
        "servo": {},
    }
    for index, fields in SERVO_FIELDS.items():
        ok_rows = [row for row in rows if row[fields["read_ok"]] == 1]
        errors = []
        for row in ok_rows:
            target = row[fields["target"]]
            position = row[fields["position"]]
            errors.append(target - position if target is not None and position is not None else None)
        result["servo"][str(index)] = {
            "role": next((row[fields["role"]].strip() for row in rows if row[fields["role"]].strip()), ""),
            "successful_reads": len(ok_rows),
            "failed_reads": len(rows) - len(ok_rows),
            "position_raw": _range(row[fields["position"]] for row in ok_rows),
            "position_error_raw": _range(errors),
            "speed_raw": _range(row[fields["speed"]] for row in ok_rows),
            "load_raw": _range(row[fields["load"]] for row in ok_rows),
            "voltage_raw": _range(row[fields["voltage"]] for row in ok_rows),
            "temperature_raw": _range(row[fields["temperature"]] for row in ok_rows),
            "max_data_age_ms": max(
                (row[fields["age"]] for row in ok_rows if row[fields["age"]] is not None),
                default=None,
            ),
        }
    return result


def _svg_chart(rows, title, field_pairs):
    width, height = 920, 230
    left, right, top, bottom = 62, 18, 28, 38
    points = []
    for label, field, color in field_pairs:
        values = [(row["time_ms"], row[field]) for row in rows if row[field] is not None]
        if values:
            points.append((label, values, color))
    if not points:
        return "<section><h3>{}</h3><p>No valid samples.</p></section>".format(html.escape(title))

    all_x = [x for _, values, _ in points for x, _ in values]
    all_y = [y for _, values, _ in points for _, y in values]
    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = min(all_y), max(all_y)
    if x_min == x_max:
        x_max += 1
    if y_min == y_max:
        y_min -= 1
        y_max += 1

    def sx(value):
        return left + (value - x_min) * (width - left - right) / (x_max - x_min)

    def sy(value):
        return top + (y_max - value) * (height - top - bottom) / (y_max - y_min)

    paths = []
    legends = []
    for offset, (label, values, color) in enumerate(points):
        path = " ".join(
            ("M" if index == 0 else "L") + "{:.1f},{:.1f}".format(sx(x), sy(y))
            for index, (x, y) in enumerate(values)
        )
        paths.append('<path d="{}" fill="none" stroke="{}" stroke-width="2"/>'.format(path, color))
        legends.append(
            '<text x="{}" y="18" fill="{}">{}</text>'.format(
                left + offset * 150, color, html.escape(label)
            )
        )
    return """<section><h3>{title}</h3>
<svg viewBox="0 0 {width} {height}" role="img" aria-label="{title}">
<rect x="{left}" y="{top}" width="{plot_width}" height="{plot_height}" fill="none" stroke="#64748b"/>
{legends}
<text x="8" y="{top}" fill="currentColor">{y_max}</text>
<text x="8" y="{y_bottom}" fill="currentColor">{y_min}</text>
<text x="{left}" y="{height_minus}" fill="currentColor">{x_min} ms</text>
<text x="{right_label}" y="{height_minus}" text-anchor="end" fill="currentColor">{x_max} ms</text>
{paths}</svg></section>""".format(
        title=html.escape(title), width=width, height=height, left=left, top=top,
        plot_width=width-left-right, plot_height=height-top-bottom,
        legends="".join(legends), y_max=y_max, y_min=y_min,
        y_bottom=height-bottom, height_minus=height-8, right_label=width-right,
        x_min=x_min, x_max=x_max, paths="".join(paths),
    )


def write_html_report(rows, summary, output_path):
    colors = ("#2563eb", "#ea580c", "#16a34a", "#9333ea")
    charts = []
    for metric, label in (
        ("position", "Target and position (raw)"),
        ("load", "Reported load (raw, not force)"),
        ("voltage", "Reported voltage register (raw)"),
        ("temperature", "Reported temperature register (raw)"),
    ):
        pairs = []
        if metric == "position":
            pairs = [
                ("S1 target", SERVO_FIELDS[1]["target"], colors[0]),
                ("S1 position", SERVO_FIELDS[1]["position"], colors[1]),
                ("S2 target", SERVO_FIELDS[2]["target"], colors[2]),
                ("S2 position", SERVO_FIELDS[2]["position"], colors[3]),
            ]
        else:
            pairs = [
                ("Servo 1", SERVO_FIELDS[1][metric], colors[0]),
                ("Servo 2", SERVO_FIELDS[2][metric], colors[1]),
            ]
        charts.append(_svg_chart(rows, label, pairs))

    document = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Single finger servo log report</title>
<style>body{{font:15px system-ui;margin:24px;max-width:1100px;color:#172033;background:#f8fafc}}
section{{background:#fff;border:1px solid #cbd5e1;border-radius:10px;padding:14px;margin:14px 0}}
svg{{width:100%;height:auto}}pre{{white-space:pre-wrap}}.warning{{color:#b45309}}</style>
<h1>Single finger servo log report</h1>
<p class="warning">All plotted servo values are raw registers until the driver conversion is verified.</p>
<pre>{summary}</pre>{charts}</html>""".format(
        summary=html.escape(json.dumps(summary, ensure_ascii=False, indent=2)),
        charts="".join(charts),
    )
    Path(output_path).write_text(document, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="HTML report path")
    args = parser.parse_args(argv)
    rows = read_log(args.input)
    summary = analyze(rows)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.output:
        write_html_report(rows, summary, args.output)
        print("report:", args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

