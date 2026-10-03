"""Offline tests for maixcam2/supported_class_mock_probe.py.

These tests never touch hardware: no serial port is enumerated, opened or
written, and the real ``maix`` runtime is never imported.  Device identity,
live authorisation and run-time abort behaviour are exercised with fake
modules and fake serial objects.

The assertions target behaviour and safety contracts, not literal source text.
"""

import builtins
import contextlib
import hashlib
import importlib.util
import inspect
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIXCAM2_ROOT = PROJECT_ROOT / "maixcam2"
sys.path.insert(0, str(MAIXCAM2_ROOT))

import link_monitor  # noqa: E402
import protocol  # noqa: E402
import supported_class_mock_probe as probe  # noqa: E402
from protocol import decode_frame, encode_frame  # noqa: E402


PRODUCTION_FILES = (
    "main.py",
    "protocol.py",
    "link_monitor.py",
    "target_tracker.py",
    "vision_source.py",
)
PROBE_PATH = MAIXCAM2_ROOT / "supported_class_mock_probe.py"
FIXED_TAIL = (320, 240, 80, 120, 96)
WRITE_MODES = ("w", "a", "x", "+")
FULL_RUN_FRAMES = 30  # 10 s at PING 1 Hz + VISION 2 Hz


def production_digests():
    digests = {}
    for name in PRODUCTION_FILES:
        digests[name] = hashlib.sha256((MAIXCAM2_ROOT / name).read_bytes()).hexdigest()
    return digests


class SandboxGuard:
    """Block file writes and forbidden imports; simulate a PC unless told otherwise."""

    def __init__(self, allow_maix=False):
        self.allow_maix = allow_maix
        self.write_attempts = []
        self.imports = []
        self._real_open = builtins.open
        self._real_import = builtins.__import__

    def _open(self, file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in WRITE_MODES):
            self.write_attempts.append((str(file), mode))
            raise AssertionError("probe attempted a write open: {}".format(file))
        return self._real_open(file, mode, *args, **kwargs)

    def _import(self, name, *args, **kwargs):
        self.imports.append(name)
        root = name.split(".")[0]
        if root in ("serial", "pyserial") or "scs0009" in name:
            raise AssertionError("probe attempted a forbidden import: {}".format(name))
        if root == "maix" and not self.allow_maix:
            raise ImportError("no maix runtime on this host")
        return self._real_import(name, *args, **kwargs)

    def imported_maix(self):
        return any(item.split(".")[0] == "maix" for item in self.imports)

    def __enter__(self):
        builtins.open = self._open
        builtins.__import__ = self._import
        return self

    def __exit__(self, *exc_info):
        builtins.open = self._real_open
        builtins.__import__ = self._real_import
        return False


def make_fake_maix(device_id="maixcam2", raises=None, omit_device_id=False,
                   omit_sys=False):
    """Build a fake ``maix`` package exposing only ``maix.sys.device_id``."""
    maix_module = types.ModuleType("maix")
    if omit_sys:
        return {"maix": maix_module}
    sys_module = types.ModuleType("maix.sys")
    if not omit_device_id:
        def device_id_fn():
            if raises is not None:
                raise raises
            return device_id

        sys_module.device_id = device_id_fn
    maix_module.sys = sys_module
    return {"maix": maix_module, "maix.sys": sys_module}


@contextlib.contextmanager
def fake_maix_installed(**kwargs):
    modules = make_fake_maix(**kwargs)
    saved = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        yield
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


class FakeClock:
    def __init__(self):
        self.now = 0

    def ticks_ms(self):
        return self.now

    def sleep_ms(self, duration_ms):
        self.now += duration_ms

    @staticmethod
    def ticks_diff(previous_ms, now_ms):
        return now_ms - previous_ms


class EchoAckSerial:
    """Fake UART that ACKs every frame it receives.  Never touches hardware."""

    def __init__(self, status=0):
        self.writes = []
        self.status = status
        self._pending = bytearray()

    def write(self, frame):
        self.writes.append(frame)
        message = decode_frame(frame)
        self._pending.extend(encode_frame("ACK", message["seq"], self.status))
        return len(frame)

    def read(self):
        if not self._pending:
            return b""
        data = bytes(self._pending)
        self._pending = bytearray()
        return data


class SilentSerial:
    """Fake UART that never answers, so pending frames time out."""

    def __init__(self):
        self.writes = []

    def write(self, frame):
        self.writes.append(frame)
        return len(frame)

    @staticmethod
    def read():
        return b""


class RaisingReadSerial(EchoAckSerial):
    def __init__(self, fail_after_reads=3):
        super().__init__()
        self.fail_after_reads = fail_after_reads
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.reads > self.fail_after_reads:
            raise OSError("simulated UART read failure")
        return super().read()


class PartialWriteSerial(EchoAckSerial):
    def __init__(self, fail_on_write=4):
        super().__init__()
        self.fail_on_write = fail_on_write

    def write(self, frame):
        if len(self.writes) + 1 == self.fail_on_write:
            self.writes.append(frame)
            return max(0, len(frame) - 3)
        return super().write(frame)


class MalformedAckSerial(EchoAckSerial):
    """Answers one frame with an ACK carrying the wrong argument count."""

    def __init__(self, malformed_on_write=3):
        super().__init__()
        self.malformed_on_write = malformed_on_write

    def write(self, frame):
        message = decode_frame(frame)
        self.writes.append(frame)
        if len(self.writes) == self.malformed_on_write:
            self._pending.extend(encode_frame("ACK", message["seq"]))
        else:
            self._pending.extend(encode_frame("ACK", message["seq"], 0))
        return len(frame)


class RejectedAckSerial(EchoAckSerial):
    def __init__(self, reject_on_write=3):
        super().__init__()
        self.reject_on_write = reject_on_write

    def write(self, frame):
        message = decode_frame(frame)
        self.writes.append(frame)
        status = 1 if len(self.writes) == self.reject_on_write else 0
        self._pending.extend(encode_frame("ACK", message["seq"], status))
        return len(frame)


class UnexpectedAckSerial(EchoAckSerial):
    def __init__(self, extra_on_write=3):
        super().__init__()
        self.extra_on_write = extra_on_write

    def write(self, frame):
        message = decode_frame(frame)
        self.writes.append(frame)
        if len(self.writes) == self.extra_on_write:
            self._pending.extend(encode_frame("ACK", 60000, 0))
        else:
            self._pending.extend(encode_frame("ACK", message["seq"], 0))
        return len(frame)


class TimestampingSilentSerial:
    """Never ACKs.  Records the clock value of every write and counts writes
    that happen at or after the ACK timeout boundary.

    It does not raise, because write_tracked swallows exceptions and would turn
    a hard failure into a plain tx_fail abort, masking the ordering defect.
    """

    def __init__(self, clock, boundary_ms=None):
        self.clock = clock
        self.boundary_ms = (
            probe.ACK_TIMEOUT_MS if boundary_ms is None else boundary_ms
        )
        self.writes = []
        self.write_times = []
        self.writes_at_or_after_boundary = 0

    def write(self, frame):
        if self.clock.now >= self.boundary_ms:
            self.writes_at_or_after_boundary += 1
        self.writes.append(frame)
        self.write_times.append(self.clock.now)
        return len(frame)

    @staticmethod
    def read():
        return b""


def missing_selection_path():
    return str(Path(tempfile.gettempdir()) / "supported_class_mock_probe_absent.txt")


@contextlib.contextmanager
def no_selection_file():
    original = probe.selection_file_path
    probe.selection_file_path = lambda script_path=None: missing_selection_path()
    try:
        yield
    finally:
        probe.selection_file_path = original


def live_argv(class_id, live_class=None):
    return [
        "--class",
        str(class_id),
        "--live",
        "--live-ack",
        probe.LIVE_ACK_TOKEN,
        "--live-class",
        str(class_id if live_class is None else live_class),
    ]


def authorised_request(class_id, live_class=None):
    return probe.resolve_request(
        argv=live_argv(class_id, live_class),
        environ={},
        selection_text=None,
        device_is_maixcam2=True,
        device_detail="device_id='maixcam2'",
    )


def run_live(request, serial, run_seconds=10):
    clock = FakeClock()
    return probe.run_live_with_serial(
        request,
        serial,
        now_ms_fn=clock.ticks_ms,
        sleep_ms_fn=clock.sleep_ms,
        ticks_diff=clock.ticks_diff,
        run_seconds=run_seconds,
        printer=lambda *args, **kwargs: None,
    )


class AllowedClassTest(unittest.TestCase):
    def test_39_41_65_accepted(self):
        for class_id in (39, 41, 65):
            self.assertEqual(probe.coerce_class_id(class_id), class_id)
            self.assertEqual(probe.coerce_class_id(str(class_id)), class_id)

    def test_allow_list_is_exactly_three_classes(self):
        self.assertEqual(probe.ALLOWED_CLASS_IDS, (39, 41, 65))

    def test_payload_for_each_class(self):
        expected_actions = {
            39: "CYLINDRICAL_GRASP",
            41: "POWER_GRASP",
            65: "PRECISION_GRASP",
        }
        for class_id in (39, 41, 65):
            payload = probe.build_payload(class_id)
            self.assertEqual(payload[0], class_id)
            self.assertEqual(payload[1:], FIXED_TAIL)
            self.assertEqual(
                probe.CLASS_ACTION_NAMES[class_id], expected_actions[class_id]
            )

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(probe.coerce_class_id(" 39 "), 39)

    def test_one_unchanged_script_serves_all_three_classes(self):
        before = hashlib.sha256(PROBE_PATH.read_bytes()).hexdigest()
        for class_id in (39, 41, 65):
            request = probe.resolve_request(
                argv=["--class", str(class_id)], environ={}, selection_text=None
            )
            self.assertEqual(request.class_id, class_id)
            self.assertFalse(request.live)
        after = hashlib.sha256(PROBE_PATH.read_bytes()).hexdigest()
        self.assertEqual(before, after)


class RejectedClassTest(unittest.TestCase):
    ILLEGAL = (
        None, "", "   ", "3", 3, "0", 0, "-1", -39, "+39", "39.0", 39.0,
        "40", "64", "66", "65535", "65536", "abc", "3 9", "0x27", "３９",
        True, False, [39], (39,), {"class": 39},
    )

    def test_every_illegal_class_is_refused(self):
        for value in self.ILLEGAL:
            with self.subTest(value=repr(value)):
                with self.assertRaises(probe.SelectionError):
                    probe.coerce_class_id(value)

    def test_build_payload_refuses_illegal_class(self):
        for value in ("3", 0, None, 40, True):
            with self.subTest(value=repr(value)):
                with self.assertRaises(probe.SelectionError):
                    probe.build_payload(value)

    def test_missing_class_is_refused_with_zero_hardware_access(self):
        with self.assertRaises(probe.SelectionError):
            probe.resolve_request(argv=[], environ={}, selection_text=None)

    def test_main_without_selection_exits_nonzero_and_sends_nothing(self):
        digests_before = production_digests()
        buffer = io.StringIO()
        with no_selection_file(), SandboxGuard() as guard:
            with contextlib.redirect_stdout(buffer):
                code = probe.main(argv=[], environ={})
        self.assertEqual(code, 2)
        self.assertIn("selection refused", buffer.getvalue())
        self.assertNotIn("$VISION", buffer.getvalue())
        self.assertEqual(guard.write_attempts, [])
        self.assertEqual(digests_before, production_digests())

    def test_main_with_class_3_is_refused(self):
        buffer = io.StringIO()
        with no_selection_file(), SandboxGuard():
            with contextlib.redirect_stdout(buffer):
                code = probe.main(argv=["--class", "3"], environ={})
        self.assertEqual(code, 2)
        self.assertIn("not allowed", buffer.getvalue())
        self.assertNotIn("$VISION", buffer.getvalue())

    def test_unknown_argument_is_refused(self):
        buffer = io.StringIO()
        with no_selection_file():
            with contextlib.redirect_stdout(buffer):
                code = probe.main(argv=["--confidence", "50"], environ={})
        self.assertEqual(code, 2)


class FixedFieldsTest(unittest.TestCase):
    def test_constants_match_the_plan(self):
        self.assertEqual(probe.FIXED_CENTER_X, 320)
        self.assertEqual(probe.FIXED_CENTER_Y, 240)
        self.assertEqual(probe.FIXED_WIDTH, 80)
        self.assertEqual(probe.FIXED_HEIGHT, 120)
        self.assertEqual(probe.FIXED_CONFIDENCE, 96)

    def test_build_payload_takes_only_the_class(self):
        signature = inspect.signature(probe.build_payload)
        self.assertEqual(list(signature.parameters), ["class_id"])

    def test_no_public_entry_point_accepts_geometry_or_confidence(self):
        forbidden = {
            "confidence", "width", "height", "center_x", "center_y", "payload", "conf",
        }
        for name, member in vars(probe).items():
            if not inspect.isfunction(member) or member.__module__ != probe.__name__:
                continue
            parameters = set(inspect.signature(member).parameters)
            self.assertEqual(
                parameters & forbidden,
                set(),
                "{} exposes an overridable payload field".format(name),
            )

    def test_tail_is_identical_for_every_allowed_class(self):
        tails = {probe.build_payload(class_id)[1:] for class_id in (39, 41, 65)}
        self.assertEqual(tails, {FIXED_TAIL})

    def test_every_sent_vision_frame_carries_the_fixed_fields(self):
        for class_id in (39, 41, 65):
            serial = EchoAckSerial()
            run_live(authorised_request(class_id), serial)
            vision = [
                decode_frame(frame)
                for frame in serial.writes
                if decode_frame(frame)["type"] == "VISION"
            ]
            self.assertTrue(vision)
            for message in vision:
                self.assertEqual(message["args"], [class_id, 320, 240, 80, 120, 96])


class DeviceIdentityTest(unittest.TestCase):
    """Only a positively identified MaixCAM2 may go live."""

    def test_no_maix_runtime_is_not_a_maixcam2(self):
        with SandboxGuard():
            ok, detail = probe.detect_device_identity()
        self.assertFalse(ok)
        self.assertIn("absent", detail)

    def test_maix_without_sys_submodule_is_refused(self):
        with fake_maix_installed(omit_sys=True), SandboxGuard(allow_maix=True):
            ok, _ = probe.detect_device_identity()
        self.assertFalse(ok)

    def test_missing_device_id_api_is_refused(self):
        with fake_maix_installed(omit_device_id=True), SandboxGuard(allow_maix=True):
            ok, detail = probe.detect_device_identity()
        self.assertFalse(ok)
        self.assertIn("unavailable", detail)

    def test_device_id_raising_is_refused(self):
        with fake_maix_installed(raises=RuntimeError("boom")), SandboxGuard(allow_maix=True):
            ok, detail = probe.detect_device_identity()
        self.assertFalse(ok)
        self.assertIn("raised", detail)

    def test_wrong_device_name_is_refused(self):
        for wrong in ("maixcam", "maixcam2 ", "MaixCAM2", "", None, 2, "maixcam3"):
            with self.subTest(device_id=repr(wrong)):
                with fake_maix_installed(device_id=wrong), SandboxGuard(allow_maix=True):
                    ok, detail = probe.detect_device_identity()
                self.assertFalse(ok)
                self.assertIn("expected", detail)

    def test_only_maixcam2_is_accepted(self):
        with fake_maix_installed(device_id="maixcam2"), SandboxGuard(allow_maix=True):
            ok, detail = probe.detect_device_identity()
        self.assertTrue(ok)
        self.assertIn("maixcam2", detail)

    def test_unidentified_device_never_reaches_the_uart(self):
        def explode(request):
            raise AssertionError("run_on_maix must not be called without a MaixCAM2")

        original = probe.run_on_maix
        probe.run_on_maix = explode
        try:
            for kwargs in (
                {"device_id": "maixcam"},
                {"omit_device_id": True},
                {"raises": RuntimeError("boom")},
                {"omit_sys": True},
            ):
                with self.subTest(fake=kwargs):
                    buffer = io.StringIO()
                    with fake_maix_installed(**kwargs), no_selection_file():
                        with SandboxGuard(allow_maix=True) as guard:
                            with contextlib.redirect_stdout(buffer):
                                code = probe.main(argv=live_argv(39), environ={})
                    self.assertEqual(code, 0)
                    self.assertIn('"mode": "dry_run"', buffer.getvalue())
                    self.assertIn('"hardware_accessed": false', buffer.getvalue())
                    self.assertEqual(guard.write_attempts, [])
        finally:
            probe.run_on_maix = original

    def test_identified_device_with_full_tokens_reaches_the_live_path(self):
        calls = []

        def capture(request):
            calls.append(request)
            return probe.run_live_with_serial(
                request,
                EchoAckSerial(),
                now_ms_fn=FakeClock().ticks_ms,
                sleep_ms_fn=lambda ms: None,
                run_seconds=0,
                printer=lambda *a, **k: None,
            )

        original = probe.run_on_maix
        probe.run_on_maix = capture
        try:
            buffer = io.StringIO()
            with fake_maix_installed(device_id="maixcam2"), no_selection_file():
                with SandboxGuard(allow_maix=True):
                    with contextlib.redirect_stdout(buffer):
                        code = probe.main(argv=live_argv(41), environ={})
        finally:
            probe.run_on_maix = original
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].class_id, 41)
        # run_seconds=0 sends nothing, so the contract says ABORTED, not PASS.
        self.assertEqual(code, 1)
        self.assertIn('"outcome": "ABORTED"', buffer.getvalue())


class LiveAuthorisationTest(unittest.TestCase):
    def test_no_tokens_means_no_live(self):
        request = probe.resolve_request(
            argv=["--class", "39"], environ={}, selection_text=None,
            device_is_maixcam2=True,
        )
        self.assertFalse(request.live)
        self.assertIn("no live authorisation", request.live_refused_reason)

    def test_enable_token_alone_is_not_enough(self):
        request = probe.resolve_request(
            argv=["--class", "39", "--live"], environ={}, selection_text=None,
            device_is_maixcam2=True,
        )
        self.assertFalse(request.live)

    def test_ack_token_alone_is_not_enough(self):
        request = probe.resolve_request(
            argv=["--class", "39", "--live-ack", probe.LIVE_ACK_TOKEN],
            environ={}, selection_text=None, device_is_maixcam2=True,
        )
        self.assertFalse(request.live)

    def test_wrong_ack_token_is_refused(self):
        request = probe.resolve_request(
            argv=["--class", "39", "--live", "--live-ack", "yes",
                  "--live-class", "39"],
            environ={}, selection_text=None, device_is_maixcam2=True,
        )
        self.assertFalse(request.live)

    def test_full_tokens_without_a_maixcam2_are_refused(self):
        request = probe.resolve_request(
            argv=live_argv(39), environ={}, selection_text=None,
            device_is_maixcam2=False, device_detail="maix runtime absent",
        )
        self.assertFalse(request.live)
        self.assertIn("not identified", request.live_refused_reason)

    def test_full_tokens_on_a_maixcam2_are_accepted(self):
        request = authorised_request(65)
        self.assertTrue(request.live)
        self.assertIsNone(request.live_refused_reason)

    def test_no_live_token_has_a_default(self):
        parsed = probe.parse_arguments([])
        self.assertIsNone(parsed["live"])
        self.assertIsNone(parsed["live_ack"])
        self.assertIsNone(parsed["live_class"])


class PerRoundConfirmationTest(unittest.TestCase):
    """live_class must be restated for the class of the current round."""

    def test_missing_live_class_is_refused(self):
        request = probe.resolve_request(
            argv=["--class", "39", "--live", "--live-ack", probe.LIVE_ACK_TOKEN],
            environ={}, selection_text=None, device_is_maixcam2=True,
        )
        self.assertFalse(request.live)
        self.assertIn("live_class missing", request.live_refused_reason)

    def test_stale_live_class_after_changing_class_is_refused(self):
        first = authorised_request(39)
        self.assertTrue(first.live)
        second = probe.resolve_request(
            argv=live_argv(41, live_class=39), environ={}, selection_text=None,
            device_is_maixcam2=True,
        )
        self.assertFalse(second.live)
        self.assertIn("stale authorisation", second.live_refused_reason)

    def test_stale_live_class_sends_nothing(self):
        buffer = io.StringIO()
        with fake_maix_installed(device_id="maixcam2"), no_selection_file():
            with SandboxGuard(allow_maix=True) as guard:
                with contextlib.redirect_stdout(buffer):
                    code = probe.main(argv=live_argv(41, live_class=39), environ={})
        self.assertEqual(code, 0)
        self.assertIn('"mode": "dry_run"', buffer.getvalue())
        self.assertIn('"frames_sent": 0', buffer.getvalue())
        self.assertIn("stale authorisation", buffer.getvalue())
        self.assertEqual(guard.write_attempts, [])

    def test_stale_live_class_in_the_selection_file_is_refused(self):
        text = "41\nlive=ENABLE\nlive_ack={}\nlive_class=39\n".format(
            probe.LIVE_ACK_TOKEN
        )
        request = probe.resolve_request(
            argv=[], environ={}, selection_text=text, device_is_maixcam2=True,
        )
        self.assertFalse(request.live)
        self.assertIn("stale authorisation", request.live_refused_reason)

    def test_matching_live_class_in_the_selection_file_is_accepted(self):
        for class_id in (39, 41, 65):
            text = "{}\nlive=ENABLE\nlive_ack={}\nlive_class={}\n".format(
                class_id, probe.LIVE_ACK_TOKEN, class_id
            )
            request = probe.resolve_request(
                argv=[], environ={}, selection_text=text, device_is_maixcam2=True,
            )
            self.assertTrue(request.live)
            self.assertEqual(request.class_id, class_id)

    def test_illegal_live_class_is_refused(self):
        for bad in ("3", "0", "abc", "40", "39.0"):
            with self.subTest(live_class=bad):
                request = probe.resolve_request(
                    argv=live_argv(39, live_class=bad), environ={},
                    selection_text=None, device_is_maixcam2=True,
                )
                self.assertFalse(request.live)
                self.assertIn("live_class rejected", request.live_refused_reason)


class DryRunTest(unittest.TestCase):
    def test_pc_dry_run_opens_nothing(self):
        buffer = io.StringIO()
        with no_selection_file(), SandboxGuard() as guard:
            with contextlib.redirect_stdout(buffer):
                code = probe.main(argv=["--class", "39"], environ={})
        self.assertEqual(code, 0)
        self.assertEqual(guard.write_attempts, [])
        payload = buffer.getvalue()
        self.assertIn('"mode": "dry_run"', payload)
        self.assertIn('"outcome": "DRY_RUN"', payload)
        self.assertIn('"hardware_accessed": false', payload)
        self.assertIn('"serial_opened": false', payload)
        self.assertIn('"frames_sent": 0', payload)

    def test_dry_run_preview_uses_the_production_codec(self):
        preview = probe.preview_frames(65)
        self.assertEqual(
            decode_frame(preview["vision"] + "\r\n")["args"],
            [65, 320, 240, 80, 120, 96],
        )
        self.assertEqual(decode_frame(preview["ping"] + "\r\n")["type"], "PING")

    def test_dry_run_never_imports_a_serial_backend(self):
        with no_selection_file(), SandboxGuard() as guard:
            with contextlib.redirect_stdout(io.StringIO()):
                probe.main(argv=["--class", "41"], environ={})
        self.assertNotIn("serial", [item.split(".")[0] for item in guard.imports])

    def test_report_declares_no_servo_capability(self):
        request = probe.resolve_request(
            argv=["--class", "39"], environ={}, selection_text=None
        )
        report = probe.run_dry(request)
        self.assertFalse(report["servo_capability"])
        self.assertFalse(report["hardware_accessed"])
        self.assertEqual(report["expected_titan_pose"], "NOT_CONFIGURED")
        self.assertEqual(report["expected_titan_actionable"], 0)
        self.assertIsNone(report["abort_reason"])


class SelectionFileTest(unittest.TestCase):
    def test_bare_number_line(self):
        self.assertEqual(probe.parse_selection_text("41\n"), {"class": "41"})

    def test_key_value_lines_with_comments(self):
        text = (
            "# round A\nclass=39\nlive=ENABLE\n"
            "live_ack=SERVO_DISCONNECTED_NO_5V\nlive_class=39\n"
        )
        self.assertEqual(
            probe.parse_selection_text(text),
            {
                "class": "39",
                "live": "ENABLE",
                "live_ack": "SERVO_DISCONNECTED_NO_5V",
                "live_class": "39",
            },
        )

    def test_duplicate_key_is_refused(self):
        with self.assertRaises(probe.SelectionError):
            probe.parse_selection_text("class=39\nclass=41\n")

    def test_unknown_key_is_refused(self):
        with self.assertRaises(probe.SelectionError):
            probe.parse_selection_text("confidence=50\n")

    def test_selection_file_class_is_validated(self):
        with self.assertRaises(probe.SelectionError):
            probe.resolve_request(argv=[], environ={}, selection_text="class=3\n")

    def test_selection_file_drives_all_three_rounds(self):
        for class_id in (39, 41, 65):
            request = probe.resolve_request(
                argv=[], environ={}, selection_text="{}\n".format(class_id)
            )
            self.assertEqual(request.class_id, class_id)
            self.assertFalse(request.live)

    def test_command_line_wins_over_selection_file(self):
        request = probe.resolve_request(
            argv=["--class", "65"], environ={}, selection_text="39\n"
        )
        self.assertEqual(request.class_id, 65)

    def test_environment_variable_is_validated_too(self):
        with self.assertRaises(probe.SelectionError):
            probe.resolve_request(
                argv=[], environ={probe.CLASS_ENV_NAME: "3"}, selection_text=None
            )

    def test_read_selection_file_is_read_only_and_tolerates_absence(self):
        text, source = probe.read_selection_file(missing_selection_path())
        self.assertIsNone(text)
        self.assertIsNone(source)


class ProductionModuleReuseTest(unittest.TestCase):
    def test_codec_objects_are_the_production_ones(self):
        self.assertIs(probe.encode_frame, protocol.encode_frame)
        self.assertIs(probe.StreamParser, protocol.StreamParser)
        self.assertIs(probe.AckMonitor, link_monitor.AckMonitor)
        self.assertIs(probe.write_tracked, link_monitor.write_tracked)

    def test_statistics_come_from_the_production_monitor(self):
        serial = EchoAckSerial()
        report = run_live(authorised_request(39), serial)
        reference = link_monitor.AckMonitor(probe.ACK_TIMEOUT_MS).summary()
        for field in reference.split():
            key = field.split("=")[0]
            self.assertIn(key + "=", report["link_stats"])

    def test_probe_is_not_one_of_the_production_files(self):
        self.assertNotIn(PROBE_PATH.name, PRODUCTION_FILES)
        self.assertTrue(PROBE_PATH.is_file())


class HealthyLiveRunTest(unittest.TestCase):
    def test_ten_second_run_passes_with_the_plan_cadence(self):
        serial = EchoAckSerial()
        report = run_live(authorised_request(39), serial)
        self.assertEqual(report["outcome"], probe.OUTCOME_PASS)
        self.assertIsNone(report["abort_reason"])
        self.assertEqual(report["vision_sent"], 20)
        self.assertEqual(report["ping_sent"], 10)
        self.assertEqual(report["frames_sent"], FULL_RUN_FRAMES)
        self.assertEqual(report["rx_errors"], 0)
        self.assertTrue(report["hardware_accessed"])
        self.assertLessEqual(report["backlog"], 1)
        self.assertEqual(
            set(report["error_counters"].values()), {0},
        )

    def test_report_contains_the_required_fields(self):
        report = run_live(authorised_request(65), EchoAckSerial())
        for field in ("outcome", "abort_reason", "hardware_accessed",
                      "link_stats", "rx_errors"):
            self.assertIn(field, report)

    def test_live_run_leaves_production_files_untouched(self):
        digests_before = production_digests()
        with SandboxGuard() as guard:
            run_live(authorised_request(65), EchoAckSerial())
        self.assertEqual(guard.write_attempts, [])
        self.assertEqual(digests_before, production_digests())


class FaultInjectionTest(unittest.TestCase):
    """Every injected fault must stop the run and report ABORTED."""

    def assert_aborted(self, report, serial, needle):
        self.assertEqual(report["outcome"], probe.OUTCOME_ABORTED)
        self.assertIsNotNone(report["abort_reason"])
        self.assertIn(needle, report["abort_reason"])
        self.assertTrue(report["hardware_accessed"])
        self.assertIn("link_stats", report)
        self.assertIn("rx_errors", report)
        self.assertLess(
            len(serial.writes),
            FULL_RUN_FRAMES,
            "probe kept sending after the abort",
        )

    def test_uart_read_exception_aborts(self):
        serial = RaisingReadSerial(fail_after_reads=3)
        report = run_live(authorised_request(39), serial)
        self.assert_aborted(report, serial, "serial.read raised")
        self.assertGreaterEqual(report["rx_errors"], 1)

    def test_partial_write_aborts(self):
        serial = PartialWriteSerial(fail_on_write=4)
        report = run_live(authorised_request(39), serial)
        self.assert_aborted(report, serial, "write failed")
        self.assertGreaterEqual(report["error_counters"]["tx_fail"], 1)

    def test_malformed_ack_aborts(self):
        serial = MalformedAckSerial(malformed_on_write=3)
        report = run_live(authorised_request(41), serial)
        self.assert_aborted(report, serial, "malformed ACK")
        self.assertGreaterEqual(report["error_counters"]["malformed"], 1)

    def test_rejected_ack_aborts(self):
        serial = RejectedAckSerial(reject_on_write=3)
        report = run_live(authorised_request(41), serial)
        self.assert_aborted(report, serial, "rejected")
        self.assertGreaterEqual(report["error_counters"]["rejected"], 1)

    def test_unexpected_ack_aborts(self):
        serial = UnexpectedAckSerial(extra_on_write=3)
        report = run_live(authorised_request(65), serial)
        self.assert_aborted(report, serial, "unexpected")
        self.assertGreaterEqual(report["error_counters"]["unexpected"], 1)

    def test_ack_timeout_aborts(self):
        serial = SilentSerial()
        report = run_live(authorised_request(65), serial)
        self.assert_aborted(report, serial, "timeout")
        self.assertGreaterEqual(report["error_counters"]["timeout"], 1)

    def test_abort_stops_further_frames(self):
        serial = RaisingReadSerial(fail_after_reads=2)
        report = run_live(authorised_request(39), serial)
        frames_at_abort = len(serial.writes)
        self.assertEqual(report["outcome"], probe.OUTCOME_ABORTED)
        # The serial object is untouched after the report is built.
        self.assertEqual(len(serial.writes), frames_at_abort)
        self.assertLess(frames_at_abort, FULL_RUN_FRAMES)

    def test_main_returns_nonzero_on_abort(self):
        def aborting_run(request):
            return probe.run_live_with_serial(
                request,
                SilentSerial(),
                now_ms_fn=FakeClock().ticks_ms,
                sleep_ms_fn=lambda ms: None,
                run_seconds=0,
                printer=lambda *a, **k: None,
            )

        original = probe.run_on_maix
        probe.run_on_maix = aborting_run
        try:
            buffer = io.StringIO()
            with fake_maix_installed(device_id="maixcam2"), no_selection_file():
                with SandboxGuard(allow_maix=True):
                    with contextlib.redirect_stdout(buffer):
                        code = probe.main(argv=live_argv(39), environ={})
        finally:
            probe.run_on_maix = original
        self.assertEqual(code, 1)
        self.assertIn('"outcome": "ABORTED"', buffer.getvalue())
        self.assertNotIn('"outcome": "PASS"', buffer.getvalue())

    def test_no_fault_free_run_is_ever_reported_as_pass_with_errors(self):
        for serial in (
            RaisingReadSerial(fail_after_reads=3),
            PartialWriteSerial(fail_on_write=4),
            MalformedAckSerial(malformed_on_write=3),
            RejectedAckSerial(reject_on_write=3),
            UnexpectedAckSerial(extra_on_write=3),
            SilentSerial(),
        ):
            with self.subTest(serial=type(serial).__name__):
                report = run_live(authorised_request(39), serial)
                self.assertNotEqual(report["outcome"], probe.OUTCOME_PASS)


class TimeoutBoundaryRegressionTest(unittest.TestCase):
    """A frame that has timed out must stop the round before any further write.

    Deterministic setup: FakeClock advances only through sleep_ms, the serial
    never answers, so seq 0 is sent at t=0 and reaches ACK_TIMEOUT_MS at exactly
    t=1000 ms.  The cadence would schedule a PING (last sent t=0) and a VISION
    (last sent t=500) at t=1000.  Neither may be written.
    """

    BOUNDARY_MS = probe.ACK_TIMEOUT_MS
    # Writes scheduled strictly before the boundary: PING@0, VISION@0, VISION@500.
    EXPECTED_WRITE_TIMES = [0, 0, 500]

    def _run(self, run_seconds):
        clock = FakeClock()
        serial = TimestampingSilentSerial(clock)
        report = probe.run_live_with_serial(
            authorised_request(39),
            serial,
            now_ms_fn=clock.ticks_ms,
            sleep_ms_fn=clock.sleep_ms,
            ticks_diff=clock.ticks_diff,
            run_seconds=run_seconds,
            printer=lambda *args, **kwargs: None,
        )
        return report, serial, clock

    def test_zero_writes_at_or_after_the_timeout_boundary(self):
        report, serial, _ = self._run(run_seconds=10)
        self.assertEqual(report["outcome"], probe.OUTCOME_ABORTED)
        self.assertIn("timeout", report["abort_reason"])
        self.assertEqual(
            serial.writes_at_or_after_boundary,
            0,
            "probe wrote {} frame(s) at or after t={} ms; write times were {}".format(
                serial.writes_at_or_after_boundary,
                self.BOUNDARY_MS,
                serial.write_times,
            ),
        )

    def test_exact_write_schedule_before_the_boundary(self):
        report, serial, _ = self._run(run_seconds=10)
        self.assertEqual(serial.write_times, self.EXPECTED_WRITE_TIMES)
        self.assertEqual(len(serial.writes), len(self.EXPECTED_WRITE_TIMES))
        self.assertEqual(report["frames_sent"], len(self.EXPECTED_WRITE_TIMES))
        self.assertEqual(report["ping_sent"], 1)
        self.assertEqual(report["vision_sent"], 2)

    def test_scheduled_frames_at_the_boundary_are_never_written(self):
        _, serial, _ = self._run(run_seconds=10)
        # The cadence demanded a PING and a VISION at exactly t=1000 ms.
        self.assertNotIn(self.BOUNDARY_MS, serial.write_times)
        self.assertLess(max(serial.write_times), self.BOUNDARY_MS)

    def test_stop_point_does_not_depend_on_the_remaining_budget(self):
        counts = []
        for run_seconds in (2, 10, 30):
            report, serial, _ = self._run(run_seconds=run_seconds)
            self.assertEqual(report["outcome"], probe.OUTCOME_ABORTED)
            self.assertEqual(serial.writes_at_or_after_boundary, 0)
            counts.append(tuple(serial.write_times))
        self.assertEqual(
            counts,
            [tuple(self.EXPECTED_WRITE_TIMES)] * 3,
            "the abort point moved with the run budget",
        )

    def test_timeout_counter_is_reported(self):
        report, _, _ = self._run(run_seconds=10)
        self.assertGreaterEqual(report["error_counters"]["timeout"], 1)
        self.assertIn("timeout=", report["link_stats"])
        self.assertEqual(report["rx_errors"], 0)
        self.assertTrue(report["hardware_accessed"])

    def test_healthy_link_is_unaffected_by_the_pre_send_gate(self):
        serial = EchoAckSerial()
        report = run_live(authorised_request(39), serial)
        self.assertEqual(report["outcome"], probe.OUTCOME_PASS)
        self.assertEqual(report["frames_sent"], FULL_RUN_FRAMES)
        self.assertEqual(report["error_counters"]["timeout"], 0)


class ImportPurityTest(unittest.TestCase):
    def test_import_has_no_side_effects(self):
        digests_before = production_digests()
        spec = importlib.util.spec_from_file_location(
            "supported_class_mock_probe_fresh", PROBE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        with SandboxGuard() as guard:
            spec.loader.exec_module(module)
        self.assertEqual(guard.write_attempts, [])
        self.assertFalse(guard.imported_maix(), "maix must not be imported at import time")
        self.assertNotIn("maix", sys.modules)
        self.assertEqual(digests_before, production_digests())
        self.assertTrue(hasattr(module, "main"))

    def test_import_does_not_reach_the_uart_even_on_a_maixcam2(self):
        spec = importlib.util.spec_from_file_location(
            "supported_class_mock_probe_fresh_maix", PROBE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        with fake_maix_installed(device_id="maixcam2"):
            with SandboxGuard(allow_maix=True) as guard:
                spec.loader.exec_module(module)
        self.assertFalse(guard.imported_maix())
        self.assertEqual(guard.write_attempts, [])


class ProductionIntegrityTest(unittest.TestCase):
    def test_five_production_files_unchanged_by_a_full_dry_run(self):
        digests_before = production_digests()
        buffer = io.StringIO()
        with no_selection_file(), SandboxGuard() as guard:
            with contextlib.redirect_stdout(buffer):
                for class_id in (39, 41, 65):
                    self.assertEqual(
                        probe.main(argv=["--class", str(class_id)], environ={}), 0
                    )
        self.assertEqual(guard.write_attempts, [])
        self.assertEqual(digests_before, production_digests())

    def test_vision_source_matches_the_recorded_baseline(self):
        digest = hashlib.sha256(
            (MAIXCAM2_ROOT / "vision_source.py").read_bytes()
        ).hexdigest().upper()
        self.assertEqual(
            digest,
            "4B27679D9B7812EF5039F74366BA6455E31CE96EFA48D1632A08B2D4C5CCA084",
        )


if __name__ == "__main__":
    unittest.main()
