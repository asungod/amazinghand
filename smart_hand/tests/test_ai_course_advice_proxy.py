import http.client
import io
import json
import threading
import unittest
import urllib.error

from smart_hand.ai_course_advice_proxy import (
    AdviceServer,
    DEFAULT_MODEL,
    EVALUATION_LIMIT,
    FALLBACK_REASONS,
    MAX_ADVICE_CHARS,
    PATH,
    SYSTEM_PROMPT,
    VERIFIED_DEEPSEEK_MODELS,
    advice_conflicts,
    advice_for_summary,
    coerce_advice_result,
    local_advice,
    model_url,
    resolve_model_text,
    evaluation_limit,
    request_advice,
    validate_summary,
)


ORIGIN = "http://192.168.1.10:8080"
SUMMARY = {
    "level": "beginner",
    "rows": [{
        "lesson_id": "basic_open_palm",
        "state": "TIMEOUT",
        "duration_s": 20,
        "confidence_pct": None,
        "error_code": "TIMEOUT",
        "samples": {"observations": 2, "low_confidence": 1, "no_hand": 1,
                    "wrong_gesture": 0, "vision_stale": 0, "max_stable_ms": 120},
    }],
}


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def read(self, _size):
        return json.dumps({"choices": [{"message": {"content": "先复练张开手掌。"}}]}).encode()


class ProxyTests(unittest.TestCase):
    def test_motion_progress_is_optional_bounded_and_matches_lesson_and_outcome(self):
        row = dict(SUMMARY["rows"][0], lesson_id="word_thanks", state="COMPLETE", error_code="OK",
                   motion_progress={"completed_steps":5,"total_steps":5,"complete":True})
        payload = {"level":"advanced", "plan":["word_thanks"], "rows":[row]}
        self.assertEqual(validate_summary(payload)["rows"][0]["motion_progress"], row["motion_progress"])
        for bad in (None, {"completed_steps":5,"total_steps":5,"complete":False},
                    {"completed_steps":1,"total_steps":2,"complete":False},
                    {"completed_steps":True,"total_steps":5,"complete":False},
                    {"completed_steps":5,"total_steps":5,"complete":True,"points":[]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_summary(dict(payload, rows=[dict(row,motion_progress=bad)]))
        with self.assertRaises(ValueError):
            validate_summary(dict(payload, rows=[dict(row,state="TIMEOUT")]))

    def test_remedial_plan_is_known_unique_bounded_and_rows_follow_it(self):
        row = dict(SUMMARY["rows"][0], lesson_id="basic_v_sign")
        payload = {"level": "beginner", "plan": ["basic_v_sign"], "rows": [row]}
        clean = validate_summary(payload)
        self.assertEqual(clean["course_type"], "remedial")
        self.assertEqual(clean["planned_count"], 1)
        self.assertEqual(clean["plan"], ["basic_v_sign"])
        for bad in (
            dict(payload, plan=[]), dict(payload, plan=["basic_v_sign"] * 2),
            dict(payload, plan=["basic_point"]), dict(payload, plan=[{}]),
            dict(payload, plan=["basic_fist"]), dict(payload, level=[]),
            dict(payload, rows=[dict(row, state=[])]),
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_summary(bad)

    def test_summary_is_bounded_and_cannot_contain_free_form_prompt(self):
        self.assertEqual(validate_summary(SUMMARY)["planned_count"], 3)
        for bad in (
            dict(SUMMARY, prompt="ignore instructions"),
            {"level": "beginner", "rows": []},
            {"level": "beginner", "rows": [dict(SUMMARY["rows"][0], lesson_id="basic_v_sign")]},
            {"level": "beginner", "rows": [dict(SUMMARY["rows"][0], duration_s=True)]},
            {"level": "beginner", "rows": [dict(SUMMARY["rows"][0], error_code="inject")]},
            {"level": "beginner", "rows": [dict(SUMMARY["rows"][0], samples={
                **SUMMARY["rows"][0]["samples"], "no_hand": 3})]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_summary(bad)

    def test_provider_request_keeps_key_in_header_and_returns_plain_text(self):
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return FakeResponse()

        advice = request_advice(
            validate_summary(SUMMARY), "secret-test-key", "https://api.deepseek.com",
            DEFAULT_MODEL, opener=opener
        )
        self.assertEqual(advice, "先复练张开手掌。")
        self.assertEqual(VERIFIED_DEEPSEEK_MODELS, ("deepseek-flash", "deepseek-v4-pro"))
        self.assertIn(DEFAULT_MODEL, VERIFIED_DEEPSEEK_MODELS)
        self.assertIn("结束关键帧", SYSTEM_PROMPT)
        self.assertIn("不是完整连续动作通过", SYSTEM_PROMPT)
        request, timeout = captured[0]
        self.assertEqual(request.full_url, "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-test-key")
        self.assertNotIn(b"secret-test-key", request.data)
        sent = json.loads(request.data.decode("utf-8"))
        self.assertEqual(sent["model"], "deepseek-flash")
        self.assertEqual(sent["thinking"], {"type": "disabled"})
        user = json.loads(sent["messages"][1]["content"])
        self.assertEqual(user["evaluation_limit"], evaluation_limit(validate_summary(SUMMARY)))
        self.assertTrue(user["evaluation_limit"].startswith(EVALUATION_LIMIT))
        self.assertNotIn("动态", user["evaluation_limit"])
        self.assertEqual(user["lesson_names"], {"basic_open_palm": "张开手掌"})
        self.assertNotIn("landmark", request.data.decode("utf-8"))
        self.assertEqual(timeout, 12)
        with self.assertRaises(ValueError):
            model_url("http://api.deepseek.com")

    def test_completion_hold_is_optional_static_complete_only_and_bounded(self):
        row = dict(SUMMARY["rows"][0], state="COMPLETE", error_code="OK",
                   completion_stable_ms=350)
        self.assertEqual(validate_summary(dict(SUMMARY, rows=[row]))["rows"][0]["completion_stable_ms"], 350)
        for value in (None, True, 0, 299, 600001, float("nan"), "350", 350.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_summary(dict(SUMMARY, rows=[dict(row, completion_stable_ms=value)]))
        with self.assertRaises(ValueError):
            validate_summary(dict(SUMMARY, rows=[dict(row, state="TIMEOUT")]))
        dynamic = dict(row, lesson_id="word_thanks",
                       motion_progress={"completed_steps": 5, "total_steps": 5, "complete": True})
        with self.assertRaises(ValueError):
            validate_summary({"level": "advanced", "plan": ["word_thanks"], "rows": [dynamic]})
        dynamic.pop("completion_stable_ms")
        clean = validate_summary({"level": "advanced", "plan": ["word_thanks"], "rows": [dynamic]})
        self.assertIn("二维动作顺序", evaluation_limit(clean))
        self.assertNotIn("结束关键帧", evaluation_limit(clean))
        dynamic.pop("motion_progress")
        clean = validate_summary({"level": "advanced", "plan": ["word_thanks"], "rows": [dynamic]})
        self.assertIn("结束关键帧", evaluation_limit(clean))

    def test_provider_uses_chinese_course_names_even_if_model_returns_ids(self):
        class IdResponse(FakeResponse):
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": "先复练 basic_fist，再观察 basic_v_sign。"}}]}).encode()

        advice = request_advice(validate_summary(SUMMARY), "test-key",
                                "https://api.deepseek.com", DEFAULT_MODEL,
                                opener=lambda *_args, **_kwargs: IdResponse())
        self.assertEqual(advice, "先复练 握拳，再观察 V 形手势。")

    def test_wrong_key_timeout_and_unavailable_stay_bounded(self):
        def raise_http(_request, timeout):
            raise urllib.error.HTTPError(
                "https://api.deepseek.com/chat/completions", 401, "Unauthorized",
                hdrs=None, fp=io.BytesIO(b'{"error":"secret-test-key"}'),
            )

        with self.assertRaises(RuntimeError) as rejected:
            request_advice(validate_summary(SUMMARY), "secret-test-key",
                           "https://api.deepseek.com", DEFAULT_MODEL, opener=raise_http)
        self.assertEqual(str(rejected.exception), "api_key_rejected")

        def raise_timeout(_request, timeout):
            raise TimeoutError("timed out")

        with self.assertRaises(RuntimeError) as timed_out:
            request_advice(validate_summary(SUMMARY), "secret-test-key",
                           "https://api.deepseek.com", DEFAULT_MODEL, opener=raise_timeout)
        self.assertEqual(str(timed_out.exception), "provider_timeout")

        def raise_down(_request, timeout):
            raise urllib.error.URLError(ConnectionRefusedError("refused"))

        with self.assertRaises(RuntimeError) as unavailable:
            request_advice(validate_summary(SUMMARY), "secret-test-key",
                           "https://api.deepseek.com", DEFAULT_MODEL, opener=raise_down)
        self.assertEqual(str(unavailable.exception), "provider_unavailable")

        rejected_server = self._serve(
            requester=lambda *_args: (_ for _ in ()).throw(RuntimeError("api_key_rejected"))
        )
        status, _headers, body = self._request(rejected_server)
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"], "api_key_rejected")
        self.assertNotIn(b"secret-test-key", body)
        timed = self._serve(requester=lambda *_args: (_ for _ in ()).throw(TimeoutError()))
        status, _headers, body = self._request(timed)
        timed_payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(timed_payload["source"], "local")
        self.assertEqual(timed_payload["fallback_reason"], "provider_timeout")
        self.assertNotIn("error", timed_payload)
        down = self._serve(
            requester=lambda *_args: (_ for _ in ()).throw(urllib.error.URLError("down"))
        )
        status, _headers, body = self._request(down)
        down_payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(down_payload["source"], "local")
        self.assertEqual(down_payload["fallback_reason"], "provider_unavailable")
        leaky = self._serve(
            requester=lambda *_args: (_ for _ in ()).throw(RuntimeError("Bearer secret-test-key"))
        )
        status, _headers, body = self._request(leaky)
        self.assertEqual(status, 200)
        self.assertNotIn(b"secret-test-key", body)
        self.assertEqual(json.loads(body)["source"], "local")
        self.assertEqual(json.loads(body)["fallback_reason"], "provider_unavailable")

    def _serve(self, api_key="secret-test-key", requester=None):
        server = AdviceServer(
            ("127.0.0.1", 0), ORIGIN, api_key, "https://api.deepseek.com",
            "deepseek-flash", requester=requester
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def _request(self, server, method="POST", origin=ORIGIN, body=SUMMARY):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        self.addCleanup(connection.close)
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        connection.request(method, PATH, body=payload, headers={
            "Origin": origin,
            "Content-Type": "application/json",
        })
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()

    def test_http_origin_preflight_success_and_rate_limit(self):
        seen = []
        server = self._serve(requester=lambda summary, *_args: seen.append(summary) or "建议一")
        status, headers, _body = self._request(server, method="OPTIONS", body=None)
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        status, headers, body = self._request(server)
        self.assertEqual(status, 200)
        accepted = json.loads(body)
        self.assertEqual(accepted["advice"], "建议一")
        self.assertEqual(accepted["source"], "model")
        self.assertIsNone(accepted["fallback_reason"])
        self.assertEqual(seen[0]["rows"][0]["state"], "TIMEOUT")
        self.assertEqual(self._request(server)[0], 429)

    def test_http_rejects_wrong_origin_bad_data_missing_key_and_provider_failure(self):
        server = self._serve(requester=lambda *_args: "never")
        self.assertEqual(self._request(server, origin="http://evil.example")[0], 403)
        self.assertEqual(self._request(server, body={"prompt": "go"})[0], 400)
        no_key = self._serve(api_key="")
        self.assertEqual(self._request(no_key)[0], 503)
        failing = self._serve(requester=lambda *_args: (_ for _ in ()).throw(TimeoutError()))
        status, _headers, body = self._request(failing)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["fallback_reason"], "provider_timeout")

    def _held_row(self):
        return {
            "level": "beginner",
            "rows": [{
                "lesson_id": "basic_open_palm",
                "state": "COMPLETE",
                "duration_s": 8,
                "confidence_pct": 90,
                "error_code": "OK",
                "completion_stable_ms": 305,
                "samples": {
                    "observations": 10, "low_confidence": 0, "no_hand": 0,
                    "wrong_gesture": 8, "vision_stale": 0, "max_stable_ms": 280,
                },
            }],
        }

    def test_acceptable_model_text_is_kept(self):
        summary = validate_summary(self._held_row())
        kept = "下次让整只手入镜，再复练张开手掌，并看实时标签。"
        advice = request_advice(
            summary, "test-key", "https://api.deepseek.com", DEFAULT_MODEL,
            opener=lambda *_args, **_kwargs: self._text_response(kept),
        )
        self.assertEqual(advice, kept)
        self.assertNotIn("本地核对", advice)
        self.assertFalse(advice_conflicts(advice, summary))

    def test_thin_record_reports_insufficient_evidence(self):
        summary = validate_summary(SUMMARY)
        advice = local_advice(summary)
        self.assertIn("证据不足", advice)
        self.assertIn("张开手掌", advice)
        self.assertIn("本次不足", advice)
        self.assertIn("下次练习建议", advice)
        self.assertNotIn("已经达到保持门限", advice)
        self.assertNotIn("食指", advice)
        self.assertNotIn("稳定度不足", advice)
        self.assertNotIn("保持偏短", advice)
        self.assertNotIn("basic_open_palm", advice)
        self.assertFalse(advice_conflicts(advice, summary))
        invented = advice_for_summary(
            summary, "test-key", "https://api.deepseek.com", DEFAULT_MODEL,
            opener=lambda *_args, **_kwargs: self._text_response("食指弯曲不足，所以这次没练会。"),
        )
        self.assertEqual(invented["source"], "local")
        self.assertEqual(invented["fallback_reason"], "evidence_conflict")
        self.assertIn("证据不足", invented["advice"])
        self.assertNotIn("食指", invented["advice"])

    def test_bad_inference_about_hold_and_stability_is_replaced(self):
        payload = self._held_row()
        summary = validate_summary(payload)
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data.decode("utf-8")))
            return self._text_response(
                "张开手掌保持偏短。手型不符说明学习者稳定度不足。"
                "完成率就是准确率。做错了8次。"
            )

        result = advice_for_summary(
            summary, "test-key", "https://api.deepseek.com", DEFAULT_MODEL, opener=opener
        )
        advice = result["advice"]
        limit = json.loads(captured[0]["messages"][1]["content"])["evaluation_limit"]
        self.assertIn("305毫秒", limit)
        self.assertIn("已达到300毫秒门限", limit)
        self.assertEqual(result["source"], "local")
        self.assertEqual(result["fallback_reason"], "evidence_conflict")
        self.assertIn("张开手掌", advice)
        self.assertIn("305", advice)
        self.assertIn("已经达到保持门限", advice)
        self.assertIn("识别或拍摄", advice)
        self.assertIn("手型不符读数", advice)
        self.assertNotIn("保持偏短", advice)
        self.assertNotIn("稳定度不足", advice)
        self.assertNotIn("准确率", advice)
        self.assertNotIn("做错了8次", advice)
        self.assertNotIn("次错误", advice)
        self.assertFalse(advice_conflicts(advice, summary))
        server = self._serve(requester=lambda *_args: "张开手掌保持偏短，学习者稳定度不足。")
        status, _headers, body = self._request(server, body=payload)
        self.assertEqual(status, 200)
        served = json.loads(body)
        self.assertEqual(served["source"], "local")
        self.assertEqual(served["fallback_reason"], "evidence_conflict")
        self.assertIn("已经达到保持门限", served["advice"])
        self.assertNotIn("保持偏短", served["advice"])
        self.assertNotIn("稳定度不足", served["advice"])

    def test_model_unavailable_uses_local_advice_without_network_text(self):
        summary = validate_summary(SUMMARY)

        def raise_down(_request, timeout):
            raise urllib.error.URLError(ConnectionRefusedError("refused"))

        advice = advice_for_summary(
            summary, "test-key", "https://api.deepseek.com", DEFAULT_MODEL, opener=raise_down
        )
        self.assertEqual(advice["source"], "local")
        self.assertEqual(advice["fallback_reason"], "provider_unavailable")
        self.assertIn("张开手掌", advice["advice"])
        self.assertIn("证据不足", advice["advice"])
        self.assertNotIn("refused", advice["advice"])
        with self.assertRaises(RuntimeError) as raised:
            request_advice(summary, "test-key", "https://api.deepseek.com",
                           DEFAULT_MODEL, opener=raise_down)
        self.assertEqual(str(raised.exception), "provider_unavailable")

    def test_negation_does_not_excuse_a_later_hold_claim(self):
        summary = validate_summary(self._held_row())
        slipped = "不能判断拍摄条件，但张开手掌保持不足。"
        self.assertTrue(advice_conflicts(slipped, summary))
        self.assertFalse(advice_conflicts("不能把这次写成保持不足。", summary))
        denied = resolve_model_text(summary, slipped)
        self.assertEqual(denied["source"], "local")
        self.assertEqual(denied["fallback_reason"], "evidence_conflict")
        self.assertIn("305", denied["advice"])
        self.assertIn("已经达到保持门限", denied["advice"])
        self.assertNotIn("保持不足", denied["advice"])
        server = self._serve(requester=lambda *_args: slipped)
        status, _headers, body = self._request(server, body=self._held_row())
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"advice", "source", "fallback_reason"})
        self.assertEqual(payload["source"], "local")
        self.assertEqual(payload["fallback_reason"], "evidence_conflict")
        self.assertNotIn("保持不足", payload["advice"])

    def test_timeout_record_rejects_a_completion_claim(self):
        summary = validate_summary(SUMMARY)
        claimed = "张开手掌已经完成，全部课程均已通过。"
        self.assertTrue(advice_conflicts(claimed, summary))
        self.assertIn("超时", local_advice(summary))
        self.assertNotIn("已经完成", local_advice(summary))
        self.assertNotIn("均已通过", local_advice(summary))
        resolved = resolve_model_text(summary, claimed)
        self.assertEqual(resolved["source"], "local")
        self.assertEqual(resolved["fallback_reason"], "evidence_conflict")
        self.assertIn("超时", resolved["advice"])
        self.assertNotIn("已经完成", resolved["advice"])
        self.assertNotIn("均已通过", resolved["advice"])
        matched = resolve_model_text(summary, "张开手掌这次超时，先让整只手入镜。")
        self.assertEqual(matched["source"], "model")
        self.assertIsNone(matched["fallback_reason"])
        self.assertIn("这次超时", matched["advice"])
        server = self._serve(requester=lambda *_args: claimed)
        status, _headers, body = self._request(server)
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "local")
        self.assertEqual(payload["fallback_reason"], "evidence_conflict")
        self.assertNotIn("已经完成", payload["advice"])
        rejected = self._serve(
            requester=lambda *_args: (_ for _ in ()).throw(RuntimeError("api_key_rejected"))
        )
        status, _headers, body = self._request(rejected)
        self.assertEqual(status, 502)
        self.assertEqual(set(json.loads(body)), {"error"})

    def _samples(self, **overrides):
        samples = {
            "observations": 2, "low_confidence": 0, "no_hand": 0,
            "wrong_gesture": 0, "vision_stale": 0, "max_stable_ms": 0,
        }
        samples.update(overrides)
        return samples

    def _lesson(self, lesson_id, state, **extra):
        row = {
            "lesson_id": lesson_id,
            "state": state,
            "duration_s": 8,
            "confidence_pct": 80 if state == "COMPLETE" else None,
            "error_code": "OK" if state == "COMPLETE" else state,
            "samples": self._samples(),
        }
        row.update(extra)
        return row

    def _assert_contract(self, payload):
        self.assertEqual(set(payload), {"advice", "source", "fallback_reason"})
        self.assertIsInstance(payload["advice"], str)
        self.assertTrue(payload["advice"].strip())
        self.assertLessEqual(len(payload["advice"]), MAX_ADVICE_CHARS)
        if payload["source"] == "model":
            self.assertIsNone(payload["fallback_reason"])
        elif payload["source"] == "local":
            self.assertIn(payload["fallback_reason"], FALLBACK_REASONS)
        else:
            self.fail("unexpected source {}".format(payload["source"]))

    def test_scope_mention_and_future_steps_stay_model_text(self):
        partial = validate_summary(SUMMARY)
        note = "全部课程只是训练参考，不是能力认证。"
        self.assertFalse(advice_conflicts(note, partial))
        kept = resolve_model_text(partial, note)
        self._assert_contract(kept)
        self.assertEqual(kept["source"], "model")
        self.assertEqual(kept["advice"], note)
        dynamic = validate_summary({
            "level": "advanced",
            "plan": ["word_thanks"],
            "rows": [self._lesson(
                "word_thanks", "TIMEOUT",
                motion_progress={"completed_steps": 2, "total_steps": 5, "complete": False},
            )],
        })
        future = "下次分 2 步检查拍摄条件。"
        matched = "本次完成 2/5 步，下次先看画面。"
        wrong = "本次完成 5/5 步。"
        self.assertFalse(advice_conflicts(future, dynamic))
        self.assertFalse(advice_conflicts(matched, dynamic))
        self.assertTrue(advice_conflicts(wrong, dynamic))
        self.assertEqual(resolve_model_text(dynamic, future)["source"], "model")
        self.assertEqual(resolve_model_text(dynamic, matched)["advice"], matched)
        replaced = resolve_model_text(dynamic, wrong)
        self.assertEqual(replaced["source"], "local")
        self.assertEqual(replaced["fallback_reason"], "evidence_conflict")
        self.assertNotIn("5/5", replaced["advice"])

    def test_malformed_envelopes_are_replaced_by_a_legal_local_result(self):
        summary = validate_summary(SUMMARY)
        leaked = "SHOULD_NOT_LEAK"
        malformed = (
            {"advice": leaked, "source": "model", "fallback_reason": "evidence_conflict"},
            {"advice": leaked, "source": "local", "fallback_reason": None},
            {"advice": leaked, "source": "local", "fallback_reason": "made_up"},
            {"advice": "", "source": "model", "fallback_reason": None},
            {"advice": "x" * (MAX_ADVICE_CHARS + 1), "source": "model", "fallback_reason": None},
            {"advice": leaked, "source": "cloud", "fallback_reason": None},
            {"advice": leaked, "source": "model"},
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                result = coerce_advice_result(summary, payload)
                self._assert_contract(result)
                self.assertEqual(result["source"], "local")
                self.assertEqual(result["fallback_reason"], "evidence_conflict")
                self.assertNotIn(leaked, result["advice"])
        server = self._serve(requester=lambda *_args: malformed[0])
        status, _headers, body = self._request(server)
        served = json.loads(body)
        self.assertEqual(status, 200)
        self._assert_contract(served)
        self.assertEqual(served["fallback_reason"], "evidence_conflict")
        self.assertNotIn(leaked, served["advice"])

    def test_offline_acceptance_matrix_keeps_allowed_text_and_blocks_conflicts(self):
        complete = self._lesson
        all_done = validate_summary({
            "level": "beginner",
            "plan": ["basic_open_palm", "basic_fist"],
            "rows": [
                complete("basic_open_palm", "COMPLETE", completion_stable_ms=320),
                complete("basic_fist", "COMPLETE", completion_stable_ms=400),
            ],
        })
        partial = validate_summary(SUMMARY)
        mixed = validate_summary({
            "level": "beginner",
            "plan": ["basic_open_palm", "basic_fist"],
            "rows": [
                complete("basic_open_palm", "COMPLETE", completion_stable_ms=305),
                complete("basic_fist", "TIMEOUT"),
            ],
        })
        dynamic = validate_summary({
            "level": "advanced",
            "plan": ["word_thanks"],
            "rows": [complete(
                "word_thanks", "TIMEOUT",
                motion_progress={"completed_steps": 2, "total_steps": 5, "complete": False},
            )],
        })
        missing_hold = validate_summary({
            "level": "beginner",
            "plan": ["basic_open_palm"],
            "rows": [complete("basic_open_palm", "COMPLETE")],
        })
        held = validate_summary(self._held_row())
        cases = (
            ("all_complete_allows_plan_pass", all_done, "全部课程均已通过。", True),
            ("all_complete_allows_scope_disclaimer", all_done, "全部课程只是训练参考，不是能力认证。", True),
            ("all_complete_blocks_false_timeout", all_done, "张开手掌这次超时。", False),
            ("partial_blocks_plan_pass", partial, "全部课程均已通过。", False),
            ("partial_allows_scope_disclaimer", partial, "全部课程只是训练参考，不是能力认证。", True),
            ("partial_blocks_false_completion", partial, "张开手掌已经完成。", False),
            ("mixed_allows_named_completion", mixed, "张开手掌已完成。", True),
            ("mixed_blocks_other_lesson_completion", mixed, "握拳已完成。", False),
            ("mixed_allows_named_timeout", mixed, "握拳这次超时。", True),
            ("mixed_blocks_plan_pass", mixed, "全部课程均已通过。", False),
            ("mixed_allows_scope_disclaimer", mixed, "全部课程只是训练参考，不是能力认证。", True),
            ("dynamic_allows_matching_progress", dynamic, "本次完成 2/5 步。", True),
            ("dynamic_blocks_wrong_progress", dynamic, "本次完成 5/5 步。", False),
            ("dynamic_allows_future_steps", dynamic, "下次分 2 步检查拍摄条件。", True),
            ("dynamic_blocks_false_completion", dynamic, "谢谢已经完成。", False),
            ("missing_hold_allows_plain_advice", missing_hold, "先让整只手入镜。", True),
            ("missing_hold_blocks_invented_hold", missing_hold, "通过时保持 305 毫秒。", False),
            ("missing_hold_allows_hold_disclaimer", missing_hold, "不能据此描述保持长短。", True),
            ("negation_allows_denied_hold_claim", held, "不能把这次写成保持不足。", True),
            ("negation_blocks_contrast_hold_claim", held, "不能判断拍摄条件，但张开手掌保持不足。", False),
            ("contradiction_blocks_timeout_called_complete", partial, "张开手掌已经完成，全部课程均已通过。", False),
            ("contradiction_allows_matching_timeout", partial, "张开手掌这次超时，先让整只手入镜。", True),
        )
        for name, summary, text, allowed in cases:
            with self.subTest(name=name):
                self.assertFalse(advice_conflicts(local_advice(summary), summary))
                self.assertEqual(advice_conflicts(text, summary), not allowed)
                result = resolve_model_text(summary, text)
                self._assert_contract(result)
                if allowed:
                    self.assertEqual(result["source"], "model")
                    self.assertEqual(result["advice"], text)
                else:
                    self.assertEqual(result["source"], "local")
                    self.assertEqual(result["fallback_reason"], "evidence_conflict")
                    self.assertNotEqual(result["advice"], text)
        server = self._serve(requester=lambda *_args: "全部课程只是训练参考，不是能力认证。")
        status, _headers, body = self._request(server)
        accepted = json.loads(body)
        self.assertEqual(status, 200)
        self._assert_contract(accepted)
        self.assertEqual(accepted["source"], "model")
        self.assertEqual(accepted["advice"], "全部课程只是训练参考，不是能力认证。")
        failed = self._serve(requester=lambda *_args: (_ for _ in ()).throw(
            urllib.error.URLError(ConnectionRefusedError("refused"))
        ))
        status, _headers, body = self._request(failed)
        unavailable = json.loads(body)
        self.assertEqual(status, 200)
        self._assert_contract(unavailable)
        self.assertEqual(unavailable["source"], "local")
        self.assertEqual(unavailable["fallback_reason"], "provider_unavailable")
        self.assertNotIn("refused", unavailable["advice"])
        rejected = self._serve(requester=lambda *_args: (_ for _ in ()).throw(
            RuntimeError("api_key_rejected")
        ))
        status, _headers, body = self._request(rejected)
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body), {"error": "api_key_rejected"})
        self.assertNotIn(b"advice", body)

    @staticmethod
    def _text_response(text):
        class Response(FakeResponse):
            def read(self, _size):
                return json.dumps({"choices": [{"message": {"content": text}}]}).encode()
        return Response()


if __name__ == "__main__":
    unittest.main()
