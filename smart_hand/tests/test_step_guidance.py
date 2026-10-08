"""Read-only stage explanations and real-page teaching preview regressions."""
import json
import unittest

from smart_hand.tests.test_sign_sequence import observation, hold
from sign_sequence import SEQUENCES, SignSequenceTracker
from smart_hand.tests import test_course_report_quality as page_harness
from smart_hand.maixcam2.web_stream import PreviewServer, _CONTROL_PAGE


class StageGuidanceTests(unittest.TestCase):
    def test_step_practice_copy_discloses_pause_and_retained_progress(self):
        page = _CONTROL_PAGE.decode("utf-8")
        self.assertIn("保留本轮已确认步骤", page)
        self.assertIn("分步达标不证明整段动作连续", page)
        self.assertIn("允许中途暂停，不证明整段动作连续", page)
        self.assertNotIn("离开画面超过 2 秒重新开始", page)

    def test_each_stage_has_bounded_instruction_and_check_states(self):
        for lesson, stages in SEQUENCES.items():
            tracker, now = SignSequenceTracker(lesson), 0
            for phase, _ in stages:
                tracker.observe(observation(phase), now)
                snap = tracker.snapshot()
                if phase == 'help_close':
                    self.assertEqual(snap['observation_state'], 'CHECKING')
                    self.assertIn('人工复核', snap['instruction'])
                    self.assertEqual(snap['completed_steps'], 2)
                    continue
                self.assertEqual(snap['observation_state'], 'HOLDING')
                self.assertTrue(snap['checks'])
                self.assertTrue(all(c['state'] == 'met' for c in snap['checks']))
                self.assertLessEqual(len(snap['checks']), 4)
                self.assertLessEqual(len(snap['instruction']), 160)
                self.assertTrue(all(len(c['label']) <= 48 for c in snap['checks']))
                tracker.observe(observation(phase), now + 320)
                self.assertFalse(tracker.snapshot()['checks'])
                now += 400
            self.assertEqual(tracker.snapshot()['complete'], lesson != 'signal_help')
            if lesson != 'signal_help':
                self.assertEqual(tracker.snapshot()['observation_state'], 'COMPLETE')

    def test_help_close_open_geometry_does_not_blame_user_or_advance(self):
        tracker = SignSequenceTracker('signal_help')
        now = hold(tracker, observation('palm_open'), 0)
        now = hold(tracker, observation('thumb_in'), now)
        wrong = observation('help_close')
        wrong['gesture_id'] = 'FIST'  # A favourable label alone cannot pass.
        wrong['motion_evidence']['finger_extension'] = [.95]*4
        hold(tracker, wrong, now)
        snap = tracker.snapshot()
        self.assertEqual(snap['completed_steps'], 2)
        self.assertEqual(snap['observation_state'], 'CHECKING')
        self.assertEqual(snap['checks'][0]['state'], 'unmet')
        self.assertIn('人工复核', snap['feedback'])
        self.assertIn('不代表你做错', snap['feedback'])
        self.assertIn('不自动评分', snap['instruction'])
        self.assertEqual(snap['phase_hold_ms'], 0)

    def test_missing_and_invalid_evidence_never_retain_met_checks(self):
        tracker = SignSequenceTracker('word_thanks')
        tracker.observe(observation('thumb_open'), 0)
        tracker.observe({'error_code': 'NO_HAND'}, 100)
        self.assertEqual(tracker.snapshot()['checks'], [])
        self.assertEqual(tracker.snapshot()['observation_state'], 'MISSING')
        self.assertEqual(tracker.snapshot()['phase_hold_ms'], 0)
        tracker.observe({'error_code': 'SDK_ERROR'}, 200)
        self.assertEqual(tracker.snapshot()['checks'], [])
        self.assertEqual(tracker.snapshot()['observation_state'], 'RESET')

    def test_snapshot_reads_and_external_mutation_cannot_confirm_a_step(self):
        tracker = SignSequenceTracker('word_thanks')
        tracker.observe(observation('thumb_open'), 0)
        for _ in range(5):
            snap = tracker.snapshot()
            snap['checks'][0]['state'] = 'unmet'
            snap['step_titles'].clear()
        self.assertEqual(tracker.index, 0)
        self.assertEqual(tracker.snapshot()['checks'][0]['state'], 'met')
        self.assertEqual(len(tracker.snapshot()['step_titles']), 5)
        tracker.observe(observation('thumb_open'), 299)
        self.assertEqual(tracker.index, 0)
        tracker.observe(observation('thumb_open'), 300)
        self.assertEqual(tracker.index, 1)

    def test_api_strips_private_geometry_and_rejects_unbounded_explanation(self):
        tracker = SignSequenceTracker('word_thanks')
        tracker.observe(observation('thumb_open'), 0)
        progress = tracker.snapshot()
        progress['checks'][0]['points'] = [1, 2, 3]
        progress['raw_geometry'] = 'PRIVATE'
        status = {'state': 'IMITATING', 'motion_progress': progress, 'motion_evidence': 'PRIVATE'}
        server = PreviewServer(sign_status_provider=lambda: status)
        parsed = json.loads(server._sign_status_response().split(b'\r\n\r\n', 1)[1])
        self.assertEqual(parsed['motion_progress']['checks'][0].keys(), {'label', 'state'})
        self.assertNotIn('PRIVATE', json.dumps(parsed))
        for bad in ([{'label': 'x'*49, 'state': 'met'}], [{'label': 'ok', 'state': True}],
                    [{'label': 'x', 'state': 'met'}]*5):
            progress['checks'] = bad
            parsed = json.loads(server._sign_status_response().split(b'\r\n\r\n', 1)[1])
            self.assertNotIn('checks', parsed['motion_progress'])
        progress['step_instructions'] = ['x'*161]*5
        parsed = json.loads(server._sign_status_response().split(b'\r\n\r\n', 1)[1])
        self.assertNotIn('step_instructions', parsed['motion_progress'])


class StepGuidancePageTests(unittest.TestCase):
    def run_page(self, checks):
        page_harness.CourseReportQualityTests.run_page(self, checks, exports=
            'globalThis.renderSequence=renderSequence;globalThis.SEQUENCE_TITLES=SEQUENCE_TITLES;')

    def test_preview_changes_only_explanation_and_does_not_send_requests(self):
        self.run_page(r"""
renderSequence({lesson_id:'word_thanks',state:'LESSON_SELECTED'});
el('sequencePreview').onclick();
assert(el('sequenceModeTitle').textContent.includes('不计成绩'));
assert(el('sequenceEvidence').hidden);
el('sequenceNext').onclick();assert(el('sequenceStage').textContent.includes('2/5'));
el('sequencePrev').onclick();assert(el('sequenceStage').textContent.includes('1/5'));
el('sequenceNext').onclick();el('sequenceNext').onclick();el('sequenceNext').onclick();el('sequenceNext').onclick();
assert(el('sequenceNext').disabled);el('sequenceNext').onclick();
assert(el('sequenceStage').textContent.includes('5/5'));
el('sequenceFollow').onclick();assert(el('sequenceStage').textContent.includes('1/5'));
assert(el('sequenceModeTitle').textContent.includes('判定'));
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);assert(savedText===null);
assert(!el('courseOutcome').textContent.includes('已通过'));
""")

    def test_current_step_checks_and_hold_are_not_static_stable_or_pass(self):
        self.run_page(r"""
const motion={completed_steps:1,total_steps:5,complete:false,scope:'2d_sequence_prototype',
prompt:'第一次弯拇指',instruction:'让相机看清拇指弯曲',step_instructions:['一','二','三','四','五'],
observation_state:'HOLDING',checks:[{label:'四指收拢',state:'met'}],phase_hold_ms:150,required_hold_ms:300};
await state({lesson_id:'word_thanks',state:'IMITATING',valid:false,error_code:'LOW_CONFIDENCE',stable_ms:9999,
link_online:true,recognition_fresh:true,motion_progress:motion});
assert(el('sequenceStage').textContent.includes('2/5'));
assert(el('sequenceHoldText').textContent.includes('150 / 300'));
assert.strictEqual(el('sequenceHold').value,150);
assert(!el('courseOutcome').textContent.includes('已通过'));
el('sequencePreview').onclick();el('sequenceNext').onclick();
await state({lesson_id:'word_thanks',state:'IMITATING',motion_progress:motion});
assert(el('sequenceStage').textContent.includes('正在看教学'));
assert(el('sequenceStage').textContent.includes('2/5'));
el('sequenceFollow').onclick();assert(el('sequenceStage').textContent.includes('当前判定'));
assert.strictEqual(posts.length,0);
""")

    def test_old_checks_clear_on_no_hand_stale_and_independent_watchdog(self):
        self.run_page(r"""
const motion={completed_steps:2,total_steps:3,complete:false,scope:'2d_sequence_prototype',prompt:'四指握住拇指',
observation_state:'HOLDING',checks:[{label:'目标标签',state:'met'}],phase_hold_ms:170,required_hold_ms:300};
await state({state:'IMITATING',lesson_id:'signal_help',recognition_observed_ms:10,recognition_fresh:true,motion_progress:motion});
assert(el('sequenceChecks').textContent.includes('已观察到'));
now+=1600;intervals.find(i=>i.ms===200).fn();
assert(!el('sequenceChecks').textContent.includes('已观察到'));
assert.strictEqual(el('sequenceHold').value,0);
assert(el('sequenceStage').textContent.includes('已确认 2 步'));
el('sequencePreview').onclick();el('sequenceFollow').onclick();
assert(!el('sequenceChecks').textContent.includes('已观察到'),'returning from preview cannot revive stale conditions');
await state({state:'IMITATING',lesson_id:'signal_help',recognition_observed_ms:20,recognition_error_code:'NO_HAND',motion_progress:motion});
assert(el('sequenceHint').textContent.includes('未检测到手'));
assert(!el('sequenceChecks').textContent.includes('已观察到'));
await state({state:'IMITATING',lesson_id:'signal_help',recognition_fresh:false,motion_progress:motion});
assert(!el('sequenceChecks').textContent.includes('已观察到'));
""")

    def test_malformed_progress_and_text_injection_never_show_hold_as_success(self):
        self.run_page(r"""
const motion={completed_steps:2,total_steps:3,complete:false,scope:'2d_sequence_prototype',prompt:'test',
observation_state:'HOLDING',checks:[{label:'<img src=x onerror=alert(1)>',state:'met'}],phase_hold_ms:150,required_hold_ms:300};
renderSequence({lesson_id:'signal_help',state:'IMITATING',motion_progress:motion});
assert(el('sequenceChecks').textContent.includes('<img'));assert(!el('sequenceChecks').innerHTML);
motion.checks[0].state='bogus';renderSequence({lesson_id:'signal_help',state:'IMITATING',motion_progress:motion});
assert.strictEqual(el('sequenceHold').value,0);assert(el('sequenceHint').textContent.includes('格式无效'));
motion.total_steps=2;renderSequence({lesson_id:'signal_help',state:'IMITATING',motion_progress:motion});
assert(el('sequenceHint').textContent.includes('有效步骤'));
renderSequence({lesson_id:'basic_fist'});assert(el('sequenceGuide').hidden);
assert.strictEqual(posts.length,0);assert.strictEqual(aiRequests.length,0);
""")

    def test_all_course_labels_match_device_and_selection_resets_preview(self):
        expected = {lid: [item[1] for item in seq] for lid, seq in SEQUENCES.items()}
        self.run_page('assert.deepStrictEqual(SEQUENCE_TITLES,'+json.dumps(expected, ensure_ascii=False)+');'+r"""
renderSequence({lesson_id:'word_thanks'});el('sequencePreview').onclick();el('sequenceNext').onclick();
renderSequence({lesson_id:'word_hello'});
assert(el('sequenceStage').textContent.includes('1/2'));assert(!el('sequenceEvidence').hidden);
assert(el('sequencePreview')['aria-pressed']==='false');
assert.strictEqual(posts.length,0);
""")


if __name__ == '__main__':
    unittest.main()
