"""MaixCAM2 front-panel UART2 communication MVP.

Run with protocol.py, link_monitor.py, target_tracker.py and vision_source.py
in the same MaixVision application directory.
"""

from maix import app, err, pinmap, time, uart

import os
import re

from link_monitor import AckMonitor, write_tracked
from protocol import StreamParser, encode_frame
try:
    from sign_motion import (
        ACTION_CANCEL as SIGN_ACTION_CANCEL,
        ACTION_HOME as SIGN_ACTION_HOME,
        ACTION_START as SIGN_ACTION_START,
        SignMotionController,
        STATE_COMPLETED as SIGN_MOTION_COMPLETED,
        STATE_CANCELLED as SIGN_MOTION_CANCELLED,
        STATE_FAILED as SIGN_MOTION_FAILED,
    )
except Exception:  # pragma: no cover - rehab-only deployments may omit it
    SignMotionController = None
    SIGN_ACTION_START = 1
    SIGN_ACTION_CANCEL = 2
    SIGN_ACTION_HOME = 3
    SIGN_MOTION_COMPLETED = 5
    SIGN_MOTION_CANCELLED = 6
    SIGN_MOTION_FAILED = 7
from rehab_hand_source import HandLandmarksVisionSource
from rehab_goal import RepetitionGoalController
from rehab_imitation import (
    ImitationSessionController,
    TERMINATION_REASON_HAND_VISION_INIT_FAILED,
)
from rehab_quality import RhythmQualityTracker  # noqa: F401
from rehab_session_log import SessionCsvLogger
from rehab_train import TRAIN_MODE_REHAB, TrainButtonController
from status_snapshot import (  # noqa: F401
    AITRUST_TIMEOUT_MS,
    UNKNOWN_AITRUST_SNAPSHOT,
    UNKNOWN_SNAPSHOT,
    aitrust_status_line,
    authority_display_line,
    authority_status_line,
    interpret_aitrust,
    interpret_status,
)
from target_tracker import TargetTracker, VisionScheduler
from vision_source import DisabledVisionSource, create_vision_source


UART_DEVICE = "/dev/ttyS2"
UART_BAUD = 115200
VISION_MODE = "yolo11"  # "mock", "yolo11", or "disabled"
YOLO_MODEL_PATH = "/root/models/yolo11n.mud"
YOLO_CONFIDENCE_THRESHOLD = 0.5
YOLO_IOU_THRESHOLD = 0.45
YOLO_ALLOWED_CLASS_IDS = (39, 41, 65)  # bottle, cup, remote
SHOW_PREVIEW = True
PREVIEW_INTERVAL_MS = 100  # Keep overlay feedback responsive at about 10 FPS
# Explicit LAN-preview opt-in.  With the default False value main.py never
# imports live_sidecar, opens a socket, or asks a frame to encode JPEG bytes.
LIVE_WEB_ENABLED = False
# Keep a single spacing constant so the hand imitation and target screens can
# render compact Chinese text without adjacent lines overlapping on the
# 320x224 preview frame.
OVERLAY_LINE_HEIGHT_PX = 27
# A small black offset makes the white overlay readable over both bright and
# dark camera content without relying on the device-specific filled-rectangle
# behaviour of ``draw_rect``.
OVERLAY_TEXT_SHADOW_PX = 2
OVERLAY_FONT_NAME = "sourcehansans"
OVERLAY_FONT_SIZE = 18
OVERLAY_FONT_PATHS = (
    "/maixapp/share/font/SourceHanSansCN-Regular.otf",
    "/maixapp/share/font/SourceHanSansCN-Regular.ttf",
)
OVERLAY_FONT = None
VISION_PROCESS_INTERVAL_MS = 50  # Cap camera/NPU/display work at 20 FPS
HAND_PROCESS_INTERVAL_MS = 50  # Cap landmark inference to 20 FPS
TARGET_STABLE_FRAMES = 3
TARGET_STALE_TIMEOUT_MS = 750
TARGET_MATCH_IOU = 0.2
PING_INTERVAL_MS = 1000
VISION_INTERVAL_MS = 500
ACK_TIMEOUT_MS = 1000
STATUS_TIMEOUT_MS = 1500
STATS_INTERVAL_MS = 5000
IMITATION_GOAL_REPETITIONS = 5
IMITATION_TIMEOUT_MS = 60000
IMITATION_TERMINAL_HOLD_MS = 8000
HAND_MODEL_PATH = "/root/models/hand_landmarks.mud"
# Sign-only same-frame detector retry: max two calls, conf_th2 stays 0.8.
SIGN_DETECTOR_RETRY_ENABLED = True
SESSION_LOG_PATH = "/root/smart_hand_rehab_sessions.csv"
TARGET_LABELS = {39: "bottle", 41: "cup", 65: "remote"}
TARGET_INTENTS = {
    39: "CYLINDRICAL",
    41: "POWER",
    65: "PRECISION",
}
WEB_TRAIN_BOTTLE_CLASS_ID = 39


def _env_flag(name, default=False):
    """Read an explicit opt-in boolean without changing the old default."""
    try:
        value = os.getenv(name)
    except Exception:
        value = None
    if value is None:
        return bool(default)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _project_marker_enabled(filename):
    """Return True only when an explicit marker ships with this project.

    MaixVision project launches do not always provide a convenient place to
    define environment variables.  A separate deployment directory can opt in
    without changing the frozen rehabilitation source by including the empty
    marker file next to ``main.py``.
    """
    candidates = (filename,)
    try:
        candidates = (os.path.join(os.path.dirname(__file__), filename), filename)
    except Exception:
        pass
    for path in candidates:
        try:
            handle = open(path, "rb")
            handle.close()
            return True
        except Exception:
            continue
    return False


# Sign training is deliberately off for the existing rehab deployment.  A
# launch environment may opt in with SIGN_MODE=1.  The dedicated OpenSignHand
# project may instead include ``opensignhand.enable`` beside main.py; the old
# rehabilitation project contains no marker and therefore stays unchanged.
_OPENSIGNHAND_MARKER = _project_marker_enabled("opensignhand.enable")
SIGN_MODE = _env_flag("SIGN_MODE", _OPENSIGNHAND_MARKER)
_OPENSIGNHAND_MECHANICAL_MARKER = _project_marker_enabled(
    "opensignhand_mechanical.enable"
)
SIGN_MECHANICAL_DEMO_ENABLED = bool(
    SIGN_MODE
    and _env_flag("OPENSIGNHAND_MECHANICAL_DEMO", _OPENSIGNHAND_MECHANICAL_MARKER)
)
if SIGN_MODE:
    # Manual confirmation is mandatory in sign mode, so the same-origin device
    # control page is enabled by default.  SIGN_MODE=0 or LIVE_WEB_ENABLED=0
    # still provides an explicit emergency opt-out.
    LIVE_WEB_ENABLED = _env_flag("LIVE_WEB_ENABLED", True)
SIGN_SESSION_LOG_PATH = os.getenv(
    "SIGN_SESSION_LOG_PATH", "/root/smart_hand_sign_sessions.csv"
)
SIGN_STALE_TIMEOUT_MS = 1500
SIGN_SCREEN_DEMO_MS = 3000
# Titan sends SIGNSTAT only when the fixed servo recipe changes state.  The
# validated open/close sequence can take ~18 s, so this timeout must be much
# longer than the ordinary 1.5 s STATUS freshness window.
SIGN_MOTION_STATUS_TIMEOUT_MS = 30000


# This map is intentionally presentation-only.  The protocol, state-machine,
# console logs, and CSV values continue to use their original English codes.
OVERLAY_PHRASE_TRANSLATIONS = (
    ("START/CANCEL VIA CONFIRMED WEB ACTION", "请在电脑网页开始或取消"),
    ("SIGN STATE", "训练状态"),
    ("USER WAIT_DEMO", "等待系统示范"),
    ("TRAIN READY - TAP TO START", "训练就绪-点击开始"),
    ("CANCEL TRAIN", "取消训练"),
    ("USER CANCELLED", "已取消"),
    ("TRAIN COMPLETE", "训练完成"),
    ("TRAIN FAILED", "训练失败"),
    ("TRAIN LOCKED", "训练锁定"),
    ("LOCK: WAIT TITAN", "锁定: 等待泰坦"),
    ("LOCK: WAIT TARGET", "锁定: 等待目标"),
    ("LOCK: WAIT ACTION", "锁定: 等待可执行动作"),
    ("LOCK: WAIT POSE", "锁定: 等待姿态"),
    ("LOCK: GATE FAULT", "锁定: 闸门故障"),
    ("LOCK: READY", "锁定: 就绪"),
    ("START TRAIN", "开始训练"),
    ("MOTION LOCKED", "动作已锁定"),
    ("WAIT_DEMO", "等待示范"),
    ("NEXT: HOLD CLOSED", "下一步: 保持握拳"),
    ("NEXT: SLOW DOWN", "下一步: 放慢速度"),
    ("NEXT: MOVE STEADY", "下一步: 稳定移动"),
    ("NEXT: KEEP RHYTHM", "下一步: 保持节奏"),
    ("NEXT: GOOD JOB", "下一步: 做得好"),
    ("NEXT: TRY AGAIN", "下一步: 请再试一次"),
    ("FEEDBACK HOLD TOO SHORT", "闭合识别不足，请保持闭合并保持手掌稳定"),
    ("FEEDBACK TOO SLOW", "节奏偏慢，请按提示稍快"),
    ("FEEDBACK TOO FAST", "节奏偏快，请按提示放慢"),
    ("FEEDBACK UNKNOWN", "数据不足，暂不评价"),
    ("FEEDBACK OK", "节奏和保持正常"),
    ("TRACKING LOW", "画面跟踪不足，请调整手掌和光线"),
)
OVERLAY_TOKEN_TRANSLATIONS = {
    "SIGN": "实时手型",
    "STABLE": "稳定",
    "LESSON_SELECTED": "已选课程",
    "DEMONSTRATING": "示范中",
    "IMITATING": "模仿中",
    "CANCELLED": "已取消",
    "VALID": "有效",
    "INVALID": "无效",
    "OPEN_PALM": "张开手掌",
    "FIST": "握拳",
    "V_SIGN": "V 手势",
    "POINT": "食指指向",
    "THUMBS_UP": "竖拇指",
    "L_SHAPE": "L 形手型",
    "OK_PINCH": "OK／确认",
    "NO_HAND": "未检测到手",
    "hand_not_found": "未检测到手",
    "SmartHand": "灵巧手",
    "infer": "推理",
    "TARGET": "目标",
    "INTENT": "意图",
    "TRAIN": "训练",
    "REP": "次数",
    "code": "代码",
    "bottle": "瓶子",
    "cup": "杯子",
    "remote": "遥控器",
    "none": "无",
    "CYLINDRICAL": "圆柱",
    "POWER": "电源",
    "PRECISION": "精准",
    "CYL": "圆柱",
    "PWR": "电源",
    "PREC": "精准",
    "UNSUPPORTED": "不支持",
    "TITAN": "泰坦",
    "ONLINE": "在线",
    "DEGRADED": "降级",
    "WAIT": "等待",
    "UNKNOWN": "未知",
    "ACK_TIMEOUT": "应答超时",
    "STATUS_TIMEOUT": "状态超时",
    "RUNNING": "运行中",
    "QUEUED": "排队中",
    "ACK": "应答",
    "RTT": "延迟",
    "GOAL": "目标",
    "LOCKED": "已锁定",
    "HAND": "手部",
    "OPEN": "张开",
    "CLOSED": "握拳",
    "NONE": "无",
    "USER": "用户",
    "COMPLETE": "完成",
    "REVIEWED": "人工复核已记录（非自动通过）",
    "TIMEOUT": "超时",
    "IMITATE": "模仿",
    "RESULT": "结果",
    "PASS": "通过",
    "INCOMPLETE": "未完成",
    "TIME": "用时",
    "AVG": "平均",
    "Q": "质",
    "P": "节",
    "H": "保持",
    "AUTH": "权限",
    "L": "链",
    "V": "视",
    "S": "旧",
    "A": "动",
    "G": "门",
    "ON": "开",
    "OFF": "关",
    "FAULT": "故障",
    "OK": "正常",
    "NO_ACTION": "无动作",
    "NOT_CONFIGURED": "未配置",
    "INVALID_PROFILE": "配置无效",
    "SUBMITTED": "已提交",
    "BLOCKED": "已阻止",
    "UNK": "未知",
    "FAST": "过快",
    "SLOW": "过慢",
    "MIX": "混合",
    "SHORT": "不足",
    "WARN": "警告",
}


def report_repeated_error(label, count, exc):
    if count == 1 or count % 100 == 0:
        print("{} count={}: {}".format(label, count, exc))


def load_overlay_font(image_module):
    """Load the optional Chinese overlay font and return its draw name.

    MaixCAM2 images still render with the built-in font when no compatible
    font is installed.  Keeping this function best-effort is important for
    older firmware images, where ``load_font`` or the shared font path may be
    absent.
    """
    global OVERLAY_FONT
    OVERLAY_FONT = None
    if image_module is None:
        return None
    load_font = getattr(image_module, "load_font", None)
    if load_font is None:
        return None
    for font_path in OVERLAY_FONT_PATHS:
        try:
            if not os.path.exists(font_path):
                continue
        except Exception:
            # Some constrained firmware builds do not expose normal path
            # probing; let the loader decide whether the path is usable.
            pass
        try:
            load_font(OVERLAY_FONT_NAME, font_path, size=OVERLAY_FONT_SIZE)
            fonts = getattr(image_module, "fonts", None)
            if fonts is not None and OVERLAY_FONT_NAME not in fonts():
                continue
            OVERLAY_FONT = OVERLAY_FONT_NAME
            return OVERLAY_FONT
        except Exception:
            continue
    return None


def translate_overlay_text(text):
    """Translate one display line while preserving dynamic numbers/codes."""
    translated = str(text)
    for source, target in OVERLAY_PHRASE_TRANSLATIONS:
        translated = translated.replace(source, target)
    translated = re.sub(
        r"(\d+(?:\.\d+)?)ms\b",
        r"\1毫秒",
        translated,
    )
    translated = re.sub(
        r"(\d+(?:\.\d+)?)s\b",
        r"\1秒",
        translated,
    )
    # One pass over source tokens only: translated V/L/OK gesture names must
    # never be translated a second time as authority/health abbreviations.
    keys = sorted(OVERLAY_TOKEN_TRANSLATIONS, key=len, reverse=True)
    translated = re.sub(
        r"(?<![A-Za-z0-9_])(?:{})(?![A-Za-z0-9_])".format(
            "|".join(re.escape(key) + (r"(?==)" if key in ("L", "V", "S", "A", "G") else "")
                     for key in keys)),
        lambda match: OVERLAY_TOKEN_TRANSLATIONS[match.group(0)], translated,
    )
    return translated


def target_status_lines(payload):
    if payload is None:
        return "TARGET none", "INTENT none"
    class_id = payload[0]
    confidence = payload[5]
    label = TARGET_LABELS.get(class_id, "class{}".format(class_id))
    intent = TARGET_INTENTS.get(class_id, "UNSUPPORTED")
    return (
        "TARGET {} {}%".format(label, confidence),
        "INTENT {}".format(intent),
    )


def sign_overlay_lines(recognition, state):
    """Presentation-only compact caption; evidence stays in the web metrics."""
    recognition = recognition or {}
    gesture = recognition.get("gesture_id") or "NONE"
    return "SIGN {}".format(gesture), "SIGN STATE {}".format(state or "UNAVAILABLE")


def draw_overlay_text(frame, image_module, x, y, text):
    """Draw high-contrast status text on a changing camera background.

    MaixCAM2 firmware versions differ in how a negative ``draw_rect``
    thickness is handled, so use a portable text shadow instead of a filled
    background strip.  The fallback keeps older image modules functional.
    """
    global OVERLAY_FONT
    shadow = getattr(image_module, "COLOR_BLACK", image_module.COLOR_RED)
    foreground = getattr(image_module, "COLOR_WHITE", image_module.COLOR_RED)
    offset = OVERLAY_TEXT_SHADOW_PX
    display_text = translate_overlay_text(text) if OVERLAY_FONT else text

    def draw_string(px, py, value, color, font=None):
        if font is None:
            frame.draw_string(px, py, value, color=color)
        else:
            frame.draw_string(px, py, value, color=color, font=font)

    try:
        for dx, dy in (
            (-offset, -offset),
            (offset, -offset),
            (-offset, offset),
            (offset, offset),
        ):
            draw_string(x + dx, y + dy, display_text, shadow, OVERLAY_FONT)
        draw_string(x, y, display_text, foreground, OVERLAY_FONT)
    except Exception:
        # A loaded font can still be rejected by a mismatched firmware API.
        # Disable it for subsequent frames and keep the original English line
        # visible rather than allowing preview rendering to stop the loop.
        OVERLAY_FONT = None
        for dx, dy in (
            (-offset, -offset),
            (offset, -offset),
            (-offset, offset),
            (offset, offset),
        ):
            draw_string(x + dx, y + dy, text, shadow)
        draw_string(x, y, text, foreground)


def link_status_line(ack_monitor):
    if ack_monitor.consecutive_timeouts > 0:
        state = "DEGRADED"
    elif ack_monitor.acked > 0:
        state = "ONLINE"
    else:
        state = "WAIT"
    rtt_ms = ack_monitor.last_rtt_ms
    return "TITAN {} ACK={} RTT={}ms".format(
        state,
        ack_monitor.acked,
        rtt_ms if rtt_ms is not None else -1,
    )


def train_lock_reason(snapshot, train_controller, now_ms, elapsed_ms, vision_phase):
    """Return a presentation-only explanation for the current TRAIN lock."""
    if vision_phase != "TARGET":
        return "WAIT TARGET"
    if not isinstance(snapshot, dict) or snapshot.get("ver") is None:
        return "WAIT TITAN"
    if not snapshot.get("link_online"):
        return "WAIT TITAN"
    if not snapshot.get("have_vision") or snapshot.get("vision_stale"):
        return "WAIT TARGET"
    if not snapshot.get("have_actionable"):
        return "WAIT ACTION"
    if snapshot.get("pose") != 0:
        return "WAIT POSE"
    if not snapshot.get("gate_present") or snapshot.get("gate_fault"):
        return "GATE FAULT"
    if (
        train_controller.pending_seq is not None
        or train_controller.active_seq is not None
        or (
            train_controller.terminal_since_ms is not None
            and elapsed_ms(now_ms, train_controller.terminal_since_ms)
            < train_controller.terminal_hold_ms
        )
    ):
        return "WAIT ACTION"
    return "READY"


def configure_uart2():
    err.check_raise(
        pinmap.set_pin_function("B0", "UART2_TX"),
        "Failed to configure B0/U2T as UART2_TX",
    )
    err.check_raise(
        pinmap.set_pin_function("B1", "UART2_RX"),
        "Failed to configure B1/U2R as UART2_RX",
    )
    return uart.UART(UART_DEVICE, UART_BAUD)


def elapsed_ms(now_ms, previous_ms):
    ticks_diff = getattr(time, "ticks_diff", None)
    if ticks_diff is not None:
        # MaixPy argument order is (previous, current), unlike MicroPython.
        return ticks_diff(previous_ms, now_ms)
    return now_ms - previous_ms


def handle_message(
    message,
    ack_monitor,
    now_ms,
    authority,
    train_controller=None,
    sign_motion_controller=None,
):
    if message["type"] == "ACK":
        if len(message["args"]) != 1:
            ack_monitor.note_malformed()
            print("Malformed ACK:", message)
            return
        status = message["args"][0]
        if train_controller is not None:
            train_controller.note_ack(message["seq"], status, now_ms)
        if sign_motion_controller is not None:
            sign_motion_controller.note_ack(message["seq"], status, now_ms)
        result = ack_monitor.acknowledge(
            message["seq"], status, now_ms, elapsed_ms
        )
        print(
            "ACK seq={} status={} result={}".format(
                message["seq"], status, result
            )
        )
    elif message["type"] == "STATUS":
        # STATUS is Titan telemetry only. Never close PING/VISION pending.
        try:
            snapshot = interpret_status(message)
        except ValueError:
            print("Malformed STATUS:", message)
            return
        authority["snapshot"] = snapshot
        authority["last_status_ms"] = now_ms
        authority["status_seen"] = True
        print(authority_status_line(snapshot))
    elif message["type"] == "AITRUST":
        # AITRUST is Titan telemetry only. Never close PING/VISION/TRAIN/SIGN pending ACK.
        # Cannot trigger training start or mechanical actions.
        try:
            snapshot = interpret_aitrust(message)
        except ValueError as exc:
            print("Malformed AITRUST:", message, exc)
            return
        authority["aitrust_snapshot"] = snapshot
        authority["last_aitrust_ms"] = now_ms
        authority["aitrust_seen"] = True
        authority["aitrust_generation"] = authority.get("aitrust_generation", 0) + 1
        print(aitrust_status_line(snapshot))
    elif message["type"] == "TRAINSTAT":
        if train_controller is None or not train_controller.note_train_status(
            message, now_ms, elapsed_ms
        ):
            print("Malformed/unexpected TRAINSTAT:", message)
            return
        print(train_controller.status_line(False))
    elif message["type"] == "SIGNSTAT":
        if sign_motion_controller is None or not sign_motion_controller.note_status(
            message, now_ms
        ):
            print("Malformed/unexpected SIGNSTAT:", message)
            return
        print("SIGNSTAT state={} result={}".format(
            sign_motion_controller.state,
            sign_motion_controller.result,
        ))
    else:
        print("Titan message:", message)


def expire_authority_snapshot(authority, now_ms):
    """Fail closed when Titan STATUS telemetry stops arriving.

    ACK/PING/VISION link monitoring remains independent. This only controls the
    freshness of the Titan-authority display and prevents a stale snapshot from
    looking like a current mechanical state after a peer reset or disconnect.
    """
    last_status_ms = authority.get("last_status_ms")
    if last_status_ms is None:
        return False
    if elapsed_ms(now_ms, last_status_ms) < STATUS_TIMEOUT_MS:
        return False
    authority["snapshot"] = dict(UNKNOWN_SNAPSHOT)
    authority["last_status_ms"] = None
    print("Titan STATUS expired; authority UNKNOWN")
    return True


def expire_aitrust_snapshot(authority, now_ms):
    """Fail closed when Titan AITRUST telemetry stops arriving (1500 ms).

    Maintains independent freshness for the TitanTrust AI reference.
    """
    last_aitrust_ms = authority.get("last_aitrust_ms")
    if last_aitrust_ms is None:
        return False
    if elapsed_ms(now_ms, last_aitrust_ms) < AITRUST_TIMEOUT_MS:
        return False
    authority["aitrust_snapshot"] = dict(UNKNOWN_AITRUST_SNAPSHOT)
    authority["last_aitrust_ms"] = None
    print("Titan AITRUST expired")
    return True


def send_frame(serial, ack_monitor, message_type, sequence, now_ms, *args):
    frame = encode_frame(message_type, sequence, *args)
    success, error_text = write_tracked(
        serial, frame, sequence, message_type, now_ms, ack_monitor
    )
    if not success:
        print(
            "UART TX failed type={} seq={}: {}".format(
                message_type, sequence, error_text
            )
        )
    return success


def close_vision_source(source):
    close = getattr(source, "close", None)
    if close is not None:
        close()
        return
    # Existing YOLO source is integrity-pinned. Release its owned Maix objects
    # here so the historical source baseline remains unchanged.
    import gc

    for attribute, empty_value in (
        ("last_frame", None),
        ("last_objects", []),
        ("camera", None),
        ("detector", None),
    ):
        if hasattr(source, attribute):
            setattr(source, attribute, empty_value)
    gc.collect()


def new_target_pipeline():
    tracker = TargetTracker(
        TARGET_STABLE_FRAMES,
        TARGET_STALE_TIMEOUT_MS,
        TARGET_MATCH_IOU,
    )
    return tracker, VisionScheduler(
        tracker,
        VISION_PROCESS_INTERVAL_MS,
        VISION_INTERVAL_MS,
    )


def start_imitation_after_train(
    previous_train_state, train_controller, imitation_controller, now_ms
):
    if (
        previous_train_state != "COMPLETED"
        and train_controller.state == "COMPLETED"
        and imitation_controller.state == "IDLE"
    ):
        imitation_controller.start(now_ms)
        return True
    return False


def web_train_rejection_reason(
    target_tracker,
    authority,
    ack_monitor,
    train_controller,
    imitation_controller,
    vision_phase,
    now_ms,
):
    """Return a safe rejection reason; this function never sends UART data."""
    if vision_phase != "TARGET":
        return "not_target_phase"
    if imitation_controller.state != "IDLE":
        return "training_not_idle"
    target = target_tracker.active
    target_seen_ms = target_tracker.active_seen_ms
    if (
        not isinstance(target, (tuple, list)) or len(target) != 6
        or any(type(value) is not int for value in target)
        or target_seen_ms is None
        or elapsed_ms(now_ms, target_seen_ms) > TARGET_STALE_TIMEOUT_MS
    ):
        return "bottle_not_stable"
    if target[0] != WEB_TRAIN_BOTTLE_CLASS_ID:
        return "not_bottle"
    if target[5] < int(YOLO_CONFIDENCE_THRESHOLD * 100.0 + 0.5):
        return "bottle_confidence_low"
    snapshot = authority.get("snapshot") if isinstance(authority, dict) else None
    last_status_ms = authority.get("last_status_ms") if isinstance(authority, dict) else None
    if (
        not isinstance(snapshot, dict) or snapshot.get("ver") is None
        or last_status_ms is None
        or elapsed_ms(now_ms, last_status_ms) >= STATUS_TIMEOUT_MS
    ):
        return "titan_status_stale"
    if not snapshot.get("link_online"):
        return "titan_link_offline"
    if not snapshot.get("have_vision") or snapshot.get("vision_stale") is not False:
        return "titan_vision_stale"
    if not snapshot.get("have_actionable"):
        return "titan_not_actionable"
    if snapshot.get("pose") != 0:
        return "titan_pose_not_ok"
    if not snapshot.get("gate_present") or snapshot.get("gate_fault"):
        return "titan_gate_unavailable"
    if getattr(ack_monitor, "consecutive_timeouts", 0) != 0:
        return "uart_degraded"
    if not train_controller.enabled(snapshot, now_ms, elapsed_ms):
        return "train_busy"
    return None


def consume_web_train_intent(
    live_sidecar,
    serial,
    ack_monitor,
    sequence,
    target_tracker,
    authority,
    train_controller,
    imitation_controller,
    vision_phase,
    now_ms,
):
    """Consume at most one web intent through the existing tracked TRAIN path."""
    request_id = live_sidecar.take_web_train_intent()
    if request_id is None:
        return sequence
    reason = web_train_rejection_reason(
        target_tracker, authority, ack_monitor, train_controller,
        imitation_controller, vision_phase, now_ms,
    )
    if reason is not None:
        live_sidecar.note_web_train_rejected(request_id, reason)
        return sequence
    if not send_frame(
        serial, ack_monitor, "TRAIN", sequence, now_ms, TRAIN_MODE_REHAB
    ):
        live_sidecar.note_web_train_rejected(request_id, "uart_write_failed")
        return sequence
    train_controller.note_sent(sequence, now_ms)
    live_sidecar.note_web_train_submitted(request_id)
    return (sequence + 1) & 0xFFFF


def _sign_controller_status(controller):
    """Read a controller snapshot without assuming one concrete API shape."""
    if controller is None:
        return {}
    status_method = getattr(controller, "status", None)
    if callable(status_method):
        try:
            status = status_method()
            if isinstance(status, dict):
                return dict(status)
        except Exception:
            pass
    status = {}
    for key in (
        "state", "lesson_id", "lesson_name", "selected_lesson_id",
        "selected_lesson", "gesture_id", "confidence", "stable_ms",
        "valid", "error_code", "can_start", "can_cancel",
    ):
        value = getattr(controller, key, None)
        if value is not None:
            status[key] = value
    return status


def sign_status_snapshot(
    controller,
    recognition=None,
    sign_motion_controller=None,
    authority=None,
    now_ms=None,
):
    """Build the JSON-safe status consumed by the sign web endpoint.

    This is presentation/transport state only.  It never infers that a
    course started merely because a gesture was recognized.
    """
    status = _sign_controller_status(controller)
    if str(status.get("state", "")).upper() == "COMPLETE":
        course_gesture = status.get("gesture_id")
        if isinstance(course_gesture, str):
            status["course_gesture_id"] = course_gesture
    # Preserve course evidence before overlaying the live recognizer. The
    # controller retains the result that met its gate; live values can reset
    # after completion and must not replace that evidence in a report.
    course_stable = status.get("stable_ms")
    if type(course_stable) is int and 0 <= course_stable <= 600000:
        status["course_stable_ms"] = course_stable
    course_confidence = status.get("confidence")
    if type(course_confidence) in (int, float) and 0 <= course_confidence <= 1:
        status["course_confidence"] = course_confidence
    controller_error = status.get("error_code")
    if controller_error is not None:
        status["session_error_code"] = controller_error
    if recognition is not None:
        observed_ms = recognition.get("observed_ms")
        if type(observed_ms) is int and observed_ms >= 0:
            read_ms = now_ms if now_ms is not None else time.ticks_ms()
            age_ms = elapsed_ms(read_ms, observed_ms)
            status["recognition_observed_ms"] = observed_ms
            status["recognition_age_ms"] = max(0, age_ms)
            status["recognition_fresh"] = 0 <= age_ms < SIGN_STALE_TIMEOUT_MS
        recognition_error = recognition.get("error_code")
        if recognition_error is not None:
            status["recognition_error_code"] = recognition_error
        for key in ("gesture_id", "confidence", "stable_ms", "valid"):
            if key in recognition:
                status[key] = recognition[key]
        if isinstance(recognition.get("shape_debug"), dict):
            status["shape_debug"] = recognition["shape_debug"]
    state = status.get("state")
    if not isinstance(state, str) or not state:
        state = "unavailable" if controller is None else "idle"
    status["state"] = state
    if state.upper() not in ("FAULT", "TIMEOUT", "CANCELLED", "REVIEWED"):
        if recognition is not None and recognition.get("error_code") is not None:
            status["error_code"] = recognition.get("error_code")
    if "lesson_id" not in status:
        selected = status.get("selected_lesson_id")
        if isinstance(selected, (str, int)):
            status["lesson_id"] = selected
    lesson = status.get("lesson")
    if isinstance(lesson, dict):
        if "lesson_name" not in status:
            status["lesson_name"] = lesson.get(
                "name_zh", lesson.get("chinese_name", lesson.get("lesson_id"))
            )
        for key in ("demo_mode", "mechanical_pose"):
            if key not in status and key in lesson:
                status[key] = lesson.get(key)
    # Explicitly expose the confirmation policy for the UI and audit logs.
    status["requires_confirmation"] = True
    if sign_motion_controller is not None:
        try:
            status["mechanical_motion"] = sign_motion_controller.status()
        except Exception:
            status["mechanical_motion"] = {"state": "unavailable"}
    if "can_start" not in status:
        status["can_start"] = bool(
            controller is not None
            and status.get("lesson_id") is not None
            and state in ("LESSON_SELECTED", "lesson_selected")
        )
    if "can_cancel" not in status:
        status["can_cancel"] = bool(
            controller is not None
            and state in (
                "DEMO_READY", "DEMONSTRATING", "IMITATING",
                "demo_ready", "demonstrating", "imitating",
            )
        )
    if authority is not None:
        if now_ms is None:
            ticks_ms = getattr(time, "ticks_ms", None)
            if callable(ticks_ms):
                try:
                    now_ms = ticks_ms()
                except Exception:
                    now_ms = None
            if now_ms is None:
                try:
                    import time as _py_time
                    if hasattr(_py_time, "monotonic"):
                        now_ms = int(_py_time.monotonic() * 1000)
                    else:
                        now_ms = int(_py_time.time() * 1000)
                except Exception:
                    now_ms = None

        if now_ms is not None:
            expire_authority_snapshot(authority, now_ms)
            expire_aitrust_snapshot(authority, now_ms)

        last_status_ms = authority.get("last_status_ms")
        snap = authority.get("snapshot")
        status_stale = (
            now_ms is not None
            and last_status_ms is not None
            and elapsed_ms(now_ms, last_status_ms) >= STATUS_TIMEOUT_MS
        )
        if last_status_ms is not None and not status_stale and isinstance(snap, dict):
            status["link_online"] = bool(snap.get("link_online"))
        elif authority.get("status_seen") or status_stale:
            status["link_online"] = False
        else:
            status["link_online"] = None

        last_aitrust_ms = authority.get("last_aitrust_ms")
        ai_snap = authority.get("aitrust_snapshot")
        generation = authority.get("aitrust_generation", 0)
        aitrust_expired = (
            now_ms is not None
            and last_aitrust_ms is not None
            and elapsed_ms(now_ms, last_aitrust_ms) >= AITRUST_TIMEOUT_MS
        )
        if (
            last_aitrust_ms is not None
            and not aitrust_expired
            and isinstance(ai_snap, dict)
            and ai_snap.get("version") is not None
        ):
            status["aitrust"] = {
                "version": ai_snap.get("version"),
                "ready": bool(ai_snap.get("ready")),
                "class_id": ai_snap.get("class_id"),
                "vision_age_ms": ai_snap.get("vision_age_ms"),
                "seq": ai_snap.get("seq"),
                "generation": generation,
                "expired": False,
                "rx_time_ms": last_aitrust_ms,
            }
        elif authority.get("aitrust_seen") or aitrust_expired:
            status["aitrust"] = {
                "generation": generation,
                "expired": True,
                "state": "expired",
            }
        else:
            status["aitrust"] = {
                "generation": 0,
                "expired": False,
                "state": "not_reported",
            }
    return status


def _sign_controller_lesson_ids(controller):
    """Return a catalog if the controller exposes one, else ``None``."""
    if controller is None:
        return ()
    for name in ("lesson_ids", "LESSON_IDS", "lessons", "LESSONS", "catalog"):
        value = getattr(controller, name, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if isinstance(value, dict):
            return tuple(value.keys())
        if isinstance(value, (tuple, list, set)):
            return tuple(value)
    return None


def _sign_selected_lesson(controller):
    status = _sign_controller_status(controller)
    for key in ("lesson_id", "selected_lesson_id"):
        value = status.get(key)
        if value is not None:
            return value
    for key in ("lesson_id", "selected_lesson_id"):
        value = getattr(controller, key, None)
        if value is not None:
            return value
    selected = getattr(controller, "selected_lesson", None)
    if isinstance(selected, dict):
        return selected.get("lesson_id", selected.get("id"))
    return selected if isinstance(selected, (str, int)) else None


def _sign_lesson_config(controller):
    status = _sign_controller_status(controller)
    lesson = status.get("lesson")
    if isinstance(lesson, dict):
        return lesson
    lesson = getattr(controller, "lesson", None)
    return lesson if isinstance(lesson, dict) else None


def _sign_mechanical_sequence_id(controller):
    """Return the fixed recipe id for the selected lesson, if any."""
    lesson = _sign_lesson_config(controller)
    if lesson is None:
        return None
    value = lesson.get("mechanical_sequence_id")
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13) else None


def _sign_mechanical_enabled_for(controller, motion_controller=None):
    return bool(
        SIGN_MECHANICAL_DEMO_ENABLED
        and motion_controller is not None
        and _sign_mechanical_sequence_id(controller) is not None
    )


def _sign_call(controller, method_names, *args):
    """Call the first available controller method; return (ok, reason, raw)."""
    if controller is None:
        return False, "sign_unavailable", None
    method = None
    for name in method_names:
        candidate = getattr(controller, name, None)
        if callable(candidate):
            method = candidate
            break
    if method is None:
        return False, "controller_interface", None
    try:
        result = method(*args)
    except Exception as exc:
        return False, "controller_{}".format(type(exc).__name__), None
    if result is False:
        return False, "controller_rejected", result
    if isinstance(result, dict):
        if result.get("ok") is False or result.get("accepted") is False:
            reason = result.get("reason", "controller_rejected")
            return False, str(reason), result
    return True, None, result


def sign_start_rejection_reason(
    authority,
    ack_monitor,
    controller,
    now_ms,
    mechanical=False,
    motion_controller=None,
):
    """Fail-closed Titan/safety checks for an explicitly confirmed start."""
    if controller is None:
        return "sign_unavailable"
    if _sign_selected_lesson(controller) is None:
        return "lesson_not_selected"
    status = _sign_controller_status(controller)
    state = str(status.get("state", "")).upper()
    if state in ("DEMO_READY", "DEMONSTRATING", "IMITATING"):
        return "sign_busy"
    lesson = _sign_lesson_config(controller)
    demo_mode = lesson.get("demo_mode") if isinstance(lesson, dict) else None
    mechanical_pose = lesson.get("mechanical_pose") if isinstance(lesson, dict) else None
    if demo_mode in ("full", "partial"):
        # No unverified pose may be presented as a formal mechanical sign.
        # The current MVP lessons are screen_only and therefore do not need
        # the full Titan gate/actionable target checks below.
        if mechanical_pose is None or lesson.get("mechanical_pose_status") not in (
            "VALIDATED", "validated", "OK", "ok"
        ):
            return "mechanical_demo_unverified"
    if mechanical:
        if not _sign_mechanical_enabled_for(controller, motion_controller):
            return "mechanical_demo_unavailable"
        if not motion_controller.can_start():
            return "mechanical_busy"
    snapshot = authority.get("snapshot") if isinstance(authority, dict) else None
    last_status_ms = authority.get("last_status_ms") if isinstance(authority, dict) else None
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("ver") is None
        or last_status_ms is None
        or elapsed_ms(now_ms, last_status_ms) >= SIGN_STALE_TIMEOUT_MS
    ):
        return "titan_status_stale"
    if not snapshot.get("link_online"):
        return "titan_link_offline"
    if mechanical or demo_mode != "screen_only":
        # A mechanical recipe is guarded by Titan's deterministic gate even
        # though its lesson metadata remains screen_only until bench review.
        if not snapshot.get("gate_present") or snapshot.get("gate_fault"):
            return "titan_gate_unavailable"
    if demo_mode != "screen_only":
        if not snapshot.get("have_vision") or snapshot.get("vision_stale") is not False:
            return "titan_vision_stale"
        if not snapshot.get("have_actionable"):
            return "titan_not_actionable"
        if snapshot.get("pose") != 0:
            return "titan_pose_not_ok"
        if not snapshot.get("gate_present") or snapshot.get("gate_fault"):
            return "titan_gate_unavailable"
    if getattr(ack_monitor, "consecutive_timeouts", 0) != 0:
        return "uart_degraded"
    return None


def consume_sign_intent(
    live_sidecar,
    sign_controller,
    authority,
    ack_monitor,
    now_ms,
    serial=None,
    sequence=None,
    sign_motion_controller=None,
):
    """Consume one queued sign command after main-loop safety revalidation.

    HTTP callbacks only enqueue.  The main loop may translate an explicitly
    confirmed request into the fixed ``SIGN`` recipe, but the browser cannot
    supply servo positions or bypass the Titan protocol boundary.
    """
    take = getattr(live_sidecar, "take_web_sign_intent", None)
    if not callable(take):
        return False
    command = take()
    if not isinstance(command, dict):
        return False
    request_id = command.get("request_id")
    action = command.get("action")
    reject = getattr(live_sidecar, "note_web_sign_rejected", None)
    applied = getattr(live_sidecar, "note_web_sign_applied", None)

    def fail(reason):
        if callable(reject):
            reject(request_id, reason)
        return False

    if action == "select":
        lesson_id = command.get("lesson_id")
        if not isinstance(lesson_id, (str, int)) or not str(lesson_id):
            return fail("invalid_lesson")
        lesson_ids = _sign_controller_lesson_ids(sign_controller)
        if lesson_ids is not None and lesson_id not in lesson_ids and str(lesson_id) not in lesson_ids:
            return fail("invalid_lesson")
        state = str(_sign_controller_status(sign_controller).get("state", "")).upper()
        if state in ("DEMO_READY", "DEMONSTRATING", "IMITATING"):
            return fail("sign_busy")
        ok, reason, _raw = _sign_call(
            sign_controller,
            ("select_lesson", "select", "choose_lesson", "choose"),
            lesson_id,
        )
        if not ok:
            return fail(reason or "invalid_lesson")
        if callable(applied):
            applied(request_id, "lesson_selected")
        return True
    if action == "start":
        reason = sign_start_rejection_reason(
            authority,
            ack_monitor,
            sign_controller,
            now_ms,
            mechanical=_sign_mechanical_enabled_for(
                sign_controller, sign_motion_controller
            ),
            motion_controller=sign_motion_controller,
        )
        if reason is not None:
            return fail(reason)
        ok, reason, _raw = _sign_call(
            sign_controller,
            ("start", "begin", "confirm_start"),
            now_ms,
            True,
            True,
            True,
            False,
        )
        if not ok:
            return fail(reason or "start_rejected")
        # The controller deliberately separates human confirmation from its
        # demo and learner phases.  Start the deterministic screen demo here;
        # main-loop tick/elapsed time will finish it after 3 seconds.
        ok, reason, _raw = _sign_call(
            sign_controller,
            ("begin_demo", "start_demo"),
            now_ms,
            True,
            True,
            False,
        )
        if not ok:
            return fail(reason or "demo_rejected")
        mechanical = _sign_mechanical_enabled_for(
            sign_controller, sign_motion_controller
        )
        if mechanical:
            if serial is None or sequence is None:
                _sign_call(sign_controller, ("fault",), "mechanical_transport_unavailable", now_ms)
                return fail("mechanical_transport_unavailable")
            sequence_id = _sign_mechanical_sequence_id(sign_controller)
            if not sign_motion_controller.begin_request(
                SIGN_ACTION_START, sequence, now_ms, sequence_id
            ):
                _sign_call(sign_controller, ("fault",), "mechanical_busy", now_ms)
                return fail("mechanical_busy")
            if not send_frame(
                serial,
                ack_monitor,
                "SIGN",
                sequence,
                now_ms,
                1,
                SIGN_ACTION_START,
                sequence_id,
            ):
                sign_motion_controller.note_send_failed(sequence)
                _sign_call(sign_controller, ("fault",), "mechanical_uart_write_failed", now_ms)
                return fail("uart_write_failed")
            sign_motion_controller.note_sent(
                sequence, SIGN_ACTION_START, now_ms, sequence_id
            )
            sign_motion_controller.last_sent_sequence = sequence
        if callable(applied):
            applied(request_id, "started")
        return True
    if action == "review":
        # Teaching-only outcome: no send_frame, no UART ACK completion and no
        # mechanical start/cancel/home. Bind the review to the selected run.
        status = _sign_controller_status(sign_controller)
        if (command.get("manual_confirm") is not True or
                command.get("lesson_id") != status.get("lesson_id") or
                type(command.get("session_token")) is not int or
                command.get("session_token") != status.get("session_token") or
                status.get("state") != "IMITATING" or status.get("can_review") is not True):
            return fail("review_not_allowed")
        last_status_ms = authority.get("last_status_ms")
        snapshot = authority.get("snapshot") or {}
        if (snapshot.get("link_online") is not True or type(last_status_ms) is not int or
                elapsed_ms(now_ms, last_status_ms) >= SIGN_STALE_TIMEOUT_MS):
            return fail("link_offline")
        if _sign_mechanical_enabled_for(sign_controller, sign_motion_controller):
            if sign_motion_controller.status().get("state") != SIGN_MOTION_COMPLETED:
                return fail("mechanical_incomplete")
        ok, reason, _raw = _sign_call(sign_controller, ("review_manual",),
                                    now_ms, True, command["session_token"])
        if not ok:
            return fail(reason or "review_not_allowed")
        if callable(applied):
            applied(request_id, "manual_review_recorded")
        return True
    if action == "cancel":
        mechanical = _sign_mechanical_enabled_for(
            sign_controller, sign_motion_controller
        )
        if mechanical and sign_motion_controller.can_cancel():
            if serial is None or sequence is None:
                return fail("mechanical_transport_unavailable")
            sequence_id = _sign_mechanical_sequence_id(sign_controller)
            if not sign_motion_controller.begin_request(
                SIGN_ACTION_CANCEL, sequence, now_ms, sequence_id
            ):
                return fail("mechanical_busy")
            if not send_frame(
                serial,
                ack_monitor,
                "SIGN",
                sequence,
                now_ms,
                1,
                SIGN_ACTION_CANCEL,
                sequence_id,
            ):
                sign_motion_controller.note_send_failed(sequence)
                return fail("uart_write_failed")
            sign_motion_controller.note_sent(
                sequence, SIGN_ACTION_CANCEL, now_ms, sequence_id
            )
            sign_motion_controller.last_sent_sequence = sequence
            ok, reason, _raw = _sign_call(
                sign_controller, ("cancel", "stop", "abort"), now_ms
            )
            if not ok:
                return fail(reason or "cancel_rejected")
            if callable(applied):
                applied(request_id, "cancelled")
            return True
        ok, reason, _raw = _sign_call(
            sign_controller, ("cancel", "stop", "abort"), now_ms
        )
        if not ok:
            return fail(reason or "cancel_rejected")
        if callable(applied):
            applied(request_id, "cancelled")
        return True
    return fail("invalid_command")


def load_sign_components():
    """Load optional sign modules without affecting the rehab import path.

    The feature modules are intentionally owned separately from this adapter.
    Missing modules therefore produce an unavailable sign mode rather than a
    copied fallback classifier or a partial hardware action.
    """
    try:
        from sign_lesson import SignLessonController
    except Exception as exc:
        return None, None, None, "sign_lesson_unavailable:{}".format(type(exc).__name__)
    try:
        from sign_session_log import SignSessionCsvLogger
    except Exception:
        SignSessionCsvLogger = None
    classifier = None
    try:
        import gesture_classifier as gesture_module

        cls = getattr(gesture_module, "GestureClassifier", None)
        # The deployed learned JSON is the earlier three-class model.  The
        # The expanded OpenSignHand UI also needs expression shapes beyond the
        # legacy three-class model, so sign mode deliberately uses the bounded
        # rule classifier.
        # Model loading remains available to host experiments via
        # ``create_classifier`` and is not silently presented as multi-class.
        if callable(cls):
            try:
                classifier = cls()
            except TypeError:
                classifier = cls(HAND_MODEL_PATH)
    except Exception:
        # A controller can still expose screen-only lessons while recognition
        # reports classifier_unavailable.  Do not turn this into a rehab fault.
        classifier = None
    try:
        controller = SignLessonController()
    except TypeError:
        try:
            controller = SignLessonController(lessons=None)
        except Exception as exc:
            return None, None, classifier, "sign_controller_init:{}".format(type(exc).__name__)
    except Exception as exc:
        return None, None, classifier, "sign_controller_init:{}".format(type(exc).__name__)
    logger = None
    if callable(SignSessionCsvLogger):
        try:
            logger = SignSessionCsvLogger(SIGN_SESSION_LOG_PATH)
        except Exception:
            logger = None
    return controller, logger, classifier, None


def _sign_controller_active(controller):
    status = _sign_controller_status(controller)
    if status.get("active") is True:
        return True
    value = status.get("state", getattr(controller, "state", ""))
    return str(value).upper() in (
        "RUNNING", "ACTIVE", "DEMO", "DEMONSTRATING", "IMITATE",
        "IMITATING", "LEARNING",
    )


def _sign_observe(controller, recognition, now_ms):
    if controller is None or not _sign_controller_active(controller):
        return None
    for name in ("observe", "update", "step", "consume"):
        method = getattr(controller, name, None)
        if callable(method):
            try:
                return method(recognition, now_ms)
            except TypeError:
                try:
                    return method(recognition)
                except Exception:
                    return None
            except Exception:
                return None
    return None


def _sign_terminal(controller):
    if controller is None:
        return False
    status = _sign_controller_status(controller)
    value = status.get("terminal")
    if value is True:
        return True
    state = str(status.get("state", "")).lower()
    return state.upper() in (
        "COMPLETE", "COMPLETED", "REVIEWED", "TIMEOUT", "CANCELLED", "FAILED", "FAULT"
    )


def _sign_log_session(logger, controller, now_ms):
    if logger is None or controller is None:
        return None
    append = getattr(logger, "append", None)
    if not callable(append):
        return None
    try:
        return append(controller, now_ms)
    except Exception:
        return None


def record_sign_terminal(logger, controller, now_ms, already_recorded=False):
    """Persist one terminal sign session and retry after transient I/O errors."""
    if not _sign_terminal(controller):
        return False
    if already_recorded:
        return True
    return _sign_log_session(logger, controller, now_ms) is not None


def tick_sign_controller(
    controller,
    authority,
    now_ms,
    vision_fresh,
    sign_motion_controller=None,
    ack_monitor=None,
):
    """Advance one sign controller cycle and finish the fixed screen demo.

    No UART or servo call is made here.  The only external inputs are the
    already-authoritative Titan status snapshot and local hand-source health.
    """
    if controller is None:
        return None
    snapshot = authority.get("snapshot") if isinstance(authority, dict) else None
    last_status_ms = authority.get("last_status_ms") if isinstance(authority, dict) else None
    link_online = bool(
        isinstance(snapshot, dict)
        and snapshot.get("link_online")
        and last_status_ms is not None
        and elapsed_ms(now_ms, last_status_ms) < SIGN_STALE_TIMEOUT_MS
    )
    vision_fresh = bool(vision_fresh)
    tick = getattr(controller, "tick", None)
    if callable(tick):
        tick(
            now_ms,
            link_online=link_online,
            vision_fresh=vision_fresh,
            vision_stale=not vision_fresh,
        )
    mechanical = _sign_mechanical_enabled_for(
        controller, sign_motion_controller
    )
    if mechanical and sign_motion_controller is not None:
        pending_ack = None
        if ack_monitor is not None and sign_motion_controller.active_request_seq is not None:
            pending_ack = sign_motion_controller.active_request_seq in getattr(
                ack_monitor, "pending", {}
            )
        sign_motion_controller.tick(
            now_ms,
            ack_pending=pending_ack,
            status_fresh=bool(link_online),
        )
        motion_status = sign_motion_controller.status()
        if motion_status["state"] == SIGN_MOTION_COMPLETED:
            status = _sign_controller_status(controller)
            if str(status.get("state", "")).upper() == "DEMONSTRATING":
                finish_demo = getattr(controller, "finish_demo", None)
                if callable(finish_demo):
                    finish_demo(
                        now_ms,
                        link_online=link_online,
                        vision_fresh=vision_fresh,
                        vision_stale=not vision_fresh,
                    )
        elif motion_status["state"] == SIGN_MOTION_FAILED:
            # A terminal motion result belongs to the demonstration that sent
            # it.  After a new lesson is selected, the previous ACK failure
            # must not fault that new lesson before it can start.
            status = _sign_controller_status(controller)
            if str(status.get("state", "")).upper() == "DEMONSTRATING":
                fault = getattr(controller, "fault", None)
                if callable(fault):
                    fault(motion_status.get("last_error") or "mechanical_motion_failed", now_ms)
        elif motion_status["state"] == SIGN_MOTION_CANCELLED:
            # The browser cancellation already transitions the local lesson;
            # this branch covers a Titan-side cancellation/link-loss report.
            status = _sign_controller_status(controller)
            if str(status.get("state", "")).upper() not in (
                "CANCELLED", "COMPLETE", "REVIEWED", "FAULT", "TIMEOUT"
            ):
                cancel = getattr(controller, "cancel", None)
                if callable(cancel):
                    cancel(now_ms)
    status = _sign_controller_status(controller)
    state = str(status.get("state", "")).upper()
    demo_started_ms = status.get("demo_started_ms")
    if (
        state == "DEMONSTRATING"
        and isinstance(demo_started_ms, int)
        and not mechanical
        and elapsed_ms(now_ms, demo_started_ms) >= SIGN_SCREEN_DEMO_MS
    ):
        finish_demo = getattr(controller, "finish_demo", None)
        if callable(finish_demo):
            finish_demo(
                now_ms,
                link_online=link_online,
                vision_fresh=vision_fresh,
                vision_stale=not vision_fresh,
            )
    return _sign_controller_status(controller)


class ImitationCancelButtonController:
    """Release-edge touch controller for the local imitation cancel button."""

    def __init__(self):
        self.display_rect = None
        self.pressed_inside = False
        self.last_pressed = False

    def set_display_rect(self, rect):
        self.display_rect = tuple(rect) if rect is not None else None

    def reset(self):
        self.display_rect = None
        self.pressed_inside = False
        self.last_pressed = False

    def _inside(self, x, y):
        if self.display_rect is None:
            return False
        left, top, width, height = self.display_rect
        return left <= x < left + width and top <= y < top + height

    def update_touch(self, x, y, pressed, enabled):
        """Return true only for an enabled press followed by an inside release."""
        inside = self._inside(x, y)
        emit = False
        if pressed and not self.last_pressed:
            self.pressed_inside = bool(enabled and inside)
        elif not pressed and self.last_pressed:
            emit = bool(enabled and inside and self.pressed_inside)
            self.pressed_inside = False
        self.last_pressed = bool(pressed)
        return emit


def main():
    serial = configure_uart2()
    parser = StreamParser()
    ack_monitor = AckMonitor(ACK_TIMEOUT_MS)
    target_tracker, vision_scheduler = new_target_pipeline()
    vision_read_errors = 0
    uart_read_errors = 0
    try:
        vision_source = create_vision_source(
            VISION_MODE,
            YOLO_MODEL_PATH,
            YOLO_CONFIDENCE_THRESHOLD,
            YOLO_IOU_THRESHOLD,
            YOLO_ALLOWED_CLASS_IDS,
        )
    except Exception as exc:
        print("vision init failed; PING-only mode:", exc)
        vision_source = DisabledVisionSource("init_failed")
    screen = None
    image_module = None
    touch = None
    if VISION_MODE == "yolo11" and SHOW_PREVIEW:
        try:
            from maix import display, image, touchscreen

            screen = display.Display()
            image_module = image
            touch = touchscreen.TouchScreen()
            load_overlay_font(image_module)
        except Exception as exc:
            print("display/touch init failed; console-only mode:", exc)
    sequence = 0
    last_ping_ms = None
    last_stats_ms = None
    last_preview_ms = None
    last_hand_process_ms = None
    authority = {
        "snapshot": dict(UNKNOWN_SNAPSHOT),
        "last_status_ms": None,
        "status_seen": False,
        "aitrust_snapshot": dict(UNKNOWN_AITRUST_SNAPSHOT),
        "last_aitrust_ms": None,
        "aitrust_seen": False,
        "aitrust_generation": 0,
    }
    train_controller = TrainButtonController(ACK_TIMEOUT_MS)
    imitation_controller = ImitationSessionController(
        IMITATION_GOAL_REPETITIONS,
        IMITATION_TIMEOUT_MS,
        stable_frames=3,
        terminal_hold_ms=IMITATION_TERMINAL_HOLD_MS,
        quality_tracker=RhythmQualityTracker(
            stable_frames=3, hold_grace_ms=700
        ),
    )
    cancel_controller = ImitationCancelButtonController()
    goal_controller = RepetitionGoalController(initial=IMITATION_GOAL_REPETITIONS)
    session_logger = SessionCsvLogger(SESSION_LOG_PATH)
    recorded_session_start_ms = None
    sign_controller = None
    sign_session_logger = None
    sign_recognition = {
        "gesture_id": None,
        "confidence": 0.0,
        "stable_ms": 0,
        "valid": False,
        "error_code": "sign_disabled",
    }
    sign_recorded_terminal = False
    sign_vision_read_ok = False
    sign_enabled = bool(SIGN_MODE)
    sign_motion_controller = None
    if sign_enabled and SIGN_MECHANICAL_DEMO_ENABLED and SignMotionController is not None:
        try:
            sign_motion_controller = SignMotionController(
                sequence_id=1,
                ack_timeout_ms=ACK_TIMEOUT_MS,
                status_timeout_ms=SIGN_MOTION_STATUS_TIMEOUT_MS,
            )
        except Exception as exc:
            print("sign mechanical demo unavailable:", exc)
    vision_phase = "TARGET"
    hand_source = None
    vision_payload = None
    if sign_enabled:
        sign_controller, sign_session_logger, sign_classifier, sign_error = load_sign_components()
        if sign_error is not None:
            print("sign mode component unavailable:", sign_error)
        try:
            close_vision_source(vision_source)
        except Exception:
            pass
        vision_source = None
        try:
            hand_source = HandLandmarksVisionSource(
                HAND_MODEL_PATH, classifier=sign_classifier,
                sign_detector_retry=SIGN_DETECTOR_RETRY_ENABLED,
            )
            print("sign detector retry={} max_calls=2 second_stage=0.8".format(
                SIGN_DETECTOR_RETRY_ENABLED))
            sign_vision_read_ok = True
        except Exception as exc:
            print("sign hand vision init failed:", exc)
            hand_source = None
            sign_vision_read_ok = False
        if sign_controller is not None and (
            sign_classifier is None or hand_source is None
        ):
            # Do not expose a partially wired sign mode as runnable.  Keeping
            # the controller out of the runtime snapshot also makes the API
            # explicitly report unavailable and fail-closed on start.
            print("sign mode unavailable; classifier and hand source are required")
            sign_controller = None
            sign_session_logger = None
        vision_phase = "SIGN"
        sign_recognition["error_code"] = (
            "sign_unavailable" if sign_controller is None else "not_started"
        )
    live_sidecar = None
    if LIVE_WEB_ENABLED:
        try:
            from live_sidecar import LiveWebSidecar

            def live_runtime_state():
                return {
                    "vision_phase": vision_phase,
                    "vision_source": vision_source,
                    "hand_source": hand_source,
                    "vision_scheduler": vision_scheduler,
                    "vision_stale_after_ms": TARGET_STALE_TIMEOUT_MS,
                    "vision_mode": VISION_MODE,
                    "vision_model": os.path.basename(YOLO_MODEL_PATH),
                    "target_payload": target_tracker.active,
                    "target_labels": TARGET_LABELS,
                    "train_controller": train_controller,
                    "imitation_controller": imitation_controller,
                    "sign_controller": sign_controller,
                    "sign_status": lambda: sign_status_snapshot(
                        sign_controller,
                        sign_recognition,
                        sign_motion_controller,
                        authority=authority,
                    ),
                    "authority": authority,
                    "ack_monitor": ack_monitor,
                }

            live_sidecar = LiveWebSidecar(
                live_runtime_state,
                elapsed_ms=elapsed_ms,
                sign_enabled=sign_enabled,
                now_ms_provider=time.ticks_ms,
            )
            if live_sidecar.start(host="0.0.0.0", port=8080):
                print("live web preview started on port 8080")
            else:
                print("live web preview unavailable:", live_sidecar.stream_fault)
        except Exception as exc:
            # The preview is strictly observational; setup must never prevent
            # vision, UART, safety gating, or local training from running.
            print("live web preview init failed; continuing:", exc)
            live_sidecar = None

    print("smart_hand MaixCAM2 link started on", UART_DEVICE)
    while not app.need_exit():
        now_ms = time.ticks_ms()
        try:
            received = serial.read()
        except Exception as exc:
            uart_read_errors += 1
            received = None
            report_repeated_error("UART RX failed", uart_read_errors, exc)
        if received:
            now_ms = time.ticks_ms()
            for message in parser.feed(received):
                train_state_before = train_controller.state
                handle_message(
                    message,
                    ack_monitor,
                    now_ms,
                    authority,
                    train_controller,
                    sign_motion_controller,
                )
                if not sign_enabled and start_imitation_after_train(
                    train_state_before,
                    train_controller,
                    imitation_controller,
                    now_ms,
                ):
                    print("USER IMITATION START goal={}".format(
                        imitation_controller.goal_repetitions
                    ))

        expire_authority_snapshot(authority, now_ms)
        expire_aitrust_snapshot(authority, now_ms)
        train_controller.expire(now_ms, elapsed_ms)
        imitation_controller.expire(now_ms, elapsed_ms)

        if sign_enabled and sign_controller is not None:
            try:
                tick_sign_controller(
                    sign_controller,
                    authority,
                    now_ms,
                    bool(sign_vision_read_ok and hand_source is not None),
                    sign_motion_controller,
                    ack_monitor,
                )
                sign_recorded_terminal = record_sign_terminal(
                    sign_session_logger,
                    sign_controller,
                    now_ms,
                    sign_recorded_terminal,
                )
            except Exception as exc:
                report_repeated_error("sign controller tick failed", 1, exc)

        if (
            not sign_enabled
            and imitation_controller.state == "ACTIVE"
            and vision_phase != "HAND"
        ):
            try:
                close_vision_source(vision_source)
                vision_source = None
                hand_source = HandLandmarksVisionSource(HAND_MODEL_PATH)
                vision_phase = "HAND"
                last_preview_ms = None
                last_hand_process_ms = None
                print("VISION PHASE HAND: YOLO released; motion request disabled")
            except Exception as exc:
                print("hand vision init failed:", exc)
                imitation_controller.mark_timeout(
                    now_ms, TERMINATION_REASON_HAND_VISION_INIT_FAILED
                )
                vision_phase = "HAND"

        if (
            not sign_enabled
            and
            imitation_controller.state in ("COMPLETE", "TIMEOUT")
            and recorded_session_start_ms != imitation_controller.started_ms
        ):
            print(imitation_controller.result_log_line(now_ms, elapsed_ms))
            try:
                session_number = session_logger.append(
                    imitation_controller,
                    now_ms,
                    elapsed_ms,
                    train_controller.last_duration_ms,
                )
                if session_number is not None:
                    reason_number = session_logger.append_reason(
                        imitation_controller,
                        session_number=session_number,
                    )
                    print("REASON SESSION {} path={}".format(
                        "SAVED" if reason_number is not None else "NOT SAVED",
                        SESSION_LOG_PATH + ".reason.csv",
                    ))
                    quality_number = session_logger.append_quality(
                        imitation_controller,
                        session_number=session_number,
                    )
                    print("QUALITY SESSION {} path={}".format(
                        "SAVED" if quality_number is not None else "NOT SAVED",
                        SESSION_LOG_PATH + ".quality.csv",
                    ))
                print("USER SESSION SAVED session={} path={}".format(
                    session_number, SESSION_LOG_PATH
                ))
            except Exception as exc:
                print("user session save failed:", exc)
            recorded_session_start_ms = imitation_controller.started_ms

        if (
            not sign_enabled
            and
            vision_phase == "HAND"
            and imitation_controller.terminal_expired(now_ms, elapsed_ms)
        ):
            try:
                close_vision_source(hand_source)
                hand_source = None
                vision_source = create_vision_source(
                    VISION_MODE,
                    YOLO_MODEL_PATH,
                    YOLO_CONFIDENCE_THRESHOLD,
                    YOLO_IOU_THRESHOLD,
                    YOLO_ALLOWED_CLASS_IDS,
                )
                target_tracker, vision_scheduler = new_target_pipeline()
                imitation_controller.reset()
                cancel_controller.reset()
                vision_phase = "TARGET"
                last_preview_ms = None
                last_hand_process_ms = None
                print("VISION PHASE TARGET: hand model released; YOLO restored")
            except Exception as exc:
                print("target vision restore failed; PING-only mode:", exc)
                vision_source = DisabledVisionSource("restore_failed")
                vision_phase = "TARGET"
                imitation_controller.reset()
                cancel_controller.reset()

        train_enabled = train_controller.enabled(
            authority["snapshot"], now_ms, elapsed_ms
        ) and vision_phase == "TARGET" and not sign_enabled
        goal_enabled = bool(
            vision_phase == "TARGET"
            and not sign_enabled
            and train_controller.pending_seq is None
            and train_controller.active_seq is None
            and imitation_controller.state == "IDLE"
        )
        if touch is not None:
            try:
                touch_x, touch_y, touch_pressed = touch.read()
                cancel_enabled = bool(
                    not sign_enabled
                    and
                    vision_phase == "HAND"
                    and imitation_controller.state == "ACTIVE"
                )
                if cancel_controller.update_touch(
                    touch_x, touch_y, touch_pressed, cancel_enabled
                ):
                    if imitation_controller.cancel(now_ms):
                        print("USER IMITATION CANCELLED")
                if goal_controller.update_touch(
                    touch_x, touch_y, touch_pressed, goal_enabled
                ):
                    imitation_controller.goal_repetitions = goal_controller.goal
                    print("USER GOAL CHANGED goal={}".format(
                        imitation_controller.goal_repetitions
                    ))
                if train_controller.update_touch(
                    touch_x, touch_y, touch_pressed, train_enabled
                ):
                    if send_frame(
                        serial,
                        ack_monitor,
                        "TRAIN",
                        sequence,
                        now_ms,
                        TRAIN_MODE_REHAB,
                    ):
                        train_controller.note_sent(sequence, now_ms)
                        sequence = (sequence + 1) & 0xFFFF
            except Exception as exc:
                report_repeated_error("touch read failed", 1, exc)
                touch = None

        # Local touch keeps its existing priority in rehab mode.  Sign mode
        # consumes only its bounded select/start/cancel queue; neither branch
        # lets the HTTP thread emit a TRAIN frame or touch servo parameters.
        if live_sidecar is not None:
            if sign_enabled:
                if sign_motion_controller is not None:
                    sign_motion_controller.last_sent_sequence = None
                consume_sign_intent(
                    live_sidecar,
                    sign_controller,
                    authority,
                    ack_monitor,
                    now_ms,
                    serial=serial,
                    sequence=sequence,
                    sign_motion_controller=sign_motion_controller,
                )
                if (
                    sign_motion_controller is not None
                    and sign_motion_controller.last_sent_sequence == sequence
                ):
                    sequence = (sequence + 1) & 0xFFFF
            else:
                web_train_reason = web_train_rejection_reason(
                    target_tracker, authority, ack_monitor, train_controller,
                    imitation_controller, vision_phase, now_ms,
                )
                live_sidecar.set_web_train_availability(
                    web_train_reason is None, web_train_reason
                )
                live_sidecar.set_web_train_submission_ready(
                    web_train_reason is None
                )
                sequence = consume_web_train_intent(
                    live_sidecar,
                    serial,
                    ack_monitor,
                    sequence,
                    target_tracker,
                    authority,
                    train_controller,
                    imitation_controller,
                    vision_phase,
                    now_ms,
                )

        if last_ping_ms is None or elapsed_ms(now_ms, last_ping_ms) >= PING_INTERVAL_MS:
            send_frame(serial, ack_monitor, "PING", sequence, now_ms)
            sequence = (sequence + 1) & 0xFFFF
            last_ping_ms = now_ms

        if (
            sign_enabled
            and vision_phase == "SIGN"
            and hand_source is not None
            and (
                last_hand_process_ms is None
                or elapsed_ms(now_ms, last_hand_process_ms)
                >= HAND_PROCESS_INTERVAL_MS
            )
        ):
            try:
                hand_now_ms = time.ticks_ms()
                sign_recognition = hand_source.read_sign(hand_now_ms)
                if isinstance(sign_recognition, dict):
                    # Timestamp completed inference, not the start of NPU work.
                    sign_recognition["observed_ms"] = time.ticks_ms()
                sign_vision_read_ok = True
                last_hand_process_ms = hand_now_ms
                _sign_observe(sign_controller, sign_recognition, hand_now_ms)
                sign_recorded_terminal = record_sign_terminal(
                    sign_session_logger,
                    sign_controller,
                    hand_now_ms,
                    sign_recorded_terminal,
                )
                if screen is not None and (
                    last_preview_ms is None
                    or elapsed_ms(hand_now_ms, last_preview_ms)
                    >= PREVIEW_INTERVAL_MS
                ):
                    frame = hand_source.last_frame
                    hand_source.draw_hand(frame)
                    recognition = sign_recognition or {}
                    overlay_lines = sign_overlay_lines(
                        recognition,
                        _sign_controller_status(sign_controller).get("state"),
                    )
                    for line_index, line in enumerate(overlay_lines):
                        draw_overlay_text(
                            frame,
                            image_module,
                            2,
                            2 + line_index * OVERLAY_LINE_HEIGHT_PX,
                            line,
                        )
                    if live_sidecar is not None:
                        live_sidecar.offer(frame, hand_now_ms)
                    screen.show(frame)
                    last_preview_ms = hand_now_ms
            except Exception as exc:
                sign_vision_read_ok = False
                sign_recognition = {
                    "gesture_id": None, "confidence": 0.0,
                    "stable_ms": 0, "valid": False,
                    "error_code": "vision_read_failed",
                    "observed_ms": time.ticks_ms(),
                }
                _sign_observe(sign_controller, sign_recognition, hand_now_ms)
                vision_read_errors += 1
                report_repeated_error(
                    "sign vision read failed", vision_read_errors, exc
                )

        if (
            vision_phase == "HAND"
            and hand_source is not None
            and (
                last_hand_process_ms is None
                or elapsed_ms(now_ms, last_hand_process_ms)
                >= HAND_PROCESS_INTERVAL_MS
            )
        ):
            try:
                posture = hand_source.read()
                hand_now_ms = time.ticks_ms()
                last_hand_process_ms = hand_now_ms
                completed_rep = imitation_controller.observe(
                    posture, hand_now_ms, elapsed_ms
                )
                if completed_rep:
                    print("USER REPETITION {} COMPLETE".format(
                        imitation_controller.repetitions
                    ))
                if screen is not None and (
                    last_preview_ms is None
                    or elapsed_ms(hand_now_ms, last_preview_ms)
                    >= PREVIEW_INTERVAL_MS
                ):
                    frame = hand_source.last_frame
                    hand_source.draw_hand(frame)
                    score_text = (
                        "{:.2f}".format(hand_source.last_score)
                        if hand_source.last_score is not None
                        else "--"
                    )
                    draw_overlay_text(
                        frame,
                        image_module,
                        2,
                        2,
                        "HAND {} {}".format(
                            posture if posture is not None else "NONE",
                            score_text,
                        ),
                    )
                    result_lines = imitation_controller.result_lines(
                        hand_now_ms, elapsed_ms
                    )
                    if result_lines is None:
                        overlay_lines = (
                            imitation_controller.status_line(
                                hand_now_ms, elapsed_ms
                            ),
                            imitation_controller.quality_feedback_line(),
                            "MOTION LOCKED",
                        )
                    else:
                        overlay_lines = (
                            result_lines[0],
                            result_lines[1],
                            imitation_controller.quality_feedback_line(),
                            imitation_controller.coaching_line(),
                        )
                    for line_index, line in enumerate(overlay_lines):
                        draw_overlay_text(
                            frame,
                            image_module,
                            2,
                            30 + line_index * OVERLAY_LINE_HEIGHT_PX,
                            line,
                        )
                    cancel_rect = [
                        max(2, frame.width() - 150),
                        max(2, frame.height() - 46),
                        145,
                        40,
                    ]
                    if imitation_controller.state == "ACTIVE":
                        frame.draw_rect(
                            cancel_rect[0],
                            cancel_rect[1],
                            cancel_rect[2],
                            cancel_rect[3],
                            image_module.COLOR_RED,
                            3,
                        )
                        draw_overlay_text(
                            frame,
                            image_module,
                            cancel_rect[0] + 8,
                            cancel_rect[1] + 10,
                            "CANCEL TRAIN",
                        )
                        cancel_controller.set_display_rect(
                            image_module.resize_map_pos(
                                frame.width(),
                                frame.height(),
                                screen.width(),
                                screen.height(),
                                image_module.Fit.FIT_CONTAIN,
                                *cancel_rect
                            )
                        )
                    else:
                        cancel_controller.set_display_rect(None)
                    if live_sidecar is not None:
                        live_sidecar.offer(frame, hand_now_ms)
                    screen.show(frame)
                    last_preview_ms = hand_now_ms
            except Exception as exc:
                vision_read_errors += 1
                report_repeated_error(
                    "hand vision read failed", vision_read_errors, exc
                )

        if (
            vision_phase == "TARGET"
            and VISION_MODE != "disabled"
            and vision_scheduler.process_due(
            now_ms, elapsed_ms
            )
        ):
            try:
                vision_payload = vision_source.read()
                preview_now_ms = time.ticks_ms()
                if screen is not None and (
                    last_preview_ms is None
                    or elapsed_ms(preview_now_ms, last_preview_ms)
                    >= PREVIEW_INTERVAL_MS
                ):
                    frame = vision_source.last_frame
                    for obj in vision_source.last_objects:
                        if (
                            YOLO_ALLOWED_CLASS_IDS is not None
                            and obj.class_id not in YOLO_ALLOWED_CLASS_IDS
                        ):
                            continue
                        frame.draw_rect(
                            obj.x,
                            obj.y,
                            obj.w,
                            obj.h,
                            color=image_module.COLOR_RED,
                        )
                    target_line, intent_line = target_status_lines(vision_payload)
                    overlay_lines = (
                        "SmartHand YOLO11 | infer {}ms".format(
                            vision_source.last_inference_ms
                        ),
                        target_line,
                        intent_line,
                        link_status_line(ack_monitor),
                        authority_display_line(authority["snapshot"]),
                        "LOCK: {}".format(
                            train_lock_reason(
                                authority["snapshot"],
                                train_controller,
                                now_ms,
                                elapsed_ms,
                                vision_phase,
                            )
                        ),
                        train_controller.status_line(train_enabled),
                    )
                    for line_index, line in enumerate(overlay_lines):
                        draw_overlay_text(
                            frame,
                            image_module,
                            2,
                            2 + line_index * OVERLAY_LINE_HEIGHT_PX,
                            line,
                        )
                    button_rect = [
                        max(2, frame.width() - 230),
                        max(2, frame.height() - 58),
                        225,
                        52,
                    ]
                    goal_rect = [
                        max(2, button_rect[0] - 168),
                        button_rect[1],
                        160,
                        button_rect[3],
                    ]
                    frame.draw_rect(
                        goal_rect[0],
                        goal_rect[1],
                        goal_rect[2],
                        goal_rect[3],
                        image_module.COLOR_RED,
                        3,
                    )
                    draw_overlay_text(
                        frame,
                        image_module,
                        goal_rect[0] + 8,
                        goal_rect[1] + 15,
                        goal_controller.status_line(goal_enabled),
                    )
                    frame.draw_rect(
                        button_rect[0],
                        button_rect[1],
                        button_rect[2],
                        button_rect[3],
                        image_module.COLOR_RED,
                        3,
                    )
                    draw_overlay_text(
                        frame,
                        image_module,
                        button_rect[0] + 8,
                        button_rect[1] + 15,
                        "START TRAIN" if train_enabled else "TRAIN LOCKED",
                    )
                    train_controller.set_display_rect(
                        image_module.resize_map_pos(
                            frame.width(),
                            frame.height(),
                            screen.width(),
                            screen.height(),
                            image_module.Fit.FIT_CONTAIN,
                            *button_rect
                        )
                    )
                    goal_controller.set_display_rect(
                        image_module.resize_map_pos(
                            frame.width(),
                            frame.height(),
                            screen.width(),
                            screen.height(),
                            image_module.Fit.FIT_CONTAIN,
                            *goal_rect
                        )
                    )
                    if live_sidecar is not None:
                        live_sidecar.offer(frame, preview_now_ms)
                    screen.show(frame)
                    last_preview_ms = preview_now_ms
            except Exception as exc:
                vision_read_errors += 1
                vision_payload = None
                report_repeated_error(
                    "vision read failed", vision_read_errors, exc
                )
            now_ms = time.ticks_ms()
            vision_scheduler.observe(vision_payload, now_ms, elapsed_ms)

        stable_payload = (
            vision_scheduler.take_send_payload(now_ms, elapsed_ms)
            if vision_phase == "TARGET"
            else None
        )
        if stable_payload is not None:
            send_frame(
                serial,
                ack_monitor,
                "VISION",
                sequence,
                now_ms,
                *stable_payload
            )
            sequence = (sequence + 1) & 0xFFFF

        ack_monitor.expire(now_ms, elapsed_ms)
        if live_sidecar is not None:
            live_sidecar.poll(time.ticks_ms())
        if last_stats_ms is None or elapsed_ms(now_ms, last_stats_ms) >= STATS_INTERVAL_MS:
            print("link stats:", ack_monitor.summary())
            print("uart stats: rx_errors={}".format(uart_read_errors))
            active_source = hand_source if vision_phase == "HAND" else vision_source
            print(
                "vision stats: phase={} {} read_errors={}".format(
                    vision_phase,
                    active_source.summary() if active_source is not None else "none",
                    vision_read_errors,
                )
            )
            print("target stats:", target_tracker.summary())
            last_stats_ms = now_ms

        time.sleep_ms(10)

    if live_sidecar is not None:
        live_sidecar.close()


if __name__ == "__main__":
    main()
