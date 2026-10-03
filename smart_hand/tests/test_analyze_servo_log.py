import csv
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from analyze_servo_log import analyze, read_log, write_html_report  # noqa: E402


FIELDS = (PROJECT_ROOT / "data" / "single_finger_log_template.csv").read_text(
    encoding="utf-8"
).strip().split(",")


def row(sequence, time_ms, servo1_ok=1, servo2_ok=1):
    value = {field: "" for field in FIELDS}
    value.update({
        "session_id": "S1",
        "trial_id": "T1",
        "sample_seq": str(sequence),
        "time_ms": str(time_ms),
        "servo1_role": "joint1",
        "servo1_target_raw": str(100 + sequence),
        "servo1_position_raw": str(90 + sequence) if servo1_ok else "",
        "servo1_speed_raw": "5" if servo1_ok else "",
        "servo1_load_raw": "20" if servo1_ok else "",
        "servo1_voltage_raw": "60" if servo1_ok else "",
        "servo1_temperature_raw": "30" if servo1_ok else "",
        "servo1_read_ok": str(servo1_ok),
        "servo1_data_age_ms": "2" if servo1_ok else "",
        "servo2_role": "joint2",
        "servo2_target_raw": str(200 + sequence),
        "servo2_position_raw": str(195 + sequence) if servo2_ok else "",
        "servo2_speed_raw": "6" if servo2_ok else "",
        "servo2_load_raw": "21" if servo2_ok else "",
        "servo2_voltage_raw": "60" if servo2_ok else "",
        "servo2_temperature_raw": "31" if servo2_ok else "",
        "servo2_read_ok": str(servo2_ok),
        "servo2_data_age_ms": "3" if servo2_ok else "",
    })
    return value


class ServoLogAnalysisTests(unittest.TestCase):
    def write_rows(self, directory, rows):
        path = Path(directory) / "log.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_normal_log_reports_ranges_failures_and_html(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [row(0, 0), row(1, 50, servo2_ok=0), row(2, 100)])
            rows = read_log(path)
            summary = analyze(rows)
            self.assertEqual(summary["samples"], 3)
            self.assertEqual(summary["duration_ms"], 100)
            self.assertEqual(summary["mean_interval_ms"], 50)
            self.assertEqual(summary["servo"]["2"]["failed_reads"], 1)
            self.assertEqual(summary["servo"]["1"]["position_error_raw"], {"minimum": 10, "maximum": 10})
            report = Path(directory) / "report.html"
            write_html_report(rows, summary, report)
            content = report.read_text(encoding="utf-8")
            self.assertIn("raw, not force", content)
            self.assertIn("<svg", content)

    def test_decreasing_time_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [row(0, 100), row(1, 99)])
            with self.assertRaisesRegex(ValueError, "time_ms decreased"):
                read_log(path)

    def test_failed_read_cannot_claim_fresh_feedback(self):
        bad = row(0, 0, servo1_ok=0)
        bad["servo1_position_raw"] = "123"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [bad])
            with self.assertRaisesRegex(ValueError, "failed read"):
                read_log(path)

    def test_multiple_trials_in_one_file_are_rejected(self):
        second = row(1, 50)
        second["trial_id"] = "T2"
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_rows(directory, [row(0, 0), second])
            with self.assertRaisesRegex(ValueError, "exactly one"):
                read_log(path)


if __name__ == "__main__":
    unittest.main()

