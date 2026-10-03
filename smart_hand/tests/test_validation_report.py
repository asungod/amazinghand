import tempfile
import sys
import unittest
from unittest import mock
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from create_validation_report import build_report, run_checks, sha256_record  # noqa: E402


class ValidationReportTests(unittest.TestCase):
    def test_hash_record_reports_digest_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.bin"
            path.write_bytes(b"abc")
            present = sha256_record("sample", path)
            missing = sha256_record("missing", path.with_name("missing.bin"))

        self.assertEqual(
            present["sha256"],
            "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD",
        )
        self.assertEqual(present["bytes"], 3)
        self.assertEqual(missing["sha256"], "MISSING")

    def test_report_marks_failure_and_strips_ansi_sequences(self):
        record = {"label": "file", "path": "file", "sha256": "ABC", "bytes": 1}
        report = build_report(
            "2026-08-11T20:00:00+08:00",
            1,
            "\x1b[31mFAILED\x1b[0m\n",
            [record],
            [record],
            [record],
            r"D:\Micu\RTTWorkspace\titan_uart_test",
        )

        self.assertIn("Result: `FAIL`", report)
        self.assertIn("FAILED", report)
        self.assertNotIn("\x1b", report)
        self.assertIn("no Git or network action performed", report)

    @mock.patch("create_validation_report.subprocess.run")
    def test_run_checks_forwards_selected_studio_project(self, run):
        run.return_value = mock.Mock(returncode=0, stdout="ok\n", stderr="")
        studio = Path(r"D:\alternate\titan_project")

        returncode, output = run_checks(PROJECT_ROOT, studio)

        self.assertEqual(returncode, 0)
        self.assertEqual(output, "ok\n")
        command = run.call_args.args[0]
        self.assertEqual(command[-2:], ["-StudioProject", str(studio)])


if __name__ == "__main__":
    unittest.main()
