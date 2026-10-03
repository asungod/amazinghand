#!/usr/bin/env python3
"""OpenSignHand 语音模块静态内存预算统计。

用法（在项目根目录直接跑）::

    python smart_hand/host/voice_memory_budget.py
    python smart_hand/host/voice_memory_budget.py --json
    python smart_hand/host/voice_memory_budget.py --firmware-root D:/Micu/RTTWorkspace/titan_uart_test

这个脚本只读文件，不写任何固件源码，也不改链接脚本或 board.h。
它做三件事：

1. 从 ``smart_hand/titan_rtthread`` 与 ``smart_hand/titan_ai/voice/generated``
   的头文件/源文件里 **解析** 宏与声明，推导语音模块的静态内存占用。
   脚本里没有硬编码的业务数字：数组维度全部来自宏，结构体布局由头文件里
   的成员声明推出，宏一改输出就跟着变。
2. 用工程自己的 ARM 工具链对 ``rtthread.elf`` 实测基线（size / nm），
   并从 ``board/linker_scripts/fsp.ld`` 与 ``board/board.h`` 解析 RAM/Flash
   口径与 RT-Thread 堆范围。
3. 出一张中文表，并给出"已存在的 static"/"集成后的完整预算"两套合计、
   相对链接脚本 RAM 区与相对 RT-Thread 堆的剩余、Flash 侧余量。

数字来源标注约定：

* ``[解析]`` 从源码/头文件解析得到；
* ``[实测]`` 从 ELF/MAP 或交叉编译器实测得到；
* ``[未确认]`` 无法从仓库确定 —— 脚本不会把它当成实测数字使用。

退出码：0 = 全部在预算内；1 = 有区域超预算；2 = 无法完成统计（缺文件/缺工具链）。

为什么必须区分"堆"与"链接脚本 RAM 区"
--------------------------------------
``fsp.ld`` 的 RAM 区是 1,523,712 B，但 RT-Thread 的堆只从
``__RAM_segment_used_end__`` 起算到 ``RA_SRAM_END``（board.h），实测只有
386,060 B —— 绝大部分 RAM 已经被固件的 .bss 吃掉，并没有交给堆。
语音模块的 ring/工作区都是几百 KB 量级，走 rt_malloc 会被这 386,060 B 卡死，
所以本脚本按"静态分配（.bss）"口径核算，并把堆口径单独列出来做对照。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SMART_DIR = PROJECT_ROOT / "smart_hand"
RT_DIR = SMART_DIR / "titan_rtthread"
GEN_DIR = SMART_DIR / "titan_ai" / "voice" / "generated"

DEFAULT_FIRMWARE_ROOT = Path("D:/Micu/RTTWorkspace/titan_uart_test")

# 工程自带的 GNU ARM 工具链（任务书给的那条路径）。
DEFAULT_TOOLCHAIN_DIR = Path(
    "D:/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/"
    "GNU_Tools_for_ARM_Embedded_Processors/13.3/bin"
)

# 语音模块编译后会产生这些目标文件名。只有这些 .o 里定义的符号才算语音模块的。
VOICE_OBJECT_STEMS = {
    "voice_audio_titan", "voice_audio", "voice_kws", "voice_features",
}

# 语音模块源码文件（用于解析 static 与函数内局部数组）。
VOICE_C_SOURCES = {
    "voice_audio_titan.c": RT_DIR / "voice_audio_titan.c",
    "voice_kws.c": RT_DIR / "voice_kws.c",
    "voice_features.c": RT_DIR / "voice_features.c",
    "voice_audio.c": RT_DIR / "voice_audio.c",
}

# 宏表来源：label -> 路径。宏的名字会带进输出，方便追来源。
MACRO_SOURCES = {
    "voice_config.h": RT_DIR / "voice_config.h",
    "voice_audio.h": RT_DIR / "voice_audio.h",
    "voice_audio_titan.h": RT_DIR / "voice_audio_titan.h",
    "voice_kws.h": RT_DIR / "voice_kws.h",
    "voice_features.h": RT_DIR / "voice_features.h",
    "voice_model_data.h": GEN_DIR / "voice_model_data.h",
    "voice_audio_titan.c": RT_DIR / "voice_audio_titan.c",
}

# 结构体定义所在头文件。
STRUCT_SOURCES = {
    "voice_ring_t": RT_DIR / "voice_audio.h",
    "voice_capture_stats_t": RT_DIR / "voice_audio_titan.h",
    "voice_kws_t": RT_DIR / "voice_kws.h",
    "voice_frontend_t": RT_DIR / "voice_features.h",
}

MODEL_DATA_C = GEN_DIR / "voice_model_data.c"
MODEL_DATA_H = GEN_DIR / "voice_model_data.h"

# C 基本类型 -> (sizeof, _Alignof)。这是 C ABI 事实，不是业务数字。
# ARM AAPCS 与 x86-64 SysV 对这几个标量类型的宽度/对齐一致，脚本会再用
# 目标编译器实测 _Alignof 交叉验证（见 verify_with_compiler）。
PRIM_TYPES = {
    "char": (1, 1),
    "int8_t": (1, 1),
    "uint8_t": (1, 1),
    "int16_t": (2, 2),
    "uint16_t": (2, 2),
    "int32_t": (4, 4),
    "uint32_t": (4, 4),
    "int64_t": (8, 8),
    "uint64_t": (8, 8),
    "float": (4, 4),
    "double": (8, 8),
    "size_t": (4, 4),
    "intptr_t": (4, 4),
    "uintptr_t": (4, 4),
}

# 不是类型的关键字，避免把控制语句误当声明。
NOT_A_TYPE = {
    "return", "else", "case", "break", "continue", "if", "for", "while",
    "switch", "goto", "do", "sizeof", "extern", "typedef", "struct", "union",
    "enum", "register", "inline", "default",
}

KEYWORDS_BEFORE_TYPE = {"static", "volatile", "const", "unsigned", "signed"}


# --------------------------------------------------------------------------
# 文本工具
# --------------------------------------------------------------------------

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def blank_comments(text: str) -> str:
    """把注释换成等长空格，保持后面算行号用的偏移量不变。"""
    def repl(match: re.Match) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    text = re.sub(r"/\*.*?\*/", repl, text, flags=re.S)
    text = re.sub(r"//[^\n]*", repl, text)
    return text


def blank_preprocessor(text: str) -> str:
    """把 # 开头的行换成空格（保留换行），否则缩进判定会被宏定义串味。"""
    return re.sub(r"^[ \t]*#.*$",
                  lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                  text, flags=re.M)


def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度（CJK 算 2 列）补齐，让中文表对齐。"""
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def align_up(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    return (value + alignment - 1) // alignment * alignment


# --------------------------------------------------------------------------
# 宏解析与求值
# --------------------------------------------------------------------------

class MacroTable:
    """解析 #define，并按 C 语义递归求值成整数/浮点数。"""

    _DEFINE_RE = re.compile(
        r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)(\([^)]*\))?[ \t]*(.*)$",
        re.M,
    )
    # 求值前的白名单：只允许数字、十六进制、运算符与括号。
    _SAFE_EXPR = re.compile(r"^[0-9a-fA-FxXeE.+\-*/%() \t]+$")
    _NUM_SUFFIX = re.compile(r"(?<=[0-9.])[uUlLfF]{1,3}\b")
    _IDENT = re.compile(r"[A-Za-z_]\w*")
    # 出现浮点字面量时才用 Python 的真除法，否则必须模仿 C 的整数除法。
    _FLOAT_LITERAL = re.compile(r"\d\.\d|\d[eE][-+]?\d")
    _TRUE_DIV = re.compile(r"(?<!/)/(?!/)")

    def __init__(self) -> None:
        self.raw: dict[str, str] = {}
        self.source: dict[str, str] = {}   # 宏名 -> 定义它的文件 label
        self.line: dict[str, int] = {}     # 宏名 -> 定义行号
        self._cache: dict[str, object] = {}
        self._pending: set[str] = set()

    def load(self, label: str, path: Path) -> None:
        text = read_text(path)
        body = blank_comments(text).replace("\\\n", " ")
        for match in self._DEFINE_RE.finditer(body):
            name, params, value = match.group(1), match.group(2), match.group(3)
            if params is not None:
                continue  # 函数式宏，本脚本按对象式宏处理
            self.raw[name] = value.strip()
            self.source[name] = label
            self.line[name] = line_of(body, match.start())

    def value(self, name: str):
        """返回宏的数值；解析不出就返回 None（调用方必须标注"未确认"）。"""
        if name in self._cache:
            return self._cache[name]
        if name in self._pending or name not in self.raw:
            return None
        self._pending.add(name)
        try:
            result = self.eval_expr(self.raw[name])
        finally:
            self._pending.discard(name)
        self._cache[name] = result
        return result

    def eval_expr(self, expr: str):
        """按 C 语义求值一个算术表达式，例如 "VOICE_FFT_SIZE / 2U"。

        关键点：C 的整数除法向零截断，Python 的 / 是真除法。只在表达式里
        确实出现浮点字面量时才用真除法，否则把 / 换成 //，否则
        VOICE_FRAME_LEN 这类宏会算成 400.0 而不是 400。
        """
        text = self._NUM_SUFFIX.sub("", expr)
        saw_float = [False]
        try:
            text = self._substitute(text, saw_float)
        except _UnresolvedMacro:
            return None
        if not self._SAFE_EXPR.match(text):
            return None
        if not saw_float[0] and not self._FLOAT_LITERAL.search(text):
            text = self._TRUE_DIV.sub("//", text)
        try:
            value = eval(compile(text, "<macro>", "eval"), {"__builtins__": {}}, {})
        except Exception:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    def int_value(self, name: str):
        """取一个必须是正整数的宏（数组维度、元素个数）。"""
        value = self.value(name)
        if value is None or isinstance(value, float):
            return None
        return int(value)

    def dim_count(self, dim: str):
        """求一个数组维度，维度本身可以是表达式（如 VOICE_FFT_SIZE / 2U）。"""
        value = self.eval_expr(dim) if not dim.strip().isdigit() else int(dim)
        if not isinstance(value, int) or value <= 0:
            return None
        return value

    def _substitute(self, expr: str, saw_float: list) -> str:
        def repl(match: re.Match) -> str:
            token = match.group(0)
            value = self.value(token)
            if value is None:
                raise _UnresolvedMacro(token)
            if isinstance(value, float):
                saw_float[0] = True
                return repr(value)
            return str(value)

        return self._IDENT.sub(repl, expr)

    def origin(self, name: str) -> str:
        label = self.source.get(name)
        if label is None:
            return "未找到定义"
        return f"{label}:{self.line[name]}"


class _UnresolvedMacro(Exception):
    pass


# --------------------------------------------------------------------------
# 结构体布局（从头文件成员声明推导）
# --------------------------------------------------------------------------

class Member:
    def __init__(self, decl: str, line: int) -> None:
        self.decl = decl
        self.line = line
        self.name = ""
        self.type = ""
        self.dims: list[str] = []
        self.size: int | None = None
        self.align: int | None = None
        self.offset: int | None = None
        self.unresolved: str | None = None


class StructInfo:
    def __init__(self, name: str, label: str, line: int) -> None:
        self.name = name
        self.label = label
        self.line = line
        self.members: list[Member] = []
        self.size: int | None = None
        self.align: int | None = None

    def member(self, name: str) -> Member | None:
        for item in self.members:
            if item.name == name:
                return item
        return None


_STRUCT_RE = re.compile(r"typedef\s+struct\s*\{(.*?)\}\s*([A-Za-z_]\w*)\s*;", re.S)
_MEMBER_RE = re.compile(
    r"^(?:(?:volatile|const|signed|unsigned|register)\s+)*"
    r"(?P<type>[A-Za-z_]\w*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<dims>(?:\[[^\]]*\])*)$"
)


def parse_struct(label: str, path: Path, name: str, macros: MacroTable) -> StructInfo:
    """label 是给人看的文件标签（如 voice_kws.h），name 是结构体名。"""
    text = read_text(path)
    body = blank_comments(text)
    match = re.search(
        r"typedef\s+struct\s*\{(?P<body>.*?)\}\s*" + re.escape(name) + r"\s*;",
        body, re.S,
    )
    if match is None:
        raise BudgetError(f"{label} 里找不到结构体 {name} 的定义")

    info = StructInfo(name, label, line_of(body, match.start()))
    for raw_member in match.group("body").split(";"):
        decl = " ".join(raw_member.split())
        if not decl or decl.startswith("#"):
            continue
        member = _MEMBER_RE.match(decl)
        if member is None:
            # 成员声明解析不了 -> 整个结构体标为未确认，而不是猜。
            fallback = Member(decl, line_of(body, match.start()))
            fallback.name = decl
            fallback.unresolved = f"成员声明无法解析: {decl!r}"
            info.members.append(fallback)
            continue
        item = Member(decl, line_of(body, match.start()))
        item.type = member.group("type")
        item.name = member.group("name")
        item.dims = re.findall(r"\[([^\]]*)\]", member.group("dims"))
        info.members.append(item)

    _layout_struct(info, macros)
    return info


def _layout_struct(info: StructInfo, macros: MacroTable) -> None:
    offset = 0
    max_align = 1
    for item in info.members:
        if item.unresolved:
            info.size = None
            info.align = None
            return
        prim = PRIM_TYPES.get(item.type)
        if prim is None:
            item.unresolved = f"未知类型 {item.type!r}（不在 C 基本类型表内）"
            info.size = None
            info.align = None
            return
        size, align = prim
        for dim in item.dims:
            count = macros.dim_count(dim)
            if count is None:
                item.unresolved = f"数组维度 {dim} 无法求值"
                info.size = None
                info.align = None
                return
            size *= count
        item.size = size
        item.align = align
        offset = align_up(offset, align)
        item.offset = offset
        offset += size
        max_align = max(max_align, align)
    info.size = align_up(offset, max_align)
    info.align = max_align


# --------------------------------------------------------------------------
# 定点声明解析（文件级 static / 函数内 static / 局部数组）
# --------------------------------------------------------------------------

_PLAIN_DECL_RE = re.compile(r"(?P<decl>[^;{}()]*);")
_DECL_PARTS_RE = re.compile(
    r"^(?P<quals>(?:(?:static|volatile|const|unsigned|signed|register)\s+)*)"
    r"(?P<type>[A-Za-z_]\w*)\s+"
    r"(?P<name>[A-Za-z_]\w*)\s*"
    r"(?P<dims>(?:\[[^\]]*\])*)$"
)


def decl_start(text: str, span_start: int, span_end: int) -> int:
    """_PLAIN_DECL_RE 的匹配可能把前面一整片被涂空的注释/宏也吞进来。

    真正属于这条声明的文本，是从匹配区间里第一个非空白字符开始的。
    返回这个位置，用它算行号与缩进才准。
    """
    found = re.search(r"\S", text[span_start:span_end])
    return span_end if found is None else span_start + found.start()


class DataObject:
    def __init__(self, file_label: str, line: int, storage: str, decl: str) -> None:
        self.file = file_label
        self.line = line
        self.storage = storage      # "文件级 static" / "函数内 static" / "函数内局部"
        self.decl = decl
        self.name = ""
        self.type = ""
        self.dims: list[str] = []
        self.scope = ""             # 函数名（函数内对象）
        self.size: int | None = None
        self.align: int | None = None
        self.note = ""

    def origin(self) -> str:
        return f"{self.file}:{self.line}"


def extract_function_body(text: str, func_name: str) -> tuple[str, int] | None:
    """返回 (函数体文本, 起始行号)，用于锁定某个函数内部的局部数组。"""
    match = re.search(r"^[A-Za-z_].*?\b" + re.escape(func_name) + r"\s*\(",
                      text, re.M | re.S)
    if match is None:
        return None
    brace = text.find("{", match.end())
    if brace < 0:
        return None
    depth = 0
    for idx in range(brace, len(text)):
        if text[idx] == "{":
            depth += 1
        elif text[idx] == "}":
            depth -= 1
            if depth == 0:
                return text[brace:idx + 1], line_of(text, brace)
    return None


def find_data_objects(file_label: str, path: Path, structs: dict[str, StructInfo],
                      macros: MacroTable) -> list[DataObject]:
    text = read_text(path)
    body = blank_preprocessor(blank_comments(text))
    found: list[DataObject] = []

    for match in _PLAIN_DECL_RE.finditer(body):
        decl = " ".join(match.group("decl").split())
        if not decl or decl.startswith("#"):
            continue
        parts = _DECL_PARTS_RE.match(decl)
        if parts is None:
            continue
        quals = parts.group("quals")
        type_name = parts.group("type")
        if type_name in NOT_A_TYPE:
            continue
        if "static" not in quals and type_name not in structs:
            continue
        # 只收有维度的数组或已识别类型/基本类型的对象定义。
        dims = re.findall(r"\[([^\]]*)\]", parts.group("dims"))
        if not dims and type_name not in structs and type_name not in PRIM_TYPES:
            continue

        offset = decl_start(body, match.start("decl"), match.end("decl"))
        line = line_of(body, offset)
        indent = body[body.rfind("\n", 0, offset) + 1:offset]
        # 本工程的文件级定义一律顶格；有缩进就说明在函数体里。
        is_file_scope = indent == ""
        is_static = "static" in quals
        if is_static and is_file_scope:
            storage = "文件级 static"
        elif is_static:
            storage = "函数内 static"
        elif is_file_scope:
            storage = "文件级（非 static）"
        else:
            continue  # 函数内的非 static 局部：单独按函数提取

        item = DataObject(file_label, line, storage, decl)
        item.type = type_name
        item.name = parts.group("name")
        item.dims = dims
        if not is_file_scope:
            item.scope = _enclosing_function(body, offset)
        _size_object(item, structs, macros)
        found.append(item)

    return found


def _enclosing_function(text: str, offset: int) -> str:
    """粗略找出 offset 所在的函数名（往前找最近的一个顶层 '函数名(' 行）。"""
    head = text[:offset]
    for match in reversed(list(re.finditer(r"^([A-Za-z_][\w \t*]*?)\b([A-Za-z_]\w*)\s*\(",
                                           head, re.M))):
        candidate = match.group(2)
        if candidate not in NOT_A_TYPE:
            return candidate
    return "?"


def _size_object(item: DataObject, structs: dict[str, StructInfo],
                 macros: MacroTable) -> None:
    struct = structs.get(item.type)
    if struct is not None:
        if struct.size is None:
            item.note = f"{item.type} 布局未确认"
            return
        size, align = struct.size, struct.align
    else:
        prim = PRIM_TYPES.get(item.type)
        if prim is None:
            item.note = f"未确认类型 {item.type}"
            return
        size, align = prim
    dims: list[str] = []
    for dim in item.dims:
        count = macros.dim_count(dim)
        if count is None:
            item.note = f"数组维度 {dim} 未确认"
            return
        size *= count
        dims.append(f"{count:,}")
    item.size = size
    item.align = align
    item.note = f"{item.type}[{']['.join(dims)}]" if dims else item.type


# --------------------------------------------------------------------------
# 模型数据（Flash / .rodata）
# --------------------------------------------------------------------------

_ARRAY_RE = re.compile(
    r"^(?:const\s+)?(?P<type>[A-Za-z_]\w*)\s+"
    r"(?P<ptr>\*\s*const\s+|const\s+\*\s*const\s+|const\s+)?"
    r"(?P<name>[A-Za-z_]\w*)\s*\[(?P<count>[^\]]*)\]\s*=\s*\{(?P<body>.*?)\};",
    re.M | re.S,
)
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


class ModelArray:
    def __init__(self, name: str, type_spec: str, declared: int | None,
                 measured: int | None, elem_size: int, line: int,
                 is_pointer: bool = False) -> None:
        self.name = name
        self.type_spec = type_spec
        self.declared = declared
        self.measured = measured
        self.elem_size = elem_size
        self.line = line
        self.is_pointer = is_pointer

    @property
    def count(self) -> int | None:
        if self.declared is not None and self.measured is not None:
            return self.declared if self.declared == self.measured else None
        return self.declared if self.declared is not None else self.measured

    @property
    def size(self) -> int | None:
        count = self.count
        return None if count is None else count * self.elem_size


def parse_model_arrays(path: Path, macros: MacroTable) -> list[ModelArray]:
    text = read_text(path)
    body = blank_comments(text)
    arrays: list[ModelArray] = []
    for match in _ARRAY_RE.finditer(body):
        type_name = match.group("type")
        prim = PRIM_TYPES.get(type_name)
        if prim is None:
            continue
        is_pointer = match.group("ptr") is not None and "*" in match.group("ptr")
        # 指针数组：元素是 32 位目标上的一个指针（Cortex-M85 字长 4）。
        elem_size = 4 if is_pointer else prim[0]
        count_expr = " ".join(match.group("count").split())
        declared = macros.dim_count(count_expr)
        init_body = match.group("body")
        if is_pointer:
            # 指针数组的初值是字符串字面量，按引号数计数。
            measured = len(_STRING_RE.findall(init_body))
        else:
            measured = len(re.findall(r"-?\d+", init_body))
        arrays.append(ModelArray(match.group("name"), match.group("type"),
                                 declared, measured, elem_size,
                                 line_of(body, match.start()),
                                 is_pointer=is_pointer))
    return arrays


# --------------------------------------------------------------------------
# 基线：ELF 实测 / 链接脚本 / board.h
# --------------------------------------------------------------------------

class BudgetError(Exception):
    """无法完成统计（缺文件、缺工具链等）。"""


class Baseline:
    def __init__(self) -> None:
        self.elf_text: int | None = None
        self.elf_data: int | None = None
        self.elf_bss: int | None = None
        self.elf_path: str | None = None
        self.size_tool: str | None = None
        self.segment_used_end: int | None = None
        self.segment_used_end_source: str = "未确认"
        self.ram_start: int | None = None
        self.ram_length: int | None = None
        self.flash_start: int | None = None
        self.flash_length: int | None = None
        self.sram_size_kib: int | None = None
        self.sram_end: int | None = None
        self.heap_begin: int | None = None
        self.heap_end: int | None = None
        self.present_voice_symbols: list[str] = []
        self.missing_voice_symbols: list[str] = []
        # 符号名 -> (定义它的目标文件, 字节数)。同名符号可能来自别的模块，
        # 光凭 nm 名字对上是会误报的（本工程里 smart_hand_uart.o 就有一个
        # 同名的 g_stats），所以必须看 map 里的归属。
        self.symbol_owner: dict[str, tuple[str, int | None]] = {}
        self.notes: list[str] = []

    def classify(self, name: str, voice_stems: set[str]) -> str:
        owner = self.symbol_owner.get(name)
        if owner is None:
            return "不在当前 ELF 中"
        obj, size = owner
        stem = Path(obj).stem
        if stem in voice_stems:
            return f"已链接进当前 ELF（{obj}，{size:,} B）" if size else f"已链接进当前 ELF（{obj}）"
        return f"同名符号来自 {obj}（不是语音模块，勿混算）"

    @property
    def voice_linked(self) -> bool:
        """True once the voice objects actually participate in the link.

        This changes what the surplus numbers MEAN. Before integration the
        voice statics are hypothetical and get projected against free space.
        After integration they are already inside .bss, so fw_ram_used,
        heap_size and flash_used all include them -- subtracting the same
        budget a second time reports a deficit that does not exist.
        """
        return bool(self.present_voice_symbols)

    @property
    def heap_size(self) -> int | None:
        if self.heap_begin is None or self.heap_end is None:
            return None
        return self.heap_end - self.heap_begin

    @property
    def fw_ram_used(self) -> int | None:
        """固件已占 RAM：优先用 map/ELF 里 __RAM_segment_used_end__ 的实测偏移。"""
        if self.segment_used_end is not None and self.ram_start is not None:
            return self.segment_used_end - self.ram_start
        if self.elf_data is not None and self.elf_bss is not None:
            return self.elf_data + self.elf_bss
        return None

    @property
    def fw_flash_used(self) -> int | None:
        if self.elf_text is None or self.elf_data is None:
            return None
        return self.elf_text + self.elf_data


_MAP_SYMBOL_RE = re.compile(
    r"^\s*\.(?P<section>bss|data|rodata|ram_noinit|ram_zero)\.(?P<name>[A-Za-z_]\w*)\s+"
    r"0x[0-9a-fA-F]+\s+0x(?P<size>[0-9a-fA-F]+)\s+(?P<obj>\S+)\s*$",
    re.M,
)


def parse_map_symbols(map_path: Path) -> dict[str, tuple[str, int | None]]:
    """从 rtthread.map 抓"符号 -> 定义它的目标文件"，用来防止同名符号误判。"""
    text = read_text(map_path)
    owners: dict[str, tuple[str, int | None]] = {}
    for match in _MAP_SYMBOL_RE.finditer(text):
        name = match.group("name")
        if name in owners:
            continue
        owners[name] = (match.group("obj"), int(match.group("size"), 16))
    return owners


def find_toolchain(explicit: Path | None) -> Path | None:
    candidates = []
    if explicit is not None:
        candidates.append(explicit)
    candidates.append(DEFAULT_TOOLCHAIN_DIR)
    for candidate in candidates:
        if (candidate / "arm-none-eabi-size.exe").exists() or \
           (candidate / "arm-none-eabi-size").exists():
            return candidate
    return None


def tool(toolchain: Path | None, name: str) -> str | None:
    if toolchain is not None:
        for suffix in (".exe", ""):
            candidate = toolchain / f"{name}{suffix}"
            if candidate.exists():
                return str(candidate)
    found = shutil.which(name)
    return found


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return (result.stdout or "") + (result.stderr or "")


def collect_baseline(firmware_root: Path, toolchain: Path | None,
                     voice_symbols: list[str]) -> Baseline:
    base = Baseline()
    elf = firmware_root / "Debug" / "rtthread.elf"
    map_file = firmware_root / "Debug" / "rtthread.map"
    ld = firmware_root / "board" / "linker_scripts" / "fsp.ld"
    board_h = firmware_root / "board" / "board.h"

    # --- 链接脚本口径 ---
    if ld.exists():
        text = read_text(ld)
        for attr, name in (("ram_start", "RAM_START"), ("ram_length", "RAM_LENGTH"),
                           ("flash_start", "FLASH_START"),
                           ("flash_length", "FLASH_LENGTH")):
            match = re.search(rf"^{name}\s*=\s*(0x[0-9a-fA-F]+)\s*;", text, re.M)
            if match:
                setattr(base, attr, int(match.group(1), 16))
    else:
        base.notes.append(f"链接脚本不存在: {ld}")

    # --- board.h 口径（只读，绝不修改） ---
    if board_h.exists():
        text = read_text(board_h)
        match = re.search(r"#define\s+RA_SRAM_SIZE\s+(\d+)", text)
        if match:
            base.sram_size_kib = int(match.group(1))
        match = re.search(
            r"#define\s+RA_SRAM_END\s*\(\s*(0x[0-9a-fA-F]+)\s*\+\s*RA_SRAM_SIZE\s*\*\s*(\d+)\s*\)",
            text)
        if match:
            base.sram_end = int(match.group(1), 16) + base.sram_size_kib * int(match.group(2))
    else:
        base.notes.append(f"board.h 不存在: {board_h}")

    # --- ELF 实测 ---
    if elf.exists():
        base.elf_path = str(elf)
        size_cmd = tool(toolchain, "arm-none-eabi-size")
        nm_cmd = tool(toolchain, "arm-none-eabi-nm")
        if size_cmd:
            base.size_tool = size_cmd
            first = run([size_cmd, str(elf)]).strip().splitlines()
            for line in first:
                fields = line.split()
                if len(fields) >= 4 and fields[0].isdigit():
                    base.elf_text = int(fields[0])
                    base.elf_data = int(fields[1])
                    base.elf_bss = int(fields[2])
                    break
        else:
            base.notes.append("找不到 arm-none-eabi-size，ELF 基线标记为未确认")

        if nm_cmd:
            nm_out = run([nm_cmd, str(elf)])
            for line in nm_out.splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[-1] == "__RAM_segment_used_end__":
                    try:
                        base.segment_used_end = int(fields[0], 16)
                        base.segment_used_end_source = "ELF 符号实测 (arm-none-eabi-nm)"
                    except ValueError:
                        pass

        # map 文件用来判"符号到底属于哪个目标文件"，这是实测归属信息。
        if map_file.exists():
            base.symbol_owner = parse_map_symbols(map_file)

        base.present_voice_symbols = sorted(
            s for s in voice_symbols
            if (own := base.symbol_owner.get(s)) is not None
            and Path(own[0]).stem in VOICE_OBJECT_STEMS)
        base.missing_voice_symbols = sorted(s for s in voice_symbols
                                            if s not in base.present_voice_symbols)

        # 没有 nm 时退回 map 文件（同样属于实测，不是估算）。
        if base.segment_used_end is None and map_file.exists():
            match = re.search(r"(0x[0-9a-fA-F]+)\s+__RAM_segment_used_end__",
                              read_text(map_file))
            if match:
                base.segment_used_end = int(match.group(1), 16)
                base.segment_used_end_source = "rtthread.map 实测"
    else:
        base.notes.append(f"ELF 不存在: {elf}（基线未确认）")

    if base.sram_end is not None:
        base.heap_end = base.sram_end
        base.heap_begin = base.segment_used_end
    return base


# --------------------------------------------------------------------------
# 交叉验证：用目标编译器实测 sizeof / _Alignof
# --------------------------------------------------------------------------

VERIFY_HEADER = "\n".join([
    '#include "voice_audio.h"',
    '#include "voice_audio_titan.h"',
    '#include "voice_kws.h"',
    '#include "voice_features.h"',
    "",
])


def verify_with_compiler(structs: dict[str, StructInfo], macros: MacroTable,
                         voice_symbols: list[str]) -> dict:
    """用 C 编译器实测结构体 sizeof/_Alignof，和 Python 推导的布局对账。

    返回 {"ok": bool, "compiler": str|None, "rows": [...], "note": str}
    """
    arm_gcc = None
    arm_candidates = [
        DEFAULT_TOOLCHAIN_DIR / "arm-none-eabi-gcc.exe",
        DEFAULT_TOOLCHAIN_DIR / "arm-none-eabi-gcc",
    ]
    for candidate in arm_candidates:
        if candidate.exists():
            arm_gcc = (str(candidate), ["-mcpu=cortex-m85", "-mthumb"],
                       tool(DEFAULT_TOOLCHAIN_DIR, "arm-none-eabi-nm"))
            break
    if arm_gcc is None:
        host_gcc = shutil.which("gcc")
        host_nm = shutil.which("nm")
        if host_gcc and host_nm:
            arm_gcc = (host_gcc, [], host_nm)
    if arm_gcc is None:
        return {"ok": None, "compiler": None, "rows": [],
                "note": "无可用 C 编译器，结构体尺寸未能交叉验证（标记为未确认）"}

    compiler, extra_flags, nm_path = arm_gcc
    lines = [VERIFY_HEADER]
    wanted: list[tuple[str, str, int | None]] = []   # (符号名, 说明, 期望值)

    def emit(symbol: str, expr: str, expected: int | None) -> None:
        lines.append(f"const char {symbol}[{expr}];")
        wanted.append((symbol, expr, expected))

    for name, info in structs.items():
        emit(f"vmb_sz_{name}", f"sizeof({name})", info.size)
        emit(f"vmb_al_{name}", f"_Alignof({name})", info.align)
        for member in info.members:
            if member.unresolved:
                continue
            emit(f"vmb_mb_{name}_{member.name}",
                 f"sizeof((({name} *)0)->{member.name})", member.size)

    # 线程栈上的两个局部数组（voice_kws_predict 内部）。
    for symbol, expr, macro, elem in (
        ("vmb_local_features", "sizeof(int8_t[VOICE_MODEL_INPUT_COUNT])",
         "VOICE_MODEL_INPUT_COUNT", 1),
        ("vmb_local_probabilities", "sizeof(float[VOICE_MODEL_CLASS_COUNT])",
         "VOICE_MODEL_CLASS_COUNT", 4),
    ):
        count = _macro_or_none(macros, macro)
        if count is not None:
            emit(symbol, expr, count * elem)

    with tempfile.TemporaryDirectory(prefix="vmb_") as tmp:
        src = Path(tmp) / "probe.c"
        obj = Path(tmp) / "probe.o"
        src.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [compiler, "-c", "-I", str(RT_DIR), "-I", str(GEN_DIR),
               *extra_flags, str(src), "-o", str(obj)]
        out = run(cmd)
        if not obj.exists():
            return {"ok": None, "compiler": compiler, "rows": [],
                    "note": f"交叉验证编译失败，尺寸未验证:\n{out.strip()[:800]}"}
        nm_out = run([nm_path, "-S", "-t", "d", str(obj)])

    measured: dict[str, int] = {}
    for line in nm_out.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[1].isdigit():
            measured[fields[3]] = int(fields[1])

    rows = []
    ok = True
    for symbol, expr, expected in wanted:
        actual = measured.get(symbol)
        match = actual is not None and actual == expected
        if not match:
            ok = False
        rows.append({"symbol": symbol, "expr": expr,
                     "expected": expected, "measured": actual, "match": match})
    return {"ok": ok, "compiler": compiler, "rows": rows, "note": ""}


def _macro_or_none(macros: MacroTable, name: str):
    value = macros.value(name)
    return None if value is None else int(value)


def force_utf8_stdout() -> None:
    """让中文在管道/重定向下也是 UTF-8，而不是随控制台代码页乱掉。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------

def build_report(args) -> dict:
    macros = MacroTable()
    for label, path in MACRO_SOURCES.items():
        if path.exists():
            macros.load(label, path)

    firmware_root = Path(args.firmware_root)
    board_h = firmware_root / "board" / "board.h"
    if board_h.exists():
        macros.load("board.h", board_h)

    # --- 结构体布局 ---
    structs: dict[str, StructInfo] = {}
    for name, path in STRUCT_SOURCES.items():
        if path.exists():
            structs[name] = parse_struct(path.name, path, name, macros)

    # --- 源码里的数据对象 ---
    objects: list[DataObject] = []
    for label, path in VOICE_C_SOURCES.items():
        if path.exists():
            objects.extend(find_data_objects(label, path, structs, macros))

    # voice_kws_predict 的线程栈局部数组（非 static，所以上面那遍不会收）。
    stack_locals: list[DataObject] = []
    predict_path = VOICE_C_SOURCES["voice_kws.c"]
    if predict_path.exists():
        body = blank_comments(read_text(predict_path))
        located = extract_function_body(body, "voice_kws_predict")
        if located is not None:
            func_text, start_line = located
            for match in _PLAIN_DECL_RE.finditer(func_text):
                decl = " ".join(match.group("decl").split())
                parts = _DECL_PARTS_RE.match(decl)
                if parts is None or "static" in parts.group("quals"):
                    continue
                dims = re.findall(r"\[([^\]]*)\]", parts.group("dims"))
                if not dims:
                    continue
                position = decl_start(func_text, match.start("decl"),
                                      match.end("decl"))
                item = DataObject(
                    "voice_kws.c",
                    start_line + line_of(func_text, position) - 1,
                    "函数内局部（线程栈）", decl)
                item.name = parts.group("name")
                item.type = parts.group("type")
                item.dims = dims
                item.scope = "voice_kws_predict"
                _size_object(item, structs, macros)
                stack_locals.append(item)

    # --- 语音模块假设的实例化（当前仓库没有任何地方实例化它们） ---
    workspace = [o for o in objects if o.storage == "文件级（非 static）"]
    standalone = [o for o in objects if o.storage in ("文件级 static", "函数内 static")]

    # --- 模型数据 ---
    model_arrays = parse_model_arrays(MODEL_DATA_C, macros) if MODEL_DATA_C.exists() else []
    model_bytes = sum(a.size or 0 for a in model_arrays)
    model_conflicts = [a for a in model_arrays
                       if a.declared is not None and a.measured is not None
                       and a.declared != a.measured]

    voice_symbol_names = [o.name for o in standalone]

    # --- 基线实测 ---
    toolchain = find_toolchain(Path(args.toolchain) if args.toolchain else None)
    baseline = collect_baseline(firmware_root, toolchain, voice_symbol_names)

    # --- 交叉验证 ---
    if args.no_verify:
        verification = {"ok": None, "compiler": None, "rows": [],
                        "note": "已用 --no-verify 跳过"}
    else:
        verification = verify_with_compiler(structs, macros, voice_symbol_names)
    if verification["ok"] is False:
        structs_verified = False
    elif verification["ok"] is True:
        structs_verified = True
    else:
        structs_verified = None

    # --- 合计 ---
    static_total = sum(o.size for o in standalone if o.size is not None)
    static_unconfirmed = [o for o in standalone if o.size is None]

    workspace_structs = [
        ("voice_kws_t", structs.get("voice_kws_t")),
        ("voice_frontend_t", structs.get("voice_frontend_t")),
    ]
    workspace_bytes = sum(info.size for _, info in workspace_structs
                          if info is not None and info.size is not None)
    stack_bytes = sum(o.size for o in stack_locals if o.size is not None)

    full_static = static_total + workspace_bytes
    full_conservative = full_static + stack_bytes

    # --- 余量 ---
    ram_remaining = None
    if baseline.ram_length is not None and baseline.fw_ram_used is not None:
        ram_remaining = baseline.ram_length - baseline.fw_ram_used

    heap_size = baseline.heap_size
    heap_remaining = None
    if heap_size is not None and baseline.fw_ram_used is not None:
        heap_remaining = heap_size  # HEAP_BEGIN 已扣除固件占用，这就是堆的可用量

    flash_used = baseline.fw_flash_used
    flash_remaining = None
    if baseline.flash_length is not None and flash_used is not None:
        flash_remaining = baseline.flash_length - flash_used

    # --- 判定 ---
    checks: list[dict] = []

    if ram_remaining is None:
        checks.append(_check("链接脚本 RAM 区", None,
                             "RAM_LENGTH 或 ELF 基线未确认，无法判定", True))
    else:
        if baseline.voice_linked:
            # 固件已用里已经包含语音的 .bss，不能再减一次。
            checks.append(_check(
                "链接脚本 RAM 区", ram_remaining,
                f"RAM_LENGTH {baseline.ram_length:,} B - 固件已用 "
                f"{baseline.fw_ram_used:,} B（语音已计入其中）",
                ram_remaining >= 0))
        else:
            need = full_conservative
            checks.append(_check(
                "链接脚本 RAM 区", ram_remaining - need,
                f"RAM_LENGTH {baseline.ram_length:,} B - 固件已用 "
                f"{baseline.fw_ram_used:,} B - 语音完整预算 {need:,} B",
                ram_remaining - need >= 0))

    if heap_size is None:
        checks.append(_check("RT-Thread 堆", None,
                             "堆范围未确认（缺 __RAM_segment_used_end__ 或 RA_SRAM_END）", True))
    else:
        if baseline.voice_linked:
            # HEAP_BEGIN 随 .bss 上移，heap_size 已经是语音之后的余量。
            checks.append(_check(
                "RT-Thread 堆", heap_size,
                "HEAP_BEGIN 随 .bss 上移，此值已扣除语音 static；"
                "任何新增 rt_malloc 都要从这里面出",
                heap_size >= 0))
        else:
            # 语音模块按设计必须走 .bss：只拿"已存在的 static"去比堆。
            checks.append(_check(
                "RT-Thread 堆（仅示意，语音不走堆）", heap_size - static_total,
                f"堆可用 {heap_size:,} B - 语音 static {static_total:,} B；"
                f"工作区 {workspace_bytes:,} B 也必须落 .bss，不是 rt_malloc",
                heap_size - static_total >= 0))

    if flash_remaining is None:
        checks.append(_check("Flash", None, "FLASH_LENGTH 或 ELF 基线未确认，无法判定", True))
    else:
        checks.append(_check(
            "Flash（.rodata/.text）",
            (flash_remaining if baseline.voice_linked else flash_remaining - model_bytes),
            f"FLASH_LENGTH {baseline.flash_length:,} B - 固件已用 {flash_used:,} B"
            + ("" if baseline.voice_linked else f" - 模型 {model_bytes:,} B"),
            (flash_remaining if baseline.voice_linked else flash_remaining - model_bytes) >= 0))

    if not structs_verified:
        checks.append(_check(
            "结构体尺寸交叉验证", None,
            verification["note"] or "编译器实测与解析结果不一致（见下表）",
            structs_verified is None))

    failures = [c for c in checks if not c["pass"]]

    return {
        "firmware_root": str(firmware_root),
        "macros": macros,
        "structs": structs,
        "standalone": standalone,
        "stack_locals": stack_locals,
        "workspace_structs": workspace_structs,
        "model_arrays": model_arrays,
        "model_bytes": model_bytes,
        "model_conflicts": model_conflicts,
        "verification": verification,
        "structs_verified": structs_verified,
        "baseline": baseline,
        "totals": {
            "static_total": static_total,
            "static_unconfirmed": static_unconfirmed,
            "workspace_bytes": workspace_bytes,
            "stack_bytes": stack_bytes,
            "full_static": full_static,
            "full_conservative": full_conservative,
            "ram_remaining": ram_remaining,
            "heap_size": heap_size,
            "heap_remaining": heap_remaining,
            "flash_used": flash_used,
            "flash_remaining": flash_remaining,
        },
        "checks": checks,
        "failures": failures,
    }


def _check(name: str, remaining, detail: str, passed: bool) -> dict:
    return {"name": name, "remaining": remaining, "detail": detail, "pass": passed}


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def section_of(obj: DataObject) -> str:
    if obj.storage == "函数内局部（线程栈）":
        return "线程栈"
    return ".bss"


def print_table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [display_width(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], display_width(cell))
    line = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    print(line)
    print("| " + " | ".join(pad(h, widths[i]) for i, h in enumerate(headers)) + " |")
    print(line)
    for row in rows:
        print("| " + " | ".join(pad(c, widths[i]) for i, c in enumerate(row)) + " |")
    print(line)


def render(report: dict, as_json: bool = False) -> int:
    macros: MacroTable = report["macros"]
    structs: dict[str, StructInfo] = report["structs"]
    baseline: Baseline = report["baseline"]
    totals = report["totals"]

    if as_json:
        payload = {
            "firmware_root": report["firmware_root"],
            "structs": {
                name: {
                    "bytes": info.size,
                    "align": info.align,
                    "source": f"{info.label}:{info.line}",
                    "verified_by_compiler": report["structs_verified"],
                    "members": [
                        {"name": m.name, "type": m.type, "dims": m.dims,
                         "bytes": m.size, "offset": m.offset,
                         "declared_at": f"{info.label}:{m.line}",
                         "unconfirmed": m.unresolved}
                        for m in info.members
                    ],
                }
                for name, info in structs.items()
            },
            "existing_statics": [
                {"name": o.name, "type": o.type, "dims": o.dims, "bytes": o.size,
                 "section": section_of(o), "storage": o.storage, "scope": o.scope,
                 "source": o.origin(), "note": o.note,
                 "elf_status": baseline.classify(o.name, VOICE_OBJECT_STEMS),
                 "linked_in_elf_from_voice_object":
                     o.name in baseline.present_voice_symbols}
                for o in report["standalone"]
            ],
            "workspace": [
                {"name": name, "bytes": info.size if info else None,
                 "section": ".bss（静态分配）",
                 "source": f"{info.label}:{info.line}" if info else "未确认"}
                for name, info in report["workspace_structs"]
            ] + [
                {"name": o.name, "bytes": o.size, "section": "线程栈",
                 "source": o.origin(), "note": f"{o.type}{o.decl[o.decl.find('['):]}"
                 if o.size is not None else o.note}
                for o in report["stack_locals"]
            ],
            "model_flash": {
                "total_bytes": report["model_bytes"],
                "arrays": [
                    {"name": a.name, "type": a.type_spec, "count_declared": a.declared,
                     "count_measured": a.measured, "elem_bytes": a.elem_size,
                     "bytes": a.size,
                     "source": f"voice_model_data.c:{a.line}"}
                    for a in report["model_arrays"]
                ],
            },
            "baseline": {
                "elf": baseline.elf_path,
                "text": baseline.elf_text, "data": baseline.elf_data,
                "bss": baseline.elf_bss,
                "fw_ram_used": baseline.fw_ram_used,
                "fw_flash_used": baseline.fw_flash_used,
                "ram_start": baseline.ram_start, "ram_length": baseline.ram_length,
                "flash_start": baseline.flash_start,
                "flash_length": baseline.flash_length,
                "segment_used_end": baseline.segment_used_end,
                "segment_used_end_source": baseline.segment_used_end_source,
                "heap_begin": baseline.heap_begin, "heap_end": baseline.heap_end,
                "heap_size": totals["heap_size"],
                "sram_size_kib": baseline.sram_size_kib,
                "voice_symbols_present_in_elf": baseline.present_voice_symbols,
                "voice_symbols_missing_from_elf": baseline.missing_voice_symbols,
                "notes": baseline.notes,
            },
            "macro_sources": {m: macros.origin(m) for m in sorted(macros.raw)},
            "totals": {k: v for k, v in totals.items() if k != "static_unconfirmed"},
            "checks": report["checks"],
            "ok": not report["failures"],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not report["failures"] else 1

    b = baseline
    print("=" * 78)
    print("OpenSignHand 语音模块静态内存预算")
    print("=" * 78)
    print(f"项目根目录   : {PROJECT_ROOT}")
    print(f"固件工程目录 : {report['firmware_root']}")
    print()

    # ---- 表 1：已存在的 static ----
    print("【表 1】语音模块已存在的 static（源码里已经写在 voice_audio_titan.c 的）")
    rows = []
    for obj in report["standalone"]:
        note = (f"{obj.storage}；{obj.note or obj.type}；{obj.origin()}；"
                f"{b.classify(obj.name, VOICE_OBJECT_STEMS)}")
        rows.append([obj.name, f"{obj.size:,}" if obj.size is not None else "未确认",
                     section_of(obj), note])
    rows.append(["—— 小计 ——", f"{totals['static_total']:,}", ".bss", "已存在的 static 合计"])
    print_table(rows, ["区域名", "字节数", "section", "备注"])
    print()

    # ---- 表 2：集成后才产生的工作区预算 ----
    print("【表 2】集成后才产生的工作区预算（当前仓库无任何代码实例化它们）")
    rows = []
    for name, info in report["workspace_structs"]:
        if info is None:
            rows.append([name, "未确认", ".bss", "头文件里找不到定义"])
            continue
        note = (f"调用方持有；{info.label}:{info.line}；成员："
                + ", ".join(f"{m.name}={m.size:,}" for m in info.members
                            if m.size is not None))
        rows.append([name, f"{info.size:,}", ".bss（静态分配）", note])
    for obj in report["stack_locals"]:
        note = (f"{obj.storage}；{obj.scope}() 内的非 static 局部；{obj.origin()}；"
                f"调用该函数时占用线程栈，不是 .bss")
        rows.append([obj.name, f"{obj.size:,}" if obj.size is not None else "未确认",
                     "线程栈", note])
    rows.append(["—— 小计 ——", f"{totals['workspace_bytes'] + totals['stack_bytes']:,}",
                 "—",
                 f"其中 .bss {totals['workspace_bytes']:,} B + 线程栈 "
                 f"{totals['stack_bytes']:,} B"])
    print_table(rows, ["区域名", "字节数", "section", "备注"])
    print()

    # ---- 表 3：模型数据（Flash） ----
    print("【表 3】模型数据 Flash 占用（voice_model_data.c 的 const 数组）")
    rows = []
    for arr in report["model_arrays"]:
        count = arr.count if arr.count is not None else None
        if count is None:
            note = (f"声明 {arr.declared} 与实测 {arr.measured} 不一致，未确认；"
                    f"voice_model_data.c:{arr.line}")
            rows.append([arr.name, "未确认", ".rodata", note])
            continue
        note = (f"{arr.type_spec}{' *' if arr.is_pointer else ''} × {count:,}"
                f"（元素 {arr.elem_size} B）；声明维度 {arr.declared}，"
                f"初值实测 {arr.measured}；voice_model_data.c:{arr.line}")
        if arr.is_pointer:
            note += "；指针指向的字符串字面量也在 .rodata，脚本未计入"
        rows.append([arr.name, f"{arr.size:,}", ".rodata", note])
    rows.append(["—— 小计 ——", f"{report['model_bytes']:,}", ".rodata",
                 "整体下载进 Flash，不占 RAM"])
    print_table(rows, ["区域名", "字节数", "section", "备注"])
    print()

    # ---- 表 4：基线 ----
    print("【表 4】既有基线（实测，非估算）")
    rows = []
    if b.elf_text is not None:
        rows.append([".text", f"{b.elf_text:,}", ".text",
                     f"arm-none-eabi-size 实测；{b.elf_path}"])
        rows.append([".data", f"{b.elf_data:,}", ".data", "arm-none-eabi-size 实测"])
        rows.append([".bss", f"{b.elf_bss:,}", ".bss", "arm-none-eabi-size 实测"])
        rows.append(["固件已用 RAM", f"{b.fw_ram_used:,}", ".data+.bss",
                     f"__RAM_segment_used_end__ - RAM_START；来源：{b.segment_used_end_source}"])
        rows.append(["固件已用 Flash", f"{b.fw_flash_used:,}", ".text+.data",
                     "arm-none-eabi-size 实测"])
    else:
        rows.append(["固件基线", "未确认", "—", "ELF 或工具链缺失"])
    if b.ram_length is not None:
        rows.append(["链接脚本 RAM 区", f"{b.ram_length:,}", "—",
                     f"fsp.ld: RAM_START=0x{b.ram_start:08X}, "
                     f"RAM_LENGTH=0x{b.ram_length:X}"])
    if totals["heap_size"] is not None:
        rows.append(["RT-Thread 堆可用", f"{totals['heap_size']:,}", "—",
                     f"board.h: HEAP_END=RA_SRAM_END=0x{b.heap_end:08X}"
                     f" (RA_SRAM_SIZE={b.sram_size_kib} KiB)，"
                     f"HEAP_BEGIN=__RAM_segment_used_end__=0x{b.heap_begin:08X}"])
    if b.flash_length is not None:
        rows.append(["Flash 区", f"{b.flash_length:,}", "—",
                     f"fsp.ld: FLASH_START=0x{b.flash_start:08X}, "
                     f"FLASH_LENGTH=0x{b.flash_length:X}"])
    for note in b.notes:
        rows.append(["提示", "—", "—", note])
    print_table(rows, ["区域名", "字节数", "section", "备注"])
    print()

    # ---- 结论 ----
    print("【结论】")
    static_total = totals["static_total"]
    workspace = totals["workspace_bytes"]
    stack = totals["stack_bytes"]
    full = totals["full_static"]
    conservative = totals["full_conservative"]

    print(f"  语音模块已存在的 static 合计        : {static_total:,} B")
    print(f"  语音模块集成后的完整预算（.bss）    : {full:,} B"
          f"  （static {static_total:,} + 工作区 {workspace:,}）")
    print(f"  含线程栈局部数组的保守值            : {conservative:,} B"
          f"  （另加 features/probabilities {stack:,}）")
    print()
    if totals["static_unconfirmed"]:
        print("  未确认的 static："
              + ", ".join(f"{o.name}({o.note})" for o in totals["static_unconfirmed"]))
        print()

    if totals["ram_remaining"] is not None:
        left = totals["ram_remaining"] - conservative
        print(f"  相对链接脚本 RAM 区的剩余           : {totals['ram_remaining']:,} B"
              f"；扣掉完整预算后 {left:,} B")
    else:
        print("  相对链接脚本 RAM 区的剩余           : 未确认")
    heap_size = totals["heap_size"]
    if heap_size is not None:
        print(f"  相对 RT-Thread 堆的剩余             : {heap_size:,} B"
              f"（堆的总可用量，未扣运行期已分配）")
        print(f"      -> 语音模块的 static {static_total:,} B 占堆 {static_total / heap_size:.1%}；"
              f"加上工作区 {full:,} B 占堆 {full / heap_size:.1%}")
        print("      -> 结论：语音模块必须走静态分配（.bss），不要走 rt_malloc。")
        print("         堆只有上面这个数字，被固件的 .bss 挤掉了绝大部分 RAM。")
    else:
        print("  相对 RT-Thread 堆的剩余             : 未确认")
    print()
    if totals["flash_remaining"] is not None:
        print(f"  Flash 余量                          : {totals['flash_remaining']:,} B"
              f"；模型 {report['model_bytes']:,} B 占 Flash 的 "
              f"{report['model_bytes'] / b.flash_length:.2%}")
        print(f"      -> 扣掉模型后剩 "
              f"{totals['flash_remaining'] - report['model_bytes']:,} B")
    else:
        print("  Flash 余量                          : 未确认")
    print()

    # ---- 校验 ----
    print("【校验】")
    for check in report["checks"]:
        if check["remaining"] is None:
            mark = "跳过" if check["pass"] else "失败"
            print(f"  [{mark}] {check['name']}：{check['detail']}")
        else:
            mark = "通过" if check["pass"] else "失败"
            print(f"  [{mark}] {check['name']}：剩余 {check['remaining']:,} B —— "
                  f"{check['detail']}")
    print()

    print("【ELF 链接状态】语音模块的 .o 在当前固件里存在吗？")
    if b.symbol_owner or b.present_voice_symbols:
        for obj in report["standalone"]:
            print(f"  {pad(obj.name, 22)}: {b.classify(obj.name, VOICE_OBJECT_STEMS)}")
        if b.present_voice_symbols:
            print("  => 语音模块已经参与链接，上面的 static 是已经吃掉的 RAM。")
        else:
            print("  => 语音模块尚未参与链接：上面的 static 是"
                  "「一旦集成到固件就会吃掉」的 RAM，当前 ELF 里还没有它们。")
    else:
        print("  未确认（ELF/map/nm 不可用）")
    print()

    # ---- 交叉验证 ----
    print("【结构体尺寸交叉验证】")
    verification = report["verification"]
    if verification["ok"] is None:
        print(f"  {verification['note']}")
    else:
        print(f"  编译器: {verification['compiler']}")
        bad = [r for r in verification["rows"] if not r["match"]]
        if not bad:
            print(f"  解析推导与编译器实测一致（{len(verification['rows'])} 项）")
        else:
            print("  以下项解析值与实测不一致：")
            for row in bad:
                print(f"    {row['expr']}: 解析 {row['expected']} vs 实测 {row['measured']}")
    print()

    if report["model_conflicts"]:
        print("【模型数据告警】声明维度与初值个数不一致："
              + ", ".join(a.name for a in report["model_conflicts"]))
        print()

    skipped = [c for c in report["checks"] if c["remaining"] is None]
    if report["failures"]:
        print("!! 预算超限 !!")
        for check in report["failures"]:
            print(f"   - {check['name']}: {check['detail']}")
        return 1
    if skipped:
        print(f"其余已核对的区域在预算内；有 {len(skipped)} 项因基线缺失无法判定："
              + "、".join(c["name"] for c in skipped))
        return 0
    print("全部区域在预算内。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="统计 OpenSignHand 语音模块的静态内存预算（只读，不改任何固件文件）")
    parser.add_argument("--firmware-root", default=str(DEFAULT_FIRMWARE_ROOT),
                        help="titan_uart_test 工程目录（链接脚本/board.h/ELF 所在）")
    parser.add_argument("--toolchain", default=None,
                        help="GNU ARM 工具链 bin 目录（默认用 RT-Thread Studio 里那套）")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过用 C 编译器交叉验证结构体尺寸")
    args = parser.parse_args(argv)

    try:
        report = build_report(args)
    except BudgetError as exc:
        print(f"无法完成统计：{exc}", file=sys.stderr)
        return 2
    return render(report, as_json=args.json)


if __name__ == "__main__":
    force_utf8_stdout()
    sys.exit(main())
