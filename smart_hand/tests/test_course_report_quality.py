"""Report regressions based on observed counts, not device accuracy claims."""
import json
import re
import shutil
import subprocess
import unittest

from smart_hand.maixcam2.web_stream import PreviewServer, _CONTROL_PAGE
from smart_hand.tests.test_web_stream import FakeConnection, FakeSocketModule


class CourseReportQualityTests(unittest.TestCase):
    def run_page(self, checks, saved=None, exports=""):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for real-page report test")
        script = _CONTROL_PAGE.decode("utf-8").split("<script>", 1)[1].split("</script>", 1)[0]
        if exports:
            # Expose real closure members for assertions, never reimplement their logic.
            close = script.rfind("}())")
            self.assertGreater(close, 0)
            script = script[:close] + exports + "\n" + script[close:]
        driver = r"""
const assert=require('assert'),elements={},intervals=[],aiRequests=[],downloads=[],posts=[],keyListeners=[];
let focusId=null;
function el(id){if(!elements[id])elements[id]={textContent:'',className:'',style:{},hidden:false,disabled:false,children:[],appendChild(v){this.children.push(v);},focus(){focusId=id;},getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;}};return elements[id];}
const beginner=el('beginner');beginner['data-level']='beginner';
const advanced=el('advanced');advanced['data-level']='advanced';
const communicationButtons=COMMUNICATION_TEXT.map((text,i)=>{const button=el('communication_'+i);button['data-communication']=text;return button;});
global.document={getElementById:el,querySelectorAll(q){return q==='[data-level]'?[beginner,advanced]:q==='[data-communication]'?communicationButtons:[];},addEventListener(type,fn){if(type==='keydown')keyListeners.push(fn);},body:{appendChild(){},removeChild(){}},createElement:()=>({click(){}})};
let now=1000,sign={state:'IDLE'},savedText=INITIAL_STORAGE;
global.performance={now:()=>now};
global.localStorage={getItem:()=>savedText,setItem:(k,v)=>{savedText=v;},removeItem:()=>{savedText=null;}};
global.setInterval=(fn,ms)=>intervals.push({fn,ms});
global.Blob=function(parts){downloads.push(String(parts[0]));};
global.URL={createObjectURL:()=>'blob:test',revokeObjectURL:()=>{}};
global.fetch=(url,opts)=>{
if(url.includes('/api/v1/ai/course-advice')){aiRequests.push(JSON.parse(opts.body));return Promise.resolve({ok:true,json:()=>Promise.resolve({advice:'检查入镜与光照，再短时复练。',source:'model',fallback_reason:null})});}
if(opts&&opts.method==='POST'){posts.push(url);return Promise.resolve({json:()=>Promise.resolve({state:'queued'})});}
return Promise.resolve({json:()=>Promise.resolve(url.includes('/api/v1/sign/status')?sign:{can_submit:false,state:'idle'})});};
""".replace("INITIAL_STORAGE", json.dumps(json.dumps(saved) if saved is not None else None))
        driver = driver.replace("COMMUNICATION_TEXT", json.dumps(re.findall(
            r'data-communication="([^"]+)"', _CONTROL_PAGE.decode('utf-8'))))
        driver += script + r"""
async function flush(){for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));}
async function state(x){sign=x;now+=500;intervals.find(i=>i.ms===500).fn();await flush();}
async function run(){await flush();
""" + checks + r"""
console.log('REPORT_QUALITY_OK');}
run().catch(e=>{console.error(e);process.exit(1);});
"""
        result = subprocess.run([node, "-"], input=driver, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("REPORT_QUALITY_OK", result.stdout)

    def test_three_completed_courses_report_process_issues_and_saved_gate_hold(self):
        self.run_page(r"""
el('historyToggle').onclick();beginner.onclick();await flush();
for(let i=0;i<5;i++)await state({state:'IMITATING',lesson_id:'basic_open_palm',stable_ms:i===4?312:0,
recognition_error_code:i===0?'NO_HAND':i===1?'LOW_CONFIDENCE':'OK',session_error_code:i>=2?'WRONG_GESTURE':'OK'});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',confidence:0,stable_ms:0,error_code:'NO_HAND',
session_error_code:'OK',course_confidence:1,course_stable_ms:350});
let report=el('levelReport').textContent;
assert(!report.includes('没有明确的失败或低置信度项目'));
assert(report.includes('张开手掌已达标，但过程记录出现'));
assert(report.includes('低置信度 1 次'));assert(report.includes('未检测到手 1 次'));
assert(report.includes('手型与目标不符 3 次'));
assert(report.includes('课程通过时的保持值：350 毫秒'));
assert(report.includes('记录时识别分数 100%；原因 无'));
assert(!report.includes('旧动态'));assert(!report.includes('二维动作'));
el('levelNext').onclick();await flush();
for(let i=0;i<16;i++)await state({state:'IMITATING',lesson_id:'basic_fist',stable_ms:i===15?5137:0,
recognition_error_code:i<6?'NO_HAND':i<8?'LOW_CONFIDENCE':'OK',session_error_code:i>=8&&i<15?'WRONG_GESTURE':'OK'});
await state({state:'COMPLETE',lesson_id:'basic_fist',confidence:.96,course_confidence:.96,stable_ms:0,
course_stable_ms:370,error_code:'OK',session_error_code:'OK'});
el('levelNext').onclick();await flush();
for(let i=0;i<3;i++)await state({state:'IMITATING',lesson_id:'basic_v_sign',stable_ms:0,recognition_error_code:i<2?'NO_HAND':'OK'});
await state({state:'COMPLETE',lesson_id:'basic_v_sign',confidence:1,course_confidence:1,stable_ms:0,
course_stable_ms:320,error_code:'OK',session_error_code:'OK'});
report=el('levelReport').textContent;
assert(report.includes('完成率：100%'));assert(report.includes('未完成：0'));
assert(report.includes('握拳已达标，但过程记录出现低置信度 2 次、未检测到手 6 次、手型与目标不符 7 次'));
assert(report.includes('V 形手势已达标，但过程记录出现未检测到手 2 次'));
assert(report.includes('未采到非零读数'));assert(!report.includes('最长连续稳定 0'));
assert(report.includes('课程通过时的保持值：320 毫秒'));
assert(report.includes('不是独立做错次数'));assert(report.includes('复练握拳：先让整只手完整入镜'));
assert(el('levelAiFocus').textContent.includes('握拳'));
assert.deepStrictEqual(JSON.parse(savedText).sessions[0].rows.map(r=>r.completion_stable_ms),[350,370,320]);
el('levelAiAdvice').onclick();await flush();
assert.deepStrictEqual(aiRequests[0].rows.map(r=>r.completion_stable_ms),[350,370,320]);
assert.strictEqual(aiRequests[0].rows[2].samples.max_stable_ms,0);
assert(!JSON.stringify(aiRequests[0]).match(/image|landmark|servo/i));
el('levelDownload').onclick();assert(downloads[0].includes('课程通过时的保持值：320 毫秒'));
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
""")

    def test_real_page_separates_completed_course_from_live_hand_and_stale_feedback(self):
        self.run_page(r"""
let completed={state:'COMPLETE',lesson_id:'signal_help',session_error_code:'OK',course_gesture_id:'FIST',
course_confidence:.96,motion_progress:{completed_steps:3,total_steps:3,complete:true,scope:'2d_sequence_prototype'},
gesture_id:'OPEN_PALM',confidence:.99,stable_ms:120,valid:true,error_code:'OK',
recognition_observed_ms:100,recognition_fresh:true};
await state(completed);
assert(el('courseOutcome').textContent.includes('已通过'));
assert(el('courseOutcome').textContent.includes('3/3'));
assert(el('courseOutcomeDetail').textContent.includes('握拳'));
assert(el('gesture').textContent.includes('张开手掌'));
assert(el('stepTag4').textContent.includes('动作序列原型达标'));
assert(!el('stepTag5').textContent.includes('结束关键帧'));
await state({...completed,gesture_id:'UNKNOWN',valid:false,confidence:0,stable_ms:0,
recognition_error_code:'NO_HAND',recognition_observed_ms:200});
assert(el('gesture').textContent==='未检测到手');assert(el('confidence').textContent==='--');
assert(el('validity').textContent==='未检测到手');assert(el('hudGesture').textContent==='未检测到手');
assert(el('courseOutcome').textContent.includes('已通过'));assert(el('courseOutcomeDetail').textContent.includes('握拳'));
await state({...completed,recognition_error_code:'vision_read_failed',recognition_observed_ms:250});
assert(el('gesture').textContent==='识别暂不可用');assert(el('confidence').textContent==='--');
assert(el('healthVision').className==='health-val warn');assert(el('courseOutcome').textContent.includes('已通过'));
// Repeated HTTP responses with the same observation cannot renew live age.
for(let i=0;i<4;i++)await state(completed);
assert(el('gesture').textContent==='识别已过期');assert(el('validity').textContent==='已过期');
assert(el('healthVision').className==='health-val warn');
assert(el('courseOutcome').textContent.includes('已通过'));
await state({...completed,recognition_observed_ms:300});assert(el('gesture').textContent==='张开手掌');
now+=1600;intervals.find(i=>i.ms===200).fn();
assert(el('gesture').textContent==='识别已过期');assert(el('confidence').textContent==='--');
assert(el('courseOutcome').textContent.includes('已通过'));
await state({...completed,recognition_observed_ms:400,recognition_fresh:false});
assert(el('gesture').textContent==='识别已过期');
await state({state:'LESSON_SELECTED',lesson_id:'basic_v_sign'});
assert(el('courseOutcome').textContent==='尚未完成课程');
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
""")

    def test_result_and_live_metadata_are_bounded_whitelisted_scalars(self):
        status={"state":"COMPLETE","course_gesture_id":"FIST","recognition_observed_ms":100,
                "recognition_age_ms":1600,"recognition_fresh":False,"raw_points":[1,2]}
        server=PreviewServer(sign_status_provider=lambda:status)
        parsed=json.loads(server._sign_status_response().split(b"\r\n\r\n",1)[1])
        self.assertEqual(parsed["course_gesture_id"], "FIST")
        self.assertFalse(parsed["recognition_fresh"])
        self.assertEqual(parsed["recognition_age_ms"], 1600)
        self.assertNotIn("raw_points", parsed)
        status.update(state="IMITATING",recognition_observed_ms=True,
                      recognition_age_ms=-1,recognition_fresh="true")
        parsed=json.loads(server._sign_status_response().split(b"\r\n\r\n",1)[1])
        for key in ("course_gesture_id","recognition_observed_ms","recognition_age_ms","recognition_fresh"):
            self.assertNotIn(key, parsed)

    def test_legacy_zero_hold_is_missing_evidence_not_a_failed_pose(self):
        self.run_page(r"""
beginner.onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_open_palm',stable_ms:0});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',stable_ms:0,confidence:1,error_code:'OK',course_stable_ms:0});
const report=el('levelReport').textContent;
assert(report.includes('课程通过时的保持值：未记录'));
assert(report.includes('不能将缺失或网页的 0 值理解为没有保持'));
assert(report.includes('没有明确的失败或低置信度项目'));
assert(!report.includes('最长连续稳定 0'));
el('levelAiAdvice').onclick();await flush();assert(!('completion_stable_ms' in aiRequests[0].rows[0]));
""")

    def test_dynamic_final_hold_is_not_claimed_as_static_completion_hold(self):
        self.run_page(r"""
advanced.onclick();await flush();
await state({state:'IMITATING',lesson_id:'word_hello',recognition_error_code:'LOW_CONFIDENCE',stable_ms:0,
motion_progress:{completed_steps:1,total_steps:2,complete:false,scope:'2d_sequence_prototype'}});
await state({state:'COMPLETE',lesson_id:'word_hello',course_stable_ms:900,confidence:.95,
motion_progress:{completed_steps:2,total_steps:2,complete:true,scope:'2d_sequence_prototype'}});
const report=el('levelReport').textContent;
assert(report.includes('二维动作序列原型通过'));assert(!report.includes('课程通过时的保持值'));
assert(report.includes('低置信度 0 次'));assert(!report.includes('结束关键帧'));
el('levelAiAdvice').onclick();await flush();assert(!('completion_stable_ms' in aiRequests[0].rows[0]));
""")

    def test_history_rejects_fabricated_hold_but_restores_new_and_old_rows(self):
        row = {"lesson_id": "basic_open_palm", "state": "COMPLETE", "duration_s": 10,
               "confidence": "95%", "error_code": "OK", "completion_stable_ms": 350,
               "samples": {"observations": 3, "low_confidence": 1, "no_hand": 0,
                           "wrong_gesture": 0, "vision_stale": 0, "max_stable_ms": 120}}
        session = {"id": "qa_session", "level": "beginner", "plan": ["basic_open_palm"],
                   "time": 1000, "rows": [row]}
        saved = {"version": 1, "enabled": True, "sessions": [session]}
        self.run_page("assert(el('historyStatus').textContent.includes('已恢复'));", saved)
        row.pop("completion_stable_ms")
        self.run_page("assert(el('historyStatus').textContent.includes('已恢复'));", saved)
        row["completion_stable_ms"] = True
        self.run_page("assert(el('historyStatus').textContent.includes('已忽略'));", saved)

    def test_course_evidence_transport_rejects_invalid_values(self):
        for hold, score, accepted_hold, accepted_score in (
            (350, .95, True, True), (True, True, False, False),
            (350.0, float("nan"), False, False), (600001, float("inf"), False, False),
            (-1, -1, False, False), ("350", "0.95", False, False),
        ):
            with self.subTest(hold=hold, score=score):
                conn = FakeConnection(b"GET /api/v1/sign/status HTTP/1.1\r\n\r\n")
                status = {"state": "COMPLETE", "course_stable_ms": hold, "course_confidence": score,
                          "raw_points": [1, 2], "stable_ms": 0}
                server = PreviewServer(socket_module=FakeSocketModule([conn]),
                                       sign_status_provider=lambda: status)
                self.assertTrue(server.start())
                server.poll()
                result = json.loads(bytes(conn.sent).split(b"\r\n\r\n", 1)[1])
                self.assertEqual("course_stable_ms" in result, accepted_hold)
                self.assertEqual("course_confidence" in result, accepted_score)
                self.assertNotIn("raw_points", result)


if __name__ == "__main__":
    unittest.main()
