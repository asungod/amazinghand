import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIXCAM2_ROOT = PROJECT_ROOT / "maixcam2"
sys.path.insert(0, str(MAIXCAM2_ROOT))

from live_sidecar import LiveWebSidecar  # noqa: E402
from web_stream import PreviewServer  # noqa: E402
from sign_lesson import (  # noqa: E402
    SignLessonController,
    STATE_COMPLETE,
    STATE_DEMONSTRATING,
    STATE_FAULT,
    STATE_IMITATING,
)
from sign_session_log import SignSessionCsvLogger  # noqa: E402
from sign_motion import SignMotionController  # noqa: E402
from rehab_hand_source import HandLandmarksVisionSource  # noqa: E402


def load_main_module():
    fake_time = types.SimpleNamespace(
        ticks_ms=lambda: 0,
        ticks_diff=lambda previous, current: current - previous,
    )
    fake_maix = types.ModuleType("maix")
    fake_maix.app = types.SimpleNamespace(need_exit=lambda: True)
    fake_maix.time = fake_time
    fake_maix.err = types.SimpleNamespace()
    fake_maix.pinmap = types.SimpleNamespace()
    fake_maix.uart = types.SimpleNamespace()
    spec = importlib.util.spec_from_file_location(
        "maix_sign_main_under_test", MAIXCAM2_ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"maix": fake_maix}):
        spec.loader.exec_module(module)
    return module


class FakeSignSidecar:
    def __init__(self, command):
        self.command = command
        self.rejected = []
        self.applied = []

    def take_web_sign_intent(self):
        command, self.command = self.command, None
        return command

    def note_web_sign_rejected(self, request_id, reason):
        self.rejected.append((request_id, reason))

    def note_web_sign_applied(self, request_id, reason=None):
        self.applied.append((request_id, reason))


class FakeSignSerial:
    def __init__(self):
        self.writes = []

    def write(self, frame):
        self.writes.append(frame)
        return len(frame)


def authority(*, link_online=True, have_vision=True, last_status_ms=0):
    return {
        "snapshot": {
            "ver": 1,
            "link_online": link_online,
            "have_vision": have_vision,
            "vision_stale": False,
            "have_actionable": False,
            "pose": 0,
            "gate_present": False,
            "gate_fault": False,
        },
        "last_status_ms": last_status_ms,
    }


class SignIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()

    def test_select_start_screen_demo_then_stable_result_and_log(self):
        controller = SignLessonController()
        monitor = types.SimpleNamespace(consecutive_timeouts=0)
        sidecar = FakeSignSidecar(
            {"request_id": 1, "action": "select", "lesson_id": "basic_open_palm"}
        )
        self.assertTrue(
            self.main.consume_sign_intent(
                sidecar, controller, authority(), monitor, 0
            )
        )
        self.assertEqual(controller.state, "LESSON_SELECTED")
        sidecar.command = {"request_id": 2, "action": "start"}
        self.assertTrue(
            self.main.consume_sign_intent(
                sidecar, controller, authority(have_vision=False), monitor, 10
            )
        )
        self.assertEqual(controller.state, STATE_DEMONSTRATING)
        self.assertTrue(
            self.main.tick_sign_controller(
                controller, authority(have_vision=False, last_status_ms=2000), 3010, True
            )
        )
        self.assertEqual(controller.state, STATE_IMITATING)
        result = {
            "gesture_id": "OPEN_PALM",
            "confidence": 0.95,
            "stable_ms": 300,
            "valid": True,
            "error_code": "OK",
        }
        controller.observe(result, 3310)
        self.assertEqual(controller.state, STATE_COMPLETE)
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        logger = SignSessionCsvLogger(path)
        self.assertEqual(logger.append(controller, 3310), 1)
        contents = Path(path).read_text(encoding="utf-8")
        self.assertIn("basic_open_palm", contents)
        self.assertIn(",COMPLETE,COMPLETE,", contents)

    def test_screen_only_start_only_needs_fresh_online_status(self):
        controller = SignLessonController()
        controller.select_lesson("basic_fist", 0)
        monitor = types.SimpleNamespace(consecutive_timeouts=0)
        self.assertIsNone(
            self.main.sign_start_rejection_reason(
                authority(have_vision=False), monitor, controller, 10
            )
        )

    def test_opt_in_mechanical_start_is_one_fixed_sign_frame(self):
        controller = SignLessonController()
        controller.select_lesson("basic_open_palm", 0)
        monitor = types.SimpleNamespace(
            consecutive_timeouts=0, pending={}, record=lambda *args: None
        )
        # send_frame uses write_tracked, whose monitor needs a record method.
        serial = FakeSignSerial()
        motion = SignMotionController(status_timeout_ms=30000)
        old_enabled = self.main.SIGN_MECHANICAL_DEMO_ENABLED
        self.main.SIGN_MECHANICAL_DEMO_ENABLED = True
        try:
            ready = authority(last_status_ms=2000)
            ready["snapshot"].update(
                gate_present=True, gate_fault=False, have_actionable=True
            )
            sidecar = FakeSignSidecar(
                {"request_id": 1, "action": "select", "lesson_id": "basic_open_palm"}
            )
            self.assertTrue(
                self.main.consume_sign_intent(
                    sidecar, controller, ready, monitor, 0,
                    serial=serial, sequence=7, sign_motion_controller=motion,
                )
            )
            sidecar.command = {"request_id": 2, "action": "start"}
            self.assertTrue(
                self.main.consume_sign_intent(
                    sidecar, controller, ready, monitor, 10,
                    serial=serial, sequence=7, sign_motion_controller=motion,
                )
            )
            frame = self.main.StreamParser().feed(serial.writes[0])[0]
            self.assertEqual(frame["type"], "SIGN")
            self.assertEqual(frame["args"], [1, 1, 1])
            self.assertEqual(controller.state, STATE_DEMONSTRATING)
            self.assertEqual(sidecar.applied[-1], (2, "started"))
        finally:
            self.main.SIGN_MECHANICAL_DEMO_ENABLED = old_enabled

    def test_all_thirteen_lessons_emit_their_fixed_titan_sequence(self):
        old_enabled = self.main.SIGN_MECHANICAL_DEMO_ENABLED
        self.main.SIGN_MECHANICAL_DEMO_ENABLED = True
        try:
            for lesson_id, expected_sequence_id in (
                ("basic_open_palm", 1),
                ("basic_fist", 2),
                ("basic_v_sign", 3),
                ("basic_point", 4),
                ("basic_thumbs_up", 5),
                ("basic_l_shape", 6),
                ("basic_ok_pinch", 7),
                ("word_hello", 8),
                ("word_thanks", 9),
                ("signal_help", 10),
                ("word_no", 11),
                ("word_attention", 12),
                ("word_like", 13),
            ):
                controller = SignLessonController()
                monitor = types.SimpleNamespace(
                    consecutive_timeouts=0, pending={}, record=lambda *args: None
                )
                serial = FakeSignSerial()
                motion = SignMotionController(status_timeout_ms=30000)
                ready = authority(last_status_ms=0)
                ready["snapshot"].update(gate_present=True, gate_fault=False)
                sidecar = FakeSignSidecar({
                    "request_id": 1,
                    "action": "select",
                    "lesson_id": lesson_id,
                })
                self.assertTrue(self.main.consume_sign_intent(
                    sidecar, controller, ready, monitor, 0,
                    serial=serial, sequence=7, sign_motion_controller=motion,
                ))
                sidecar.command = {"request_id": 2, "action": "start"}
                self.assertTrue(self.main.consume_sign_intent(
                    sidecar, controller, ready, monitor, 1,
                    serial=serial, sequence=7, sign_motion_controller=motion,
                ))
                frame = self.main.StreamParser().feed(serial.writes[0])[0]
                self.assertEqual(frame["args"], [1, 1, expected_sequence_id])
        finally:
            self.main.SIGN_MECHANICAL_DEMO_ENABLED = old_enabled

    def test_mechanical_signstat_completion_finishes_demo(self):
        controller = SignLessonController()
        controller.select_lesson("basic_open_palm", 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(0, link_online=True, vision_fresh=True)
        motion = SignMotionController(status_timeout_ms=30000)
        motion.begin_request(1, 7, 0, 1)
        motion.note_sent(7, 1, 0, 1)
        motion.note_ack(7, 0, 1)
        motion.note_status(
            {"type": "SIGNSTAT", "seq": 0, "args": [1, 7, 1, 5, 1, 1, 1]},
            2000,
        )
        old_enabled = self.main.SIGN_MECHANICAL_DEMO_ENABLED
        self.main.SIGN_MECHANICAL_DEMO_ENABLED = True
        try:
            ready = authority(last_status_ms=2000)
            ready["snapshot"].update(gate_present=True, gate_fault=False)
            status = self.main.tick_sign_controller(
                controller, ready, 2000, True, motion, types.SimpleNamespace(pending={})
            )
            self.assertEqual(status["state"], STATE_IMITATING)
        finally:
            self.main.SIGN_MECHANICAL_DEMO_ENABLED = old_enabled

    def test_previous_motion_failure_does_not_fault_newly_selected_lesson(self):
        controller = SignLessonController()
        controller.select_lesson("basic_open_palm", 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(0, link_online=True, vision_fresh=True)
        motion = SignMotionController(status_timeout_ms=30000)
        motion.begin_request(1, 7, 0, 1)
        motion.note_sent(7, 1, 0, 1)
        motion.note_ack(7, 3, 1)
        old_enabled = self.main.SIGN_MECHANICAL_DEMO_ENABLED
        self.main.SIGN_MECHANICAL_DEMO_ENABLED = True
        try:
            ready = authority(last_status_ms=1)
            ready["snapshot"].update(gate_present=True, gate_fault=False)
            status = self.main.tick_sign_controller(
                controller, ready, 1, True, motion, types.SimpleNamespace(pending={})
            )
            self.assertEqual(status["state"], STATE_FAULT)
            controller.select_lesson("basic_fist", 2)
            status = self.main.tick_sign_controller(
                controller, ready, 2, True, motion, types.SimpleNamespace(pending={})
            )
            self.assertEqual(status["state"], "LESSON_SELECTED")
            self.assertEqual(status["lesson_id"], "basic_fist")
        finally:
            self.main.SIGN_MECHANICAL_DEMO_ENABLED = old_enabled

    def test_shape_diagnostics_are_bounded_and_contain_no_landmarks(self):
        recognition = HandLandmarksVisionSource._normalize_recognition({
            "gesture_id": "UNKNOWN", "confidence": 0.72,
            "stable_ms": 0, "valid": False, "error_code": "LOW_CONFIDENCE",
            "finger_extension": [0.9, 0.1, 0.1, 0.1],
            "thumb_extension": 0.6, "top_candidate": "L_SHAPE",
            "normalized_landmarks": [1, 2, 3],
        })
        self.assertEqual(recognition["shape_debug"]["top_candidate"], "L_SHAPE")
        self.assertNotIn("normalized_landmarks", recognition)
        controller = SignLessonController()
        status = self.main.sign_status_snapshot(controller, recognition)
        self.assertEqual(status["shape_debug"]["finger_extension"], [0.9, 0.1, 0.1, 0.1])

    def test_motion_progress_survives_main_snapshot_without_private_geometry(self):
        controller = SignLessonController()
        controller.select_lesson("word_thanks", 0)
        recognition = {"gesture_id":"THUMBS_UP", "confidence":.95,"stable_ms":300,
                       "valid":True,"error_code":"OK","motion_evidence":{"private":"geometry"}}
        status = self.main.sign_status_snapshot(controller, recognition)
        self.assertEqual(status["motion_progress"]["total_steps"], 5)
        self.assertNotIn("motion_evidence", status)

    def test_course_hold_and_confidence_survive_live_recognition_reset(self):
        controller = SignLessonController()
        controller.select_lesson("basic_v_sign", 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(10, link_online=True, vision_fresh=True)
        controller.finish_demo(20, link_online=True, vision_fresh=True)
        matching = {"gesture_id": "V_SIGN", "confidence": .95, "stable_ms": 0,
                    "valid": True, "error_code": "OK"}
        controller.observe_result(matching, 30)
        controller.observe_result(matching, 380)
        self.assertEqual(controller.state, STATE_COMPLETE)
        live = {"gesture_id": "UNKNOWN", "confidence": 0, "stable_ms": 0,
                "valid": False, "error_code": "NO_HAND"}
        status = self.main.sign_status_snapshot(controller, live)
        self.assertEqual(status["course_stable_ms"], 350)
        self.assertEqual(status["course_confidence"], .95)
        self.assertEqual(status["stable_ms"], 0)
        self.assertEqual(status["confidence"], 0)
        self.assertEqual(status["session_error_code"], "OK")
        self.assertEqual(status["recognition_error_code"], "NO_HAND")
        self.assertEqual(status["course_gesture_id"], "V_SIGN")
        self.assertEqual(status["gesture_id"], "UNKNOWN")

    def test_course_evidence_is_independent_of_live_age_and_hand_change(self):
        controller = SignLessonController()
        controller.select_lesson("basic_fist", 0)
        controller.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
        controller.begin_demo(10, link_online=True, vision_fresh=True)
        controller.finish_demo(20, link_online=True, vision_fresh=True)
        controller.observe({"gesture_id":"FIST","confidence":.96,"stable_ms":350,
                            "valid":True,"error_code":"OK"}, 50)
        live = {"gesture_id":"OPEN_PALM","confidence":.99,"stable_ms":100,
                "valid":True,"error_code":"OK","observed_ms":100}
        for now, fresh in ((100, True), (1599, True), (1600, False), (1700, False), (99, False)):
            status = self.main.sign_status_snapshot(controller, live, now_ms=now)
            self.assertEqual(status["state"], "COMPLETE")
            self.assertEqual(status["course_gesture_id"], "FIST")
            self.assertEqual(status["course_confidence"], .96)
            self.assertEqual(status["gesture_id"], "OPEN_PALM")
            self.assertEqual(status["recognition_fresh"], fresh)
            self.assertEqual(status["recognition_observed_ms"], 100)
            self.assertNotIn("motion_evidence", status)
        controller.select_lesson("basic_v_sign", 1800)
        status = self.main.sign_status_snapshot(controller, live, now_ms=1800)
        self.assertNotIn("course_gesture_id", status)

    def test_unverified_future_mechanical_demo_is_rejected(self):
        lessons = {
            "future": {
                "lesson_id": "future",
                "prototype_id": "OPEN_PALM",
                "confidence_threshold": 0.7,
                "required_hold_ms": 300,
                "demo_mode": "partial",
                "mechanical_pose": 7,
                "mechanical_pose_status": "PENDING_HARDWARE_VALIDATION",
            }
        }
        controller = SignLessonController(lessons=lessons)
        controller.select_lesson("future", 0)
        reason = self.main.sign_start_rejection_reason(
            authority(), types.SimpleNamespace(consecutive_timeouts=0), controller, 10
        )
        self.assertEqual(reason, "mechanical_demo_unverified")

    def test_sign_status_keeps_controller_state_and_queues_request_state(self):
        controller = SignLessonController()
        controller.select_lesson("basic_fist", 0)
        sidecar = LiveWebSidecar(
            lambda: {
                "sign_controller": controller,
                "sign_status": lambda: self.main.sign_status_snapshot(controller),
            }
        )
        queued = sidecar.enqueue_web_sign_select("basic_fist")
        self.assertEqual(queued["state"], "queued_for_main")
        pending = sidecar.sign_status()
        self.assertEqual(pending["state"], "LESSON_SELECTED")
        self.assertEqual(pending["request_state"], "pending")
        request = sidecar.take_web_sign_intent()
        sidecar.note_web_sign_applied(request["request_id"], "lesson_selected")
        status = sidecar.sign_status()
        self.assertEqual(status["state"], "LESSON_SELECTED")
        self.assertEqual(status["request_state"], "applied")
        self.assertEqual(status["request_reason"], "lesson_selected")

    def test_terminal_session_error_is_not_hidden_by_no_hand_recognition(self):
        controller = SignLessonController()
        controller.select_lesson("basic_fist", 0)
        controller.start(
            1, manual_confirm=True, link_online=False, vision_fresh=True
        )
        status = self.main.sign_status_snapshot(
            controller,
            {
                "gesture_id": "UNKNOWN",
                "confidence": 0.0,
                "stable_ms": 0,
                "valid": False,
                "error_code": "hand_not_found",
            },
        )
        self.assertEqual(status["state"], "FAULT")
        self.assertEqual(status["error_code"], "LINK_OFFLINE")
        self.assertEqual(status["session_error_code"], "LINK_OFFLINE")
        self.assertEqual(status["recognition_error_code"], "hand_not_found")

    def test_fault_is_terminal_and_is_logged(self):
        controller = SignLessonController()
        controller.select_lesson("basic_v_sign", 0)
        controller.start(
            10, manual_confirm=True, link_online=True, vision_fresh=True
        )
        controller.begin_demo(10, link_online=True, vision_fresh=True)
        controller.fault("EXTERNAL_FAULT", 20)
        self.assertEqual(controller.state, STATE_FAULT)
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        logger = SignSessionCsvLogger(path)
        self.assertEqual(logger.append(controller, 20), 1)
        self.assertIn(",FAULT,FAULT,", Path(path).read_text(encoding="utf-8"))

    def test_terminal_logging_retries_after_transient_append_failure(self):
        controller = SignLessonController()
        controller.select_lesson("basic_fist", 0)
        controller.start(
            10, manual_confirm=True, link_online=True, vision_fresh=True
        )
        controller.fault("EXTERNAL_FAULT", 20)

        class RetryLogger:
            def __init__(self):
                self.calls = 0

            def append(self, _controller, _now_ms):
                self.calls += 1
                return None if self.calls == 1 else 9

        logger = RetryLogger()
        recorded = self.main.record_sign_terminal(logger, controller, 20, False)
        self.assertFalse(recorded)
        recorded = self.main.record_sign_terminal(logger, controller, 21, recorded)
        self.assertTrue(recorded)
        self.assertEqual(logger.calls, 2)

    def test_http_sign_select_only_enqueues_and_rejects_servo_fields(self):
        calls = []
        server = PreviewServer(
            sign_select_handler=lambda lesson_id: calls.append(lesson_id) or {
                "request_id": 1,
                "state": "queued_for_main",
            },
            sign_start_handler=lambda: {"request_id": 2},
            sign_cancel_handler=lambda: {"request_id": 3},
            sign_status_provider=lambda: {"state": "LESSON_SELECTED"},
        )
        body = b'{"lesson_id":"basic_fist"}'
        raw = (
            b"POST /api/v1/sign/select HTTP/1.1\r\n"
            b"Host: device:8080\r\nOrigin: http://device:8080\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body
        )
        response = server._sign_request_response(raw, "select")
        self.assertIn(b"202 Accepted", response)
        self.assertEqual(calls, ["basic_fist"])

        servo_body = b'{"lesson_id":"basic_fist","servo_angle":42}'
        servo_raw = raw.replace(body, servo_body).replace(
            str(len(body)).encode("ascii"), str(len(servo_body)).encode("ascii")
        )
        response = server._sign_request_response(servo_raw, "select")
        self.assertIn(b"400 Bad Request", response)
        self.assertEqual(calls, ["basic_fist"])


if __name__ == "__main__":
    unittest.main()
