"""Independent finite-state controller for OpenSignHand sign-shape lessons.

This controller is intentionally separate from the existing rehabilitation
controller.  It coordinates lesson selection, an explicitly confirmed demo,
learner imitation, stable recognition, and terminal outcomes.  It never emits
servo angles or sends UART frames.  A caller must still perform any hardware
action through its existing safety boundary after checking ``action_allowed``.

The bundled lessons are *basic hand-shape/expression prototypes*, not mappings to
formal Chinese sign-language words.  This distinction is part of the public
configuration so a UI cannot accidentally present them as a complete sign
language system.
"""


from sign_sequence import SEQUENCES, SignSequenceTracker

STATE_IDLE = "IDLE"
STATE_LESSON_SELECTED = "LESSON_SELECTED"
STATE_DEMO_READY = "DEMO_READY"
STATE_DEMONSTRATING = "DEMONSTRATING"
STATE_IMITATING = "IMITATING"
STATE_COMPLETE = "COMPLETE"
STATE_REVIEWED = "REVIEWED"
STATE_TIMEOUT = "TIMEOUT"
STATE_CANCELLED = "CANCELLED"
STATE_FAULT = "FAULT"

# Short constants keep route/UI code readable while preserving the explicit
# STATE_* names used in logs and tests.
IDLE = STATE_IDLE
LESSON_SELECTED = STATE_LESSON_SELECTED
DEMO_READY = STATE_DEMO_READY
DEMONSTRATING = STATE_DEMONSTRATING
IMITATING = STATE_IMITATING
COMPLETE = STATE_COMPLETE
REVIEWED = STATE_REVIEWED
TIMEOUT = STATE_TIMEOUT
CANCELLED = STATE_CANCELLED
FAULT = STATE_FAULT

STATES = (
    STATE_IDLE,
    STATE_LESSON_SELECTED,
    STATE_DEMO_READY,
    STATE_DEMONSTRATING,
    STATE_IMITATING,
    STATE_COMPLETE,
    STATE_REVIEWED,
    STATE_TIMEOUT,
    STATE_CANCELLED,
    STATE_FAULT,
)
TERMINAL_STATES = (STATE_COMPLETE, STATE_REVIEWED, STATE_TIMEOUT, STATE_CANCELLED, STATE_FAULT)

ERROR_OK = "OK"
ERROR_NO_LESSON = "NO_LESSON"
ERROR_UNKNOWN_LESSON = "UNKNOWN_LESSON"
ERROR_INVALID_STATE = "INVALID_STATE"
ERROR_MANUAL_CONFIRM_REQUIRED = "MANUAL_CONFIRM_REQUIRED"
ERROR_LINK_OFFLINE = "LINK_OFFLINE"
ERROR_VISION_STALE = "VISION_STALE"
ERROR_TIMEOUT = "TIMEOUT"
ERROR_CANCELLED = "CANCELLED"
ERROR_UNKNOWN_GESTURE = "UNKNOWN_GESTURE"
ERROR_WRONG_GESTURE = "WRONG_GESTURE"
ERROR_LOW_CONFIDENCE = "LOW_CONFIDENCE"
ERROR_INVALID_RESULT = "INVALID_RESULT"
ERROR_EXTERNAL_FAULT = "EXTERNAL_FAULT"

DEMO_MODES = ("full", "partial", "screen_only")


class LessonConfig(dict):
    """Plain mapping with attribute access, suitable for MaixPy callers."""

    def __init__(self, **values):
        dict.__init__(self, values)
        self.__dict__.update(values)

    def copy(self):
        return LessonConfig(**dict(self))


def _lesson(
    lesson_id,
    name_zh,
    prototype_id,
    demo_mode,
    mechanical_pose,
    mechanical_pose_candidate=None,
    mechanical_pose_status="NOT_CONFIGURED",
    mechanical_sequence_id=None,
    mechanical_motion_status="NOT_CONFIGURED",
    mechanical_semantics=None,
    reference_source=None,
    action_type="static_shape_prototype",
    scope_note="仅用于有限词表训练原型，不代表正式手语词义",
    confidence_threshold=0.64,
    required_hold_ms=300,
):
    if demo_mode not in DEMO_MODES:
        raise ValueError("unsupported demo_mode")
    return LessonConfig(
        lesson_id=lesson_id,
        name_zh=name_zh,
        chinese_name=name_zh,
        # Explicit wording prevents the course selector from implying a
        # formal sign-language translation.
        reference_source=(reference_source or
                          "OpenSignHand 基础手型原型定义（非正式手语词义）"),
        action_type="2d_sequence_prototype" if lesson_id in SEQUENCES else action_type,
        prototype_id=prototype_id,
        confidence_threshold=float(confidence_threshold),
        required_hold_ms=int(required_hold_ms),
        demo_mode=demo_mode,
        mechanical_pose=mechanical_pose,
        mechanical_pose_candidate=mechanical_pose_candidate,
        mechanical_pose_status=mechanical_pose_status,
        # A sequence id names a fixed Titan recipe; it is never a raw servo
        # pose.  Keep this metadata explicit so opt-in runtime code can
        # reject every lesson that has not been bench reviewed.
        mechanical_sequence_id=mechanical_sequence_id,
        mechanical_motion_status=mechanical_motion_status,
        mechanical_semantics=mechanical_semantics,
        scope_note=("视觉评估二维动作顺序与次数原型，不代表完整标准手语认证"
                    if lesson_id in SEQUENCES else scope_note),
    )


DEFAULT_LESSONS = {
    "basic_open_palm": _lesson(
        "basic_open_palm",
        "张开手掌基础手型原型",
        "OPEN_PALM",
        "screen_only",
        None,
        mechanical_pose_candidate=1,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=1,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "仅表示已验证开合端点组成的问候演示候选动作；"
            "不等同于正式手语词义，须现场复核后启用"
        ),
    ),
    "basic_fist": _lesson(
        "basic_fist",
        "握拳基础手型原型",
        "FIST",
        "screen_only",
        None,
        mechanical_pose_candidate=2,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=2,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "四组手指闭合并短暂保持后回到张开姿态；"
            "仅用于基础握拳手型辅助示范"
        ),
    ),
    "basic_v_sign": _lesson(
        "basic_v_sign",
        "V 形基础手型原型",
        "V_SIGN",
        "screen_only",
        None,
        mechanical_pose_candidate=3,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=3,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "食指与中指保持张开，无名指与拇指闭合，随后回到张开姿态；"
            "仅用于 V 形基础手型辅助示范"
        ),
    ),
    "basic_point": _lesson(
        "basic_point",
        "食指指向常用表达手型",
        "POINT",
        "screen_only",
        None,
        mechanical_pose_candidate=4,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=4,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "食指伸展，其余机械手指收拢；用于‘你/指示’类表达的核心手型展示；"
            "不等同于完整标准手语动作"
        ),
    ),
    "basic_thumbs_up": _lesson(
        "basic_thumbs_up",
        "竖拇指常用表达手型",
        "THUMBS_UP",
        "screen_only",
        None,
        mechanical_pose_candidate=5,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=5,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "拇指伸展，其余机械手指收拢；用于‘好/赞’类常见表达展示；"
            "不等同于完整标准手语动作"
        ),
    ),
    "basic_l_shape": _lesson(
        "basic_l_shape",
        "L 形基础手型原型",
        "L_SHAPE",
        "screen_only",
        None,
        mechanical_pose_candidate=6,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=6,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "食指与拇指伸展成 L 形，其余机械手指收拢；"
            "仅用于 L 形基础手型辅助展示，不认证手指字母或拼读能力"
        ),
    ),
    "basic_ok_pinch": _lesson(
        "basic_ok_pinch",
        "OK／确认常用表达手型",
        "OK_PINCH",
        "screen_only",
        None,
        mechanical_pose_candidate=7,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=7,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "拇指与食指形成捏合，其余机械手指伸展；"
            "用于‘确认／可以’类常见表达展示，不等同于完整标准手语词"
        ),
    ),
    "word_hello": _lesson(
        "word_hello",
        "日常问候：你好",
        "THUMBS_UP",
        "screen_only",
        None,
        mechanical_pose_candidate=8,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=8,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "先以食指指向交流对象，再切换为竖拇指；"
            "视觉端按顺序评估食指指向与竖拇指"
        ),
        reference_source="公开国家通用手语应用报道中的‘你好’动作说明",
        action_type="two_stage_word_demo_final_keyframe",
        scope_note="机械手演示‘你好’两阶段动作；视觉评估结束关键帧",
    ),
    "word_thanks": _lesson(
        "word_thanks",
        "礼貌用语：谢谢",
        "THUMBS_UP",
        "screen_only",
        None,
        mechanical_pose_candidate=9,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=9,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "其余机械手指保持收拢，拇指连续弯曲两次；"
            "视觉端评估拇指两次屈伸及结束伸直"
        ),
        reference_source="公开无障碍服务场景中的‘谢谢’动作说明",
        action_type="repeated_thumb_word_demo_final_keyframe",
        scope_note="机械手演示‘谢谢’动态动作；视觉评估结束关键帧",
    ),
    "signal_help": _lesson(
        "signal_help",
        "应急表达：求助信号",
        "FIST",
        "screen_only",
        None,
        mechanical_pose_candidate=10,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=10,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "张开手掌、将拇指收进掌心，再由其余机械手指包住；"
            "视觉端评估张掌、收拇指、握拳三个阶段"
        ),
        reference_source="Signal for Help 国际安全求助手势公开说明",
        action_type="international_safety_signal_final_keyframe",
        scope_note="国际安全求助手势，不属于国家通用手语词；视觉评估结束关键帧",
    ),
    "word_no": _lesson(
        "word_no",
        "日常表达：拒绝／不",
        "POINT",
        "screen_only",
        None,
        mechanical_pose_candidate=11,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=11,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "食指伸展并左右摆动两次，其余机械手指保持收拢；"
            "视觉端评估食指相对掌部两次左右摆动"
        ),
        reference_source="OpenSignHand 日常表达动作原型",
        action_type="lateral_point_word_demo_final_keyframe",
        scope_note="用于拒绝／否定语境的演示动作原型；不等同于完整标准手语词",
    ),
    "word_attention": _lesson(
        "word_attention",
        "提示表达：请注意",
        "POINT",
        "screen_only",
        None,
        mechanical_pose_candidate=12,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=12,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "食指保持伸展并连续弯曲提示两次，其余机械手指保持收拢；"
            "视觉端评估食指两次屈伸及结束伸直"
        ),
        reference_source="OpenSignHand 提示表达动作原型",
        action_type="repeated_index_word_demo_final_keyframe",
        scope_note="用于吸引注意的演示动作原型；不等同于完整标准手语词",
    ),
    "word_like": _lesson(
        "word_like",
        "情感表达：喜欢／爱心",
        "OK_PINCH",
        "screen_only",
        None,
        mechanical_pose_candidate=13,
        mechanical_pose_status="PENDING_HARDWARE_VALIDATION",
        mechanical_sequence_id=13,
        mechanical_motion_status="READY_FOR_BENCH_VALIDATION",
        mechanical_semantics=(
            "先展示 L 形，再由拇指与食指完成捏合；"
            "视觉端按顺序评估 L 形与捏合"
        ),
        reference_source="OpenSignHand 情感表达动作原型",
        action_type="two_stage_like_demo_final_keyframe",
        scope_note="用于喜欢／爱心主题的演示动作原型；不等同于完整标准手语词",
    ),
}


def lesson_catalog():
    """Return defensive copies of the supported lesson definitions."""
    return dict((key, value.copy()) for key, value in DEFAULT_LESSONS.items())


def get_lesson(lesson_id):
    config = DEFAULT_LESSONS.get(lesson_id)
    return None if config is None else config.copy()


get_lessons = lesson_catalog
get_lesson_catalog = lesson_catalog


def _value(source, key, default=None):
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


class SignLessonController:
    """Fail-closed state machine for one manually started lesson session."""

    def __init__(self, lessons=None, timeout_ms=15000, dynamic_timeout_ms=60000):
        if timeout_ms <= 0 or dynamic_timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        raw_lessons = DEFAULT_LESSONS if lessons is None else lessons
        self.lessons = self._copy_lessons(raw_lessons)
        if not self.lessons:
            raise ValueError("at least one lesson is required")
        self.timeout_ms = int(timeout_ms)
        self.dynamic_timeout_ms = max(self.timeout_ms, int(dynamic_timeout_ms))
        self.state = STATE_IDLE
        self.lesson = None
        self.started_ms = None
        self.demo_started_ms = None
        self.imitation_started_ms = None
        self.completed_ms = None
        self.last_now_ms = None
        self.last_result = None
        self.error_code = ERROR_OK
        self.manual_confirmed = False
        self._match_since_ms = None
        self._deadline_ms = None
        self._link_online = False
        self._vision_fresh = False
        self._transition_history = []
        self._last_logged_session = None
        self._session_counter = 0
        self.session_token = None
        self._sequence = None

    @staticmethod
    def _copy_lessons(lessons):
        if isinstance(lessons, dict):
            values = lessons.items()
        else:
            values = ((item.get("lesson_id"), item) for item in lessons)
        copied = {}
        for lesson_id, item in values:
            if not lesson_id:
                raise ValueError("lesson_id is required")
            if isinstance(item, LessonConfig):
                config = item.copy()
            elif isinstance(item, dict):
                config = LessonConfig(**dict(item))
            else:
                config = LessonConfig(**dict(item))
            required = (
                "lesson_id", "prototype_id", "confidence_threshold",
                "required_hold_ms", "demo_mode", "mechanical_pose",
            )
            for key in required:
                if key not in config:
                    raise ValueError("lesson missing {}".format(key))
            if config["demo_mode"] not in DEMO_MODES:
                raise ValueError("unsupported demo_mode")
            config["lesson_id"] = lesson_id
            config.setdefault("name_zh", lesson_id)
            config.setdefault("chinese_name", config["name_zh"])
            config.setdefault(
                "reference_source",
                "OpenSignHand 基础手型原型定义（非正式手语词义）",
            )
            config.setdefault("action_type", "static_shape_prototype")
            config.setdefault("scope_note", "基础手型原型，不代表正式手语词义")
            config.setdefault("mechanical_sequence_id", None)
            config.setdefault("mechanical_motion_status", "NOT_CONFIGURED")
            config.setdefault("mechanical_semantics", None)
            copied[lesson_id] = LessonConfig(**dict(config))
        return copied

    def _clock(self, now_ms):
        if now_ms is None:
            now_ms = 0 if self.last_now_ms is None else self.last_now_ms
        now_ms = int(now_ms)
        if self.last_now_ms is not None and now_ms < self.last_now_ms:
            raise ValueError("now_ms must be monotonic")
        self.last_now_ms = now_ms
        return now_ms

    def _transition(self, state, error_code=ERROR_OK):
        self.state = state
        self.error_code = error_code
        self._transition_history.append(state)

    def _healthy(self, link_online, vision_fresh, vision_stale=False):
        self._link_online = bool(link_online)
        self._vision_fresh = bool(vision_fresh) and not bool(vision_stale)
        return self._link_online and self._vision_fresh

    def _fault_for_health(self, link_online, vision_fresh, vision_stale=False):
        if not link_online:
            self._transition(STATE_FAULT, ERROR_LINK_OFFLINE)
        elif vision_stale or not vision_fresh:
            self._transition(STATE_FAULT, ERROR_VISION_STALE)
        else:
            self._transition(STATE_FAULT, ERROR_EXTERNAL_FAULT)
        self.completed_ms = self.last_now_ms
        return self.status()

    def select_lesson(self, lesson_id, now_ms=None):
        now_ms = self._clock(now_ms)
        if lesson_id not in self.lessons:
            self.error_code = ERROR_UNKNOWN_LESSON
            return self.status()
        if self.state in (
            STATE_DEMO_READY, STATE_DEMONSTRATING, STATE_IMITATING
        ):
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        self.lesson = self.lessons[lesson_id].copy()
        self._sequence = SignSequenceTracker(lesson_id) if lesson_id in SEQUENCES else None
        self.started_ms = None
        self.demo_started_ms = None
        self.imitation_started_ms = None
        self.completed_ms = None
        self.last_result = None
        self.manual_confirmed = False
        self._match_since_ms = None
        self._deadline_ms = None
        self._last_logged_session = None
        self._session_counter += 1
        self.session_token = self._session_counter
        self._transition(STATE_LESSON_SELECTED, ERROR_OK)
        return self.status()

    # Short alias for route handlers.
    select = select_lesson
    choose_lesson = select_lesson

    def start(
        self,
        now_ms=None,
        manual_confirm=False,
        link_online=False,
        vision_fresh=False,
        vision_stale=False,
    ):
        """Accept the explicit human confirmation and prepare the demo.

        Detection alone never calls this method.  A web/physical-button
        handler should pass ``manual_confirm=True`` only after the user has
        pressed the start control.
        """
        now_ms = self._clock(now_ms)
        if self.lesson is None:
            self.error_code = ERROR_NO_LESSON
            return self.status()
        if self.state != STATE_LESSON_SELECTED:
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        if not manual_confirm:
            self.manual_confirmed = False
            self.error_code = ERROR_MANUAL_CONFIRM_REQUIRED
            return self.status()
        if not self._healthy(link_online, vision_fresh, vision_stale):
            return self._fault_for_health(link_online, vision_fresh, vision_stale)
        self.manual_confirmed = True
        self.started_ms = now_ms
        self.demo_started_ms = None
        self.imitation_started_ms = None
        self.completed_ms = None
        self._match_since_ms = None
        self._deadline_ms = None
        self._transition(STATE_DEMO_READY, ERROR_OK)
        return self.status()

    def begin_demo(
        self, now_ms=None, link_online=False, vision_fresh=False, vision_stale=False
    ):
        now_ms = self._clock(now_ms)
        if self.state != STATE_DEMO_READY or not self.manual_confirmed:
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        if not self._healthy(link_online, vision_fresh, vision_stale):
            return self._fault_for_health(link_online, vision_fresh, vision_stale)
        self.demo_started_ms = now_ms
        self._transition(STATE_DEMONSTRATING, ERROR_OK)
        return self.status()

    start_demo = begin_demo

    def finish_demo(
        self, now_ms=None, link_online=False, vision_fresh=False, vision_stale=False
    ):
        """Finish the screen/mechanical demonstration and begin imitation."""
        now_ms = self._clock(now_ms)
        if self.state != STATE_DEMONSTRATING:
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        if not self.manual_confirmed:
            self.error_code = ERROR_MANUAL_CONFIRM_REQUIRED
            return self.status()
        # A learner's hand is normally absent while the reference motion is
        # being shown.  Treat that as an expected imitation precondition, not
        # as a terminal camera fault.  The UART link must still be healthy;
        # recognition will report NO_HAND until the learner enters the frame.
        self._link_online = bool(link_online)
        self._vision_fresh = bool(vision_fresh) and not bool(vision_stale)
        if not self._link_online:
            return self._fault_for_health(link_online, vision_fresh, vision_stale)
        self.imitation_started_ms = now_ms
        if self._sequence is not None:
            self._sequence.reset()
        self._deadline_ms = now_ms + (self.dynamic_timeout_ms if self._sequence is not None else self.timeout_ms)
        self._match_since_ms = None
        self._transition(STATE_IMITATING, ERROR_OK)
        return self.status()

    begin_imitation = finish_demo
    demo_complete = finish_demo
    complete_demo = finish_demo
    confirm_start = start

    def _result_mapping(self, result):
        if result is None:
            return None
        if isinstance(result, dict):
            return result
        return {
            "gesture_id": _value(result, "gesture_id"),
            "confidence": _value(result, "confidence", 0.0),
            "stable_ms": _value(result, "stable_ms", 0),
            "valid": _value(result, "valid", False),
            "error_code": _value(result, "error_code", ERROR_INVALID_RESULT),
        }

    def observe_result(
        self,
        result,
        now_ms=None,
        link_online=True,
        vision_fresh=True,
        vision_stale=False,
    ):
        now_ms = self._clock(now_ms)
        if self.state != STATE_IMITATING:
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        if not self._healthy(link_online, vision_fresh, vision_stale):
            return self._fault_for_health(link_online, vision_fresh, vision_stale)
        if self._deadline_ms is not None and now_ms >= self._deadline_ms:
            self._transition(STATE_TIMEOUT, ERROR_TIMEOUT)
            self.completed_ms = now_ms
            return self.status()

        mapped = self._result_mapping(result)
        if mapped is None:
            if self._sequence is not None:
                self._sequence.observe({}, now_ms)
            self._match_since_ms = None
            self.last_result = {
                "gesture_id": "UNKNOWN",
                "confidence": 0.0,
                "stable_ms": 0,
                "valid": False,
                "error_code": ERROR_INVALID_RESULT,
            }
            self.error_code = ERROR_INVALID_RESULT
            return self.status()
        try:
            gesture_id = mapped.get("gesture_id")
            confidence = float(mapped.get("confidence", 0.0))
            stable_ms = int(mapped.get("stable_ms", 0))
            valid = bool(mapped.get("valid", False))
            recognition_error = mapped.get("error_code", ERROR_INVALID_RESULT)
        except (TypeError, ValueError):
            gesture_id = "UNKNOWN"
            confidence = 0.0
            stable_ms = 0
            valid = False
            recognition_error = ERROR_INVALID_RESULT
        self.last_result = {
            "gesture_id": gesture_id,
            "confidence": max(0.0, min(1.0, confidence)),
            "stable_ms": max(0, stable_ms),
            "valid": valid,
            "error_code": recognition_error,
        }

        if self._sequence is not None:
            if self._sequence.observe(mapped, now_ms):
                self._transition(STATE_COMPLETE, ERROR_OK)
                self.completed_ms = now_ms
            else:
                self.error_code = (str(recognition_error) if recognition_error not in ("OK", "LOW_CONFIDENCE")
                                   else "SEQUENCE_IN_PROGRESS")
            return self.status()

        expected = self.lesson["prototype_id"]
        threshold = float(self.lesson["confidence_threshold"])
        matching = (
            valid
            and recognition_error == ERROR_OK
            and gesture_id == expected
            and confidence >= threshold
        )
        if not matching:
            self._match_since_ms = None
            if recognition_error not in (ERROR_OK, None):
                self.error_code = str(recognition_error)
            elif gesture_id in (None, "UNKNOWN") or not valid:
                self.error_code = ERROR_UNKNOWN_GESTURE
            elif confidence < threshold:
                self.error_code = ERROR_LOW_CONFIDENCE
            else:
                self.error_code = ERROR_WRONG_GESTURE
            return self.status()

        if self._match_since_ms is None:
            self._match_since_ms = now_ms
        elapsed_match = now_ms - self._match_since_ms
        effective_stable = max(stable_ms, elapsed_match)
        self.last_result["stable_ms"] = effective_stable
        self.error_code = ERROR_OK
        if effective_stable >= int(self.lesson["required_hold_ms"]):
            self._transition(STATE_COMPLETE, ERROR_OK)
            self.completed_ms = now_ms
        return self.status()

    observe = observe_result
    update = observe_result
    handle_result = observe_result

    def tick(
        self,
        now_ms=None,
        link_online=None,
        vision_fresh=None,
        vision_stale=False,
    ):
        now_ms = self._clock(now_ms)
        if link_online is None:
            link_online = self._link_online
        if vision_fresh is None:
            vision_fresh = self._vision_fresh
        if self.state in (STATE_DEMO_READY, STATE_DEMONSTRATING, STATE_IMITATING):
            self._link_online = bool(link_online)
            self._vision_fresh = bool(vision_fresh) and not bool(vision_stale)
            if not self._link_online:
                return self._fault_for_health(link_online, vision_fresh, vision_stale)
            # Missing/temporarily unavailable hand observations are handled by
            # the recognition result and the bounded imitation timeout.  They
            # must not abort a successful mechanical demonstration.
        if (
            self.state == STATE_IMITATING
            and self._deadline_ms is not None
            and now_ms >= self._deadline_ms
        ):
            self._transition(STATE_TIMEOUT, ERROR_TIMEOUT)
            self.completed_ms = now_ms
        return self.status()

    def cancel(self, now_ms=None):
        now_ms = self._clock(now_ms)
        if self.state in (STATE_IDLE,) or self.state in TERMINAL_STATES:
            self.error_code = ERROR_INVALID_STATE
            return self.status()
        self._transition(STATE_CANCELLED, ERROR_CANCELLED)
        self.completed_ms = now_ms
        self._match_since_ms = None
        return self.status()

    def review_manual(self, now_ms=None, manual_confirm=False, session_token=None):
        """Record the operator's review, never an automatic or actuator pass."""
        now_ms = self._clock(now_ms)
        if (manual_confirm is not True or type(session_token) is not int or
                session_token != self.session_token or self._sequence is None or
                self.state != STATE_IMITATING):
            result = self.status()
            result.update(ok=False, reason="review_not_allowed")
            return result
        if self._deadline_ms is not None and now_ms >= self._deadline_ms:
            self.tick(now_ms)
            result = self.status()
            result.update(ok=False, reason="review_expired")
            return result
        self._transition(STATE_REVIEWED, "MANUAL_REVIEW")
        self.completed_ms = now_ms
        self._sequence._clear_hold()
        self._sequence.checks = []
        self._match_since_ms = None
        result = self.status()
        result["ok"] = True
        return result

    def fault(self, error_code=ERROR_EXTERNAL_FAULT, now_ms=None):
        now_ms = self._clock(now_ms)
        if self.state in TERMINAL_STATES:
            return self.status()
        self._transition(STATE_FAULT, error_code or ERROR_EXTERNAL_FAULT)
        self.completed_ms = now_ms
        return self.status()

    def reset(self, now_ms=None):
        self._clock(now_ms)
        self.state = STATE_IDLE
        self.lesson = None
        self._sequence = None
        self.started_ms = None
        self.demo_started_ms = None
        self.imitation_started_ms = None
        self.completed_ms = None
        self.last_result = None
        self.error_code = ERROR_OK
        self.manual_confirmed = False
        self._match_since_ms = None
        self._deadline_ms = None
        self._transition_history = [STATE_IDLE]
        self._last_logged_session = None
        self.session_token = None
        return self.status()

    def can_act(self, link_online=None, vision_fresh=None, vision_stale=False):
        if link_online is None:
            link_online = self._link_online
        if vision_fresh is None:
            vision_fresh = self._vision_fresh
        return bool(
            self.state == STATE_DEMONSTRATING
            and self.manual_confirmed
            and link_online
            and vision_fresh
            and not vision_stale
            and self.lesson is not None
        )

    @property
    def action_allowed(self):
        return self.can_act()

    @property
    def lesson_id(self):
        return None if self.lesson is None else self.lesson["lesson_id"]

    @property
    def current_lesson(self):
        return self.lesson

    @property
    def transition_history(self):
        return list(self._transition_history)

    def status(self):
        result = self.last_result or {
            "gesture_id": "UNKNOWN",
            "confidence": 0.0,
            "stable_ms": 0,
            "valid": False,
            "error_code": self.error_code,
        }
        data = {
            "state": self.state,
            "lesson_id": self.lesson_id,
            "lesson": None if self.lesson is None else self.lesson.copy(),
            "gesture_id": result.get("gesture_id", "UNKNOWN"),
            "confidence": float(result.get("confidence", 0.0)),
            "stable_ms": int(result.get("stable_ms", 0)),
            "valid": bool(result.get("valid", False)),
            "error_code": self.error_code,
            "started_ms": self.started_ms,
            "demo_started_ms": self.demo_started_ms,
            "imitation_started_ms": self.imitation_started_ms,
            "completed_ms": self.completed_ms,
            "manual_confirmed": self.manual_confirmed,
            "session_token": self.session_token,
            "action_allowed": self.action_allowed,
            "can_review": self.state == STATE_IMITATING and self._sequence is not None,
        }
        if self._sequence is not None:
            data["motion_progress"] = self._sequence.snapshot()
        return data

    snapshot = status


# Names useful to route code and tests without creating another state machine.
SignTrainingStateMachine = SignLessonController
SignSessionController = SignLessonController
SignLessonStateMachine = SignLessonController
LessonStateMachine = SignLessonController

LESSON_CONFIGS = DEFAULT_LESSONS
