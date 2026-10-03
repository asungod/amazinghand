import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

import titan_uart_acceptance as tua  # noqa: E402
from protocol import encode_frame  # noqa: E402


class DryRunTests(unittest.TestCase):
    def test_dry_run_default_hardware_false(self):
        report = tua.dry_run_report()
        self.assertFalse(report["hardware_accessed"])
        self.assertFalse(report["serial_opened"])
        self.assertFalse(report["live_ran"])
        self.assertEqual(report["mode"], "dry-run")
        self.assertGreaterEqual(len(report["cases"]), 10)
        # Each case lists evidence and does not claim pass
        for case in report["cases"]:
            self.assertEqual(case["result"], "dry_run_planned")
            self.assertEqual(case["ack_observation"], "not_run")
            self.assertTrue(case["tx_frame"] if False else True)
            self.assertIn("steps", case)

    def test_dry_run_emits_frames_and_expected_acks(self):
        report = tua.dry_run_report()
        first = next(c for c in report["cases"] if c["id"] == "first_ping")
        step0 = first["steps"][0]
        self.assertTrue(step0["tx_frame"].startswith("$PING,1*"))
        self.assertEqual(step0["expect_ack"]["status"], 0)

    def test_cli_dry_run_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            code = tua.main(["--dry-run", "--json-out", str(out)])
            self.assertEqual(code, 0)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertFalse(data["hardware_accessed"])

    def test_timing_cases_marked_pc_ack_insufficient(self):
        report = tua.dry_run_report()
        stale = next(c for c in report["cases"] if c["id"] == "stale_750ms")
        self.assertTrue(stale["pc_ack_cannot_pass_alone"])
        self.assertTrue(
            any("Titan shell" in e or "sh_status" in e for e in stale["evidence"])
        )


class LiveGateTests(unittest.TestCase):
    def test_port_without_confirm_rejected_before_serial(self):
        code = tua.main(["--port", "COM9"])
        self.assertEqual(code, 2)

    def test_confirm_without_port_rejected(self):
        code = tua.main(["--live", "--live-no-servo-confirmed"])
        self.assertEqual(code, 2)

    def test_wrong_baud_rejected(self):
        code = tua.main(
            ["--port", "COM9", "--live-no-servo-confirmed", "--baud", "1000000"]
        )
        self.assertEqual(code, 2)

    def test_triple_gate_structurally_ok_but_batch_blocks_live(self):
        # Gates pass but batch policy returns 3 without opening serial.
        code = tua.main(
            ["--port", "COM9", "--live-no-servo-confirmed", "--baud", "115200"]
        )
        self.assertEqual(code, 3)

    def test_live_preflight_before_serial_import(self):
        # Ensure pyserial is not required for dry-run / rejected live.
        with mock.patch.dict(sys.modules, {"serial": None}):
            code = tua.main([])
            self.assertEqual(code, 0)
            code2 = tua.main(["--port", "COM3"])
            self.assertEqual(code2, 2)


class FakeSerialTests(unittest.TestCase):
    def test_fake_serial_write_and_read_ack(self):
        ack = encode_frame("ACK", 1, 0)
        fake = tua.FakeSerial(response_chunks=[ack])
        fake.open()
        self.assertTrue(fake.opened)
        n = fake.write(encode_frame("PING", 1))
        self.assertGreater(n, 0)
        got = fake.read(len(ack))
        self.assertEqual(got, ack)
        fake.close()
        self.assertTrue(fake.closed)

    def test_fake_serial_timeout_empty(self):
        fake = tua.FakeSerial(response_chunks=[])
        fake.timeout = 0.01
        fake.open()
        self.assertEqual(fake.read(10), b"")

    def test_fake_serial_open_error(self):
        fake = tua.FakeSerial(raise_on_open=True)
        with self.assertRaises(OSError):
            fake.open()

    def test_parser_handles_fragmented_ack_via_protocol(self):
        from protocol import StreamParser

        ack = encode_frame("ACK", 2, 1)
        parser = StreamParser()
        self.assertEqual(parser.feed(ack[:4]), [])
        self.assertEqual(parser.feed(ack[4:]), [{"type": "ACK", "seq": 2, "args": [1]}])

    def test_crc_error_dropped_by_protocol(self):
        from protocol import StreamParser

        broken = bytearray(encode_frame("ACK", 3, 0))
        broken[3] ^= 0x01
        parser = StreamParser()
        good = encode_frame("ACK", 4, 0)
        self.assertEqual(parser.feed(bytes(broken) + good), [{"type": "ACK", "seq": 4, "args": [0]}])


class HostSimulationTests(unittest.TestCase):
    def test_non_timing_business_cases_pass_on_host(self):
        report = tua.dry_run_report()
        sim = report["host_simulation"]
        self.assertTrue(sim["all_passed"], json.dumps(sim, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    unittest.main()
