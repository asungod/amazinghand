import sys
import tempfile
import unittest
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from generate_rehab_session_report import (  # noqa: E402
    generate_report,
    load_sessions,
    quality_feedback,
)


HEADER = (
    "schema,session,outcome,repetitions,goal,completion_pct,"
    "demo_ms,imitation_ms,avg_rep_ms\n"
)


class RehabSessionReportTests(unittest.TestCase):
    def test_quality_feedback_maps_statuses_without_rewriting_them(self):
        self.assertEqual(quality_feedback({"quality_status": "DEGRADED", "rhythm_status": "TOO_SLOW", "hold_status": "OK", "valid_frame_pct": 100.0}), "节奏偏慢，请按提示稍快")
        self.assertEqual(quality_feedback({"quality_status": "DEGRADED", "rhythm_status": "NORMAL", "hold_status": "INSUFFICIENT", "valid_frame_pct": 100.0}), "闭合识别不足，请保持闭合并保持手掌稳定")
        self.assertEqual(quality_feedback({"quality_status": "DEGRADED", "rhythm_status": "NORMAL", "hold_status": "OK", "valid_frame_pct": 72.5}), "画面跟踪不足，请调整手掌和光线")
        self.assertEqual(quality_feedback(None), "数据不足，暂不评价")

    def test_generates_nonclinical_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            output = root / "report.html"
            csv_path.write_text(
                HEADER
                + "1,1,COMPLETE,5,5,100,17800,20437,4087\n"
                + "1,2,TIMEOUT,2,5,40,17600,60000,30000\n",
                encoding="utf-8",
            )
            sessions = generate_report(csv_path, output)
            self.assertEqual(len(sessions), 2)
            page = output.read_text(encoding="utf-8")
            self.assertIn("70%", page)
            self.assertIn("完成会话平均完成率", page)
            self.assertIn("100%", page)
            self.assertRegex(page, r"完成会话</div><div class=\"value\">1</div>")
            self.assertIn("结果分布", page)
            self.assertIn("其中 0 条明确标记为 imitation_timeout", page)
            self.assertIn("其余 TIMEOUT 原因未作安全测试断言", page)
            self.assertNotIn("安全测试记录", page)
            self.assertIn("TIMEOUT 不单独用于推断训练能力下降", page)
            self.assertIn("完成会话", page)
            self.assertIn("不构成诊断", page)
            self.assertIn("训练趋势", page)
            self.assertIn("完成率", page)
            self.assertIn("会话 1", page)
            self.assertIn("4.1s/次", page)

    def test_reason_sidecar_renders_without_changing_legacy_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            reason_path = root / "sessions.csv.reason.csv"
            output = root / "report.html"
            csv_path.write_text(
                HEADER + "1,1,TIMEOUT,2,5,40,17600,60000,30000\n",
                encoding="utf-8",
            )
            reason_path.write_text(
                "schema,session,outcome,termination_reason\n"
                "1,1,TIMEOUT,hand_vision_init_failed\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output)
            page = output.read_text(encoding="utf-8")
            self.assertIn("终止/超时原因", page)
            self.assertIn("hand_vision_init_failed", page)

    def test_only_explicit_imitation_timeout_counts_as_training_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            reason_path = root / "sessions.csv.reason.csv"
            output = root / "report.html"
            csv_path.write_text(
                HEADER
                + "1,1,TIMEOUT,0,5,0,17600,60000,-1\n"
                + "1,2,TIMEOUT,0,5,0,17600,60000,-1\n",
                encoding="utf-8",
            )
            reason_path.write_text(
                "schema,session,outcome,termination_reason\n"
                "1,1,TIMEOUT,imitation_timeout\n"
                "1,2,TIMEOUT,hand_vision_init_failed\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output, reason_csv=reason_path)
            page = output.read_text(encoding="utf-8")
            self.assertIn("其中 1 条明确标记为 imitation_timeout", page)
            self.assertIn("imitation_timeout", page)
            self.assertIn("hand_vision_init_failed", page)

    def test_reason_outcome_mismatch_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            reason_path = root / "sessions.csv.reason.csv"
            output = root / "report.html"
            csv_path.write_text(
                HEADER + "1,1,TIMEOUT,0,5,0,17600,60000,-1\n",
                encoding="utf-8",
            )
            reason_path.write_text(
                "schema,session,outcome,termination_reason\n"
                "1,1,COMPLETE,imitation_timeout\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output, reason_csv=reason_path)
            page = output.read_text(encoding="utf-8")
            self.assertIn("其中 0 条明确标记为 imitation_timeout", page)
            self.assertNotIn('title="imitation_timeout"', page)

    def test_duplicate_reason_session_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            reason_path = root / "sessions.csv.reason.csv"
            output = root / "report.html"
            csv_path.write_text(
                HEADER + "1,1,TIMEOUT,0,5,0,17600,60000,-1\n",
                encoding="utf-8",
            )
            reason_path.write_text(
                "schema,session,outcome,termination_reason\n"
                "1,1,TIMEOUT,imitation_timeout\n"
                "1,1,TIMEOUT,hand_vision_init_failed\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output, reason_csv=reason_path)
            page = output.read_text(encoding="utf-8")
            self.assertNotIn('title="imitation_timeout"', page)
            self.assertNotIn('title="hand_vision_init_failed"', page)

    def test_missing_quality_file_is_backward_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            output = root / "report.html"
            csv_path.write_text(HEADER + "1,1,COMPLETE,1,1,100,100,200,200\n", encoding="utf-8")
            generate_report(csv_path, output, root / "missing-quality.csv")
            page = output.read_text(encoding="utf-8")
            self.assertIn("质量数据覆盖会话", page)
            self.assertIn("0/1", page)
            self.assertIn("<th>质量状态</th>", page)
            self.assertIn('class="badge badge-quality-unknown" title="UNKNOWN"', page)
            self.assertIn('class="badge badge-rhythm-unknown" title="UNKNOWN"', page)
            self.assertIn('class="badge badge-hold-unknown" title="UNKNOWN"', page)

    def test_quality_sidecar_renders_matching_rows(self):
        quality_header = (
            "schema,session,quality_status,rhythm_status,hold_status,"
            "pace_avg_ms,pace_min_ms,pace_max_ms,fast_count,slow_count,"
            "short_hold_count,valid_frame_pct\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            quality = root / "quality.csv"
            output = root / "report.html"
            csv_path.write_text(HEADER + "1,1,COMPLETE,1,1,100,100,200,200\n", encoding="utf-8")
            quality.write_text(
                quality_header + "1,1,OK,NORMAL,OK,1000,900,1100,0,0,0,99.5\n"
                + "1,9,DEGRADED,TOO_FAST,INSUFFICIENT,1,1,1,0,0,0,100\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output, quality)
            page = output.read_text(encoding="utf-8")
            self.assertIn("1/1", page)  # unmatched session is ignored
            self.assertIn('class="badge badge-quality-ok" title="OK"', page)
            self.assertIn('class="badge badge-rhythm-normal" title="NORMAL"', page)
            self.assertIn('class="badge badge-hold-ok" title="OK"', page)

    def test_quality_sidecar_is_auto_discovered(self):
        quality_header = (
            "schema,session,quality_status,rhythm_status,hold_status,"
            "pace_avg_ms,pace_min_ms,pace_max_ms,fast_count,slow_count,"
            "short_hold_count,valid_frame_pct\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            quality = root / "sessions.csv.quality.csv"
            output = root / "report.html"
            csv_path.write_text(HEADER + "1,1,COMPLETE,1,1,100,100,200,200\n", encoding="utf-8")
            quality.write_text(
                quality_header + "1,1,OK,NORMAL,OK,1000,900,1100,0,0,0,99.5\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output)
            page = output.read_text(encoding="utf-8")
            self.assertIn("质量数据覆盖会话", page)
            self.assertIn("1/1", page)
            self.assertIn('class="badge badge-quality-ok" title="OK"', page)
            self.assertIn('class="badge badge-rhythm-normal" title="NORMAL"', page)
            self.assertIn('class="badge badge-hold-ok" title="OK"', page)

    def test_bad_or_duplicate_quality_rows_are_ignored(self):
        quality_header = (
            "schema,session,quality_status,rhythm_status,hold_status,"
            "pace_avg_ms,pace_min_ms,pace_max_ms,fast_count,slow_count,"
            "short_hold_count,valid_frame_pct\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            csv_path = root / "sessions.csv"
            quality = root / "quality.csv"
            output = root / "report.html"
            csv_path.write_text(HEADER + "1,1,COMPLETE,1,1,100,100,200,200\n", encoding="utf-8")
            quality.write_text(
                quality_header + "1,1,OK,NORMAL,OK,1000,900,1100,0,0,0,99\n"
                + "1,1,BAD,NORMAL,OK,1000,900,1100,0,0,0,99\n"
                + "1,2,BAD,NORMAL,OK,nope,900,1100,0,0,0,99\n",
                encoding="utf-8",
            )
            generate_report(csv_path, output, quality)
            page = output.read_text(encoding="utf-8")
            self.assertIn('class="badge badge-quality-ok" title="OK"', page)
            self.assertIn('class="badge badge-rhythm-normal" title="NORMAL"', page)
            self.assertNotIn('title="BAD"', page)

    def test_rejects_inconsistent_completion_percentage(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "bad.csv"
            csv_path.write_text(
                HEADER + "1,1,COMPLETE,5,5,80,17800,20437,4087\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "percentage mismatch"):
                load_sessions(csv_path)


if __name__ == "__main__":
    unittest.main()
