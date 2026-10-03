"""Opt-in PC-only AI advice proxy for the MaixCAM2 training page.

Run on the same computer as the browser, never on MaixCAM2.  The API key is
read from the PC environment and is never sent to the browser or the device.
No imports from the firmware or motion-control modules are made here.
"""

import argparse
import getpass
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


PATH = "/api/v1/ai/course-advice"
LEVELS = {
    "beginner": ("basic_open_palm", "basic_fist", "basic_v_sign"),
    "intermediate": (
        "basic_point", "basic_thumbs_up", "basic_l_shape", "basic_ok_pinch"
    ),
    "advanced": (
        "word_hello", "word_thanks", "word_no", "word_attention",
        "word_like", "signal_help"
    ),
}
LESSON_NAMES = {
    "basic_open_palm": "张开手掌", "basic_fist": "握拳", "basic_v_sign": "V 形手势",
    "basic_point": "食指指向", "basic_thumbs_up": "竖拇指", "basic_l_shape": "L 形手型",
    "basic_ok_pinch": "OK／确认", "word_hello": "你好", "word_thanks": "谢谢",
    "word_no": "拒绝／不", "word_attention": "请注意", "word_like": "喜欢／爱心",
    "signal_help": "求助信号",
}
STATES = frozenset(("COMPLETE", "TIMEOUT", "CANCELLED", "FAULT"))
REASONS = frozenset((
    "OK", "NONE", "TIMEOUT", "CANCELLED", "FAULT", "EXTERNAL_FAULT",
    "NO_HAND", "HAND_NOT_FOUND", "INVALID_LANDMARKS", "LOW_CONFIDENCE",
    "WRONG_GESTURE", "TARGET_MISMATCH", "LINK_OFFLINE", "VISION_STALE",
    "INVALID_RESULT", "UNKNOWN_GESTURE",
))
MAX_BODY = 4096
MAX_ADVICE_CHARS = 800
# Checked on 2026-10-01 against the official Chat Completions schema and the
# Models & Pricing page. Current IDs are deepseek-flash (DeepSeek-V4.1-Flash)
# and deepseek-v4-pro (DeepSeek-V4-Pro-0813). deepseek-chat and
# deepseek-reasoner are retired; deepseek-v4-flash is only a compatibility alias.
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
VERIFIED_DEEPSEEK_MODELS = ("deepseek-flash", "deepseek-v4-pro")
EVALUATION_LIMIT = (
    "COMPLETE 只表示课程门限达到，不是标准手语认证。samples 是网页轮询次数，"
    "读数可能重复或重叠，不是独立视频帧，也不是准确率。识别分数不能当成整段准确率。"
    "completion_stable_ms 是课程通过时保存的保持值，与网页观察到的 max_stable_ms 不同；"
    "缺失保持值或网页稳定值为0，不代表用户没有保持，不能编造具体手指弱项。"
)
SYSTEM_PROMPT = (
    "你是手势训练记录分析助手。只依据给定的匿名课程终态记录，用中文输出纯文本，"
    "总长不超过350字，并按以下三个小标题各写一节：本次不足、证据局限、下次练习建议。"
    "使用 lesson_names 提供的中文课程名，不输出英文课程ID或程序字段名。"
    "只解释本轮已记录课程的证据局限，不照抄所有技术说明；没有动态课程就不要讨论动态课程。"
    "静态课程按手型与保持门限评价；缺少动作步骤的旧动态记录才只看结束关键帧，"
    "不是完整连续动作通过；有步骤记录的动态课程也只是二维动作顺序原型。"
    "完成与过程波动可同时存在，必须结合过程统计，不能因全部完成就忽略漏检、低置信度或不符读数。"
    "读数可能重复和重叠，不可当成独立做错次数；不同观察次数不能直接比较为谁更差。"
    "区分超时、取消、设备或视觉故障和低置信度，不把漏检或超时直接归因为动作错误。"
    "缺失通过时保持值或网页稳定值为0，不表示没有保持。单次识别分数不是整段准确率。"
    "静态课程保持门限是 300 毫秒。达到或超过该值时，禁止写保持偏短或保持不足。"
    "没有通过时保持值，不能写成没保持或保持偏短。"
    "手型不符和低置信只是识别或拍摄波动的轮询读数，禁止写成学习者稳定度不足或动作能力不足。"
    "完成不是准确率。轮询次数不是独立错误次数。没有手指几何时禁止写具体手指或关节弱项。"
    "证据不够时写证据不足，并给 1 至 3 项可执行的拍摄或复练步骤。"
    "不要给医学诊断、标准手语认证或机械动作指令。建议不改变课程判定。"
)
_PROVIDER_ERROR_STATUS = {
    "api_key_rejected": 502,
    "provider_timeout": 504,
    "provider_unavailable": 502,
}
MOTION_STEP_COUNTS = {"word_hello": 2, "word_thanks": 5, "word_no": 6,
                      "word_attention": 5, "word_like": 2, "signal_help": 3}
# Same floor already enforced for completion_stable_ms. A stored hold at or
# above this value has met the course gate.
HOLD_GATE_MS = 300
_HOLD_SHORT = (
    "保持偏短", "保持不足", "保持太短", "保持过短", "保持不够",
    "保持时间不够", "保持时间偏短", "保持时间太短",
)
_ABILITY = (
    "稳定度不足", "稳定性不足", "稳定度不够", "稳定性不够",
    "动作能力不足", "动作能力不够", "学习者不稳定",
)
_FINGER_PARTS = ("食指", "中指", "无名指", "小指", "拇指", "关节")
_NEGATION = ("不是", "不能", "并非", "禁止", "不要", "没法")
_FALLBACK_ERRORS = frozenset((
    "provider_timeout", "provider_unavailable",
    "provider_response_invalid", "provider_response_too_large",
))
FALLBACK_REASONS = _FALLBACK_ERRORS | frozenset(("evidence_conflict",))
_COMPLETE_PHRASES = (
    "已经完成", "已完成", "已经通过", "已通过", "均已通过", "均已完成",
    "全部通过", "全部完成", "都已通过", "都已完成",
)
_INCOMPLETE_PHRASES = ("未能完成", "没有完成", "未完成", "没有通过", "未通过")
# These phrases themselves assert that the whole plan passed.
_ALL_PASSED_PHRASES = (
    "均已通过", "均已完成", "都已通过", "都已完成", "全部通过", "全部完成",
)
# Scope words are not pass claims unless the same clause also says it passed.
_COURSE_SCOPE_PHRASES = ("全部课程", "所有课程")
_PASS_PREDICATES = _COMPLETE_PHRASES


def validate_summary(payload):
    """Accept only bounded, enum-based training data, never free-form prompts."""
    if not isinstance(payload, dict) or set(payload) not in (
        {"level", "rows"}, {"level", "rows", "plan"}
    ):
        raise ValueError("invalid_summary")
    level = payload["level"]
    if not isinstance(level, str) or level not in LEVELS:
        raise ValueError("invalid_level")
    rows = payload["rows"]
    plan = LEVELS[level]
    if "plan" in payload:
        plan = payload["plan"]
        if (
            not isinstance(plan, list) or not 1 <= len(plan) <= 3
            or any(not isinstance(lid, str) or lid not in LEVELS[level] for lid in plan)
            or len(set(plan)) != len(plan)
        ):
            raise ValueError("invalid_plan")
    if not isinstance(rows, list) or not 1 <= len(rows) <= len(plan):
        raise ValueError("invalid_rows")
    clean = []
    for index, row in enumerate(rows):
        required = {"lesson_id", "state", "duration_s", "confidence_pct", "error_code", "samples"}
        optional = {"motion_progress", "completion_stable_ms"}
        if not isinstance(row, dict) or not required <= set(row) <= required | optional:
            raise ValueError("invalid_row")
        if (row["lesson_id"] != plan[index] or not isinstance(row["state"], str)
                or row["state"] not in STATES):
            raise ValueError("invalid_row_state")
        duration = row["duration_s"]
        confidence = row["confidence_pct"]
        reason = row["error_code"]
        if isinstance(duration, bool) or not isinstance(duration, int) or not 0 <= duration <= 3600:
            raise ValueError("invalid_duration")
        if confidence is not None and (
            isinstance(confidence, bool) or not isinstance(confidence, int)
            or not 0 <= confidence <= 100
        ):
            raise ValueError("invalid_confidence")
        if not isinstance(reason, str) or reason not in REASONS:
            raise ValueError("invalid_reason")
        samples = row["samples"]
        sample_keys = {
            "observations", "low_confidence", "no_hand", "wrong_gesture",
            "vision_stale", "max_stable_ms"
        }
        if not isinstance(samples, dict) or set(samples) != sample_keys:
            raise ValueError("invalid_samples")
        for key in sample_keys:
            value = samples[key]
            limit = 600000 if key == "max_stable_ms" else 3600
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
                raise ValueError("invalid_samples")
        if any(samples[key] > samples["observations"] for key in (
            "low_confidence", "no_hand", "wrong_gesture", "vision_stale"
        )):
            raise ValueError("invalid_samples")
        clean_row = dict(row)
        if "completion_stable_ms" in row:
            hold = row["completion_stable_ms"]
            if (type(hold) is not int or not 300 <= hold <= 600000
                    or row["state"] != "COMPLETE" or row["lesson_id"] in MOTION_STEP_COUNTS):
                raise ValueError("invalid_completion_stable_ms")
        progress = row.get("motion_progress")
        if "motion_progress" in row:
            if (not isinstance(progress, dict) or set(progress) !=
                    {"completed_steps", "total_steps", "complete"} or
                    type(progress["completed_steps"]) is not int or
                    type(progress["total_steps"]) is not int or
                    not 1 <= progress["total_steps"] <= 6 or
                    not 0 <= progress["completed_steps"] <= progress["total_steps"] or
                    type(progress["complete"]) is not bool or
                    progress["complete"] != (progress["completed_steps"] == progress["total_steps"]) or
                    progress["total_steps"] != MOTION_STEP_COUNTS.get(row["lesson_id"]) or
                    progress["complete"] != (row["state"] == "COMPLETE")):
                raise ValueError("invalid_motion_progress")
            clean_row["motion_progress"] = dict(progress)
        clean.append(clean_row)
    summary = {"level": level, "planned_count": len(plan), "rows": clean}
    if "plan" in payload:
        summary["plan"] = list(plan)
        summary["course_type"] = "remedial"
    return summary


def model_url(base_url):
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("AI base URL must be HTTPS without embedded credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("AI base URL must not contain a query or fragment")
    return base_url.rstrip("/") + "/chat/completions"


def evaluation_limit(summary):
    rows = summary["rows"]
    parts = [EVALUATION_LIMIT]
    if any(row["lesson_id"] not in MOTION_STEP_COUNTS for row in rows):
        parts.append("本轮静态课程验证目标手型与保持门限，不是完整连续动作通过。")
    dynamic = [row for row in rows if row["lesson_id"] in MOTION_STEP_COUNTS]
    if any("motion_progress" in row for row in dynamic):
        parts.append("本轮带步骤记录的动态课程仅验证二维动作顺序原型，不判断身体位置或完整标准手语语义。")
    if any("motion_progress" not in row for row in dynamic):
        parts.append("本轮缺少步骤记录的旧动态结果只验证结束关键帧，不是完整连续动作通过。")
    held = []
    for row in rows:
        hold = row.get("completion_stable_ms")
        if type(hold) is int and hold >= HOLD_GATE_MS:
            held.append("{}通过时保持{}毫秒，已达到{}毫秒门限".format(
                LESSON_NAMES[row["lesson_id"]], hold, HOLD_GATE_MS
            ))
    if held:
        parts.append("".join(held) + "。这些记录禁止写成保持偏短。")
    if any(row["samples"]["wrong_gesture"] or row["samples"]["low_confidence"] for row in rows):
        parts.append("手型不符和低置信读数只代表识别或拍摄波动，不能用来判断学习者动作表现。")
    return "".join(parts)


def _clauses(text):
    """Split assertions. A negation does not cover text after a contrast."""
    normalized = re.sub(r"但是|可是|不过|然而", "\n", text)
    normalized = normalized.replace("但", "\n")
    return [part.strip() for part in re.split(r"[。！？\n；;，,]", normalized) if part.strip()]


def _positive_phrase(clause, phrase):
    start = 0
    while True:
        index = clause.find(phrase, start)
        if index < 0:
            return False
        if not any(mark in clause[:index] for mark in _NEGATION):
            return True
        start = index + len(phrase)


def _unsupported_claim(text, phrases):
    for clause in _clauses(text):
        if any(_positive_phrase(clause, phrase) for phrase in phrases):
            return True
    return False


def _claims_accuracy(text):
    if "准确率" not in text:
        return False
    masked = text
    for phrase in (
        "不是准确率", "不是识别准确率", "不能当成准确率", "不能当作准确率",
        "并非准确率", "不能代表准确率",
    ):
        masked = masked.replace(phrase, "")
    return "准确率" in masked


def _claims_independent_errors(text):
    if _unsupported_claim(text, ("独立错误", "独立做错")):
        return True
    for clause in _clauses(text):
        for match in re.finditer(r"做错\s*\d+\s*次|\d+\s*次(?:独立)?错误", clause):
            if not any(mark in clause[:match.start()] for mark in _NEGATION):
                return True
    return False


def _rows_named(clause, summary):
    found = []
    for row in summary["rows"]:
        if LESSON_NAMES[row["lesson_id"]] in clause:
            found.append(row)
    return found


def _plan_fully_complete(summary):
    rows = summary["rows"]
    return len(rows) == summary["planned_count"] and all(
        row["state"] == "COMPLETE" for row in rows
    )


def _claims_all_passed(clause):
    """True only when this clause says the whole plan passed, not merely mentions it."""
    if any(_positive_phrase(clause, phrase) for phrase in _ALL_PASSED_PHRASES):
        return True
    scoped = any(_positive_phrase(clause, phrase) for phrase in _COURSE_SCOPE_PHRASES)
    passed = any(_positive_phrase(clause, phrase) for phrase in _PASS_PREDICATES)
    return scoped and passed


def _recorded_step_claim(clause):
    """A future practice step is not this session's motion progress."""
    has_pattern = bool(
        re.search(r"\d+\s*/\s*\d+", clause)
        or re.search(r"\d+\s*步", clause)
        or "全部步骤" in clause
        or "所有步骤" in clause
    )
    if not has_pattern:
        return False
    if re.search(r"下次|随后", clause) and "本次" not in clause:
        return False
    if any(mark in clause for mark in (
        "本次", "已经完成", "已完成", "完成了", "记录", "实际", "当前进度", "进度是", "进度为",
    )):
        return True
    if ("全部步骤" in clause or "所有步骤" in clause) and ("完成" in clause or "通过" in clause):
        return True
    return False


def _outcome_conflict(text, summary):
    """Compare stated outcomes with the saved rows. Unmatched facts are rejected."""
    for clause in _clauses(text):
        if _claims_all_passed(clause) and not _plan_fully_complete(summary):
            return True
        named = _rows_named(clause, summary)
        targets = named or summary["rows"]
        if any(_positive_phrase(clause, phrase) for phrase in _COMPLETE_PHRASES):
            if _claims_all_passed(clause) and not named:
                pass
            elif any(row["state"] != "COMPLETE" for row in targets):
                return True
        if any(_positive_phrase(clause, phrase) for phrase in _INCOMPLETE_PHRASES):
            if any(row["state"] == "COMPLETE" for row in targets):
                return True
        if _positive_phrase(clause, "超时") and any(row["state"] != "TIMEOUT" for row in targets):
            return True
        if _positive_phrase(clause, "已取消") and any(row["state"] != "CANCELLED" for row in targets):
            return True
        if _positive_phrase(clause, "训练故障") and any(row["state"] != "FAULT" for row in targets):
            return True
        if "保持" in clause:
            for number in (int(value) for value in re.findall(r"(\d+)\s*毫秒", clause)):
                if number == HOLD_GATE_MS and "门限" in clause:
                    continue
                if not any(
                    type(row.get("completion_stable_ms")) is int
                    and row["completion_stable_ms"] == number
                    for row in targets
                ):
                    return True
        if not _recorded_step_claim(clause):
            continue
        fraction = re.search(r"(\d+)\s*/\s*(\d+)", clause)
        counted = re.search(r"(\d+)\s*步", clause)
        mentions_all_steps = "全部步骤" in clause or "所有步骤" in clause
        if fraction or counted or mentions_all_steps:
            done = int(fraction.group(1)) if fraction else None
            total = int(fraction.group(2)) if fraction else None
            if counted and done is None:
                done = int(counted.group(1))
            for row in targets:
                progress = row.get("motion_progress")
                if fraction or counted:
                    if (not isinstance(progress, dict)
                            or (done is not None and done != progress["completed_steps"])
                            or (total is not None and total != progress["total_steps"])):
                        return True
                if mentions_all_steps and (
                    not isinstance(progress, dict) or progress["complete"] is not True
                ):
                    return True
    return False


def _invented_body_part(text, summary):
    reduced = text
    names = sorted(
        (LESSON_NAMES[row["lesson_id"]] for row in summary["rows"]),
        key=len, reverse=True,
    )
    for name in names:
        reduced = reduced.replace(name, "")
    return any(part in reduced for part in _FINGER_PARTS)


def advice_conflicts(text, summary):
    """Reject claims this summary cannot support. Prompt wording is not proof."""
    if not isinstance(text, str) or not text.strip():
        return True
    if _unsupported_claim(text, _HOLD_SHORT):
        return True
    if _unsupported_claim(text, _ABILITY):
        return True
    if _claims_accuracy(text) or _claims_independent_errors(text):
        return True
    if _invented_body_part(text, summary):
        return True
    if _outcome_conflict(text, summary):
        return True
    return False


def _course_name(row):
    return LESSON_NAMES[row["lesson_id"]]


def local_advice(summary):
    """Deterministic Chinese advice. It never treats polls as ability or accuracy."""
    gaps = []
    limits = [
        "轮询读数可能重复，不能逐条当成互不相关的失误。终态完成不能代表整段识别表现。",
    ]
    steps = []
    hold_met = False
    recognition_noise = False
    capture_gap = False
    for row in summary["rows"]:
        name = _course_name(row)
        samples = row["samples"]
        hold = row.get("completion_stable_ms")
        if row["state"] == "COMPLETE" and type(hold) is int and hold >= HOLD_GATE_MS:
            hold_met = True
            gaps.append("{}已完成，通过时保持 {} 毫秒，已经达到保持门限。".format(name, hold))
        elif row["state"] == "TIMEOUT":
            gaps.append("{}这次超时。仅凭该终态不能判断是手型还是拍摄条件。".format(name))
        elif row["state"] in ("FAULT", "CANCELLED"):
            gaps.append("{}这次没有形成可评价的动作结果。".format(name))
        elif row["state"] == "COMPLETE":
            gaps.append("{}已完成。这次没有记下通过时的保持值，不能据此描述保持长短。".format(name))
        else:
            gaps.append("{}已有终态记录，还不能判断动作细节。".format(name))
        if samples["wrong_gesture"] or samples["low_confidence"]:
            recognition_noise = True
            if samples["wrong_gesture"] and samples["low_confidence"]:
                noise = "手型不符和低置信读数"
            elif samples["wrong_gesture"]:
                noise = "手型不符读数"
            else:
                noise = "低置信读数"
            gaps.append("{}的轮询里有{}，只说明识别或拍摄有波动。".format(name, noise))
        if samples["no_hand"] or samples["vision_stale"]:
            capture_gap = True
            gaps.append("{}有未检测到手或画面过期的轮询读数，先检查入镜和连接。".format(name))
        progress = row.get("motion_progress")
        if isinstance(progress, dict):
            gaps.append("{}的记录步骤进度是 {}/{}。".format(
                name, progress["completed_steps"], progress["total_steps"]
            ))
    if not any(type(row.get("completion_stable_ms")) is int for row in summary["rows"]):
        limits.insert(0, "证据不足，不能判断具体薄弱动作，也不能判断学习者的动作表现。")
    elif recognition_noise:
        limits.append("把识别波动当成学习者动作表现的证据不足。")
    first = _course_name(summary["rows"][0])
    if capture_gap:
        steps.append("复练{}前，先让整只手留在画面中。".format(first))
    if hold_met:
        steps.append("复练{}时不必为了加长保持而改手型，先看实时标签是否连续对上该课程。".format(first))
    elif recognition_noise:
        steps.append("复练{}时放慢一次，对照实时标签，分辨是手型还是拍摄角度。".format(first))
    else:
        steps.append("再完成一次{}，只根据终态和实时标签决定下一步。".format(first))
    lines = ["本次不足"]
    lines.extend(gaps[:6])
    lines.append("证据局限")
    lines.extend(limits[:3])
    lines.append("下次练习建议")
    lines.extend(steps[:3])
    return "\n".join(lines)


# Frozen HTTP contract for a successful advice response:
# {"advice": <non-empty str, len <= MAX_ADVICE_CHARS>,
#  "source": "model" | "local",
#  "fallback_reason": null | FALLBACK_REASONS}
# source=model requires fallback_reason null.
# source=local requires fallback_reason in FALLBACK_REASONS.
# Key failures stay {"error": ...} and do not carry advice.
# Lexical checks do not establish that every natural-language fact is correct.


def advice_envelope(advice, source, fallback_reason):
    if not isinstance(advice, str) or not advice.strip() or len(advice) > MAX_ADVICE_CHARS:
        raise ValueError("invalid_advice_contract")
    if source == "model":
        if fallback_reason is not None:
            raise ValueError("invalid_advice_contract")
    elif source == "local":
        if fallback_reason not in FALLBACK_REASONS:
            raise ValueError("invalid_advice_contract")
    else:
        raise ValueError("invalid_advice_contract")
    return {
        "advice": advice,
        "source": source,
        "fallback_reason": fallback_reason,
    }


def _local_envelope(summary, reason):
    if reason not in FALLBACK_REASONS:
        reason = "evidence_conflict"
    return advice_envelope(local_advice(summary)[:MAX_ADVICE_CHARS], "local", reason)


def _model_envelope(advice):
    return advice_envelope(advice, "model", None)


def resolve_model_text(summary, text):
    """Keep model wording only when it does not contradict the saved record."""
    if not isinstance(text, str) or not text.strip():
        return _local_envelope(summary, "evidence_conflict")
    cleaned = text.strip()
    for lesson_id, name in sorted(LESSON_NAMES.items(), key=lambda item: len(item[0]), reverse=True):
        cleaned = cleaned.replace(lesson_id, name)
    if advice_conflicts(cleaned, summary):
        return _local_envelope(summary, "evidence_conflict")
    return _model_envelope(cleaned[:MAX_ADVICE_CHARS])


def _valid_envelope(result):
    if not isinstance(result, dict) or set(result) != {"advice", "source", "fallback_reason"}:
        return False
    try:
        advice_envelope(result["advice"], result["source"], result["fallback_reason"])
    except (TypeError, ValueError):
        return False
    return True


def coerce_advice_result(summary, result):
    if _valid_envelope(result):
        return result
    if isinstance(result, str):
        return resolve_model_text(summary, result)
    return _local_envelope(summary, "evidence_conflict")


def request_advice(summary, api_key, base_url, model, timeout=12, opener=None):
    if not api_key:
        raise RuntimeError("api_key_missing")
    endpoint = model_url(base_url)
    if not isinstance(model, str) or not model or len(model) > 80:
        raise ValueError("invalid_model")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(
                {"summary": summary, "evaluation_limit": evaluation_limit(summary),
                 "lesson_names": {row["lesson_id"]: LESSON_NAMES[row["lesson_id"]]
                                  for row in summary["rows"]}},
                ensure_ascii=False,
            )},
        ],
        "stream": False,
        "max_tokens": 400,
    }
    if urllib.parse.urlsplit(base_url).hostname == "api.deepseek.com":
        # Thinking is on by default and can consume the short advice budget.
        payload["thinking"] = {"type": "disabled"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint, body,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        response_context = open_url(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        try:
            exc.close()
        except Exception:
            pass
        if exc.code in (401, 403):
            raise RuntimeError("api_key_rejected") from None
        raise RuntimeError("provider_unavailable") from None
    except TimeoutError:
        raise RuntimeError("provider_timeout") from None
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), TimeoutError):
            raise RuntimeError("provider_timeout") from None
        raise RuntimeError("provider_unavailable") from None
    with response_context as response:
        if int(response.status) != 200:
            raise RuntimeError("provider_unavailable")
        raw = response.read(16385)
    if len(raw) > 16384:
        raise RuntimeError("provider_response_too_large")
    payload = json.loads(raw.decode("utf-8"))
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("provider_response_invalid")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    advice = message.get("content") if isinstance(message, dict) else None
    if not isinstance(advice, str) or not advice.strip():
        raise RuntimeError("provider_response_invalid")
    cleaned = advice.strip()
    for lesson_id, name in sorted(LESSON_NAMES.items(), key=lambda item: len(item[0]), reverse=True):
        cleaned = cleaned.replace(lesson_id, name)
    return cleaned[:MAX_ADVICE_CHARS]


def advice_for_summary(summary, api_key, base_url, model, timeout=12, opener=None):
    """Return an advice envelope. Provider failures become local fallbacks."""
    try:
        text = request_advice(
            summary, api_key, base_url, model, timeout=timeout, opener=opener
        )
    except RuntimeError as exc:
        if str(exc) in _FALLBACK_ERRORS:
            return _local_envelope(summary, str(exc))
        raise
    return resolve_model_text(summary, text)


class AdviceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, allowed_origin, api_key, base_url, model, requester=None):
        if not allowed_origin or not allowed_origin.startswith("http://"):
            raise ValueError("set the exact HTTP origin of the MaixCAM2 page")
        parsed = urllib.parse.urlsplit(allowed_origin)
        if not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("allowed origin must be scheme://host[:port] only")
        super().__init__(address, AdviceHandler)
        self.allowed_origin = allowed_origin
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.requester = requester or advice_for_summary
        self._rate_lock = threading.Lock()
        self._last_request = None

    def claim_request(self):
        with self._rate_lock:
            now = time.monotonic()
            if self._last_request is not None and now - self._last_request < 5.0:
                return False
            self._last_request = now
            return True


class AdviceHandler(BaseHTTPRequestHandler):
    def log_message(self, format_string, *args):
        # Do not print submitted training data or provider credentials.
        print("AI advice proxy: " + (format_string % args))

    def _authorized_origin(self):
        return self.headers.get("Origin") == self.server.allowed_origin

    def _send_json(self, status, payload, cors=False):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", self.server.allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        if self.path != PATH or not self._authorized_origin():
            self._send_json(403, {"error": "origin_denied"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.server.allowed_origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_POST(self):
        if self.path != PATH:
            self._send_json(404, {"error": "not_found"})
            return
        if not self._authorized_origin():
            self._send_json(403, {"error": "origin_denied"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send_json(415, {"error": "json_required"}, cors=True)
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self._send_json(413, {"error": "invalid_body_size"}, cors=True)
            return
        if not self.server.api_key:
            self._send_json(503, {"error": "api_key_missing"}, cors=True)
            return
        try:
            body = self.rfile.read(length)
            summary = validate_summary(json.loads(body.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid_summary"}, cors=True)
            return
        if not self.server.claim_request():
            self._send_json(429, {"error": "try_later"}, cors=True)
            return
        try:
            advice = self.server.requester(
                summary, self.server.api_key, self.server.base_url, self.server.model
            )
        except TimeoutError:
            error = "provider_timeout"
        except urllib.error.HTTPError as exc:
            error = "api_key_rejected" if exc.code in (401, 403) else "provider_unavailable"
        except urllib.error.URLError as exc:
            error = (
                "provider_timeout"
                if isinstance(getattr(exc, "reason", None), TimeoutError)
                else "provider_unavailable"
            )
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError, KeyError, IndexError) as exc:
            error = str(exc)
            if error not in _PROVIDER_ERROR_STATUS:
                error = "provider_unavailable"
        else:
            self._send_json(200, coerce_advice_result(summary, advice), cors=True)
            return
        if error in _FALLBACK_ERRORS:
            self._send_json(200, _local_envelope(summary, error), cors=True)
            return
        self._send_json(_PROVIDER_ERROR_STATUS[error], {"error": error}, cors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True,
                        help="exact MaixCAM2 webpage origin, e.g. http://10.78.64.1:8080")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--prompt-key", action="store_true",
                        help="prompt for the API key without echoing it")
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key and args.prompt_key:
        api_key = getpass.getpass("AI API Key: ")
    server = AdviceServer(
        ("127.0.0.1", args.port), args.origin,
        api_key,
        os.environ.get("OPEN_SIGN_AI_BASE_URL", DEFAULT_BASE_URL),
        os.environ.get("OPEN_SIGN_AI_MODEL", DEFAULT_MODEL),
    )
    print("AI advice proxy listening on http://127.0.0.1:{}; allowed origin {}".format(
        args.port, args.origin
    ))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
