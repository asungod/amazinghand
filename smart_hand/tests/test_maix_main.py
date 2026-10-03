import contextlib
import importlib.util
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIXCAM2_ROOT = PROJECT_ROOT / "maixcam2"
sys.path.insert(0, str(MAIXCAM2_ROOT))

from protocol import decode_frame  # noqa: E402
from link_monitor import AckMonitor  # noqa: E402


class FakeTime:
    def __init__(self):
        self.now_ms = 0

    def ticks_ms(self):
        return self.now_ms

    @staticmethod
    def ticks_diff(previous_ms, now_ms):
        return now_ms - previous_ms

    def sleep_ms(self, duration_ms):
        self.now_ms += duration_ms


class FakeApp:
    def __init__(self, iterations):
        self.iterations = iterations
        self.completed = 0

    def need_exit(self):
        if self.completed >= self.iterations:
            return True
        self.completed += 1
        return False


class FakeSerial:
    def __init__(self):
        self.writes = []

    @staticmethod
    def read():
        return None

    def write(self, frame):
        self.writes.append(frame)
        return len(frame)


class FailOnceReadSerial(FakeSerial):
    def __init__(self):
        super().__init__()
        self.read_calls = 0

    def read(self):
        self.read_calls += 1
        if self.read_calls == 1:
            raise OSError("temporary RX error")
        return None


class NoTargetVisionSource:
    def __init__(self):
        self.frames = 0

    def read(self):
        self.frames += 1
        return None

    def summary(self):
        return "mode=test frames={}".format(self.frames)


class FakeWebIntentSidecar:
    def __init__(self, request_id=1):
        self.request_id = request_id
        self.rejected = []
        self.submitted = []
        self.availability = []

    def set_web_train_availability(self, can_submit, reason):
        self.availability.append((can_submit, reason))

    def take_web_train_intent(self):
        request_id = self.request_id
        self.request_id = None
        return request_id

    def note_web_train_rejected(self, request_id, reason):
        self.rejected.append((request_id, reason))

    def note_web_train_submitted(self, request_id):
        self.submitted.append(request_id)


class ShortWriteSerial(FakeSerial):
    def write(self, frame):
        self.writes.append(frame)
        return len(frame) - 1


def load_main_module(iterations):
    fake_time = FakeTime()
    fake_maix = types.ModuleType("maix")
    fake_maix.app = FakeApp(iterations)
    fake_maix.time = fake_time
    fake_maix.err = types.SimpleNamespace()
    fake_maix.pinmap = types.SimpleNamespace()
    fake_maix.uart = types.SimpleNamespace()

    spec = importlib.util.spec_from_file_location(
        "maix_main_under_test", MAIXCAM2_ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"maix": fake_maix}):
        spec.loader.exec_module(module)
    module.VISION_MODE = "mock"
    module.SHOW_PREVIEW = False
    return module, fake_time


class MaixMainIntegrationTests(unittest.TestCase):
    @staticmethod
    def ready_web_state(module, *, target=(39, 100, 100, 40, 50, 80)):
        target_tracker = types.SimpleNamespace(active=target, active_seen_ms=0)
        authority = {
            "snapshot": {
                "ver": 1,
                "link_online": True,
                "have_vision": True,
                "vision_stale": False,
                "have_actionable": True,
                "pose": 0,
                "gate_present": True,
                "gate_fault": False,
            },
            "last_status_ms": 0,
        }
        return (
            target_tracker,
            authority,
            AckMonitor(module.ACK_TIMEOUT_MS),
            module.TrainButtonController(module.ACK_TIMEOUT_MS),
            types.SimpleNamespace(state="IDLE"),
        )

    def test_web_train_rejection_reasons_never_write_uart(self):
        module, _ = load_main_module(iterations=0)
        cases = (
            (None, None, "bottle_not_stable"),
            ((41, 100, 100, 40, 50, 80), None, "not_bottle"),
            ((39, 100, 100, 40, 50, 49), None, "bottle_confidence_low"),
            (None, "status_stale", "titan_status_stale"),
            (None, "link", "titan_link_offline"),
            (None, "gate", "titan_gate_unavailable"),
            (None, "pose", "titan_pose_not_ok"),
            (None, "uart", "uart_degraded"),
            (None, "busy", "train_busy"),
        )
        for target, fault, expected in cases:
            with self.subTest(expected=expected):
                target_tracker, authority, monitor, train, imitation = self.ready_web_state(
                    module, target=target or (39, 100, 100, 40, 50, 80)
                )
                if target is None and fault is None:
                    target_tracker.active = None
                if fault == "status_stale":
                    authority["last_status_ms"] = None
                elif fault == "link":
                    authority["snapshot"]["link_online"] = False
                elif fault == "gate":
                    authority["snapshot"]["gate_fault"] = True
                elif fault == "pose":
                    authority["snapshot"]["pose"] = 2
                elif fault == "uart":
                    monitor.consecutive_timeouts = 1
                elif fault == "busy":
                    train.note_sent(9, 0)
                serial = FakeSerial()
                sidecar = FakeWebIntentSidecar()
                sequence = module.consume_web_train_intent(
                    sidecar, serial, monitor, 3, target_tracker, authority, train,
                    imitation, "TARGET", 0,
                )
                self.assertEqual(sequence, 3)
                self.assertEqual(serial.writes, [])
                self.assertEqual(sidecar.rejected, [(1, expected)])

    def test_web_train_success_writes_exactly_one_train_and_only_then_notes_sent(self):
        module, _ = load_main_module(iterations=0)
        target_tracker, authority, monitor, train, imitation = self.ready_web_state(module)
        serial = FakeSerial()
        sidecar = FakeWebIntentSidecar()

        sequence = module.consume_web_train_intent(
            sidecar, serial, monitor, 3, target_tracker, authority, train,
            imitation, "TARGET", 0,
        )
        sequence = module.consume_web_train_intent(
            sidecar, serial, monitor, sequence, target_tracker, authority, train,
            imitation, "TARGET", 0,
        )

        self.assertEqual(sequence, 4)
        self.assertEqual([decode_frame(frame)["type"] for frame in serial.writes], ["TRAIN"])
        self.assertEqual(train.pending_seq, 3)
        self.assertEqual(sidecar.submitted, [1])

    def test_web_train_short_write_does_not_note_sent(self):
        module, _ = load_main_module(iterations=0)
        target_tracker, authority, monitor, train, imitation = self.ready_web_state(module)
        sidecar = FakeWebIntentSidecar()
        serial = ShortWriteSerial()

        sequence = module.consume_web_train_intent(
            sidecar, serial, monitor, 3, target_tracker, authority, train,
            imitation, "TARGET", 0,
        )

        self.assertEqual(sequence, 3)
        self.assertIsNone(train.pending_seq)
        self.assertEqual(sidecar.submitted, [])
        self.assertEqual(sidecar.rejected, [(1, "uart_write_failed")])

    def test_local_train_then_web_intent_in_same_cycle_emits_only_one_train(self):
        module, _ = load_main_module(iterations=0)
        target_tracker, authority, monitor, train, imitation = self.ready_web_state(module)
        serial = FakeSerial()
        self.assertTrue(module.send_frame(serial, monitor, "TRAIN", 3, 0, module.TRAIN_MODE_REHAB))
        train.note_sent(3, 0)
        sidecar = FakeWebIntentSidecar()

        sequence = module.consume_web_train_intent(
            sidecar, serial, monitor, 4, target_tracker, authority, train,
            imitation, "TARGET", 0,
        )

        self.assertEqual(sequence, 4)
        self.assertEqual([decode_frame(frame)["type"] for frame in serial.writes], ["TRAIN"])
        self.assertEqual(sidecar.rejected, [(1, "train_busy")])

    def test_overlay_reports_target_intent_and_link_health(self):
        module, _ = load_main_module(iterations=0)
        target, intent = module.target_status_lines((39, 320, 240, 80, 120, 75))
        monitor = types.SimpleNamespace(
            consecutive_timeouts=0,
            acked=12,
            last_rtt_ms=28,
        )

        self.assertEqual(target, "TARGET bottle 75%")
        self.assertEqual(intent, "INTENT CYLINDRICAL")
        self.assertEqual(
            module.link_status_line(monitor),
            "TITAN ONLINE ACK=12 RTT=28ms",
        )

    def test_overlay_fails_closed_without_target_or_ack(self):
        module, _ = load_main_module(iterations=0)
        monitor = types.SimpleNamespace(
            consecutive_timeouts=1,
            acked=0,
            last_rtt_ms=None,
        )

        self.assertEqual(module.target_status_lines(None), ("TARGET none", "INTENT none"))
        self.assertEqual(
            module.link_status_line(monitor),
            "TITAN DEGRADED ACK=0 RTT=-1ms",
        )

    def test_sign_overlay_translates_typical_lines_and_keeps_values(self):
        module, _ = load_main_module(iterations=0)

        self.assertEqual(
            module.translate_overlay_text("SIGN OPEN_PALM 0.95"),
            "实时手型 张开手掌 0.95",
        )
        self.assertEqual(
            module.translate_overlay_text("STABLE 350ms hand_not_found"),
            "稳定 350毫秒 未检测到手",
        )
        self.assertEqual(
            module.translate_overlay_text("SIGN STATE DEMONSTRATING"),
            "训练状态 示范中",
        )
        self.assertEqual(
            module.translate_overlay_text("LESSON_SELECTED COMPLETE"),
            "已选课程 完成",
        )
        self.assertEqual(
            module.translate_overlay_text(
                "START/CANCEL VIA CONFIRMED WEB ACTION"
            ),
            "请在电脑网页开始或取消",
        )

    def test_sign_overlay_keeps_unknown_text_and_brand_name(self):
        module, _ = load_main_module(iterations=0)

        self.assertEqual(
            module.translate_overlay_text("OpenSignHand CUSTOM_CODE 42"),
            "OpenSignHand CUSTOM_CODE 42",
        )
        self.assertEqual(
            module.translate_overlay_text("SIGN NEW_STATE 0.70"),
            "实时手型 NEW_STATE 0.70",
        )

    def test_overlay_gesture_names_are_not_retranslated_as_status_abbreviations(self):
        module, _ = load_main_module(iterations=0)
        for source, expected in (
            ("SIGN V_SIGN 0.95", "实时手型 V 手势 0.95"),
            ("SIGN L_SHAPE 0.93", "实时手型 L 形手型 0.93"),
            ("SIGN OK_PINCH 0.91", "实时手型 OK／确认 0.91"),
            ("AUTH L=ON V=ON S=OFF A=ON G=OFF", "权限 链=开 视=开 旧=关 动=开 门=关"),
            ("V 手势 L 形手型", "V 手势 L 形手型"),
            ("CUSTOM_V_SIGN_42", "CUSTOM_V_SIGN_42"),
        ):
            with self.subTest(source=source):
                self.assertEqual(module.translate_overlay_text(source), expected)

    def test_overlay_draw_calls_keep_latin_v_and_font_failure_falls_back(self):
        module, _ = load_main_module(iterations=0)
        module.OVERLAY_FONT = "testfont"
        calls = []
        frame = types.SimpleNamespace(draw_string=lambda x, y, text, **kw: calls.append((text, kw)))
        colors = types.SimpleNamespace(COLOR_BLACK=0, COLOR_WHITE=1, COLOR_RED=2)
        module.draw_overlay_text(frame, colors, 2, 3, "SIGN V_SIGN 0.95")
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(text == "实时手型 V 手势 0.95" for text, _ in calls))
        self.assertTrue(all(kw["font"] == "testfont" for _, kw in calls))
        calls.clear()
        def rejecting_font(x, y, text, **kw):
            if "font" in kw:
                raise TypeError("unsupported font")
            calls.append((text, kw))
        frame.draw_string = rejecting_font
        module.draw_overlay_text(frame, colors, 2, 3, "SIGN V_SIGN 0.95")
        self.assertIsNone(module.OVERLAY_FONT)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(text == "SIGN V_SIGN 0.95" for text, _ in calls))

    def test_only_authoritative_train_completion_starts_imitation(self):
        module, _ = load_main_module(iterations=0)
        train = types.SimpleNamespace(state="RUNNING")
        imitation = types.SimpleNamespace(state="IDLE", starts=[])
        imitation.start = imitation.starts.append
        self.assertFalse(
            module.start_imitation_after_train(
                "QUEUED", train, imitation, 100
            )
        )
        train.state = "COMPLETED"
        self.assertTrue(
            module.start_imitation_after_train(
                "RUNNING", train, imitation, 200
            )
        )
        self.assertEqual(imitation.starts, [200])

    def test_imitation_cancel_button_uses_release_edge_and_active_gate(self):
        module, _ = load_main_module(iterations=0)
        button = module.ImitationCancelButtonController()
        button.set_display_rect((10, 20, 100, 40))

        self.assertFalse(button.update_touch(20, 30, True, True))
        self.assertTrue(button.update_touch(20, 30, False, True))
        self.assertFalse(button.update_touch(20, 30, True, False))
        self.assertFalse(button.update_touch(20, 30, False, False))

    def test_imitation_cancel_is_local_and_does_not_write_uart(self):
        module, _ = load_main_module(iterations=0)
        serial = FakeSerial()
        imitation = module.ImitationSessionController(goal_repetitions=1)
        imitation.start(0)
        button = module.ImitationCancelButtonController()
        button.set_display_rect((10, 20, 100, 40))

        button.update_touch(20, 30, True, True)
        self.assertTrue(button.update_touch(20, 30, False, True))
        self.assertTrue(imitation.cancel(100))
        self.assertEqual(serial.writes, [])
        self.assertEqual(imitation.termination_reason, "user_cancelled")

    @staticmethod
    def run_main(module, serial):
        module.configure_uart2 = lambda: serial
        with contextlib.redirect_stdout(io.StringIO()):
            module.main()
        return [decode_frame(frame) for frame in serial.writes]

    def test_mock_target_sends_ping_then_rate_limited_vision(self):
        module, fake_time = load_main_module(iterations=51)
        serial = FakeSerial()

        messages = self.run_main(module, serial)

        self.assertEqual(fake_time.now_ms, 510)
        self.assertEqual([message["type"] for message in messages], ["PING", "VISION"])
        self.assertEqual(messages[0]["seq"], 0)
        self.assertEqual(messages[1]["seq"], 1)
        self.assertEqual(messages[1]["args"], [3, 320, 240, 80, 120, 96])

    def test_no_target_keeps_ping_without_vision(self):
        module, _ = load_main_module(iterations=101)
        module.create_vision_source = lambda *_args: NoTargetVisionSource()
        serial = FakeSerial()

        messages = self.run_main(module, serial)

        self.assertEqual([message["type"] for message in messages], ["PING", "PING"])
        self.assertEqual([message["seq"] for message in messages], [0, 1])

    def test_vision_initialization_failure_degrades_to_ping_only(self):
        module, _ = load_main_module(iterations=101)

        def fail_vision_init(*_args):
            raise RuntimeError("model unavailable")

        module.create_vision_source = fail_vision_init
        serial = FakeSerial()

        messages = self.run_main(module, serial)

        self.assertEqual([message["type"] for message in messages], ["PING", "PING"])
        self.assertEqual([message["seq"] for message in messages], [0, 1])

    def test_uart_read_error_is_reported_without_stopping_transmission(self):
        module, _ = load_main_module(iterations=51)
        serial = FailOnceReadSerial()
        module.configure_uart2 = lambda: serial
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            module.main()
        messages = [decode_frame(frame) for frame in serial.writes]

        self.assertIn("UART RX failed count=1", output.getvalue())
        self.assertEqual([message["type"] for message in messages], ["PING", "VISION"])

    def test_live_web_default_is_zero_creation_and_zero_socket_path(self):
        module, _ = load_main_module(iterations=1)
        created = []
        fake_sidecar_module = types.ModuleType("live_sidecar")

        class MustNotCreate:
            def __init__(self, *_args, **_kwargs):
                created.append(True)
                raise AssertionError("disabled web preview must not be created")

        fake_sidecar_module.LiveWebSidecar = MustNotCreate
        with patch.dict(sys.modules, {"live_sidecar": fake_sidecar_module}):
            messages = self.run_main(module, FakeSerial())

        self.assertFalse(module.LIVE_WEB_ENABLED)
        self.assertEqual(created, [])
        self.assertEqual([message["type"] for message in messages], ["PING"])

    def test_live_web_start_failure_keeps_existing_main_loop_running(self):
        module, _ = load_main_module(iterations=1)
        module.LIVE_WEB_ENABLED = True
        created = []
        fake_sidecar_module = types.ModuleType("live_sidecar")

        class FailingSidecar:
            def __init__(self, *_args, **_kwargs):
                created.append(self)
                self.stream_fault = "socket_start_failed:OSError"

            @staticmethod
            def start(**_kwargs):
                return False

            @staticmethod
            def poll(_now_ms):
                return 0

            @staticmethod
            def set_web_train_submission_ready(_ready):
                return None

            @staticmethod
            def set_web_train_availability(_can_submit, _reason):
                return None

            @staticmethod
            def take_web_train_intent():
                return None

            @staticmethod
            def close():
                return None

        fake_sidecar_module.LiveWebSidecar = FailingSidecar
        serial = FakeSerial()
        output = io.StringIO()
        with patch.dict(sys.modules, {"live_sidecar": fake_sidecar_module}):
            module.configure_uart2 = lambda: serial
            with contextlib.redirect_stdout(output):
                module.main()
        messages = [decode_frame(frame) for frame in serial.writes]

        self.assertEqual(len(created), 1)
        self.assertEqual([message["type"] for message in messages], ["PING"])
        self.assertIn("live web preview unavailable: socket_start_failed:OSError", output.getvalue())
        self.assertNotIn("live web preview started on port 8080", output.getvalue())

    def test_live_web_start_success_logs_port(self):
        module, _ = load_main_module(iterations=1)
        module.LIVE_WEB_ENABLED = True
        fake_sidecar_module = types.ModuleType("live_sidecar")

        class WorkingSidecar:
            stream_fault = None

            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def start(**_kwargs):
                return True

            @staticmethod
            def poll(_now_ms):
                return 0

            @staticmethod
            def set_web_train_submission_ready(_ready):
                return None

            @staticmethod
            def set_web_train_availability(_can_submit, _reason):
                return None

            @staticmethod
            def take_web_train_intent():
                return None

            @staticmethod
            def close():
                return None

        fake_sidecar_module.LiveWebSidecar = WorkingSidecar
        serial = FakeSerial()
        output = io.StringIO()
        with patch.dict(sys.modules, {"live_sidecar": fake_sidecar_module}):
            module.configure_uart2 = lambda: serial
            with contextlib.redirect_stdout(output):
                module.main()

        self.assertEqual(
            [message["type"] for message in [decode_frame(frame) for frame in serial.writes]],
            ["PING"],
        )
        self.assertIn("live web preview started on port 8080", output.getvalue())
        self.assertNotIn("live web preview unavailable:", output.getvalue())

    def test_mock_mode_ten_minute_accelerated_schedule(self):
        module, fake_time = load_main_module(iterations=60001)
        serial = FakeSerial()

        messages = self.run_main(module, serial)

        message_types = [message["type"] for message in messages]
        self.assertEqual(fake_time.now_ms, 600010)
        self.assertEqual(message_types.count("PING"), 601)
        self.assertEqual(message_types.count("VISION"), 1200)
        self.assertEqual(len(messages), 1801)
        self.assertEqual(
            [message["seq"] for message in messages], list(range(1801))
        )


class AITrustTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.module, _ = load_main_module(iterations=1)

    def test_handle_message_aitrust_valid_and_ready_boolean(self):
        authority = {
            "snapshot": {},
            "last_status_ms": None,
            "aitrust_snapshot": dict(self.module.UNKNOWN_AITRUST_SNAPSHOT),
            "last_aitrust_ms": None,
            "aitrust_seen": False,
            "aitrust_generation": 0,
        }
        ack_monitor = AckMonitor(1000)
        # 1. ready=1 -> bool True
        msg1 = {"type": "AITRUST", "seq": 5, "args": [1, 1, 0, 250]}
        self.module.handle_message(msg1, ack_monitor, 1000, authority)
        self.assertEqual(authority["aitrust_snapshot"]["version"], 1)
        self.assertIs(authority["aitrust_snapshot"]["ready"], True)
        self.assertEqual(authority["aitrust_snapshot"]["class_id"], 0)
        self.assertEqual(authority["aitrust_snapshot"]["vision_age_ms"], 250)
        self.assertEqual(authority["aitrust_snapshot"]["seq"], 5)
        self.assertEqual(authority["last_aitrust_ms"], 1000)
        self.assertTrue(authority["aitrust_seen"])
        self.assertEqual(authority["aitrust_generation"], 1)

        # 2. ready=0 -> bool False (explicitly boolean)
        msg2 = {"type": "AITRUST", "seq": 6, "args": [1, 0, 0, 2000]}
        self.module.handle_message(msg2, ack_monitor, 1500, authority)
        self.assertIs(authority["aitrust_snapshot"]["ready"], False)
        self.assertEqual(authority["aitrust_snapshot"]["class_id"], 0)
        self.assertEqual(authority["aitrust_snapshot"]["vision_age_ms"], 2000)
        self.assertEqual(authority["aitrust_snapshot"]["seq"], 6)
        self.assertEqual(authority["last_aitrust_ms"], 1500)
        self.assertEqual(authority["aitrust_generation"], 2)

    def test_handle_message_aitrust_telemetry_only_does_not_close_pending_ack(self):
        authority = {
            "snapshot": {},
            "last_status_ms": None,
            "aitrust_snapshot": dict(self.module.UNKNOWN_AITRUST_SNAPSHOT),
            "last_aitrust_ms": None,
            "aitrust_seen": False,
            "aitrust_generation": 0,
        }
        ack_monitor = AckMonitor(1000)
        ack_monitor.record(42, "SIGN", 1000)
        self.assertIn(42, ack_monitor.pending)

        msg = {"type": "AITRUST", "seq": 42, "args": [1, 1, 0, 250]}
        self.module.handle_message(msg, ack_monitor, 1050, authority)
        # Pending ACK for seq 42 must NOT be closed by AITRUST telemetry
        self.assertIn(42, ack_monitor.pending)

    def test_handle_message_aitrust_malformed_ignored_fail_closed(self):
        authority = {
            "snapshot": {},
            "last_status_ms": None,
            "aitrust_snapshot": dict(self.module.UNKNOWN_AITRUST_SNAPSHOT),
            "last_aitrust_ms": None,
            "aitrust_seen": False,
            "aitrust_generation": 0,
        }
        ack_monitor = AckMonitor(1000)
        malformed_cases = [
            {"type": "AITRUST", "seq": 1, "args": [2, 1, 0, 250]},  # unsupported version
            {"type": "AITRUST", "seq": 2, "args": [1, 1, 0]},       # 3 args
            {"type": "AITRUST", "seq": 3, "args": [1, 1, 0, 250, 0]}, # 5 args
            {"type": "AITRUST", "seq": 4, "args": [1, 2, 0, 250]},  # ready out of range
            {"type": "AITRUST", "seq": 5, "args": [1, 1, 3, 250]},  # class_id out of range
            {"type": "AITRUST", "seq": 6, "args": [1, 1, 0, 0x100000000]}, # age out of range
        ]
        for bad_msg in malformed_cases:
            with self.subTest(msg=bad_msg):
                self.module.handle_message(bad_msg, ack_monitor, 1000, authority)
                self.assertIsNone(authority["aitrust_snapshot"]["version"])
                self.assertEqual(authority["aitrust_generation"], 0)
                self.assertIsNone(authority["last_aitrust_ms"])

    def test_expire_aitrust_snapshot_timeout(self):
        authority = {
            "snapshot": {},
            "last_status_ms": None,
            "aitrust_snapshot": {"version": 1, "ready": True, "class_id": 0, "vision_age_ms": 250, "seq": 1},
            "last_aitrust_ms": 1000,
            "aitrust_seen": True,
            "aitrust_generation": 1,
        }
        # Under 1500 ms -> not expired
        self.assertFalse(self.module.expire_aitrust_snapshot(authority, 2499))
        self.assertIsNotNone(authority["last_aitrust_ms"])
        self.assertEqual(authority["aitrust_snapshot"]["version"], 1)

        # At 1500 ms -> expired
        self.assertTrue(self.module.expire_aitrust_snapshot(authority, 2500))
        self.assertIsNone(authority["last_aitrust_ms"])
        self.assertIsNone(authority["aitrust_snapshot"]["version"])

    def test_sign_status_snapshot_aitrust_and_link_online_coordination(self):
        controller = types.SimpleNamespace(status=lambda: {"state": "IDLE", "lesson_id": 1})
        authority = {
            "snapshot": {"ver": 1, "link_online": True},
            "last_status_ms": 1000,
            "status_seen": True,
            "aitrust_snapshot": {"version": 1, "ready": True, "class_id": 0, "vision_age_ms": 250, "seq": 1},
            "last_aitrust_ms": 1000,
            "aitrust_seen": True,
            "aitrust_generation": 5,
        }
        # 1. Fresh status + fresh aitrust
        status = self.module.sign_status_snapshot(controller, authority=authority)
        self.assertIs(status["link_online"], True)
        self.assertIs(status["aitrust"]["ready"], True)
        self.assertEqual(status["aitrust"]["class_id"], 0)
        self.assertEqual(status["aitrust"]["generation"], 5)
        self.assertIs(status["aitrust"]["expired"], False)

        # 2. Status expired (last_status_ms=None after seen), fresh aitrust
        authority["last_status_ms"] = None
        status = self.module.sign_status_snapshot(controller, authority=authority)
        self.assertIs(status["link_online"], False)
        self.assertIs(status["aitrust"]["ready"], True)

        # 3. AITRUST expired (last_aitrust_ms=None after seen)
        authority["last_aitrust_ms"] = None
        status = self.module.sign_status_snapshot(controller, authority=authority)
        self.assertIs(status["aitrust"]["expired"], True)
        self.assertEqual(status["aitrust"]["state"], "expired")

        # 4. AITRUST never reported
        authority["aitrust_seen"] = False
        authority["aitrust_generation"] = 0
        status = self.module.sign_status_snapshot(controller, authority=authority)
        self.assertEqual(status["aitrust"]["state"], "not_reported")

        # 5. Ready=0 conversion is strictly boolean False
        authority["last_aitrust_ms"] = 2000
        authority["aitrust_seen"] = True
        authority["aitrust_snapshot"] = {"version": 1, "ready": False, "class_id": 0, "vision_age_ms": 500, "seq": 2}
        status = self.module.sign_status_snapshot(controller, authority=authority)
        self.assertIs(status["aitrust"]["ready"], False)
        self.assertEqual(status["aitrust"]["class_id"], 0)

        # 6. Read-instant calculation: now_ms elapsed >= 1500 ms immediately expires link_online and aitrust
        authority["last_status_ms"] = 1000
        authority["last_aitrust_ms"] = 1000
        authority["snapshot"] = {"link_online": True}
        authority["aitrust_snapshot"] = {"version": 1, "ready": True, "class_id": 0, "vision_age_ms": 100, "seq": 3}
        authority["status_seen"] = True
        authority["aitrust_seen"] = True
        status = self.module.sign_status_snapshot(controller, authority=authority, now_ms=2500)
        self.assertIs(status["link_online"], False)
        self.assertIs(status["aitrust"]["expired"], True)
        self.assertEqual(status["aitrust"]["state"], "expired")


if __name__ == "__main__":
    unittest.main()
