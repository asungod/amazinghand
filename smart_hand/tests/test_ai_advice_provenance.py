"""Real-page checks for the frozen advice response contract."""
import shutil
import subprocess
import unittest

from smart_hand.maixcam2.web_stream import _CONTROL_PAGE


class AdviceProvenanceTests(unittest.TestCase):
    def run_page(self, checks):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for real-page provenance test")
        script = _CONTROL_PAGE.decode("utf-8").split("<script>", 1)[1].split("</script>", 1)[0]
        driver = r"""
const assert=require('assert'),elements={},intervals=[],aiRequests=[],downloads=[],posts=[];
function el(id){if(!elements[id])elements[id]={textContent:'',className:'',style:{},hidden:false,disabled:false,value:'',children:[],appendChild(v){this.children.push(v);},getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;}};return elements[id];}
const beginner=el('beginner');beginner['data-level']='beginner';
const manual=el('manual');manual['data-lesson']='basic_fist';
global.document={getElementById:el,querySelectorAll(q){return q==='[data-level]'?[beginner]:q==='[data-lesson]'?[manual]:[];},body:{appendChild(){},removeChild(){}},createElement:()=>({click(){},setAttribute(){}})};
let now=1000,sign={state:'IDLE'},pending=null;
global.performance={now:()=>now};
global.setInterval=(fn,ms)=>intervals.push({fn,ms});
global.Blob=function(parts){downloads.push(String(parts[0]||''));};
global.URL={createObjectURL:()=>'blob:test',revokeObjectURL:()=>{}};
global.fetch=(url,opts)=>{
if(url.includes('/api/v1/ai/course-advice')){
aiRequests.push(JSON.parse(opts.body));
return new Promise((resolve,reject)=>{pending={resolve,reject};});
}
if(opts&&opts.method==='POST'){posts.push(url);return Promise.resolve({json:()=>Promise.resolve({state:'queued'})});}
return Promise.resolve({json:()=>Promise.resolve(url.includes('/api/v1/sign/status')?sign:{can_submit:false,state:'idle'})});};
""" + script + r"""
async function flush(){for(let i=0;i<6;i++)await new Promise(r=>setImmediate(r));}
async function state(x){sign=x;now+=500;intervals.find(i=>i.ms===500).fn();await flush();}
function fulfill(payload,ok=true){const job=pending;pending=null;job.resolve({ok,json:()=>Promise.resolve(payload)});}
function rejectFetch(){const job=pending;pending=null;job.reject(new Error('offline'));}
function badJson(){const job=pending;pending=null;job.resolve({ok:true,json:()=>Promise.reject(new Error('bad json'))});}
async function finishOne(){
beginner.onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_open_palm'});
await state({state:'COMPLETE',lesson_id:'basic_open_palm',confidence:1,error_code:'OK',course_confidence:1,course_stable_ms:320,session_error_code:'OK'});
}
async function run(){await flush();
""" + checks + r"""
console.log('ADVICE_PROVENANCE_OK');}
run().catch(e=>{console.error(e);process.exit(1);});
"""
        result = subprocess.run([node, "-"], input=driver, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("ADVICE_PROVENANCE_OK", result.stdout)

    def test_real_page_keeps_model_and_local_sources_distinct(self):
        self.run_page(r"""
const postsBefore=posts.length;
await finishOne();
el('communicationInput').value='PRIVATE_CARD_ONLY_123';
el('communicationShow').onclick();
el('levelAiAdvice').onclick();
fulfill({advice:'检查入镜后再练张开手掌。',source:'model',fallback_reason:null});
await flush();
assert(el('levelAiBadge').textContent==='模型建议');
assert(el('levelAiBadge').className.includes('ready'));
assert(el('levelAiResult').textContent.includes('模型建议（仅供参考）'));
assert(el('levelAiResult').textContent.includes('检查入镜后再练张开手掌。'));
assert(!el('levelAiResult').textContent.includes('本地规则建议'));
assert(!el('levelAiResult').textContent.includes('DeepSeek'));
assert(el('levelAiResult').innerHTML===undefined);
el('levelDownload').onclick();
assert(downloads.at(-1).includes('建议来源：模型建议（仅供参考）。'));
assert(downloads.at(-1).includes('不改变课程判定，不触发机械动作。'));
assert(downloads.at(-1).includes('检查入镜后再练张开手掌。'));
const reasons={
evidence_conflict:'证据与记录冲突，未采用模型原文',
provider_timeout:'模型响应超时，未采用模型结果',
provider_unavailable:'模型服务不可用，未采用模型结果',
provider_response_invalid:'模型返回无法使用，未采用模型结果',
provider_response_too_large:'模型返回过长，未采用模型结果'
};
for(const reason of Object.keys(reasons)){
el('levelAiAdvice').onclick();
fulfill({advice:'本地短句'+reason,source:'local',fallback_reason:reason});
await flush();
assert.strictEqual(el('levelAiBadge').textContent,'本地建议');
assert(el('levelAiBadge').className.includes('local'));
assert(el('levelAiResult').textContent.includes('本地规则建议（未采用模型结果）'));
assert(el('levelAiResult').textContent.includes(reasons[reason]));
assert(el('levelAiResult').textContent.includes('本地短句'+reason));
assert(!el('levelAiResult').textContent.includes('模型建议（仅供参考）'));
assert(!el('levelAiStatus').textContent.includes('DeepSeek'));
el('levelDownload').onclick();
assert(downloads.at(-1).includes('建议来源：本地规则建议（未采用模型结果）。'));
assert(downloads.at(-1).includes(reasons[reason]));
assert(downloads.at(-1).includes('本地短句'+reason));
}
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
assert(!JSON.stringify(aiRequests).includes('PRIVATE_CARD_ONLY_123'));
assert(!JSON.stringify(aiRequests).match(/landmark|photo|motion_evidence/i));
assert(posts.length>=postsBefore);
""")

    def test_real_page_rejects_illegal_contracts_without_guessing_local(self):
        self.run_page(r"""
await finishOne();
const illegal=[
{advice:'只有文字'},
{advice:'多字段',source:'model',fallback_reason:null,extra:1},
{advice:'云',source:'cloud',fallback_reason:null},
{advice:'带原因',source:'model',fallback_reason:'evidence_conflict'},
{advice:'空原因',source:'local',fallback_reason:null},
{advice:'未知原因',source:'local',fallback_reason:'made_up'},
{advice:'',source:'model',fallback_reason:null},
{advice:'   ',source:'model',fallback_reason:null},
{advice:12,source:'model',fallback_reason:null},
{advice:'😀'.repeat(801),source:'model',fallback_reason:null}
];
for(const payload of illegal){
el('levelAiAdvice').onclick();
fulfill(payload);
await flush();
assert.strictEqual(el('levelAiBadge').textContent,'暂不可用',JSON.stringify(payload));
assert(el('levelAiStatus').textContent.includes('分析暂不可用'));
assert(!el('levelAiResult').textContent.includes('模型建议（仅供参考）'));
assert(!el('levelAiResult').textContent.includes('本地规则建议'));
assert(!el('levelAiResult').textContent.includes('made_up'));
assert(!el('levelReport').textContent.includes('😀'.repeat(20)));
}
el('levelAiAdvice').onclick();badJson();await flush();
assert(el('levelAiStatus').textContent.includes('分析暂不可用'));
assert(!el('levelAiResult').textContent.includes('本地规则建议'));
el('levelAiAdvice').onclick();rejectFetch();await flush();
assert(el('levelAiStatus').textContent.includes('分析暂不可用'));
assert(!el('levelAiResult').textContent.includes('本地规则建议'));
el('levelAiAdvice').onclick();
fulfill({error:'api_key_rejected'},false);await flush();
assert(el('levelAiStatus').textContent.includes('分析暂不可用'));
assert(el('levelAiStatus').textContent.includes('密钥被拒绝'));
assert(!el('levelAiStatus').textContent.includes('sk-'));
assert(!el('levelAiResult').textContent.includes('本地规则建议'));
assert(el('levelDownload').disabled===false);
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
""")

    def test_real_page_counts_unicode_code_points_and_drops_stale_or_failed_advice(self):
        self.run_page(r"""
await finishOne();
const eight='😀'.repeat(800);
el('levelAiAdvice').onclick();
fulfill({advice:eight,source:'model',fallback_reason:null});
await flush();
assert.strictEqual(el('levelAiBadge').textContent,'模型建议');
assert.strictEqual(Array.from(el('levelAiResult').textContent.match(/😀/g)).length,800);
el('levelAiAdvice').onclick();
el('levelNext').onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_fist'});
await state({state:'COMPLETE',lesson_id:'basic_fist',confidence:.9,error_code:'OK',course_confidence:.9,session_error_code:'OK'});
fulfill({advice:'迟到的模型句子',source:'model',fallback_reason:null});
await flush();
assert(!el('levelAiResult').textContent.includes('迟到的模型句子'));
assert(!el('levelReport').textContent.includes('模型建议（仅供参考）'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
await finishOne();
el('levelAiAdvice').onclick();
beginner.onclick();await flush();
fulfill({advice:'切课后的旧句子',source:'model',fallback_reason:null});
await flush();
assert(!el('levelAiResult').textContent.includes('切课后的旧句子'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
await finishOne();
el('levelAiAdvice').onclick();
fulfill({advice:'第一次模型句子',source:'model',fallback_reason:null});
await flush();
assert(el('levelAiResult').textContent.includes('模型建议（仅供参考）'));
el('levelAiAdvice').onclick();
rejectFetch();await flush();
assert.strictEqual(el('levelAiBadge').textContent,'暂不可用');
assert(el('levelAiStatus').textContent.includes('分析暂不可用'));
assert(!el('levelAiResult').textContent.includes('第一次模型句子'));
assert(!el('levelAiResult').textContent.includes('模型建议（仅供参考）'));
assert(!el('levelReport').textContent.includes('第一次模型句子'));
el('levelDownload').onclick();
assert(!downloads.at(-1).includes('第一次模型句子'));
assert(downloads.at(-1).includes('分析暂不可用'));
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
""")

    def test_manual_course_selection_clears_advice_and_invalidates_pending_request(self):
        self.run_page(r"""
await finishOne();
el('levelAiAdvice').onclick();
fulfill({advice:'原课程模型建议',source:'model',fallback_reason:null});await flush();
manual.onclick();await flush();
assert(!el('levelAiResult').textContent.includes('原课程模型建议'));
assert(!el('levelReport').textContent.includes('建议来源：模型建议'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
await finishOne();
el('levelAiAdvice').onclick();
manual.onclick();await flush();
fulfill({advice:'单课切换后的迟到建议',source:'model',fallback_reason:null});await flush();
assert(!el('levelAiResult').textContent.includes('单课切换后的迟到建议'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
assert(!posts.some(p=>p.includes('/sign/start')||p.includes('/api/v1/train')));
""")

    def test_next_course_clears_advice_before_another_terminal_record(self):
        self.run_page(r"""
await finishOne();
el('levelAiAdvice').onclick();
fulfill({advice:'上一项的本地建议',source:'local',fallback_reason:'provider_timeout'});await flush();
el('levelNext').onclick();await flush();
assert(!el('levelReport').textContent.includes('上一项的本地建议'));
assert(!el('levelAiResult').textContent.includes('建议来源：本地规则建议'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
await finishOne();
el('levelAiAdvice').onclick();
el('levelNext').onclick();await flush();
fulfill({advice:'还没新增终态的迟到建议',source:'model',fallback_reason:null});await flush();
assert(!el('levelReport').textContent.includes('还没新增终态的迟到建议'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
""")
