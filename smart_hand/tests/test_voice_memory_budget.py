"""smart_hand/host/voice_memory_budget.py 的回归测试。

这里只验证"脚本算出来的东西确实来自仓库"，不复制一份期望值列表：
凡是能从源码/头文件重新推出的数字，测试就现场重新推一遍再比对；
凡是硬性红线（不许改固件文件），测试直接对文件做哈希前后比对。
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "smart_hand" / "host"
SCRIPT = TOOLS_DIR / "voice_memory_budget.py"

SMART_DIR = PROJECT_ROOT / "smart_hand"
RT_DIR = SMART_DIR / "titan_rtthread"
GEN_DIR = SMART_DIR / "titan_ai" / "voice" / "generated"

# 固件工程里的红线文件：脚本只许读，不许写。
FIRMWARE_ROOT = Path("D:/Micu/RTTWorkspace/titan_uart_test")
RED_LINE_FILES = [
    FIRMWARE_ROOT / "board" / "board.h",
    FIRMWARE_ROOT / "board" / "linker_scripts" / "fsp.ld",
    FIRMWARE_ROOT / "Debug" / "rtthread.elf",
    FIRMWARE_ROOT / "Debug" / "rtthread.map",
]


def load_script_module():
    spec = importlib.util.spec_from_file_location("voice_memory_budget", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_script_module()

    def test_macros_use_c_integer_division(self):
        """C 的 / 是整除。VOICE_FRAME_LEN 必须是 400，不能是 400.0。"""
        macros = cls_macros(self.mod)
        self.assertEqual(macros.value("VOICE_FRAME_LEN"), 400)
        self.assertEqual(macros.value("VOICE_NUM_FRAMES"), 98)
        self.assertEqual(macros.value("VOICE_MEL_BIN_COUNT"), 257)
        self.assertEqual(macros.value("VOICE_FEATURE_COUNT"), 3920)
        self.assertEqual(macros.value("VOICE_RING_CAPACITY"), 32768)
        self.assertEqual(macros.value("VOICE_WINDOW_SAMPLES"), 16000)

    def test_struct_sizes_agree_with_compiler_probe(self):
        """脚本自己推导的布局必须和 arm-none-eabi-gcc 实测的 sizeof 一致。"""
        report = self.mod.build_report(_args(self.mod))
        verification = report["verification"]
        if verification["ok"] is None:
            self.skipTest(f"没有可用编译器: {verification['note']}")
        self.assertTrue(
            verification["ok"],
            "解析布局与编译器实测不一致: "
            + json.dumps([r for r in verification["rows"] if not r["match"]],
                         ensure_ascii=False),
        )
        self.assertGreaterEqual(len(verification["rows"]), 20)

    def test_struct_sizes_are_derived_from_header_macros(self):
        """改宏 → 尺寸跟着变。用宏的当前值反推，不在测试里写死。"""
        macros = cls_macros(self.mod)
        structs = {
            name: self.mod.parse_struct(path.name, path, name, macros)
            for name, path in self.mod.STRUCT_SOURCES.items()
        }
        ring = structs["voice_ring_t"]
        self.assertEqual(
            ring.size,
            2 * macros.dim_count("VOICE_RING_CAPACITY") + 5 * 4 + 1 + 3,
            "voice_ring_t 应当是 int16 环形缓冲 + 5 个 uint32 计数 + 1 个 uint8",
        )
        kws = structs["voice_kws_t"]
        self.assertEqual(
            kws.size,
            2 * macros.value("VOICE_MODEL_L0_OUT_COUNT")
            + macros.value("VOICE_MODEL_CLASS_COUNT") + 1,
            "voice_kws_t 应当是 stage_a + stage_b + logits + initialized",
        )
        frontend = structs["voice_frontend_t"]
        self.assertEqual(
            frontend.size,
            4 * (macros.value("VOICE_FRAME_LEN")
                 + macros.value("VOICE_FFT_SIZE")
                 + macros.value("VOICE_MEL_BANDS") * macros.value("VOICE_MEL_BIN_COUNT")
                 + 2 * macros.value("VOICE_FFT_SIZE")) + 1 + 3,
            "voice_frontend_t 的成员尺寸应当全部由 voice_config.h 的宏决定",
        )

    def test_inventory_line_numbers_point_at_the_symbol(self):
        """每条 static/局部数组报出的行号，必须真的落在那个符号所在行上。"""
        report = self.mod.build_report(_args(self.mod))
        items = list(report["standalone"]) + list(report["stack_locals"])
        self.assertTrue(items, "没有解析到任何 static，解析器坏了")
        for item in items:
            path = dict(self.mod.VOICE_C_SOURCES)[item.file]
            line = path.read_text(encoding="utf-8").splitlines()[item.line - 1]
            self.assertIn(item.name, line,
                          f"{item.file}:{item.line} 不是 {item.name} 所在行: {line!r}")

    def test_model_array_line_numbers_point_at_the_symbol(self):
        macros = cls_macros(self.mod)
        arrays = self.mod.parse_model_arrays(self.mod.MODEL_DATA_C, macros)
        self.assertTrue(arrays)
        lines = self.mod.MODEL_DATA_C.read_text(encoding="utf-8").splitlines()
        for arr in arrays:
            self.assertIn(arr.name, lines[arr.line - 1])
            if arr.declared is not None and arr.measured is not None:
                self.assertEqual(arr.declared, arr.measured,
                                 f"{arr.name} 的声明维度与初值个数对不上")

    def test_workspace_is_reported_separately_from_existing_statics(self):
        """已存在的 static 与集成后才有的工作区必须分开报，不能混成一个数。"""
        report = self.mod.build_report(_args(self.mod))
        names = {o.name for o in report["standalone"]}
        self.assertTrue({"g_voice_ring", "g_capture_buffer", "g_stats",
                         "g_running", "g_square_accumulator",
                         "g_sample_accumulator", "g_level_samples",
                         "staging"} <= names,
                        f"漏了 static: {sorted(names)}")
        workspace_names = {name for name, _ in report["workspace_structs"]}
        self.assertEqual(workspace_names, {"voice_kws_t", "voice_frontend_t"})
        self.assertFalse(names & workspace_names,
                         "工作区结构体不该出现在已存在的 static 列表里")
        stack_names = {o.name for o in report["stack_locals"]}
        self.assertEqual(stack_names, {"features", "probabilities"})

    def test_over_budget_report_exits_nonzero(self):
        """任何一项超预算都必须让 render() 返回非零。"""
        report = self.mod.build_report(_args(self.mod))
        report["checks"] = list(report["checks"]) + [
            self.mod._check("人为构造的超限项", -1, "测试用", False)
        ]
        report["failures"] = [c for c in report["checks"] if not c["pass"]]
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.mod.render(report)
        self.assertEqual(code, 1)
        self.assertIn("预算超限", buffer.getvalue())


class ScriptRunTests(unittest.TestCase):
    def run_script(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *extra],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )

    def test_runs_from_project_root(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for expected in ("语音模块静态内存预算", "【表 1】", "【结论】",
                         "相对 RT-Thread 堆的剩余", "全部区域在预算内"):
            self.assertIn(expected, result.stdout)

    def test_json_output_is_machine_readable(self):
        result = self.run_script("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIs(payload["ok"], True)
        totals = payload["totals"]
        self.assertEqual(
            totals["full_static"],
            totals["static_total"] + totals["workspace_bytes"],
        )
        self.assertEqual(
            totals["full_conservative"],
            totals["full_static"] + totals["stack_bytes"],
        )
        self.assertGreater(totals["static_total"], 0)
        self.assertGreater(payload["model_flash"]["total_bytes"], 0)
        for row in payload["existing_statics"]:
            self.assertIn("elf_status", row)

    def test_json_and_text_report_agree(self):
        run = self.run_script()
        payload = json.loads(self.run_script("--json").stdout)
        self.assertIn(f"{payload['totals']['static_total']:,}", run.stdout)
        self.assertIn(f"{payload['model_flash']['total_bytes']:,}", run.stdout)

    def test_firmware_files_are_never_written(self):
        """红线：跑脚本不许改动固件工程里的任何文件（尤其 board.h）。"""
        targets = [p for p in RED_LINE_FILES if p.exists()]
        if not targets:
            self.skipTest(f"固件工程不在本机: {FIRMWARE_ROOT}")
        before = {p: _digest(p) for p in targets}
        self.run_script()
        self.run_script("--json")
        after = {p: _digest(p) for p in targets}
        self.assertEqual(before, after, "脚本改动了固件文件")

    def test_ra_sram_size_is_untouched(self):
        board_h = FIRMWARE_ROOT / "board" / "board.h"
        if not board_h.exists():
            self.skipTest(f"board.h 不在本机: {board_h}")
        self.run_script()
        match = re.search(r"#define\s+RA_SRAM_SIZE\s+(\d+)",
                          board_h.read_text(encoding="utf-8"))
        self.assertIsNotNone(match, "board.h 里的 RA_SRAM_SIZE 不见了")
        self.assertEqual(match.group(1), "512")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _args(mod):
    return mod.argparse.Namespace(
        firmware_root=str(mod.DEFAULT_FIRMWARE_ROOT),
        toolchain=None, json=False, no_verify=False,
    )


def cls_macros(mod):
    macros = mod.MacroTable()
    for label, path in mod.MACRO_SOURCES.items():
        if path.exists():
            macros.load(label, path)
    board_h = mod.DEFAULT_FIRMWARE_ROOT / "board" / "board.h"
    if board_h.exists():
        macros.load("board.h", board_h)
    return macros


if __name__ == "__main__":
    unittest.main()
