"""Production adapter checks with SDK substitutes, not device accuracy."""
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "maixcam2"))
from gesture_classifier import GestureClassifier
from rehab_hand_source import HandLandmarksVisionSource
from smart_hand.tests.test_gesture_palm_direction import palm_shape


def sdk_hand(folded=(False, False, True, True)):
    points = palm_shape(folded)
    points[1:5] = [(0.3, 0.1), (0.8, 0.2), (1.3, 0.3), (1.8, 0.4)]
    raw = [value for x, y in points for value in (150+x*40, 90+y*40, 0)]
    return types.SimpleNamespace(points=[0]*8+raw, w=150, h=150, class_id=1)


class Detector:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def input_format(self):
        return "rgb"
    def detect(self, frame, **kwargs):
        self.calls.append((frame, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class SignDetectorRetryTests(unittest.TestCase):
    def source(self, responses, retry=True, classifier=None, **kwargs):
        detector = Detector(responses)
        frame = object()
        camera = types.SimpleNamespace(read=lambda: frame)
        fake_maix = types.SimpleNamespace(
            nn=types.SimpleNamespace(HandLandmarks=lambda **kw: detector),
            camera=types.SimpleNamespace(Camera=lambda *args: camera))
        with patch.dict(sys.modules, {"maix": fake_maix}):
            source = HandLandmarksVisionSource(
                classifier=classifier or GestureClassifier(),
                sign_detector_retry=retry, **kwargs)
        return source, detector, frame

    def test_baseline_success_has_one_call_and_keeps_classifier_label(self):
        source, detector, frame = self.source([[sdk_hand()]])
        result = source.read_sign(0)
        self.assertEqual(result["gesture_id"], "V_SIGN")
        self.assertTrue(result["valid"])
        self.assertEqual(source.last_detection_profile, "baseline")
        self.assertEqual(source.last_detection_attempts, 1)
        self.assertEqual(len(detector.calls), 1)
        self.assertIs(detector.calls[0][0], frame)

    def test_retry_uses_current_frame_and_preserves_second_stage_and_iou(self):
        source, detector, frame = self.source([[], [sdk_hand()]])
        result = source.read_sign(100)
        self.assertEqual(result["gesture_id"], "V_SIGN")
        self.assertEqual(source.last_detection_profile, "detector_relaxed")
        self.assertEqual(source.last_detection_attempts, 2)
        self.assertEqual([call[1] for call in detector.calls], [
            {"conf_th": 0.7, "iou_th": 0.45, "conf_th2": 0.8},
            {"conf_th": 0.5, "iou_th": 0.45, "conf_th2": 0.8}])
        self.assertTrue(all(call[0] is frame for call in detector.calls))

    def test_disabled_retry_or_already_low_threshold_has_no_second_call(self):
        for config in ({"retry": False}, {"confidence": 0.5}, {"confidence": 0.4}):
            with self.subTest(config=config):
                source, detector, _ = self.source([[]], **config)
                self.assertFalse(source.read_sign(0)["valid"])
                self.assertEqual(len(detector.calls), 1)

    def test_missing_hand_does_not_preserve_label_or_accumulate_hold(self):
        source, detector, _ = self.source([[sdk_hand()], [], [], [sdk_hand()], [sdk_hand()]])
        self.assertEqual(source.read_sign(0)["stable_ms"], 0)
        missing = source.read_sign(200)
        self.assertEqual(missing["error_code"], "hand_not_found")
        self.assertIsNone(missing["gesture_id"])
        self.assertEqual(missing["stable_ms"], 0)
        self.assertIsNone(source.last_hand)
        self.assertEqual(source.read_sign(500)["stable_ms"], 0)
        self.assertEqual(source.read_sign(800)["stable_ms"], 300)
        self.assertEqual(source.no_hand, 1)
        self.assertEqual(source.frames, 4)
        self.assertEqual(len(detector.calls), 5)

    def test_actual_adapter_missing_code_preserves_dynamic_course_progress(self):
        from sign_lesson import SignLessonController
        from smart_hand.tests.test_sign_sequence import observation
        source, _, _ = self.source([[], []])
        controller = SignLessonController()
        controller.select_lesson("signal_help", 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(0, link_online=True, vision_fresh=True)
        controller.finish_demo(0, link_online=True, vision_fresh=True)
        for phase, start in (("palm_open", 0), ("thumb_in", 400)):
            for delta in (0, 150, 320):
                controller.observe(observation(phase), start+delta)
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 2)
        missing = source.read_sign(850)
        self.assertEqual(missing["error_code"], "hand_not_found")
        controller.observe(missing, 850)
        progress = controller.status()["motion_progress"]
        self.assertEqual(progress["completed_steps"], 2)
        self.assertEqual(progress["observation_state"], "MISSING")
        self.assertEqual(progress["phase_hold_ms"], 0)
        self.assertFalse(progress["complete"])
        for now in (1100, 1250, 1420):
            controller.observe(observation("help_close"), now)
        # The occluded final step uses operator review, not automatic scoring.
        self.assertEqual(controller.state, "IMITATING")
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 2)
        self.assertFalse(controller.status()["motion_progress"]["complete"])
        result = controller.review_manual(1500, True, controller.session_token)
        self.assertEqual(result["state"], "REVIEWED")
        self.assertEqual(controller.status()["motion_progress"]["completed_steps"], 2)
        self.assertFalse(controller.status()["motion_progress"]["complete"])

    def test_retry_label_is_not_forced_to_v_or_l(self):
        source, _, _ = self.source([[], [sdk_hand((False,)*4)]])
        self.assertEqual(source.read_sign(0)["gesture_id"], "OPEN_PALM")
        source, _, _ = self.source([[], [sdk_hand((False, True, True, True))]])
        self.assertEqual(source.read_sign(0)["gesture_id"], "L_SHAPE")

    def test_detector_failure_resets_hold_and_still_reports_error(self):
        source, _, _ = self.source([[sdk_hand()], RuntimeError("NPU failed"), [sdk_hand()]])
        source.read_sign(0)
        with self.assertRaisesRegex(RuntimeError, "NPU failed"):
            source.read_sign(200)
        self.assertFalse(source.last_recognition["valid"])
        self.assertEqual(source.last_recognition["error_code"], "vision_read_failed")
        self.assertIsNone(source.last_frame)
        self.assertEqual(source.read_sign(600)["stable_ms"], 0)

    def test_camera_failure_resets_hold_before_detection(self):
        source, detector, frame = self.source([[sdk_hand()], [sdk_hand()]])
        source.read_sign(0)
        source.camera.read = lambda: (_ for _ in ()).throw(RuntimeError("camera failed"))
        with self.assertRaises(RuntimeError):
            source.read_sign(200)
        self.assertEqual(len(detector.calls), 1)
        source.camera.read = lambda: frame
        self.assertEqual(source.read_sign(600)["stable_ms"], 0)

    def test_invalid_geometry_resets_hold_before_next_valid_hand(self):
        invalid = sdk_hand()
        invalid.points = [0]*71
        source, _, _ = self.source([[sdk_hand()], [invalid], [sdk_hand()]])
        source.read_sign(0)
        with self.assertRaises(ValueError):
            source.read_sign(200)
        self.assertEqual(source.read_sign(600)["stable_ms"], 0)

    def test_classifier_exception_breaks_hold_and_returns_invalid_result(self):
        classifier = GestureClassifier()
        source, _, _ = self.source([[sdk_hand()], [sdk_hand()], [sdk_hand()]], classifier=classifier)
        source.read_sign(0)
        method = classifier._classify_frame
        classifier._classify_frame = lambda _points: (_ for _ in ()).throw(RuntimeError("classifier failed"))
        result = source.read_sign(200)
        self.assertFalse(result["valid"])
        self.assertEqual(result["error_code"], "classifier_RuntimeError")
        classifier._classify_frame = method
        self.assertEqual(source.read_sign(600)["stable_ms"], 0)

    def test_rehab_read_remains_single_attempt_even_with_sign_retry_enabled(self):
        source, detector, _ = self.source([[]])
        self.assertIsNone(source.read())
        self.assertEqual(len(detector.calls), 1)


if __name__ == "__main__":
    unittest.main()
