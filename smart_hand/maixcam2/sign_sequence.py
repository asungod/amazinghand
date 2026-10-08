"""Bounded 2-D sequence prototypes, independent of UART and actuator code."""
import math

from gesture_features import extract_gesture_features
from gesture_classifier import _palm_directed_extension, _classify_features


SEQUENCES = {
    "word_hello": (("shape:POINT", "伸出食指"), ("shape:THUMBS_UP", "切换竖拇指")),
    "word_like": (("shape:L_SHAPE", "摆出 L 形"), ("shape:OK_PINCH", "拇指食指捏合")),
    "word_thanks": (("thumb_open", "伸直拇指"), ("thumb_bend", "第一次弯拇指"),
                    ("thumb_open", "第一次伸直"), ("thumb_bend", "第二次弯拇指"),
                    ("thumb_open", "第二次伸直")),
    "word_attention": (("index_open", "伸直食指"), ("index_bend", "第一次弯食指"),
                       ("index_open", "第一次伸直"), ("index_bend", "第二次弯食指"),
                       ("index_open", "第二次伸直")),
    "signal_help": (("palm_open", "张开手掌"), ("thumb_in", "拇指收进掌心"),
                    ("help_close", "四指握住拇指")),
    "word_no": (("point_anchor", "食指伸直居中"), ("point_side", "第一次摆向一侧"),
                ("point_other", "第一次摆向另一侧"), ("point_side", "第二次摆向一侧"),
                ("point_other", "第二次摆向另一侧"), ("point_center", "食指回中")),
}

# Human-readable guidance for the SAME gates below; never a second classifier.
INSTRUCTIONS = {
    "shape:POINT": "其余手指收拢，伸出食指；等本步确认后再切换竖拇指。",
    "shape:THUMBS_UP": "收拢其余四指，伸出拇指；图像中的手型需被识别为竖拇指。",
    "shape:L_SHAPE": "伸出食指和拇指，其余三指收拢，展示 L 形。",
    "shape:OK_PINCH": "拇指与食指捏合，其余三指伸展。",
    "shape:FIST": "把其余四指弯下包住已收进掌心的拇指，保持握住；不要为了识别把手重新张开。",
    "help_close": "握拳，把收进掌心的拇指包在四指里面。遮挡时当前模型不能可靠核实，本步不自动评分；核对动作后可用下方人工复核结束本课，不计自动通过。",
    "thumb_open": "其余四指收拢，只伸直拇指；看到本步已确认再弯曲。",
    "thumb_bend": "其余四指继续收拢，弯曲拇指；适当转正，让相机看清弯曲，而不是整只手移出画面。",
    "index_open": "中指、无名指、小指和拇指收拢，伸直食指。",
    "index_bend": "其他手指保持收拢，只弯曲食指；让食指关节尽量清楚可见。",
    "palm_open": "张开整只手，四指和拇指伸展，掌心朝相机。",
    "thumb_in": "四指先保持伸展，把拇指收进掌心；本步确认后再握住。",
    "point_anchor": "其他手指收拢，食指伸直；保持初始位置，作为本轮摆动的参照。",
    "point_side": "保持食指伸展，向第一次选择的一侧摆动；这里只看食指相对掌面的变化，整只手平移不计。",
    "point_other": "食指摆向初始位置的另一侧；不要只在同一侧反复移动。",
    "point_center": "把伸直的食指回到本轮初始位置。",
}


def motion_evidence(points):
    """Same-frame bounded geometry; not a hand identity or accuracy score."""
    features = extract_gesture_features(points)
    normalized = features["normalized_landmarks"]
    result = {
        "finger_extension": _palm_directed_extension(features["finger_extension"], normalized),
        "thumb_angle_deg": features["thumb_angle_deg"],
        "index_angle_deg": features["joint_angles_deg"][0],
        "thumb_tip_distance": features["thumb_tip_distance"],
        # Relative to palm, not camera/world translation. Whole-hand motion
        # alone must not count as the finger's lateral bend.
        "index_lateral": normalized[8][0] - normalized[5][0],
        "thumb_inside": min(p[0] for p in normalized[5::4]) <= normalized[4][0] <=
                        max(p[0] for p in normalized[5::4]) and
                        0 <= normalized[4][1] <= normalized[9][1],
    }
    if not all(math.isfinite(value) for value in result["finger_extension"] +
               [result[k] for k in ("thumb_angle_deg", "index_angle_deg",
                                    "thumb_tip_distance", "index_lateral")]):
        raise ValueError("nonfinite motion geometry")
    # The classifier's rule thumb extension is needed for its existing gates.
    result["thumb_extension"] = _classify_features(features)[2]["thumb_extension"]
    return result


class SignSequenceTracker:
    """Ordered step practice; pauses retain confirmed steps, never hold time.

    The owning lesson controller enforces the overall session deadline.
    Completion does not certify an uninterrupted performance or hand identity.
    """
    HOLD_MS = 300
    FINAL_HOLD_MS = 300
    MAX_GAP_MS = 500
    LATERAL_DELTA = 0.35

    def __init__(self, lesson_id):
        self.steps = SEQUENCES[lesson_id]
        self.reset()

    def reset(self):
        self.index = 0
        self.since = None
        self.count = 0
        self.last_ms = None
        self.anchor = None
        self.side = None
        self.hold_ms = 0
        self.feedback = "按提示切换，保持约 0.3 秒"
        self.observation_state = "WAITING"
        self.checks = []

    def _clear_hold(self):
        self.since = None
        self.count = 0
        self.hold_ms = 0

    def snapshot(self):
        return {"completed_steps": self.index, "total_steps": len(self.steps),
                "complete": self.index == len(self.steps),
                "prompt": "动作序列完成" if self.index == len(self.steps) else self.steps[self.index][1],
                "phase_hold_ms": self.hold_ms, "required_hold_ms": self.FINAL_HOLD_MS
                if self.index == len(self.steps)-1 else self.HOLD_MS,
                "feedback": self.feedback, "scope": "2d_sequence_prototype",
                "step_titles": [step[1] for step in self.steps],
                "step_instructions": [INSTRUCTIONS[step[0]] for step in self.steps],
                "instruction": "分步序列原型达标，不证明整段连续动作或标准手语能力" if self.index == len(self.steps)
                else INSTRUCTIONS[self.steps[self.index][0]],
                "observation_state": self.observation_state,
                "checks": [dict(item) for item in self.checks]}

    def _requirements(self, key, result, evidence):
        """One source of truth for match gates and read-only explanations."""
        if key.startswith("shape:"):
            confidence = result.get("confidence")
            quality = (result.get("valid") is True and result.get("error_code") == "OK" and
                    type(confidence) in (int, float) and math.isfinite(confidence) and
                    0.64 <= confidence <= 1)
            return (("有效手型读数达到现有分数门限", quality),
                    ("当前标签符合本步要求", result.get("gesture_id") == key[6:]))
        fingers = evidence["finger_extension"]
        thumb = evidence["thumb_extension"]
        folded = ("四指图像估计接近收拢", max(fingers) <= 0.62)
        others = ("中指、无名指、小指图像估计接近收拢", max(fingers[1:]) <= 0.62)
        if key == "thumb_open":
            return (folded, ("拇指图像估计接近伸展", thumb >= 0.55),
                    ("拇指关节图像估计接近伸直", evidence["thumb_angle_deg"] >= 155))
        if key == "thumb_bend":
            return (folded, ("拇指关节图像估计接近弯曲", evidence["thumb_angle_deg"] <= 135),
                    ("拇指图像估计接近收拢", thumb <= 0.45))
        if key == "index_open":
            return (others, ("拇指图像估计接近收拢", thumb <= 0.52),
                    ("食指图像估计接近伸展", fingers[0] >= 0.72),
                    ("食指关节图像估计接近伸直", evidence["index_angle_deg"] >= 155))
        if key == "index_bend":
            return (others, ("拇指图像估计接近收拢", thumb <= 0.52),
                    ("食指关节图像估计接近弯曲", evidence["index_angle_deg"] <= 135),
                    ("食指图像估计未过度伸展", fingers[0] <= 0.85))
        if key == "palm_open":
            return (("四指图像估计接近伸展", min(fingers) >= 0.68),
                    ("拇指图像估计接近伸展", thumb >= 0.55))
        if key == "thumb_in":
            return (("四指仍接近伸展", min(fingers) >= 0.68),
                    ("拇指尖图像距离接近掌内", evidence["thumb_tip_distance"] <= 1.15),
                    ("拇指尖图像位置落在掌内范围", evidence["thumb_inside"] is True))
        if key == "help_close":
            # Hidden thumb coordinates are model estimates, not observable
            # evidence of enclosing the thumb. Never grant an automatic pass.
            return (("闭拳遮挡阶段需人工复核，不作自动评分", False),)
        pointing = (others, ("食指图像估计接近伸展", fingers[0] >= 0.72),
                    ("拇指图像估计接近收拢", thumb <= 0.52))
        lateral = evidence["index_lateral"]
        if key == "point_anchor":
            return pointing + (("保持本轮初始位置", self.anchor is not None and abs(lateral-self.anchor) <= 0.15),)
        delta = None if self.anchor is None else lateral-self.anchor
        if key == "point_side":
            position = delta is not None and self.side is not None and delta*self.side >= self.LATERAL_DELTA
            return pointing + (("食指相对掌面摆向首次选择的一侧", position),)
        if key == "point_other":
            position = delta is not None and self.side is not None and delta*self.side <= -self.LATERAL_DELTA
            return pointing + (("食指相对掌面摆到另一侧", position),)
        if key == "point_center":
            return pointing + (("食指回到本轮初始位置", delta is not None and abs(delta) <= 0.15),)
        return (("本步定义有效", False),)

    def _matches(self, key, result, evidence):
        # Preserve the existing anchor/side ownership and gates exactly.
        if key.startswith("point_"):
            fingers = evidence["finger_extension"]
            pointing = max(fingers[1:]) <= 0.62 and fingers[0] >= 0.72 and evidence["thumb_extension"] <= 0.52
            lateral = evidence["index_lateral"]
            if pointing and key == "point_anchor" and self.anchor is None:
                self.anchor = lateral
            if (pointing and key == "point_side" and self.anchor is not None and self.side is None
                    and abs(lateral-self.anchor) >= self.LATERAL_DELTA):
                self.side = 1 if lateral > self.anchor else -1
        self.checks = [{"label": label, "state": "met" if match else "unmet"}
                       for label, match in self._requirements(key, result, evidence)]
        return all(item["state"] == "met" for item in self.checks)

    @staticmethod
    def _valid_evidence(evidence):
        if not isinstance(evidence, dict):
            return False
        fingers = evidence.get("finger_extension")
        if not isinstance(fingers, (list, tuple)) or len(fingers) != 4:
            return False
        def number(value, low, high):
            return type(value) in (int, float) and math.isfinite(value) and low <= value <= high
        return (all(number(v, 0, 1) for v in fingers) and
                number(evidence.get("thumb_extension"), 0, 1) and
                number(evidence.get("thumb_angle_deg"), 0, 180) and
                number(evidence.get("index_angle_deg"), 0, 180) and
                number(evidence.get("thumb_tip_distance"), 0, 10) and
                number(evidence.get("index_lateral"), -10, 10) and
                type(evidence.get("thumb_inside")) is bool)

    def observe(self, result, now_ms):
        if self.index == len(self.steps):
            return True
        if self.last_ms is not None and now_ms < self.last_ms:
            self.reset()
            return False
        if self.last_ms == now_ms:
            return False
        previous_ms = self.last_ms
        self.last_ms = now_ms
        if not isinstance(result, dict):
            result = {}
        evidence = result.get("motion_evidence")
        usable = (self._valid_evidence(evidence) and result.get("error_code") in ("OK", "LOW_CONFIDENCE"))
        if not usable:
            # Ordinary absence pauses step practice until the controller's
            # overall deadline. Malformed geometry/SDK errors still reset.
            # The rule/capture path uses NO_HAND, while the production SDK
            # adapter emits hand_not_found. Both mean absence, not corrupt
            # geometry. Neither may earn hold time or extend the session.
            if not result or result.get("error_code") in ("NO_HAND", "hand_not_found"):
                self._clear_hold()
                self.checks = []
                self.observation_state = "MISSING"
                if self.index:
                    self.feedback = "未检测到手：本轮已确认步骤保留，当前步暂停计时；请完整入镜"
                return False
            self.reset()
            self.last_ms = now_ms
            self.observation_state = "RESET"
            self.feedback = "识别证据异常，步骤已重置；先检查画面与设备"
            return False
        if previous_ms is not None and now_ms-previous_ms > self.MAX_GAP_MS:
            self._clear_hold()
        try:
            matched = self._matches(self.steps[self.index][0], result, evidence)
        except (KeyError, TypeError, ValueError, OverflowError):
            self.reset()
            return False
        if not matched:
            self._clear_hold()
            self.observation_state = "CHECKING"
            failed = next(item["label"] for item in self.checks if item["state"] == "unmet")
            self.feedback = "尚未满足：" + failed + "。图像估计可能有误，不代表你做错。"
            return False
        if self.since is None:
            self.since = now_ms
        self.count += 1
        self.hold_ms = now_ms-self.since
        self.observation_state = "HOLDING"
        self.feedback = "当前动作保持中：{}/300 毫秒".format(min(self.hold_ms, 300))
        required = self.FINAL_HOLD_MS if self.index == len(self.steps)-1 else self.HOLD_MS
        if self.count >= 2 and self.hold_ms >= required:
            self.index += 1
            self._clear_hold()
            self.checks = []  # the next stage has not been observed yet
            self.observation_state = "COMPLETE" if self.index == len(self.steps) else "WAITING"
            self.feedback = "全部步骤已确认，二维序列原型达标" if self.index == len(self.steps) else "本步已确认，请做下一步并保持约 0.3 秒"
        return self.index == len(self.steps)
