import math
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from gesture_classifier import (  # noqa: E402
    ERROR_LOW_CONFIDENCE,
    ERROR_NO_HAND,
    FIST,
    L_SHAPE,
    OK_PINCH,
    OPEN_PALM,
    POINT,
    THUMBS_UP,
    UNKNOWN,
    V_SIGN,
    GestureClassifier,
    _classify_features,
    classify_gesture,
)
from gesture_features import extract_gesture_features  # noqa: E402
from rehab_hand_source import HandLandmarksVisionSource  # noqa: E402
from sign_lesson import (  # noqa: E402
    ERROR_LINK_OFFLINE,
    ERROR_MANUAL_CONFIRM_REQUIRED,
    ERROR_TIMEOUT,
    STATE_CANCELLED,
    STATE_COMPLETE,
    STATE_FAULT,
    STATE_IMITATING,
    STATE_LESSON_SELECTED,
    STATE_TIMEOUT,
    SignLessonController,
    lesson_catalog,
)
from sign_session_log import CSV_HEADER, SignSessionCsvLogger  # noqa: E402


def shape(pattern):
    """Make a simple 21-point fixture: False=straight, True=folded."""
    points = [(0.0, 0.0) for _ in range(21)]
    points[9] = (2.0, 0.0)
    for (base, x), folded in zip(
        ((5, 1.0), (9, 2.0), (13, 3.0), (17, 4.0)), pattern
    ):
        points[base] = (x, 0.0)
        points[base + 1] = (x, 1.0)
        points[base + 2] = ((x + 0.8), 1.0) if folded else (x, 2.0)
        points[base + 3] = ((x + 0.8), 0.2) if folded else (x, 3.0)
    return points


OPEN = shape((False, False, False, False))
FIST_POINTS = shape((True, True, True, True))
V_POINTS = shape((False, False, True, True))
POINT_POINTS = shape((False, True, True, True))
THUMBS_UP_POINTS = shape((True, True, True, True))
THUMBS_UP_POINTS[1] = (0.0, 0.5)
THUMBS_UP_POINTS[2] = (0.0, 1.0)
THUMBS_UP_POINTS[3] = (0.0, 2.0)
THUMBS_UP_POINTS[4] = (0.0, 3.0)
L_SHAPE_POINTS = shape((False, True, True, True))
L_SHAPE_POINTS[1] = (0.0, 0.5)
L_SHAPE_POINTS[2] = (0.0, 1.0)
L_SHAPE_POINTS[3] = (0.0, 2.0)
L_SHAPE_POINTS[4] = (0.0, 3.0)
OK_PINCH_POINTS = shape((True, False, False, False))
OK_PINCH_POINTS[1] = (0.2, 0.2)
OK_PINCH_POINTS[2] = (0.8, 0.2)
OK_PINCH_POINTS[3] = (1.4, 0.2)
OK_PINCH_POINTS[4] = OK_PINCH_POINTS[8]
AMBIGUOUS = shape((False, True, False, True))


class GestureFeatureTests(unittest.TestCase):
    def test_xy_and_flat_xyz_have_same_shape_features(self):
        flat = [value for x, y in OPEN for value in (x, y, 0.0)]
        xy = extract_gesture_features(OPEN)
        xyz = extract_gesture_features(flat)
        self.assertEqual(xy["finger_extension"], xyz["finger_extension"])
        self.assertEqual(len(xy["normalized_landmarks"]), 21)

    def test_rotation_is_normalized_before_classification(self):
        angle = math.radians(35.0)
        rotated = []
        for x, y in OPEN:
            rotated.append(
                (x * math.cos(angle) - y * math.sin(angle),
                 x * math.sin(angle) + y * math.cos(angle))
            )
        self.assertEqual(classify_gesture(OPEN).gesture_id, OPEN_PALM)
        self.assertEqual(classify_gesture(rotated).gesture_id, OPEN_PALM)


class GestureClassifierTests(unittest.TestCase):
    def test_partly_occluded_v_is_not_accepted_as_open_palm(self):
        points = [(0.0, 0.0) for _ in range(21)]
        points[12] = (0.5, 0.0)
        features = {"normalized_landmarks": points}
        features["finger_extension"] = (0.96, 0.94, 0.72, 0.71)
        self.assertEqual(_classify_features(features)[0], V_SIGN)
        features["finger_extension"] = (0.96, 0.94, 0.79, 0.78)
        self.assertNotEqual(_classify_features(features)[0], OPEN_PALM)

    def test_seven_prototype_shapes_and_unknown(self):
        self.assertEqual(classify_gesture(OPEN).gesture_id, OPEN_PALM)
        self.assertEqual(classify_gesture(FIST_POINTS).gesture_id, FIST)
        self.assertEqual(classify_gesture(V_POINTS).gesture_id, V_SIGN)
        self.assertEqual(classify_gesture(POINT_POINTS).gesture_id, POINT)
        self.assertEqual(classify_gesture(THUMBS_UP_POINTS).gesture_id, THUMBS_UP)
        self.assertEqual(classify_gesture(L_SHAPE_POINTS).gesture_id, L_SHAPE)
        self.assertEqual(classify_gesture(OK_PINCH_POINTS).gesture_id, OK_PINCH)
        unknown = classify_gesture(AMBIGUOUS)
        self.assertEqual(unknown.gesture_id, UNKNOWN)
        self.assertFalse(unknown.valid)
        self.assertEqual(unknown.error_code, ERROR_LOW_CONFIDENCE)

    def test_stability_is_monotonic_and_resets_on_missing_hand(self):
        classifier = GestureClassifier(stable_hold_ms=300)
        first = classifier.observe(OPEN, now_ms=100)
        second = classifier.observe(OPEN, now_ms=350)
        self.assertEqual(first.stable_ms, 0)
        self.assertEqual(second.stable_ms, 250)
        self.assertFalse(second.stable)
        missing = classifier.observe(None, now_ms=400, hand_present=False)
        self.assertEqual(missing.error_code, ERROR_NO_HAND)
        self.assertEqual(missing.stable_ms, 0)

    def test_link_and_stale_gates_fail_closed(self):
        classifier = GestureClassifier()
        self.assertEqual(
            classifier.observe(OPEN, now_ms=0, link_online=False).error_code,
            "LINK_OFFLINE",
        )
        self.assertEqual(
            classifier.observe(OPEN, now_ms=1, vision_stale=True).error_code,
            "VISION_STALE",
        )

    def test_hand_source_forwards_main_loop_tick_to_classifier(self):
        seen = []

        class Classifier:
            def observe(self, _points, now_ms=None):
                seen.append(now_ms)
                return {
                    "gesture_id": OPEN_PALM,
                    "confidence": 0.9,
                    "stable_ms": 0,
                    "valid": True,
                    "error_code": "OK",
                }

        source = HandLandmarksVisionSource.__new__(HandLandmarksVisionSource)
        source.classifier = Classifier()
        result = source._classify_landmarks(OPEN, now_ms=1234)
        self.assertEqual(seen, [1234])
        self.assertEqual(result["gesture_id"], OPEN_PALM)


class SignLessonControllerTests(unittest.TestCase):
    def test_l_course_metadata_does_not_claim_fingerspelling_instruction(self):
        lesson = lesson_catalog()["basic_l_shape"]
        self.assertEqual(lesson["name_zh"], "L 形基础手型原型")
        self.assertEqual(lesson["chinese_name"], lesson["name_zh"])
        self.assertNotIn("手指字母", lesson["name_zh"])
        self.assertIn("不认证手指字母或拼读能力", lesson["mechanical_semantics"])
        self.assertEqual(lesson["prototype_id"], "L_SHAPE")
        self.assertEqual(lesson["confidence_threshold"], 0.64)
        self.assertEqual(lesson["required_hold_ms"], 300)
        self.assertEqual(lesson["demo_mode"], "screen_only")
        self.assertIsNone(lesson["mechanical_pose"])
        self.assertEqual(lesson["mechanical_sequence_id"], 6)

    def test_default_lessons_are_prototypes_without_unverified_servo_pose(self):
        catalog = lesson_catalog()
        self.assertEqual(catalog["basic_open_palm"]["demo_mode"], "screen_only")
        self.assertIsNone(catalog["basic_open_palm"]["mechanical_pose"])
        self.assertEqual(
            catalog["basic_open_palm"]["mechanical_pose_status"],
            "PENDING_HARDWARE_VALIDATION",
        )

    def ready_controller(self, timeout_ms=1000):
        controller = SignLessonController(timeout_ms=timeout_ms)
        controller.select_lesson("basic_open_palm", now_ms=0)
        return controller

    def test_manual_confirmation_is_required_before_demo(self):
        controller = self.ready_controller()
        status = controller.start(now_ms=10, manual_confirm=False)
        self.assertEqual(status["state"], STATE_LESSON_SELECTED)
        self.assertEqual(status["error_code"], ERROR_MANUAL_CONFIRM_REQUIRED)
        self.assertFalse(status["action_allowed"])
        status = controller.start(
            now_ms=20, manual_confirm=True, link_online=True, vision_fresh=True
        )
        self.assertEqual(status["state"], "DEMO_READY")
        self.assertFalse(status["action_allowed"])
        status = controller.begin_demo(
            now_ms=30, link_online=True, vision_fresh=True
        )
        self.assertTrue(status["action_allowed"])
        self.assertEqual(status["state"], "DEMONSTRATING")

    def test_public_transition_defaults_fail_closed(self):
        controller = self.ready_controller()
        status = controller.start(now_ms=10)
        self.assertEqual(status["state"], STATE_LESSON_SELECTED)
        self.assertEqual(status["error_code"], ERROR_MANUAL_CONFIRM_REQUIRED)

        controller = self.ready_controller()
        controller.start(
            now_ms=10, manual_confirm=True, link_online=True, vision_fresh=True
        )
        status = controller.finish_demo(
            now_ms=20, link_online=True, vision_fresh=True
        )
        self.assertEqual(status["state"], "DEMO_READY")

    def test_normal_imitation_needs_stable_hold(self):
        controller = self.ready_controller()
        controller.start(
            now_ms=0, manual_confirm=True, link_online=True, vision_fresh=True
        )
        controller.begin_demo(now_ms=10, link_online=True, vision_fresh=True)
        controller.finish_demo(now_ms=20, link_online=True, vision_fresh=True)
        self.assertEqual(controller.state, STATE_IMITATING)
        result = {
            "gesture_id": OPEN_PALM,
            "confidence": 0.9,
            "stable_ms": 0,
            "valid": True,
            "error_code": "OK",
        }
        self.assertEqual(controller.observe_result(result, now_ms=30)["state"], STATE_IMITATING)
        result["stable_ms"] = 300
        self.assertEqual(controller.observe_result(result, now_ms=330)["state"], STATE_COMPLETE)

    def test_unknown_wrong_shape_does_not_complete(self):
        controller = self.ready_controller()
        controller.start(
            now_ms=0, manual_confirm=True, link_online=True, vision_fresh=True
        )
        controller.begin_demo(now_ms=5, link_online=True, vision_fresh=True)
        controller.finish_demo(now_ms=10, link_online=True, vision_fresh=True)
        status = controller.observe_result(
            {
                "gesture_id": UNKNOWN,
                "confidence": 0.95,
                "stable_ms": 1000,
                "valid": False,
                "error_code": ERROR_LOW_CONFIDENCE,
            },
            now_ms=20,
        )
        self.assertEqual(status["state"], STATE_IMITATING)
        self.assertNotEqual(status["error_code"], "OK")

    def test_missing_hand_after_demo_waits_for_imitation_instead_of_faulting(self):
        controller = self.ready_controller(timeout_ms=1000)
        controller.start(
            now_ms=0, manual_confirm=True, link_online=True, vision_fresh=True
        )
        controller.begin_demo(now_ms=5, link_online=True, vision_fresh=True)
        status = controller.finish_demo(
            now_ms=10, link_online=True, vision_fresh=False, vision_stale=True
        )
        self.assertEqual(status["state"], STATE_IMITATING)
        status = controller.tick(
            now_ms=20, link_online=True, vision_fresh=False, vision_stale=True
        )
        self.assertEqual(status["state"], STATE_IMITATING)
        self.assertEqual(controller.tick(now_ms=1010)["state"], STATE_TIMEOUT)

    def test_timeout_cancel_and_disconnect_fault(self):
        timeout = self.ready_controller(timeout_ms=100)
        timeout.start(
            now_ms=0, manual_confirm=True, link_online=True, vision_fresh=True
        )
        timeout.begin_demo(now_ms=5, link_online=True, vision_fresh=True)
        timeout.finish_demo(now_ms=10, link_online=True, vision_fresh=True)
        self.assertEqual(timeout.tick(now_ms=110)["state"], STATE_TIMEOUT)
        self.assertEqual(timeout.error_code, ERROR_TIMEOUT)

        cancelled = self.ready_controller()
        cancelled.start(
            now_ms=0, manual_confirm=True, link_online=True, vision_fresh=True
        )
        self.assertEqual(cancelled.cancel(now_ms=5)["state"], STATE_CANCELLED)

        faulted = self.ready_controller()
        status = faulted.start(
            now_ms=5,
            manual_confirm=True,
            link_online=False,
            vision_fresh=True,
        )
        self.assertEqual(status["state"], STATE_FAULT)
        self.assertEqual(status["error_code"], ERROR_LINK_OFFLINE)
        self.assertFalse(status["action_allowed"])


class SignSessionCsvLoggerTests(unittest.TestCase):
    def test_only_terminal_rows_are_written_and_reopened(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart_hand_sign_sessions.csv"
            logger = SignSessionCsvLogger(str(path))
            controller = SignLessonController()
            controller.select_lesson("basic_open_palm", now_ms=0)
            self.assertIsNone(logger.append(controller, now_ms=1))
            controller.start(
                now_ms=10, manual_confirm=True, link_online=True, vision_fresh=True
            )
            controller.begin_demo(now_ms=15, link_online=True, vision_fresh=True)
            controller.finish_demo(now_ms=20, link_online=True, vision_fresh=True)
            controller.observe_result(
                {
                    "gesture_id": OPEN_PALM,
                    "confidence": 0.95,
                    "stable_ms": 500,
                    "valid": True,
                    "error_code": "OK",
                },
                now_ms=520,
            )
            self.assertEqual(controller.state, STATE_COMPLETE)
            self.assertEqual(logger.append(controller, now_ms=520), 1)
            self.assertEqual(logger.append(controller, now_ms=521), 1)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(lines[0], CSV_HEADER.strip())
            self.assertIn("basic_open_palm", lines[1])
            self.assertIn(",COMPLETE,COMPLETE,", lines[1])
            resumed = SignSessionCsvLogger(str(path))
            self.assertEqual(resumed.next_session, 2)

    def test_reset_controller_can_append_a_new_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart_hand_sign_sessions.csv"
            logger = SignSessionCsvLogger(str(path))
            controller = SignLessonController()

            for base_ms in (0, 1000):
                controller.select_lesson("basic_open_palm", now_ms=base_ms)
                controller.start(
                    now_ms=base_ms + 10,
                    manual_confirm=True,
                    link_online=True,
                    vision_fresh=True,
                )
                controller.begin_demo(
                    now_ms=base_ms + 15, link_online=True, vision_fresh=True
                )
                controller.finish_demo(
                    now_ms=base_ms + 20, link_online=True, vision_fresh=True
                )
                controller.observe_result(
                    {
                        "gesture_id": OPEN_PALM,
                        "confidence": 0.95,
                        "stable_ms": 500,
                        "valid": True,
                        "error_code": "OK",
                    },
                    now_ms=base_ms + 520,
                )
                self.assertEqual(controller.state, STATE_COMPLETE)
                expected = 1 if base_ms == 0 else 2
                self.assertEqual(logger.append(controller), expected)
                controller.reset(now_ms=base_ms + 600)

            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 3)

    def test_repeated_fault_cannot_duplicate_one_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "smart_hand_sign_sessions.csv"
            logger = SignSessionCsvLogger(str(path))
            controller = SignLessonController()
            controller.select_lesson("basic_fist", now_ms=0)
            controller.start(
                now_ms=10,
                manual_confirm=True,
                link_online=True,
                vision_fresh=True,
            )
            controller.fault("EXTERNAL_FAULT", now_ms=20)
            self.assertEqual(logger.append(controller, now_ms=20), 1)
            controller.fault("DIFFERENT_FAULT", now_ms=30)
            self.assertEqual(logger.append(controller, now_ms=30), 1)
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
