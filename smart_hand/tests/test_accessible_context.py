"""Real-page tests: communication remains independent of AI and actuator routes."""
import unittest
import json
from smart_hand.tests import test_course_report_quality as harness
from smart_hand.maixcam2.web_stream import _CONTROL_PAGE


class AccessibleContextTests(unittest.TestCase):
    def test_device_l_course_name_and_hud_match_shape_only_boundary(self):
        from smart_hand.tests.test_sign_core import lesson_catalog
        name = lesson_catalog()["basic_l_shape"]["name_zh"]
        self.run_page(r"""
await state({state:'LESSON_SELECTED',lesson_id:'basic_l_shape',lesson_name:DEVICE_NAME});
assert.strictEqual(el('lesson').textContent,'L 形基础手型原型');
assert.strictEqual(el('hudLesson').textContent,el('lesson').textContent);
assert(!el('lesson').textContent.includes('手指字母'));
assert(el('meaningBoundary').textContent.includes('不认证手指字母'));
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);
""".replace('DEVICE_NAME', json.dumps(name)))

    def run_page(self, checks):
        # Reuse the real script harness without duplicating production logic.
        harness.CourseReportQualityTests.run_page(self, checks, exports=
            "globalThis.EXPRESSION_CONTEXT=EXPRESSION_CONTEXT;"
            "globalThis.LESSON_INFO=LESSON_INFO;globalThis.updateDetail=updateDetail;")

    def test_all_courses_have_context_and_explicit_semantic_boundaries(self):
        self.run_page(r"""
assert.deepStrictEqual(Object.keys(EXPRESSION_CONTEXT).sort(),Object.keys(LESSON_INFO).sort());
for(const id of Object.keys(LESSON_INFO)){
 updateDetail(id);
 assert(el('meaningIntent').textContent.length>10);
 assert(el('meaningExample').textContent.length>10);
 assert(!el('meaningCard').disabled);
 if(id.startsWith('word_'))assert(el('meaningBoundary').textContent.includes('尚未经专业核验'));
 else if(id!=='signal_help')assert(el('meaningBoundary').textContent.includes('不判断语义'));
}
updateDetail('signal_help');assert(el('meaningSource').href==='https://canadianwomen.org/signal-for-help/');
assert(el('meaningBoundary').textContent.includes('不代表立即报警'));
updateDetail('unrecognized');assert(el('meaningCard').disabled);
assert(el('meaningIntent').textContent.includes('选择课程后'));
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);
""")

    def test_manual_card_works_during_offline_and_no_hand_without_requests(self):
        self.run_page(r"""
await state({state:'UNAVAILABLE',link_online:false,error_code:'NO_HAND'});
updateDetail('word_thanks');el('meaningCard').onclick();
assert(el('communicationText').textContent==='谢谢你的帮助。');
assert.strictEqual(el('communicationDisplay').hidden,false);
await state({state:'IMITATING',lesson_id:'word_hello',error_code:'NO_HAND'});
assert(el('communicationText').textContent==='谢谢你的帮助。'); // recognition cannot translate or overwrite intent
el('communicationClose').onclick();assert(el('communicationDisplay').hidden);
assert(el('communicationText').textContent==='');assert(el('communicationInput').value==='');
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);assert(savedText===null);
""")

    def test_custom_text_is_bounded_text_only_and_never_saved_or_uploaded(self):
        self.run_page(r"""
el('communicationInput').value='  <img src=x onerror=alert(1)>  ';
el('communicationShow').onclick();
assert.strictEqual(el('communicationText').textContent,'<img src=x onerror=alert(1)>');
assert(!el('communicationText').innerHTML);
el('communicationInput').value='字'.repeat(81);el('communicationShow').onclick();
assert(el('communicationDisplay').hidden);assert(el('communicationStatus').textContent.includes('超过 80'));
assert(el('communicationText').textContent===''); // invalid replacement cannot keep old intent visible
el('communicationInput').value='😀'.repeat(80);el('communicationShow').onclick();
assert(!el('communicationDisplay').hidden);assert(Array.from(el('communicationText').textContent).length===80);
el('communicationClose').onclick();el('communicationInput').value='   ';el('communicationShow').onclick();
assert(el('communicationDisplay').hidden);assert(el('communicationStatus').textContent.includes('请先选择'));
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);assert(savedText===null);
""")

    def test_readability_toggles_independent_and_reversible(self):
        self.run_page(r"""
el('easyRead').onclick();el('highContrast').onclick();
assert(el('appShell').className==='app-shell easy-read high-contrast');
assert(el('easyRead')['aria-pressed']==='true');assert(el('highContrast')['aria-pressed']==='true');
el('easyRead').onclick();assert(el('appShell').className==='app-shell high-contrast');
el('highContrast').onclick();assert(el('appShell').className==='app-shell');
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);
""")

    def test_preset_buttons_and_escape_restore_focus_and_clear_text(self):
        self.run_page(r"""
assert(communicationButtons.length===4);
for(const button of communicationButtons){
 button.onclick();assert(!el('communicationDisplay').hidden);
 assert(el('communicationText').textContent===button['data-communication']);
 assert(focusId==='communicationDisplay');
 keyListeners.forEach(fn=>fn({key:'Escape'}));
 assert(el('communicationDisplay').hidden);assert(el('communicationText').textContent==='');
 assert(focusId.startsWith('communication_'));
}
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);
""")

    def test_private_card_excluded_from_course_history_report_and_ai_summary(self):
        self.run_page(r"""
el('communicationInput').value='PRIVATE_CARD_ONLY_123';el('communicationShow').onclick();
el('historyToggle').onclick();beginner.onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_open_palm',stable_ms:120,recognition_error_code:'OK'});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',course_confidence:1,course_stable_ms:320,session_error_code:'OK'});
el('levelAiAdvice').onclick();await flush();
assert(aiRequests.length===1);
assert(!JSON.stringify(aiRequests).includes('PRIVATE_CARD_ONLY_123'));
assert(!savedText.includes('PRIVATE_CARD_ONLY_123'));
el('levelDownload').onclick();assert(!downloads[0].includes('PRIVATE_CARD_ONLY_123'));
assert(el('communicationText').textContent==='PRIVATE_CARD_ONLY_123');
""")

    def test_accessibility_and_no_external_embedding_contract(self):
        html=_CONTROL_PAGE.decode('utf-8')
        self.assertIn('for="communicationInput"',html)
        self.assertIn('id="communicationDisplay" class="communication-display" hidden tabindex="-1"',html)
        self.assertIn('event.key===\'Escape\'',html)
        self.assertIn('button:focus-visible',html)
        self.assertIn('@media(max-width:760px){.context-grid{grid-template-columns:1fr}',html)
        self.assertNotIn('<iframe',html)
        self.assertNotIn('可用于手指字母和拼读训练',html)
        self.assertEqual(html.count('data-communication='),4)


if __name__=='__main__':
    unittest.main()
