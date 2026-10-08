"""Loopback-only course preview. It does not open devices or call a model.

Start from the snapshot root:

    python -B -X utf8 smart_hand/host/offline_demo.py
"""

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIX_DIR = ROOT / "smart_hand" / "maixcam2"
PAGE_PATH = Path(__file__).with_name("offline_demo.html")
WEB_STREAM_PATH = MAIX_DIR / "web_stream.py"
HOST = "127.0.0.1"
DEFAULT_PORT = 8880
BANNER = "离线演示：示例数据，非设备识别或真实训练成绩"
PREVIEW_MARK = "教学预览，不计成绩"
AI_MARK = "离线演示未调用模型"

_LESSON_RE = re.compile(
    r"'(?P<id>basic_[a-z_]+|word_[a-z_]+|signal_help)'\s*:\s*\{"
    r"name:'(?P<name>[^']*)',emoji:'(?P<emoji>[^']*)',"
    r"cat:'(?P<cat>[^']*)',desc:'(?P<desc>[^']*)'\}"
)
_CONTEXT_RE = re.compile(
    r"(?P<id>basic_[a-z_]+|word_[a-z_]+|signal_help)\s*:\s*\{"
    r"intent:'(?P<intent>[^']*)',example:'(?P<example>[^']*)',"
    r"card:'(?P<card>[^']*)'\}"
)
_LEVEL_RE = re.compile(
    r"(beginner|intermediate|advanced)\s*:\s*\{name:'([^']+)',"
    r"lessons:\[([^\]]+)\]\}"
)

_BOUNDARIES = {
    "signal_help": (
        "不是国家通用手语词，也不代表立即报警。"
        "本系统只练习二维动作，不判断危险、不联系任何人。"
    ),
    "word": (
        "这节课的名称表示练习情境。当前动作组合是项目二维实验原型，"
        "尚未经专业核验为该词的标准手语打法。"
    ),
    "shape": (
        "只验证有限手型，不判断语义、身体位置或面部表情，"
        "也不认证手指字母或交流能力。"
    ),
}


def _boundary(lesson_id):
    if lesson_id == "signal_help":
        return _BOUNDARIES["signal_help"]
    if lesson_id.startswith("word_"):
        return _BOUNDARIES["word"]
    return _BOUNDARIES["shape"]


def _load_sequences():
    if str(MAIX_DIR) not in sys.path:
        sys.path.insert(0, str(MAIX_DIR))
    from sign_sequence import SEQUENCES, INSTRUCTIONS
    return {
        lesson_id: {
            "titles": [label for _key, label in steps],
            "instructions": [INSTRUCTIONS[key] for key, _label in steps],
        }
        for lesson_id, steps in SEQUENCES.items()
    }


def _load_page_copy():
    source = WEB_STREAM_PATH.read_text(encoding="utf-8")
    lessons = {
        match.group("id"): {
            "name": match.group("name"),
            "emoji": match.group("emoji"),
            "category": match.group("cat"),
            "motion": match.group("desc"),
        }
        for match in _LESSON_RE.finditer(source)
    }
    contexts = {
        match.group("id"): {
            "intent": match.group("intent"),
            "example": match.group("example"),
            "card": match.group("card"),
        }
        for match in _CONTEXT_RE.finditer(source)
    }
    levels = []
    for match in _LEVEL_RE.finditer(source):
        ids = re.findall(r"'([^']+)'", match.group(3))
        levels.append({"id": match.group(1), "name": match.group(2), "lessons": ids})
    if [item["id"] for item in levels] != ["beginner", "intermediate", "advanced"]:
        raise RuntimeError("course levels in web_stream.py were not found")
    return lessons, contexts, levels


def example_reports():
    """Fixed sample write-ups. The numbers are not device results."""
    return [
        {
            "id": "static",
            "title": "示例 · 静态达标",
            "body": (
                "示例。课程：张开手掌。终态：完成。通过时保持：320 毫秒。"
                "这是编写好的示例记录，不是设备识别，也不是真实训练成绩。"
                "网页轮询次数没有出现在本例中，不能换算成准确率。"
            ),
        },
        {
            "id": "dynamic",
            "title": "示例 · 动态未完成",
            "body": (
                "示例。课程：谢谢。终态：未完成。步骤进度停在第 1/5 步。"
                "教学预览里的上一动作、下一动作不计成绩，翻页不是通过。"
                "这不是标准手语认证，也不是真机验收。"
            ),
        },
        {
            "id": "interrupted",
            "title": "示例 · 检测中断",
            "body": (
                "示例。状态：未检测到手。本次不能判断学习者的动作能力，"
                "也不能把中断写成手型错误。这不是设备日志。"
            ),
        },
    ]


def build_catalog():
    lessons, contexts, levels = _load_page_copy()
    sequences = _load_sequences()
    if set(lessons) != set(contexts):
        raise RuntimeError("lesson descriptions and expression context do not match")
    missing = [lesson_id for lesson_id in sequences if lesson_id not in lessons]
    if missing:
        raise RuntimeError("sequence lessons missing from the page copy: {}".format(missing))
    items = []
    for level in levels:
        rows = []
        for lesson_id in level["lessons"]:
            if lesson_id not in lessons:
                raise RuntimeError("unknown lesson {}".format(lesson_id))
            info = lessons[lesson_id]
            context = contexts[lesson_id]
            sequence = sequences.get(lesson_id, {"titles": [], "instructions": []})
            steps = list(sequence["titles"])
            rows.append({
                "id": lesson_id,
                "name": info["name"],
                "emoji": info["emoji"],
                "category": info["category"],
                "motion": info["motion"],
                "intent": context["intent"],
                "example": context["example"],
                "card": context["card"],
                "boundary": _boundary(lesson_id),
                "steps": steps,
                "instructions": list(sequence["instructions"]),
                "preview": bool(steps),
            })
        items.append({"id": level["id"], "name": level["name"], "lessons": rows})
    return {"banner": BANNER, "levels": items, "reports": example_reports(), "ai": AI_MARK}


def render_page(catalog):
    template = PAGE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(catalog, ensure_ascii=False).replace("</", "<\\/")
    if "__CATALOG_JSON__" not in template:
        raise RuntimeError("offline demo template is missing the catalog marker")
    return template.replace("__CATALOG_JSON__", payload)


def render_download():
    lines = [
        BANNER,
        "示例训练报告。以下三段都是示例，不是设备识别或真实训练成绩。",
        AI_MARK,
        "",
    ]
    for report in example_reports():
        lines.append(report["title"])
        lines.append(report["body"])
        lines.append("示例标识：本段是示例。")
        lines.append("")
    return "\n".join(lines)


class DemoHandler(BaseHTTPRequestHandler):
    catalog = None
    page = None
    download = None

    def log_message(self, format_string, *args):
        print("offline demo: " + (format_string % args))

    def _send(self, status, body, content_type, filename=None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; connect-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="{}"'.format(filename))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self._send(405, "离线演示不接受上传。\n", "text/plain; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, self.page, "text/html; charset=utf-8")
            return
        if path == "/download/example-report.txt":
            self._send(200, self.download, "text/plain; charset=utf-8",
                       "OpenSignHand_offline_example_report.txt")
            return
        self._send(404, "未找到该页。\n", "text/plain; charset=utf-8")


def make_server(port=DEFAULT_PORT):
    catalog = build_catalog()
    DemoHandler.catalog = catalog
    DemoHandler.page = render_page(catalog)
    DemoHandler.download = render_download()
    return ThreadingHTTPServer((HOST, port), DemoHandler)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    if args.port <= 0 or args.port > 65535:
        raise SystemExit("port must be between 1 and 65535")
    server = make_server(args.port)
    print("OpenSignHand offline demo at http://{}:{}/".format(HOST, server.server_address[1]))
    print(BANNER)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("offline demo stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
