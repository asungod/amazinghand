import sys
import tempfile
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "host"))

from titan_linkage_check import (  # noqa: E402
    REQUIRED_FUNCTION_GROUPS,
    evaluate_linkage,
    find_missing_function_groups,
    map_is_stale,
)


def _all_function_map_body() -> str:
    lines = []
    for group in REQUIRED_FUNCTION_GROUPS:
        # Prefer first symbol of each OR-group.
        sym = group[0]
        lines.append(f" .text.{sym}\n{sym}\n")
    return "\n".join(lines)


def _touch_sources(src: Path) -> list:
    sources = []
    for name in (
        "smart_hand_uart.c",
        "smart_hand_protocol.c",
        "smart_hand_vision_state.c",
        "smart_hand_sequence_guard.c",
        "grip_policy.c",
        "grip_pose_bank.c",
    ):
        path = src / name
        path.write_text("/* src */\n", encoding="utf-8")
        sources.append(path)
    return sources


class TitanLinkageFunctionTests(unittest.TestCase):
    def test_all_functions_present_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            src.mkdir()
            sources = _touch_sources(src)
            time.sleep(0.05)
            map_path = root / "rtthread.map"
            map_path.write_text(_all_function_map_body(), encoding="utf-8")
            result = evaluate_linkage(map_path, sources)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["reason"], "ok")
            self.assertEqual(result["missing_functions"], [])
            self.assertEqual(result["evidence_mode"], "map_only")

    def test_module_names_only_without_functions_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.c"
            src.write_text("x\n", encoding="utf-8")
            time.sleep(0.05)
            map_path = root / "rtthread.map"
            map_path.write_text(
                "\n".join(
                    [
                        "smart_hand_uart.o",
                        "smart_hand_protocol.o",
                        "smart_hand_vision_state.o",
                        "smart_hand_sequence_guard.o",
                        "grip_policy.o",
                        "eight_servo_pose_bank.o",
                    ]
                ),
                encoding="utf-8",
            )
            result = evaluate_linkage(map_path, [src])
            self.assertFalse(result["ok"])
            self.assertTrue(result["modules_present_functions_missing"])
            self.assertEqual(result["reason"], "missing_functions")
            self.assertIn("grip_policy_decide", " ".join(result["missing_functions"]))

    def test_missing_one_function_fails(self):
        body = _all_function_map_body().replace(
            "eight_servo_pose_bank_resolve", "not_the_symbol"
        )
        missing = find_missing_function_groups(body)
        self.assertTrue(
            any("eight_servo_pose_bank_resolve" in item for item in missing)
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.c"
            src.write_text("x\n", encoding="utf-8")
            time.sleep(0.05)
            map_path = root / "rtthread.map"
            map_path.write_text(body, encoding="utf-8")
            result = evaluate_linkage(map_path, [src])
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "missing_functions")

    def test_stale_map_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            map_path = root / "rtthread.map"
            map_path.write_text(_all_function_map_body(), encoding="utf-8")
            time.sleep(0.05)
            src = root / "smart_hand_uart.c"
            src.write_text("newer\n", encoding="utf-8")
            self.assertTrue(map_is_stale(map_path, [src]))
            result = evaluate_linkage(map_path, [src])
            self.assertFalse(result["ok"])
            self.assertTrue(result["stale"])

    def test_map_missing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            map_path = root / "missing.map"
            src = root / "a.c"
            src.write_text("x\n", encoding="utf-8")
            result = evaluate_linkage(map_path, [src])
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "map_missing")

    def test_comm_init_rt_wrapper_alias_accepted(self):
        body = _all_function_map_body().replace(
            "smart_hand_comm_init", "__rt_init_smart_hand_comm_init"
        )
        missing = find_missing_function_groups(body)
        self.assertFalse(any("smart_hand_comm_init" in item for item in missing))

    def test_optional_nm_ok_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.c"
            src.write_text("x\n", encoding="utf-8")
            time.sleep(0.05)
            map_path = root / "rtthread.map"
            map_path.write_text(_all_function_map_body(), encoding="utf-8")
            nm_ok = _all_function_map_body()
            result_ok = evaluate_linkage(map_path, [src], nm_output=nm_ok)
            self.assertTrue(result_ok["ok"])
            self.assertTrue(result_ok["nm_available"])
            self.assertEqual(result_ok["evidence_mode"], "map_and_elf_nm")

            nm_bad = nm_ok.replace("shp_parser_feed", "nope")
            result_bad = evaluate_linkage(map_path, [src], nm_output=nm_bad)
            self.assertFalse(result_bad["ok"])
            self.assertEqual(result_bad["reason"], "elf_missing_functions")


if __name__ == "__main__":
    unittest.main()
