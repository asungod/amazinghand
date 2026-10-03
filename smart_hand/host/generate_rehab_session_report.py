"""Generate a local, non-clinical HTML summary from MaixCAM2 session CSV."""

import argparse
import csv
import html
import os
from pathlib import Path

REQUIRED_COLUMNS = (
    "schema",
    "session",
    "outcome",
    "repetitions",
    "goal",
    "completion_pct",
    "demo_ms",
    "imitation_ms",
    "avg_rep_ms",
)
QUALITY_CSV_HEADER = (
    "schema,session,quality_status,rhythm_status,hold_status,"
    "pace_avg_ms,pace_min_ms,pace_max_ms,fast_count,slow_count,"
    "short_hold_count,valid_frame_pct"
)
REASON_CSV_HEADER = "schema,session,outcome,termination_reason"


def _badge(value, labels, kind):
    """Render a local, readable status badge while retaining the raw value."""
    raw = value or "--"
    label = labels.get(raw, raw)
    safe_class = "".join(char.lower() if char.isalnum() else "-" for char in raw)
    return '<span class="badge badge-{}-{}" title="{}">{}</span>'.format(
        kind, safe_class, html.escape(raw), html.escape(label)
    )


OUTCOME_LABELS = {
    "COMPLETE": "已完成",
    "USER_CANCELLED": "主动取消",
    "TIMEOUT": "训练超时",
}
QUALITY_LABELS = {
    "OK": "良好",
    "DEGRADED": "需调整",
    "INSUFFICIENT": "数据不足",
    "UNKNOWN": "未知",
}
RHYTHM_LABELS = {
    "NORMAL": "正常",
    "MIXED": "不稳定",
    "TOO_FAST": "偏快",
    "TOO_SLOW": "偏慢",
    "UNKNOWN": "未知",
}
HOLD_LABELS = {
    "OK": "保持正常",
    "INSUFFICIENT": "保持不足",
    "UNKNOWN": "未知",
}


def quality_feedback(quality_row):
    """Return a user-facing Chinese hint without changing quality semantics.

    The English status fields remain the source of truth and are rendered in
    their original columns.  This helper only adds presentation text; it does
    not classify rows or alter any tracker thresholds.
    """
    if not quality_row:
        return "数据不足，暂不评价"
    quality_status = quality_row.get("quality_status", "UNKNOWN")
    rhythm_status = quality_row.get("rhythm_status", "UNKNOWN")
    hold_status = quality_row.get("hold_status", "UNKNOWN")
    if "UNKNOWN" in (quality_status, rhythm_status, hold_status):
        return "数据不足，暂不评价"
    if hold_status == "INSUFFICIENT":
        return "闭合识别不足，请保持闭合并保持手掌稳定"
    if rhythm_status == "TOO_SLOW":
        return "节奏偏慢，请按提示稍快"
    if rhythm_status == "TOO_FAST":
        return "节奏偏快，请按提示放慢"
    valid_frame_pct = quality_row.get("valid_frame_pct")
    # A value below 100 means at least one observed frame was not a valid
    # OPEN/CLOSED posture. This is a display hint, not a new quality gate.
    if valid_frame_pct is not None and valid_frame_pct < 100.0:
        return "画面跟踪不足，请调整手掌和光线"
    if quality_status == "OK":
        return "动作质量良好，请继续保持"
    return "请按提示调整动作后再试"


def _integer(row, name, minimum=None, maximum=None):
    try:
        value = int(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("{} must be an integer".format(name)) from exc
    if minimum is not None and value < minimum:
        raise ValueError("{} is below {}".format(name, minimum))
    if maximum is not None and value > maximum:
        raise ValueError("{} exceeds {}".format(name, maximum))
    return value


def load_sessions(path):
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError("unexpected CSV columns")
        sessions = []
        seen = set()
        for source in reader:
            schema = _integer(source, "schema", 1, 1)
            session = _integer(source, "session", 1)
            if session in seen:
                raise ValueError("duplicate session {}".format(session))
            seen.add(session)
            outcome = source["outcome"]
            if outcome not in ("COMPLETE", "TIMEOUT"):
                raise ValueError("unknown outcome")
            repetitions = _integer(source, "repetitions", 0)
            goal = _integer(source, "goal", 1)
            completion_pct = _integer(source, "completion_pct", 0, 100)
            demo_ms = _integer(source, "demo_ms", -1)
            imitation_ms = _integer(source, "imitation_ms", 0)
            avg_rep_ms = _integer(source, "avg_rep_ms", -1)
            expected_pct = min(100, int(round(100.0 * repetitions / goal)))
            if completion_pct != expected_pct:
                raise ValueError("completion percentage mismatch")
            if outcome == "COMPLETE" and repetitions < goal:
                raise ValueError("complete session is below goal")
            sessions.append(
                {
                    "schema": schema,
                    "session": session,
                    "outcome": outcome,
                    "repetitions": repetitions,
                    "goal": goal,
                    "completion_pct": completion_pct,
                    "demo_ms": demo_ms,
                    "imitation_ms": imitation_ms,
                    "avg_rep_ms": avg_rep_ms,
                }
            )
    if not sessions:
        raise ValueError("session CSV is empty")
    return sessions


def load_quality(path):
    """Load quality sidecar rows, ignoring malformed or duplicate rows."""
    if path is None or not Path(path).exists():
        return {}
    quality = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(QUALITY_CSV_HEADER.split(",")):
            raise ValueError("unexpected quality CSV columns")
        for source in reader:
            try:
                schema = _integer(source, "schema", 1, 1)
                session = _integer(source, "session", 1)
                if session in quality:
                    continue
                statuses = {
                    key: source[key].strip() for key in
                    ("quality_status", "rhythm_status", "hold_status")
                }
                if any(not value for value in statuses.values()):
                    continue
                values = {}
                for key in ("pace_avg_ms", "pace_min_ms", "pace_max_ms", "fast_count", "slow_count", "short_hold_count"):
                    values[key] = _integer(source, key)
                valid_pct = float(source["valid_frame_pct"])
                if not 0 <= valid_pct <= 100:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            quality[session] = {"schema": schema, "session": session, **statuses, **values,
                                "valid_frame_pct": valid_pct}
    return quality


def load_reasons(path, sessions=None):
    """Load optional reasons, accepting only unique rows matching the main CSV."""
    if path is None or not Path(path).exists():
        return {}
    expected_outcomes = {
        row["session"]: row["outcome"] for row in (sessions or [])
    }
    reasons = {}
    invalid_sessions = set()
    seen_sessions = set()
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(REASON_CSV_HEADER.split(",")):
            raise ValueError("unexpected reason CSV columns")
        for source in reader:
            try:
                _integer(source, "schema", 1, 1)
                session = _integer(source, "session", 1)
                outcome = source["outcome"]
                reason = source["termination_reason"].strip()
                if outcome not in ("COMPLETE", "TIMEOUT") or not reason:
                    continue
                if session in seen_sessions:
                    invalid_sessions.add(session)
                    reasons.pop(session, None)
                    continue
                seen_sessions.add(session)
                if (
                    expected_outcomes
                    and expected_outcomes.get(session) != outcome
                ):
                    invalid_sessions.add(session)
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            reasons[session] = reason
    return {
        session: reason for session, reason in reasons.items()
        if session not in invalid_sessions
    }


def render_html(sessions, quality=None, reasons=None):
    quality = quality or {}
    reasons = reasons or {}
    completed = sum(row["outcome"] == "COMPLETE" for row in sessions)
    total_repetitions = sum(row["repetitions"] for row in sessions)
    average_completion = sum(row["completion_pct"] for row in sessions) / len(sessions)
    completed_sessions = [row for row in sessions if row["outcome"] == "COMPLETE"]
    completed_average = (
        sum(row["completion_pct"] for row in completed_sessions) / len(completed_sessions)
        if completed_sessions
        else 0
    )
    timeout_count = sum(row["outcome"] == "TIMEOUT" for row in sessions)
    cancelled_count = sum(
        row["outcome"] == "TIMEOUT"
        and reasons.get(row["session"]) == "user_cancelled"
        for row in sessions
    )
    explicit_timeout_count = sum(
        row["outcome"] == "TIMEOUT"
        and reasons.get(row["session"]) == "imitation_timeout"
        for row in sessions
    )
    timeout_note = (
        "记录含 {} 条 TIMEOUT，其中 {} 条明确标记为 imitation_timeout；"
        "只有明确 reason=imitation_timeout 的记录计为训练时限/安全超时。"
        "其余 TIMEOUT 原因未作安全测试断言。TIMEOUT 不单独用于推断训练能力下降。"
    ).format(timeout_count, explicit_timeout_count) if timeout_count else "本组记录不含 TIMEOUT。"
    quality_status_counts = {
        status: sum(
            quality.get(row["session"], {}).get("quality_status") == status
            for row in sessions
        )
        for status in ("OK", "DEGRADED", "INSUFFICIENT")
    }
    quality_note = (
        "质量状态独立于训练完成率：OK {} 条，DEGRADED {} 条，INSUFFICIENT {} 条；"
        "没有质量 sidecar 的会话不纳入质量分布。"
    ).format(
        quality_status_counts["OK"],
        quality_status_counts["DEGRADED"],
        quality_status_counts["INSUFFICIENT"],
    )
    rows = []
    trend_rows = []
    valid_averages = [
        row["avg_rep_ms"] for row in sessions if row["avg_rep_ms"] >= 0
    ]
    maximum_average = max(valid_averages) if valid_averages else 1
    for row in sessions:
        display_outcome = (
            "USER_CANCELLED"
            if reasons.get(row["session"]) == "user_cancelled"
            else row["outcome"]
        )
        quality_row = quality.get(row["session"])
        rows.append(
            "<tr><td>{}</td><td>{}</td><td>{}/{}</td><td>{}%</td>"
                "<td>{:.1f}</td><td>{}</td><td>{}</td>"
                "<td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                row["session"],
                _badge(display_outcome, OUTCOME_LABELS, "outcome"),
                row["repetitions"],
                row["goal"],
                row["completion_pct"],
                row["imitation_ms"] / 1000.0,
                "--" if row["avg_rep_ms"] < 0 else "{:.1f}".format(row["avg_rep_ms"] / 1000.0),
                "--" if row["demo_ms"] < 0 else "{:.1f}".format(row["demo_ms"] / 1000.0),
                _badge(quality_row.get("quality_status", "UNKNOWN") if quality_row else "UNKNOWN", QUALITY_LABELS, "quality"),
                _badge(quality_row.get("rhythm_status", "UNKNOWN") if quality_row else "UNKNOWN", RHYTHM_LABELS, "rhythm"),
                _badge(quality_row.get("hold_status", "UNKNOWN") if quality_row else "UNKNOWN", HOLD_LABELS, "hold"),
                html.escape(quality_feedback(quality_row)),
                html.escape(reasons.get(row["session"], "--")),
            )
        )
        average_width = (
            0
            if row["avg_rep_ms"] < 0
            else int(round(100.0 * row["avg_rep_ms"] / maximum_average))
        )
        average_label = (
            "--"
            if row["avg_rep_ms"] < 0
            else "{:.1f}s/次".format(row["avg_rep_ms"] / 1000.0)
        )
        trend_rows.append(
            "<div class=\"trend\"><div class=\"trend-label\">会话 {}</div>"
            "<div class=\"bar-track\"><div class=\"bar completion\" "
            "style=\"width:{}%\"></div></div><span>{}%</span>"
            "<div class=\"bar-track cadence-track\"><div class=\"bar cadence\" "
            "style=\"width:{}%\"></div></div><span class=\"trend-value cadence-value\">{}</span></div>".format(
                row["session"],
                row["completion_pct"],
                row["completion_pct"],
                average_width,
                average_label,
            )
        )
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartHand 康复训练记录</title>
<style>
*{{box-sizing:border-box}} body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:0;color:#17202a;background:#f4f7f9;line-height:1.5}}
.page{{max-width:1280px;margin:0 auto;padding:28px 20px 40px}} h1{{margin:0 0 4px;font-size:30px}}
.subtitle{{margin:0 0 20px;color:#59636e}} .card{{background:white;border-radius:14px;padding:20px;margin:14px 0;box-shadow:0 2px 10px #ccd6dd}}
.section-title{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 14px}}
.section-title h2{{margin:0;font-size:20px}} .section-title small{{color:#697781}}
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.metric{{padding:14px 16px;border:1px solid #e1e8ed;border-radius:10px;background:#fbfcfd}}
.metric-group{{margin:0 0 16px}} .metric-group:last-child{{margin-bottom:0}} .metric-group-title{{font-size:12px;font-weight:700;color:#697781;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px}}
.value{{font-size:28px;font-weight:700;color:#1769aa;line-height:1.2}} .metric-help{{font-size:12px;color:#697781;margin-top:4px}}
.notice{{border-left:4px solid #7d8b95;padding:10px 14px;background:#f7f9fa;border-radius:6px;margin:14px 0 0}}
.note{{color:#59636e;font-size:14px;margin:0}} .legend{{display:flex;gap:20px;flex-wrap:wrap;color:#59636e;font-size:14px;margin-bottom:14px}}
.legend-item{{display:inline-flex;align-items:center;gap:6px}} .legend-dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.trend{{display:grid;grid-template-columns:72px minmax(120px,1fr) 52px minmax(120px,1fr) 74px;gap:10px;align-items:center;margin:12px 0}}
.trend-label,.trend-value{{font-size:13px;color:#4f5d66}} .trend-value{{text-align:right;white-space:nowrap}}
.bar-track{{height:14px;background:#e8edf1;border-radius:9px;overflow:hidden}} .bar{{height:100%;border-radius:9px}}
.bar.completion{{background:#2e86de}} .bar.cadence{{background:#20bf6b}}
.table-wrap{{overflow-x:auto;-webkit-overflow-scrolling:touch}} table{{width:100%;min-width:1120px;border-collapse:collapse}}
th,td{{padding:10px 12px;border-bottom:1px solid #dfe6e9;text-align:left;white-space:nowrap;vertical-align:middle}} th{{font-size:12px;color:#59636e;background:#f7f9fa}}
.badge{{display:inline-flex;align-items:center;min-height:24px;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:700;letter-spacing:.01em}}
.badge-outcome-complete,.badge-quality-ok,.badge-rhythm-normal,.badge-hold-ok{{background:#e4f6eb;color:#1c7c45}}
.badge-outcome-user-cancelled{{background:#fff1d6;color:#996000}} .badge-outcome-timeout{{background:#ffe4e3;color:#b42318}}
.badge-quality-degraded,.badge-rhythm-mixed,.badge-hold-insufficient{{background:#fff1d6;color:#996000}}
.badge-quality-insufficient,.badge-quality-unknown,.badge-rhythm-too-fast,.badge-rhythm-too-slow,.badge-rhythm-unknown,.badge-hold-unknown{{background:#eef1f4;color:#59636e}}
@media(max-width:760px){{.page{{padding:20px 12px 30px}}h1{{font-size:24px}}.card{{padding:15px}}.trend{{grid-template-columns:58px minmax(90px,1fr) 46px;gap:7px}}.trend .cadence-track,.trend .cadence-value{{display:none}}.legend{{gap:10px;font-size:12px}}}}
</style></head><body>
<main class="page">
<h1>视觉引导手功能训练记录</h1>
<p class="subtitle">本地离线生成 · 记录设备训练过程，不作临床判断</p>
<div class="card"><div class="metric-group"><div class="metric-group-title">训练概览</div><div class="metrics">
<div class="metric"><div>训练会话</div><div class="value">{}</div><div class="metric-help">全部记录</div></div>
<div class="metric"><div>累计动作次数</div><div class="value">{}</div><div class="metric-help">跨会话合计</div></div>
<div class="metric"><div>记录完成率</div><div class="value">{:.0f}%</div><div class="metric-help">{} 次记录</div></div>
<div class="metric"><div>完成会话平均完成率</div><div class="value">{:.0f}%</div><div class="metric-help">仅统计已完成会话</div></div>
</div></div><div class="metric-group"><div class="metric-group-title">结果分布</div><div class="metrics">
<div class="metric"><div>完成会话</div><div class="value">{}</div><div class="metric-help">COMPLETE</div></div>
<div class="metric"><div>主动取消</div><div class="value">{}</div><div class="metric-help">USER_CANCELLED</div></div>
<div class="metric"><div>明确训练时限超时</div><div class="value">{}</div><div class="metric-help">imitation_timeout</div></div>
<div class="metric"><div>质量数据覆盖会话</div><div class="value">{}/{}</div><div class="metric-help">独立于完成率</div></div>
</div></div></div>
</div>
<div class="notice"><p class="note">{}<br>{}</p></div>
<div class="card"><h2>训练趋势</h2>
<div class="legend"><span class="legend-item"><i class="legend-dot" style="background:#2e86de"></i>完成率</span><span class="legend-item"><i class="legend-dot" style="background:#20bf6b"></i>平均单次用时（相对本组最长值）</span></div>
{}
</div>
<div class="card"><div class="section-title"><h2>会话明细</h2><small>左右滑动查看完整字段</small></div><div class="table-wrap"><table><thead><tr><th>会话</th><th>结果/状态</th><th>次数</th><th>训练完成率</th>
<th>模仿用时(s)</th><th>平均单次(s)</th><th>示范用时(s)</th>
<th>质量状态</th><th>节奏</th><th>保持</th><th>操作提示</th><th>终止/超时原因</th></tr></thead>
<tbody>{}</tbody></table></div></div>
<p class="note">本报告仅记录设备训练过程，不构成诊断、疗效或临床量表结论。</p>
</main>
</body></html>""".format(
        len(sessions),
        total_repetitions,
        average_completion,
        len(sessions),
        completed_average,
        completed,
        cancelled_count,
        explicit_timeout_count,
        sum(row["session"] in quality for row in sessions),
        len(sessions),
        timeout_note,
        quality_note,
        "".join(trend_rows),
        "".join(rows),
    )


def generate_report(csv_path, output_path, quality_csv=None, reason_csv=None):
    sessions = load_sessions(csv_path)
    if quality_csv is None:
        quality_csv = os.fspath(csv_path) + ".quality.csv"
    quality = load_quality(quality_csv)
    if reason_csv is None:
        reason_csv = os.fspath(csv_path) + ".reason.csv"
    reasons = load_reasons(reason_csv, sessions)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_html(sessions, quality, reasons), encoding="utf-8")
    return sessions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--quality-csv")
    parser.add_argument("--reason-csv")
    args = parser.parse_args()
    sessions = generate_report(args.csv, args.output, args.quality_csv, args.reason_csv)
    print("REPORT CREATED sessions={} output={}".format(len(sessions), args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
