import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

import uart2_loopback_probe_single_file as maix_probe  # noqa: E402
import uart_segment_probe as usp  # noqa: E402


class DryRunAndGateTests(unittest.TestCase):
    def test_default_dry_run_does_not_touch_hardware(self):
        report = usp.dry_run_report()
        self.assertFalse(report["hardware_accessed"])
        self.assertFalse(report["serial_opened"])
        self.assertEqual(report["tx_bytes"], 0)
        self.assertEqual(report["rx_bytes"], 0)
        self.assertEqual(report["timeouts"], 0)
        self.assertEqual(report["result"], "dry_run_planned")

    def test_cli_default_exit_zero_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            code = usp.main(["--dry-run", "--json-out", str(out)])
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(data["hardware_accessed"])
            self.assertFalse(data["serial_opened"])

    def test_cli_no_args_is_dry_run(self):
        code = usp.main([])
        self.assertEqual(code, 0)

    def test_port_without_confirm_rejected(self):
        code = usp.main(["--port", "COM14"])
        self.assertEqual(code, 2)

    def test_confirm_without_port_rejected(self):
        code = usp.main(["--confirm-hardware"])
        self.assertEqual(code, 2)

    def test_wrong_baud_rejected(self):
        code = usp.main(
            ["--port", "COM14", "--confirm-hardware", "--baud", "9600"]
        )
        self.assertEqual(code, 2)

    def test_rejected_live_does_not_import_serial(self):
        with mock.patch.dict(sys.modules, {"serial": None}):
            code = usp.main([])
            self.assertEqual(code, 0)
            code2 = usp.main(["--port", "COM3"])
            self.assertEqual(code2, 2)


class LoopbackMockTests(unittest.TestCase):
    def test_normal_echo(self):
        fake = usp.FakeSerial(response=usp.TEST_FRAME)
        fake.open()
        report = usp.run_loopback(fake)
        self.assertEqual(report["result"], "echo_ok")
        self.assertEqual(report["tx_bytes"], len(usp.TEST_FRAME))
        self.assertEqual(report["rx_bytes"], len(usp.TEST_FRAME))
        self.assertTrue(report["hardware_accessed"])
        self.assertTrue(report["serial_opened"])

    def test_no_echo(self):
        fake = usp.FakeSerial(response=b"")
        fake.open()
        report = usp.run_loopback(fake, timeout_s=0.02)
        self.assertEqual(report["result"], "no_echo")
        self.assertEqual(report["rx_bytes"], 0)
        self.assertGreaterEqual(report["timeouts"], 1)

    def test_malformed_echo(self):
        fake = usp.FakeSerial(response=b"NOT_THE_FRAME\n")
        fake.open()
        report = usp.run_loopback(fake)
        self.assertEqual(report["result"], "malformed_echo")

    def test_partial_echo(self):
        fake = usp.FakeSerial(response=usp.TEST_FRAME[:6], chunk_size=2)
        fake.open()
        report = usp.run_loopback(fake, timeout_s=0.02)
        self.assertEqual(report["result"], "partial_echo")
        self.assertLess(report["rx_bytes"], len(usp.TEST_FRAME))

    def test_open_failed(self):
        def factory(port, baud, timeout_s):
            fake = usp.FakeSerial(raise_on_open=True)
            fake.open()
            return fake

        code = usp.main(
            ["--port", "COM14", "--confirm-hardware"],
            serial_factory=factory,
        )
        self.assertEqual(code, 1)

    def test_live_with_fake_echo_ok(self):
        def factory(port, baud, timeout_s):
            fake = usp.FakeSerial(response=usp.TEST_FRAME)
            fake.open()
            return fake

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "live.json"
            code = usp.main(
                [
                    "--port",
                    "COM14",
                    "--confirm-hardware",
                    "--json-out",
                    str(out),
                ],
                serial_factory=factory,
            )
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["result"], "echo_ok")
            self.assertTrue(data["serial_opened"])


class MaixSingleFileTests(unittest.TestCase):
    def test_maix_probe_has_no_project_imports(self):
        source = (
            PROJECT_ROOT / "maixcam2" / "uart2_loopback_probe_single_file.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            "from protocol",
            "import protocol",
            "from link_monitor",
            "import link_monitor",
            "from main",
            "import main",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

    def test_maix_probe_pc_main_is_dry(self):
        code = maix_probe.main([])
        self.assertEqual(code, 0)

    def test_maix_probe_classifies_echo(self):
        self.assertEqual(
            maix_probe.classify_echo(maix_probe.TEST_FRAME, maix_probe.TEST_FRAME),
            "echo_ok",
        )
        self.assertEqual(
            maix_probe.classify_echo(maix_probe.TEST_FRAME, b""),
            "no_echo",
        )

    def test_maix_probe_injected_serial_echo(self):
        class _Ser:
            def write(self, data):
                self.last = data
                return len(data)

            def read(self):
                return getattr(self, "last", b"")

        clock = {"t": 0}

        def now_ms():
            return clock["t"]

        def sleep_ms(ms):
            clock["t"] += ms

        report = maix_probe.run_with_serial(_Ser(), now_ms, sleep_ms)
        self.assertEqual(report["result"], "echo_ok")
        self.assertTrue(report["hardware_accessed"])


if __name__ == "__main__":
    unittest.main()
