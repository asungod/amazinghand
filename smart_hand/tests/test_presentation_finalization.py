"""Presentation checks; no changes to recognition or course gate semantics."""
import copy
from html.parser import HTMLParser
import unittest

from smart_hand.maixcam2.web_stream import _CONTROL_PAGE
from smart_hand.tests import test_course_report_quality as report_harness
from smart_hand.tests.test_maix_main import load_main_module


class PageStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a" and attrs.get("href", "").startswith("#"):
            self.links.append(attrs["href"][1:])


class PresentationFinalizationTests(unittest.TestCase):
    def run_page(self, checks):
        report_harness.CourseReportQualityTests.run_page(self, checks)

    def test_camera_precedes_context_and_navigation_keeps_all_targets(self):
        html = _CONTROL_PAGE.decode("utf-8")
        parser = PageStructure()
        parser.feed(html)
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertTrue(set(parser.links).issubset(set(parser.ids)))
        self.assertLess(html.index('id="streamImg"'), html.index('id="expression"'))
        self.assertLess(html.index('id="expression"'), html.index('id="analysis"'))
        self.assertIn('class="next-cue"', html)
        self.assertNotIn('.video-hud{position:absolute', html)
        self.assertIn('下载包含全部内容', html)

    def test_course_item_stage_and_next_action_remain_distinct(self):
        self.run_page(r"""
beginner.onclick();await flush();
await state({state:'LESSON_SELECTED',lesson_id:'basic_open_palm',can_start:true});
assert(el('currentCoursePosition').textContent.includes('初级课程 · 第 1/3 项'));
assert(el('currentTrainingPhase').textContent.startsWith('训练阶段：'));
assert(el('stepAlert').textContent.includes('人工确认'));
await state({state:'IMITATING',lesson_id:'basic_open_palm'});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',course_confidence:1,course_stable_ms:320,session_error_code:'OK'});
assert(el('stepAlert').textContent.includes('下一项：握拳'));
assert(el('reportOverview').textContent.includes('张开手掌 · 课程达标 · 通过时保持 320 毫秒'));
assert(el('levelReport').textContent.includes('课程通过时的保持值：320 毫秒'));
el('levelNext').onclick();await flush();
await state({state:'LESSON_SELECTED',lesson_id:'basic_fist',can_start:true});
assert(el('currentCoursePosition').textContent.includes('第 2/3 项：握拳'));
assert(!posts.some(p=>p.includes('/sign/start')));
""")

    def test_compact_report_limits_priorities_but_download_keeps_all_results(self):
        self.run_page(r"""
advanced.onclick();await flush();
const plan=['word_hello','word_thanks','word_no','word_attention','word_like','signal_help'];
const totals=[2,5,6,5,2,3];
for(let i=0;i<plan.length;i++){
 await state({state:'IMITATING',lesson_id:plan[i],recognition_error_code:'NO_HAND'});
 await state({state:i===5?'REVIEWED':'TIMEOUT',lesson_id:plan[i],error_code:'OK',session_error_code:i===5?'MANUAL_REVIEWED':'TIMEOUT',motion_progress:{completed_steps:1,total_steps:totals[i],complete:false,scope:'2d_sequence_prototype'}});
 if(i<5){el('levelNext').onclick();await flush();}
}
assert(el('reportOverview').textContent.split('\n').length===6);
assert(el('reportOverview').textContent.includes('人工复核（非自动通过）'));
assert(el('reportNextPractice').textContent.split('\n').length===3);
assert(el('levelAiCompleted').textContent==='0 项');
el('levelDownload').onclick();assert(downloads[0].includes('6. 求助信号'));
assert(downloads[0].includes('证据局限：'));assert(downloads[0].includes('人工复核记录：1 项'));
assert.strictEqual(aiRequests.length,0);
""")

    def test_advice_preview_keeps_source_and_selection_clears_old_text(self):
        self.run_page(r"""
beginner.onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_open_palm'});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',course_confidence:1,course_stable_ms:320,session_error_code:'OK'});
el('levelAiAdvice').onclick();await flush();
assert(el('advicePreview').textContent.includes('模型建议（仅供参考）'));
assert(el('advicePreview').textContent.includes('检查入镜与光照'));
advanced.onclick();await flush();
assert(!el('advicePreview').textContent.includes('检查入镜与光照'));
assert(!el('advicePreview').textContent.includes('模型建议（仅供参考）'));
assert.strictEqual(aiRequests.length,1);
""")

    def test_compact_device_caption_does_not_change_observation_or_v_name(self):
        main, _ = load_main_module(iterations=0)
        recognition = {"gesture_id": "V_SIGN", "confidence": .96,
                       "stable_ms": 359, "valid": True}
        previous = copy.deepcopy(recognition)
        lines = main.sign_overlay_lines(recognition, "IMITATING")
        self.assertEqual(lines, ("SIGN V_SIGN", "SIGN STATE IMITATING"))
        self.assertEqual(recognition, previous)
        self.assertIn("V 手势", main.translate_overlay_text(lines[0]))
        self.assertEqual(len(main.sign_overlay_lines(None, None)), 2)


if __name__ == "__main__":
    unittest.main()
