"""Loopback checks for the offline course preview. No device or model."""
import json
import shutil
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from smart_hand.host.offline_demo import (
    AI_MARK, BANNER, DEFAULT_PORT, HOST, PREVIEW_MARK, build_catalog, make_server,
    render_download,
)


ROOT = Path(__file__).resolve().parents[2]


class OfflineDemoTests(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://{}:{}".format(HOST, self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            return response.status, response.headers, response.read().decode("utf-8")

    def test_server_is_loopback_and_pages_are_explicitly_sample_data(self):
        self.assertEqual(DEFAULT_PORT, 8880)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        status, headers, page = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("connect-src 'none'", headers.get('Content-Security-Policy', ''))
        self.assertIn("frame-ancestors 'none'", headers.get('Content-Security-Policy', ''))
        self.assertEqual(headers.get('Referrer-Policy'), 'no-referrer')
        self.assertIn(BANNER, page)
        self.assertIn(AI_MARK, page)
        self.assertIn(PREVIEW_MARK, page)
        self.assertNotIn("127.0.0.1:8765", page)
        self.assertNotIn("fetch(", page)
        self.assertNotIn("localStorage", page)
        self.assertNotIn("WebSocket", page)
        self.assertNotIn("开始训练", page)
        self.assertNotIn("烧录", page)
        status, headers, body = self.get("/download/example-report.txt")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers.get("Content-Disposition", ""))
        self.assertTrue(body.startswith(BANNER))
        for title in ("示例 · 静态达标", "示例 · 动态未完成", "示例 · 检测中断"):
            self.assertIn(title, page)
            self.assertIn(title, body)
            self.assertIn("示例", body)
        self.assertIn("不是设备识别", body)
        self.assertIn("翻页不是通过", body)
        request = urllib.request.Request(self.base + "/", method="POST", data=b"{}")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 405)
        missing = urllib.request.Request(self.base + "/api/v1/ai/course-advice")
        with self.assertRaises(urllib.error.HTTPError) as missing_caught:
            urllib.request.urlopen(missing, timeout=5)
        self.assertEqual(missing_caught.exception.code, 404)

    def test_catalog_follows_sequence_source_and_does_not_invent_authority(self):
        catalog = build_catalog()
        by_id = {}
        self.assertEqual([level["name"] for level in catalog["levels"]], ["初级", "中级", "高级"])
        for level in catalog["levels"]:
            for lesson in level["lessons"]:
                by_id[lesson["id"]] = lesson
                self.assertTrue(lesson["boundary"])
        self.assertEqual(by_id["word_hello"]["steps"], ["伸出食指", "切换竖拇指"])
        from sign_sequence import SEQUENCES, INSTRUCTIONS
        for lesson_id, steps in SEQUENCES.items():
            self.assertEqual(by_id[lesson_id]["steps"], [label for _key, label in steps])
            self.assertEqual(by_id[lesson_id]["instructions"], [INSTRUCTIONS[key] for key, _label in steps])
            self.assertTrue(by_id[lesson_id]["preview"])
        for lesson_id in ("basic_open_palm", "basic_fist", "basic_v_sign"):
            self.assertEqual(by_id[lesson_id]["steps"], [])
            self.assertEqual(by_id[lesson_id]["instructions"], [])
            self.assertFalse(by_id[lesson_id]["preview"])
        self.assertIn("尚未经专业核验", by_id["word_hello"]["boundary"])
        self.assertIn("不代表立即报警", by_id["signal_help"]["boundary"])
        source = (ROOT / "smart_hand" / "host" / "offline_demo.py").read_text(encoding="utf-8")
        for banned in ("DEEPSEEK", "environ", "8765", "0.0.0.0", "serial", "cv2", "requests"):
            self.assertNotIn(banned, source)

    def test_preview_paging_and_text_card_do_not_score_or_persist(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required")
        _status, _headers, page = self.get("/")
        script = page.split('id="demo-script">', 1)[1].split("</script>", 1)[0]
        catalog = page.split('id="catalog-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        driver = r"""
const assert=require('assert');
const elements={};
function el(id){if(!elements[id])elements[id]={id,textContent:'',className:'',hidden:false,disabled:false,value:'',
setAttribute(k,v){this[k]=v;},removeAttribute(k){delete this[k];},focus(){this.focused=true;},
appendChild(child){this.children=this.children||[];this.children.push(child);return child;}};return elements[id];}
el('catalog-data').textContent=CATALOG_TEXT;
const catalog=JSON.parse(el('catalog-data').textContent);
const created=[];
global.document={
getElementById:el,
createElement(tag){const node=el(tag+created.length);node.tagName=tag.toUpperCase();created.push(node);return node;},
querySelectorAll(){return created.filter(node=>node.className==='lesson');},
addEventListener(type,fn){if(type==='keydown')global.onKey=fn;},
body:{classList:{toggle(name){this.value=this.value===name?'':name;return Boolean(this.value);},value:''}}
};
""" + script + r"""
const thanks=[].concat(...catalog.levels.map(l=>l.lessons)).find(lesson=>lesson.id==='word_thanks');
const button=created.find(node=>node.textContent===thanks.name);
button.onclick();
assert(el('step-status').textContent.includes('教学预览，不计成绩'));
assert(el('step-score').textContent==='未评分');
assert(el('step-label').textContent===thanks.steps[0]);
assert(el('step-instruction').textContent===thanks.instructions[0]);
el('next-step').onclick();
assert(el('step-label').textContent===thanks.steps[1]);
assert(el('step-instruction').textContent===thanks.instructions[1]);
assert(el('step-score').textContent==='未评分');
assert(!el('step-status').textContent.includes('已通过'));
let prevented=false;
global.onKey({key:'ArrowRight',target:{tagName:'BODY'},preventDefault(){prevented=true;}});
assert(prevented);
assert(el('step-label').textContent===thanks.steps[2]);
assert(el('step-score').textContent==='未评分');
global.onKey({key:'ArrowLeft',target:{tagName:'TEXTAREA'}});
assert(el('step-label').textContent===thanks.steps[2]);
const card=created.find(node=>node.textContent==='谢谢你的帮助。');
card.onclick();
assert(el('communication-text').textContent==='谢谢你的帮助。');
assert(el('communication-text').innerHTML===undefined);
el('communication-input').value='<img src=x onerror=alert(1)>';
el('communication-show').onclick();
assert(el('communication-text').textContent==='<img src=x onerror=alert(1)>');
el('communication-input').value='字'.repeat(81);
el('communication-show').onclick();
assert(el('communication-display').hidden===true);
assert(el('communication-text').textContent==='');
el('easy-read').onclick();
assert(el('easy-read')['aria-pressed']==='true');
global.onKey({key:'Escape',target:{tagName:'BODY'}});
assert(el('communication-text').textContent==='');
assert(!el('step-status').textContent.includes('通过成绩'));
const help=[].concat(...catalog.levels.map(l=>l.lessons)).find(l=>l.id==='signal_help');
created.find(node=>node.textContent===help.name).onclick();
el('next-step').onclick();el('next-step').onclick();
assert(el('step-instruction').textContent===help.instructions[2]);
assert(el('step-instruction').textContent.includes('人工复核'));
assert(el('step-score').textContent==='未评分');
const hold=el('step-label').textContent;el('next-step').onclick();
assert(el('step-label').textContent===hold&&el('step-score').textContent==='未评分');
const staticLesson=[].concat(...catalog.levels.map(l=>l.lessons)).find(l=>l.id==='basic_open_palm');
created.find(node=>node.textContent===staticLesson.name).onclick();
assert(el('preview').hidden===true&&el('step-instruction').textContent==='');
console.log('OFFLINE_DEMO_OK');
"""
        driver = driver.replace("CATALOG_TEXT", json.dumps(catalog, ensure_ascii=False))
        result = subprocess.run([node, "-"], input=driver, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("OFFLINE_DEMO_OK", result.stdout)
        self.assertIn("示例 · 静态达标", render_download())
