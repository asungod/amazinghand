"""Operator review is not an automatic score or a hardware command."""
import copy
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_hand.tests.test_sign_sequence import SEQUENCES, observation
from smart_hand.tests.test_sign_integration import load_main_module, FakeSignSidecar, FakeSignSerial, authority
from smart_hand.tests.test_web_stream import FakeConnection, FakeSocketModule
from smart_hand.tests import test_course_report_quality as page_harness
from smart_hand.tests.test_ai_course_advice_proxy import SUMMARY
from smart_hand.ai_course_advice_proxy import validate_summary, local_advice, advice_conflicts
from live_sidecar import LiveWebSidecar, WebSignIntentLatch
from web_stream import PreviewServer
from sign_session_log import SignSessionCsvLogger
from sign_lesson import SignLessonController


def controller(lesson="signal_help"):
    c = SignLessonController()
    c.select_lesson(lesson, 0)
    c.start(0, manual_confirm=True, link_online=True, vision_fresh=True)
    c.begin_demo(0, link_online=True, vision_fresh=True)
    c.finish_demo(0, link_online=True, vision_fresh=True)
    return c


def command(c, **overrides):
    return dict({"request_id": 1, "action": "review", "lesson_id": c.status()["lesson_id"],
                 "session_token": c.session_token, "manual_confirm": True}, **overrides)


class ManualReviewTests(unittest.TestCase):
    def test_all_six_dynamic_courses_review_without_incrementing_automatic_progress(self):
        for lesson in SEQUENCES:
            c = controller(lesson)
            before = c.status()["motion_progress"]["completed_steps"]
            result = c.review_manual(1000, True, c.session_token)
            self.assertEqual(result["state"], "REVIEWED")
            self.assertEqual(result["error_code"], "MANUAL_REVIEW")
            self.assertFalse(result["can_review"])
            self.assertEqual(result["motion_progress"]["completed_steps"], before)
            self.assertFalse(result["motion_progress"]["complete"])
            self.assertFalse(c.review_manual(1001, True, c.session_token)["ok"])

    def test_review_requires_consent_current_token_and_dynamic_imitation(self):
        for consent, token in ((False, 1), (1, 1), (True, True), (True, 2), (True, None)):
            c = controller()
            self.assertFalse(c.review_manual(1000, consent, token)["ok"])
            self.assertEqual(c.state, "IMITATING")
        c = controller("basic_fist")
        self.assertFalse(c.review_manual(1000, True, c.session_token)["ok"])
        c = controller()
        old = c.session_token
        c.cancel(999)
        c.select_lesson("word_thanks", 1000)
        self.assertFalse(c.review_manual(1001, True, old)["ok"])
        c = controller()
        c.fault("SDK_ERROR", 100)
        self.assertFalse(c.review_manual(1000, True, c.session_token)["ok"])
        c = controller()
        self.assertFalse(c.review_manual(60000, True, c.session_token)["ok"])
        self.assertEqual(c.state, "TIMEOUT")

    def test_automatic_completion_cannot_be_replaced_by_review(self):
        c = controller("word_hello")
        for phase, start in (("shape:POINT", 0), ("shape:THUMBS_UP", 400)):
            c.observe(observation(phase), start)
            c.observe(observation(phase), start+300)
        self.assertEqual(c.state, "COMPLETE")
        self.assertFalse(c.review_manual(800, True, c.session_token)["ok"])
        self.assertEqual(c.state, "COMPLETE")

    def test_http_to_latch_to_main_review_has_zero_uart_or_ack_effect(self):
        main = load_main_module()
        c = controller()
        sidecar = LiveWebSidecar(lambda: {"sign_status": c.status()}, now_ms_provider=lambda: 1000)
        payload = {k: v for k, v in command(c).items() if k not in ("request_id", "action")}
        body = json.dumps(payload).encode()
        request = (b"POST /api/v1/sign/review HTTP/1.1\r\nHost: test\r\nOrigin: http://test\r\nContent-Length: "
                   + str(len(body)).encode()+b"\r\n\r\n"+body)
        conn = FakeConnection(request)
        server = PreviewServer(socket_module=FakeSocketModule([conn]),
                               sign_review_handler=sidecar.enqueue_web_sign_review)
        server.start("127.0.0.1", 8080)
        for _ in range(4):
            server.poll()
        self.assertIn(b"202 Accepted", bytes(conn.sent))
        self.assertEqual(c.state, "IMITATING")  # HTTP only enqueues.
        serial = FakeSignSerial()
        monitor = types.SimpleNamespace(consecutive_timeouts=0, pending={99: "unchanged"})
        with patch.object(main, "send_frame", side_effect=AssertionError("review must never send")):
            self.assertTrue(main.consume_sign_intent(sidecar, c, authority(last_status_ms=1000),
                                                     monitor, 1000, serial, 42))
        self.assertEqual(c.state, "REVIEWED")
        self.assertEqual(serial.writes, [])
        self.assertEqual(monitor.pending, {99: "unchanged"})
        self.assertEqual(sidecar.sign_status()["request_reason"], "manual_review_recorded")

    def test_main_rejects_delayed_lesson_session_offline_and_running_motion(self):
        main = load_main_module()
        for changes, auth in (({"session_token": 99}, authority(last_status_ms=1000)),
                              ({"lesson_id": "word_thanks"}, authority(last_status_ms=1000)),
                              ({}, authority(link_online=False, last_status_ms=1000)),
                              ({}, authority(last_status_ms=0))):
            c = controller()
            sidecar = FakeSignSidecar(command(c, **changes))
            self.assertFalse(main.consume_sign_intent(sidecar, c, auth, None, 2000))
            self.assertEqual(c.state, "IMITATING")
        for motion_state, accepted in ((2, False), (5, True)):
            c = controller()
            sidecar = FakeSignSidecar(command(c))
            motion = types.SimpleNamespace(status=lambda: {"state": motion_state})
            with patch.object(main, "SIGN_MECHANICAL_DEMO_ENABLED", True), patch.object(
                    main, "send_frame", side_effect=AssertionError("no hardware commands")):
                result = main.consume_sign_intent(sidecar, c, authority(last_status_ms=1000), None,
                                                  1000, None, None, motion)
            self.assertEqual(result, accepted)

    def test_latch_keeps_existing_expiry_and_rejects_boolean_token(self):
        clock = [0]
        latch = WebSignIntentLatch(now_ms_provider=lambda: clock[0])
        for token, consent in ((True, True), (0, True), (1, False)):
            self.assertIsNone(latch.enqueue("review", "signal_help", token, consent))
        self.assertIsNone(latch.enqueue("start", session_token=1))
        self.assertEqual(latch.enqueue("review", "signal_help", 1, True), 1)
        clock[0] = 2000
        self.assertIsNone(latch.take())

    def test_http_rejects_wrong_origin_extra_fields_missing_consent_and_bad_token(self):
        calls = []
        server = PreviewServer(sign_review_handler=lambda *args: calls.append(args) or {"request_id": 1})
        valid = {"lesson_id": "signal_help", "session_token": 1, "manual_confirm": True}
        for payload, origin, code in ((valid, b"http://evil", b"403"),
                                     (dict(valid, angles=[]), b"http://test", b"400"),
                                     (dict(valid, session_token=True), b"http://test", b"400"),
                                     (dict(valid, manual_confirm=False), b"http://test", b"400"),
                                     ({"lesson_id": "signal_help"}, b"http://test", b"400")):
            body = json.dumps(payload).encode()
            request = (b"POST /api/v1/sign/review HTTP/1.1\r\nHost: test\r\nOrigin: "+origin+
                       b"\r\nContent-Length: "+str(len(body)).encode()+b"\r\n\r\n"+body)
            self.assertIn(code, server._sign_request_response(request, "review").split(b"\r\n")[0])
        self.assertEqual(calls, [])

    def test_review_terminal_csv_is_distinct_and_written_once(self):
        c = controller()
        c.review_manual(1000, True, c.session_token)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"sessions.csv"
            logger = SignSessionCsvLogger(str(path))
            self.assertEqual(logger.append(c, 1000), 1)
            self.assertEqual(logger.append(c, 1001), 1)  # Same row number, no second write.
            contents = path.read_text(encoding="utf-8")
            self.assertEqual(len(contents.splitlines()), 2)
            self.assertIn(",REVIEWED,REVIEWED,", contents)
            self.assertNotIn(",COMPLETE,COMPLETE,", contents)

    def test_api_exposes_bounded_review_capability_not_geometry(self):
        c = controller()
        server = PreviewServer(sign_status_provider=lambda: dict(c.status(), motion_evidence="PRIVATE"))
        status = json.loads(server._sign_status_response().split(b"\r\n\r\n")[1])
        self.assertTrue(status["can_review"])
        self.assertEqual(status["session_token"], c.session_token)
        self.assertNotIn("PRIVATE", json.dumps(status))

    def test_ai_summary_manual_result_not_counted_as_automatic_pass(self):
        row = dict(copy.deepcopy(SUMMARY["rows"][0]), lesson_id="signal_help", state="REVIEWED",
                   error_code="MANUAL_REVIEW", motion_progress={"completed_steps": 2, "total_steps": 3, "complete": False})
        payload = {"level": "advanced", "plan": ["signal_help"], "rows": [row]}
        clean = validate_summary(payload)
        self.assertIn("人工复核", local_advice(clean))
        self.assertTrue(advice_conflicts("全部课程均已通过。", clean))
        for bad in (dict(row, state="COMPLETE"), dict(row, error_code="OK"),
                    dict(row, motion_progress=None), dict(row, motion_progress={"completed_steps": 3, "total_steps": 3, "complete": True})):
            with self.assertRaises(ValueError):
                validate_summary(dict(payload, rows=[bad]))


class ManualReviewPageTests(unittest.TestCase):
    def run_page(self, checks):
        page_harness.CourseReportQualityTests.run_page(self, checks)

    def test_actual_page_consent_post_outcome_history_report_and_ai_summary(self):
        self.run_page(r"""
const captured=[],oldFetch=global.fetch;
global.fetch=(url,opts)=>{if(opts&&opts.method==='POST')captured.push({url,body:JSON.parse(opts.body)});return oldFetch(url,opts);};
el('historyToggle').onclick();advanced.onclick();await flush();
const motion={completed_steps:1,total_steps:2,complete:false,scope:'2d_sequence_prototype'};
const active={state:'IMITATING',lesson_id:'word_hello',session_token:7,can_review:true,link_online:true,motion_progress:motion};
await state(active);
assert(!el('manualReviewControls').hidden);assert(el('manualReviewButton').disabled);
el('manualReviewConsent').checked=true;el('manualReviewConsent').onchange();
assert(!el('manualReviewButton').disabled);
el('manualReviewButton').onclick();await flush();
const review=captured.find(p=>p.url.endsWith('/sign/review'));
assert.deepStrictEqual(review.body,{lesson_id:'word_hello',session_token:7,manual_confirm:true});
assert(!captured.some(p=>p.url.endsWith('/sign/start')||p.url.includes('/train')));
await state({...active,state:'REVIEWED',can_review:false,session_error_code:'MANUAL_REVIEW',error_code:'NO_HAND'});
assert(el('courseOutcome').textContent.includes('非自动通过'));assert(!el('courseOutcome').className.includes('passed'));
assert(el('stepTag5').textContent.includes('人工复核'));assert(el('stepTag4').textContent.includes('非自动达标'));
const report=el('levelReport').textContent;
assert(report.includes('人工复核记录：1 项'));assert(report.includes('完成：0'));assert(report.includes('自动检测已确认步骤 1/2'));
assert(!el('levelNext').disabled);
assert.strictEqual(JSON.parse(savedText).sessions[0].rows[0].state,'REVIEWED');
el('levelDownload').onclick();assert(downloads[0].includes('人工复核记录：1 项'));
el('levelAiAdvice').onclick();await flush();assert.strictEqual(aiRequests[0].rows[0].state,'REVIEWED');
assert.strictEqual(aiRequests[0].rows[0].error_code,'MANUAL_REVIEW');
assert.strictEqual(aiRequests[0].rows[0].motion_progress.complete,false);
""")

    def test_stale_status_session_change_and_static_lesson_clear_consent(self):
        self.run_page(r"""
const active={state:'IMITATING',lesson_id:'signal_help',session_token:7,can_review:true,link_online:true};
await state(active);el('manualReviewConsent').checked=true;el('manualReviewConsent').onchange();
now+=1600;intervals.find(i=>i.ms===200).fn();
assert(el('manualReviewButton').disabled);assert(el('manualReviewControls').hidden);
await state(active);assert(!el('manualReviewConsent').checked);
el('manualReviewConsent').checked=true;el('manualReviewConsent').onchange();
await state({...active,session_token:8});assert(!el('manualReviewConsent').checked);
await state({...active,lesson_id:'basic_fist'});assert(el('manualReviewControls').hidden);
await state({state:'IMITATING',lesson_id:'signal_help'});assert(el('manualReviewControls').hidden);
assert(!posts.some(p=>p.includes('/review')));
""")


if __name__ == "__main__":
    unittest.main()
