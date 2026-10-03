import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "maixcam2"))

from web_stream import (  # noqa: E402
    LatestFrameStore,
    LatestImageStore,
    MaixJpegStreamerAdapter,
    PreviewServer,
    detect_socket_capabilities,
)


class FakeConnection:
    def __init__(self, request=b"GET /stream HTTP/1.1\r\nHost: test\r\n\r\n", block_sends=False):
        self.request_parts = [request]
        self.block_sends = block_sends
        self.sent = bytearray()
        self.closed = False
        self.nonblocking = False

    def setblocking(self, value):
        self.nonblocking = not value

    def recv(self, _size):
        if self.request_parts:
            return self.request_parts.pop(0)
        raise BlockingIOError()

    def send(self, data):
        if self.block_sends:
            raise BlockingIOError()
        self.sent.extend(data)
        return len(data)

    def close(self):
        self.closed = True


class FakeListener:
    def __init__(self, pending):
        self.pending = list(pending)
        self.bound = None
        self.closed = False
        self.nonblocking = False

    def setsockopt(self, *_args):
        pass

    def bind(self, address):
        self.bound = address

    def listen(self, _backlog):
        pass

    def setblocking(self, value):
        self.nonblocking = not value

    def accept(self):
        if not self.pending:
            raise BlockingIOError()
        return self.pending.pop(0), ("127.0.0.1", 4567)

    def close(self):
        self.closed = True


class FakeSocketModule:
    AF_INET = 2
    SOCK_STREAM = 1
    SOL_SOCKET = 1
    SO_REUSEADDR = 2

    def __init__(self, pending=()):
        self.listener = FakeListener(pending)

    def socket(self, *_args):
        return self.listener


class FakeJpegStreamer:
    def __init__(self):
        self.started = False
        self.writes = []
        self.stop_called = False

    def start(self):
        self.started = True
        return FakeMaixHttp.start_result

    def write(self, jpeg):
        self.writes.append(jpeg)
        return FakeMaixHttp.write_result

    def stop(self):
        self.stop_called = True
        self.started = False
        if FakeMaixHttp.stop_exception is not None:
            raise FakeMaixHttp.stop_exception
        return FakeMaixHttp.stop_result


class FakeMaixHttp:
    JpegStreamer = FakeJpegStreamer
    start_result = None
    write_result = None
    stop_result = None
    stop_exception = None


class FakeErr:
    ERR_NONE = object()


FakeMaixHttp.Err = FakeErr


class FakeFrame:
    def __init__(self, jpeg_image):
        self.jpeg_image = jpeg_image

    def to_jpeg(self):
        return self.jpeg_image


class FakeJpegImage:
    pass


class WebStreamTests(unittest.TestCase):
    def test_motion_progress_is_whitelisted_without_geometry(self):
        import json
        progress={"completed_steps":1,"total_steps":5,"complete":False,
                  "prompt":"第一次弯拇指","scope":"2d_sequence_prototype","raw_points":[1,2],
                  "feedback":"短暂未检测到手", "phase_hold_ms":150, "required_hold_ms":300}
        status={"state":"IMITATING","motion_progress":progress,"motion_evidence":{"private":True}}
        server=PreviewServer(sign_status_provider=lambda:status)
        body=server._sign_status_response().split(b"\r\n\r\n",1)[1]
        parsed=json.loads(body)
        self.assertEqual(parsed["motion_progress"]["completed_steps"],1)
        self.assertNotIn("motion_evidence",parsed)
        self.assertNotIn("raw_points",parsed["motion_progress"])
        self.assertEqual(parsed["motion_progress"]["feedback"], "短暂未检测到手")
        self.assertEqual(parsed["motion_progress"]["phase_hold_ms"], 150)
        status["motion_progress"]=dict(progress,phase_hold_ms=True,feedback="x"*65)
        parsed=json.loads(server._sign_status_response().split(b"\r\n\r\n",1)[1])
        self.assertNotIn("phase_hold_ms",parsed["motion_progress"])
        self.assertNotIn("feedback",parsed["motion_progress"])
        status["motion_progress"]=dict(progress,complete=True)
        self.assertNotIn("motion_progress",json.loads(server._sign_status_response().split(b"\r\n\r\n",1)[1]))

    def setUp(self):
        FakeMaixHttp.start_result = None
        FakeMaixHttp.write_result = None
        FakeMaixHttp.stop_result = None
        FakeMaixHttp.stop_exception = None

    def test_latest_frame_store_replaces_old_frame_instead_of_queueing(self):
        frames = LatestFrameStore(1024)
        self.assertTrue(frames.publish(b"old", 10))
        self.assertTrue(frames.publish(b"new", 20))
        self.assertEqual(frames.snapshot(), (2, b"new", 20))
        self.assertEqual(frames.dropped, 1)
        self.assertFalse(frames.publish(b"x" * 1025, 30))

    def test_slow_client_is_evicted_after_bounded_no_progress_and_normal_client_runs(self):
        slow_connection = FakeConnection(block_sends=True)
        normal_connection = FakeConnection()
        sockets = FakeSocketModule([slow_connection, normal_connection])
        server = PreviewServer(
            socket_module=sockets, max_consecutive_would_block=3
        )
        self.assertTrue(server.start())
        self.assertTrue(server.publish_jpeg(b"first", 1))
        for _ in range(3):
            server.poll(max_accepts=2, max_client_writes=4)
        self.assertTrue(slow_connection.closed)
        self.assertEqual(len(server.clients), 1)
        self.assertTrue(server.publish_jpeg(b"second", 2))
        self.assertEqual(server.frames.snapshot()[1], b"second")
        self.assertEqual(server.frames.dropped, 1)
        self.assertIn(b"first", bytes(normal_connection.sent))
        server.poll(max_client_writes=4)
        self.assertIn(b"second", bytes(normal_connection.sent))

    def test_stream_sends_latest_jpeg_and_telemetry_is_read_only(self):
        stream_connection = FakeConnection()
        telemetry_connection = FakeConnection(b"GET /telemetry HTTP/1.1\r\n\r\n")
        sockets = FakeSocketModule([stream_connection, telemetry_connection])
        server = PreviewServer(socket_module=sockets, telemetry_provider=lambda: b'{"schema_version":1}')
        self.assertTrue(server.start())
        server.publish_jpeg(b"annotated", 10)
        for _ in range(6):
            server.poll(max_accepts=2, max_client_writes=4)
        self.assertIn(b"multipart/x-mixed-replace", bytes(stream_connection.sent))
        self.assertIn(b"annotated", bytes(stream_connection.sent))
        self.assertIn(b"application/json", bytes(telemetry_connection.sent))
        self.assertIn(b'{"schema_version":1}', bytes(telemetry_connection.sent))
        self.assertIn(b"Access-Control-Allow-Origin: *", bytes(stream_connection.sent))
        self.assertIn(b"Access-Control-Allow-Origin: *", bytes(telemetry_connection.sent))
        self.assertTrue(telemetry_connection.closed)

    def test_telemetry_503_has_a_stable_non_sensitive_error_code(self):
        class CodedFailure(RuntimeError):
            code = "telemetry_encode_TypeError"

        connection = FakeConnection(b"GET /telemetry HTTP/1.1\r\n\r\n")
        sockets = FakeSocketModule([connection])
        server = PreviewServer(
            socket_module=sockets,
            telemetry_provider=lambda: (_ for _ in ()).throw(CodedFailure()),
        )
        self.assertTrue(server.start())
        for _ in range(3):
            server.poll(max_accepts=1, max_client_writes=1)

        response = bytes(connection.sent)
        self.assertIn(b"503 Service Unavailable", response)
        self.assertIn(b'{"error":"telemetry_unavailable","code":"telemetry_encode_TypeError"}', response)
        self.assertNotIn(b"RuntimeError", response)

    @staticmethod
    def _post_request(origin=None, content_length=b"0", body=b""):
        headers = b"POST /api/v1/train HTTP/1.1\r\nHost: device:8080\r\n"
        if origin is not None:
            headers += b"Origin: " + origin + b"\r\n"
        return headers + b"Content-Length: " + content_length + b"\r\n\r\n" + body

    def test_train_post_rejects_cross_origin_missing_origin_and_body_without_cors(self):
        cases = (
            self._post_request(b"http://evil.example"),
            self._post_request(None),
            self._post_request(b"null"),
            self._post_request(b"http://device:8080", b"1", b"x"),
        )
        for request in cases:
            with self.subTest(request=request):
                calls = []
                connection = FakeConnection(request)
                server = PreviewServer(
                    socket_module=FakeSocketModule([connection]),
                    train_request_handler=lambda: calls.append(True),
                )
                self.assertTrue(server.start())
                server.poll()
                response = bytes(connection.sent)
                self.assertEqual(calls, [])
                self.assertNotIn(b"Access-Control-Allow-Origin", response)
                self.assertTrue(
                    b"403 Forbidden" in response or b"400 Bad Request" in response
                )

    def test_same_origin_train_post_latches_once_and_returns_queued_not_started(self):
        calls = []

        def enqueue():
            calls.append(True)
            return {"request_id": 7, "state": "queued_for_main"} if len(calls) == 1 else None

        first = FakeConnection(self._post_request(b"http://device:8080"))
        second = FakeConnection(self._post_request(b"http://device:8080"))
        server = PreviewServer(
            socket_module=FakeSocketModule([first, second]),
            train_request_handler=enqueue,
        )
        self.assertTrue(server.start())
        server.poll(max_accepts=2, max_client_writes=2)
        first_response = bytes(first.sent)
        second_response = bytes(second.sent)
        self.assertIn(b"202 Accepted", first_response)
        self.assertIn(b'"state":"queued_for_main"', first_response)
        self.assertNotIn(b"started", first_response)
        self.assertIn(b"409 Conflict", second_response)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(b"Access-Control-Allow-Origin", first_response)

    def test_fragmented_post_waits_for_declared_body_before_dispatch(self):
        body = b'{"lesson_id":"basic_fist"}'
        header = (
            b"POST /api/v1/sign/select HTTP/1.1\r\n"
            b"Host: device:8080\r\nOrigin: http://device:8080\r\n"
            b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n"
        )
        calls = []
        connection = FakeConnection(header)
        connection.request_parts.append(body)
        server = PreviewServer(
            socket_module=FakeSocketModule([connection]),
            sign_select_handler=lambda lesson_id: calls.append(lesson_id) or {
                "request_id": 11,
                "state": "queued_for_main",
            },
        )
        self.assertTrue(server.start())
        server.poll(max_accepts=1, max_client_writes=1)
        self.assertEqual(calls, [])
        self.assertEqual(bytes(connection.sent), b"")

        server.poll(max_accepts=0, max_client_writes=1)
        self.assertEqual(calls, ["basic_fist"])
        self.assertIn(b"202 Accepted", bytes(connection.sent))

    def test_control_and_status_are_same_origin_pages_without_cors(self):
        control = FakeConnection(b"GET /control HTTP/1.1\r\nHost: device:8080\r\n\r\n")
        status = FakeConnection(b"GET /api/v1/train/status HTTP/1.1\r\n\r\n")
        server = PreviewServer(
            socket_module=FakeSocketModule([control, status]),
            train_status_provider=lambda: {
                "request_id": 4, "state": "rejected", "reason": "not_bottle",
            },
        )
        self.assertTrue(server.start())
        server.poll(max_accepts=2, max_client_writes=2)
        self.assertIn("手动点击".encode("utf-8"), bytes(control.sent))
        self.assertNotIn(b"Access-Control-Allow-Origin", bytes(control.sent))
        self.assertNotIn(b"fetch('/telemetry')", bytes(control.sent))
        self.assertIn(b"x.can_submit===true", bytes(control.sent))
        self.assertIn(b"inflight=false", bytes(control.sent))
        self.assertIn(b".app-shell", bytes(control.sent))
        self.assertIn(b"width:100%", bytes(control.sent))
        self.assertIn(b"height:auto", bytes(control.sent))
        self.assertNotIn(b"object-fit:fill", bytes(control.sent))
        self.assertIn(b"b.onclick=function(){", bytes(control.sent))
        self.assertIn("人工确认开始".encode("utf-8"), bytes(control.sent))
        self.assertIn(b"basic_open_palm", bytes(control.sent))
        self.assertIn(b"basic_fist", bytes(control.sent))
        self.assertIn(b"basic_v_sign", bytes(control.sent))
        self.assertIn(b"textContent", bytes(control.sent))
        self.assertNotIn(b"innerHTML", bytes(control.sent))
        self.assertNotIn(b"servo_angle", bytes(control.sent))
        self.assertIn(b"/api/v1/train", bytes(control.sent))
        self.assertIn(b'"reason":"not_bottle"', bytes(status.sent))
        self.assertIn(b'"can_submit":false', bytes(status.sent))
        self.assertIn(b'"availability_reason":"availability_unknown"', bytes(status.sent))
        self.assertNotIn(b"Access-Control-Allow-Origin", bytes(status.sent))

    def test_control_page_serves_learner_web_ui_with_stream_and_cards(self):
        control = FakeConnection(b"GET /control HTTP/1.1\r\nHost: device:8080\r\n\r\n")
        server = PreviewServer(socket_module=FakeSocketModule([control]))
        self.assertTrue(server.start())
        server.poll(max_accepts=1, max_client_writes=1)
        page = bytes(control.sent)

        # 1. 页面存在 /stream 图像和视频失败占位文案
        self.assertIn(b'src="/stream"', page)
        self.assertIn("实时画面暂不可用，训练控制未自动触发".encode("utf-8"), page)
        self.assertIn(b"streamFallback", page)

        # 2. 页面明确电脑浏览器是学习者主界面，MaixCAM2 屏幕仅调试
        self.assertIn("电脑网页训练主界面".encode("utf-8"), page)
        self.assertIn("电脑浏览器是学习者主界面，MaixCAM2 屏幕仅调试".encode("utf-8"), page)

        # 3. 三个课程 ID 和三条动作文字说明存在
        self.assertIn(b"basic_open_palm", page)
        self.assertIn(b"basic_fist", page)
        self.assertIn(b"basic_v_sign", page)
        self.assertIn(b"basic_l_shape", page)
        self.assertIn(b"basic_ok_pinch", page)
        self.assertIn(b"word_hello", page)
        self.assertIn(b"word_thanks", page)
        self.assertIn(b"signal_help", page)
        self.assertIn(b"word_no", page)
        self.assertIn(b"word_attention", page)
        self.assertIn(b"word_like", page)
        self.assertIn("张开手掌：五指自然张开，掌心朝向摄像头；".encode("utf-8"), page)
        self.assertIn("握拳：五指收拢，拇指自然覆盖或贴近弯曲手指；".encode("utf-8"), page)
        self.assertIn("V 形手势：食指和中指伸直分开，其余手指弯曲。".encode("utf-8"), page)
        self.assertIn("当前展示七种基础手型与六种日常／应急表达".encode("utf-8"), page)

        # 4. 状态中文映射覆盖 DEMONSTRATING、IMITATING、COMPLETE、TIMEOUT、CANCELLED、FAULT
        for state in ("DEMONSTRATING", "IMITATING", "COMPLETE", "TIMEOUT", "CANCELLED", "FAULT"):
            self.assertIn(state.encode("ascii"), page)
        self.assertIn("正在展示参考动作（约 3 秒）".encode("utf-8"), page)
        self.assertIn("现在请对着摄像头模仿".encode("utf-8"), page)
        self.assertIn("完成".encode("utf-8"), page)
        self.assertIn("训练超时".encode("utf-8"), page)
        self.assertIn("训练已取消".encode("utf-8"), page)
        self.assertIn("训练故障".encode("utf-8"), page)
        self.assertIn("提示人工确认".encode("utf-8"), page)
        self.assertIn("提示先选课程".encode("utf-8"), page)

        # 5. 动态设备文本仍通过 textContent，无 innerHTML
        self.assertIn(b"textContent", page)
        self.assertNotIn(b"innerHTML", page)

        # 6. 页面不存在向舵机角度、servo、angle 等参数的提交
        self.assertNotIn(b"servo", page)
        self.assertNotIn(b"angle", page)

        # 7. 旧 /api/v1/train 路径仍存在
        self.assertIn(b"/api/v1/train", page)

        # 8. 双栏布局与关键状态元素存在
        self.assertIn(b"main-grid", page)
        self.assertIn(b"col-left", page)
        self.assertIn(b"col-right", page)
        self.assertIn(b"stepAlert", page)
        self.assertIn(b"validity", page)
        self.assertIn(b"errorCode", page)
        self.assertIn(b"videoHud", page)
        self.assertIn(b"hudLesson", page)
        self.assertIn(b"hudPhase", page)
        self.assertIn(b"hudGesture", page)

        # 9. 并发与按钮失效安全（无 Promise.all，仅且仅有一个 src="/stream"，无 setButtonsDisabled(false)）
        self.assertNotIn(b"Promise.all", page)
        self.assertEqual(page.count(b'src="/stream"'), 1)
        self.assertNotIn(b"setButtonsDisabled(false)", page)

        # 10. 实时画面等比例放大（width:100%，height:auto，无 object-fit:fill）
        self.assertIn(b"width:100%", page)
        self.assertIn(b"height:auto", page)
        self.assertNotIn(b"object-fit:fill", page)

        # 11. 静态文案修正
        self.assertIn(
            "连续动作按二维步骤原型评价，不判断身体位置或完整标准手语语义。".encode("utf-8"),
            page,
        )

        # 12. 识别标签、错误原因、请求原因和请求状态全中文映射
        for tag in (
            "张开手掌", "握拳", "V 形手势", "食指指向", "竖拇指", "未识别"
        ):
            self.assertIn(tag.encode("utf-8"), page)

        for err in (
            "未检测到手", "未识别到有效手型", "识别置信度不足", "当前手型与目标不符",
            "Titan 连接断开", "视觉数据已过期", "当前阶段不允许此操作", "设备状态异常",
            "课程已选择", "训练已开始", "尚未开始", "训练正在进行", "无效课程",
            "手语训练暂不可用", "Titan 状态已过期", "视觉状态已过期", "当前状态不允许执行",
            "Titan 姿态状态异常", "Titan 安全门不可用", "通信状态异常", "机械示范尚未验证",
            "训练控制器接口不可用", "训练控制器拒绝请求", "开始请求被拒绝", "示范请求被拒绝",
            "取消请求被拒绝", "请求已过期，请重新操作", "无效请求",
        ):
            self.assertIn(err.encode("utf-8"), page)

        for req in ("请求已接收，等待设备处理", "操作已生效", "请求被拒绝", "请求已过期，请重新操作", "设备正忙，请稍后重试", "就绪"):
            self.assertIn(req.encode("utf-8"), page)

        self.assertIn("毫秒".encode("utf-8"), page)
        self.assertIn(b"LESSON_MAP", page)

        # 13. 竞赛展示增强：健康指示栏、五步流转、课程分类 Tab 与独立详情卡
        self.assertIn(b"health-bar", page)
        self.assertIn(b"healthVision", page)
        self.assertIn(b"healthTitan", page)
        self.assertIn(b"healthMotion", page)
        self.assertIn("未上报".encode("utf-8"), page)
        self.assertIn(b"process-bar", page)
        self.assertIn("3. 参考动作示范".encode("utf-8"), page)
        self.assertIn(b"cat-tabs", page)
        self.assertIn(b'data-tab="basic"', page)
        self.assertIn(b'data-tab="daily"', page)
        self.assertIn(b'data-tab="emergency"', page)
        self.assertIn(b"lessonDetailCard", page)
        self.assertIn(b"course-grid", page)

    def test_sign_status_safely_forwards_mechanical_motion_and_link_without_servo(self):
        conn = FakeConnection(b"GET /api/v1/sign/status HTTP/1.1\r\n\r\n")
        server = PreviewServer(
            socket_module=FakeSocketModule([conn]),
            sign_status_provider=lambda: {
                "request_id": 5,
                "state": "DEMONSTRATING",
                "reason": "ok",
                "link_online": True,
                "mechanical_motion": {
                    "state": 2,
                    "result": 0,
                    "completed_count": 1,
                    "sequence_id": 1,
                    "last_error": "OK",
                    "servo_angle_mailbox": [90, 100],  # 恶意/多余参数应被白名单丢弃
                },
            },
        )
        self.assertTrue(server.start())
        server.poll()
        body = bytes(conn.sent)
        self.assertIn(b'"state":"DEMONSTRATING"', body)
        self.assertIn(b'"link_online":true', body)
        self.assertIn(b'"mechanical_motion":{"state":2,"result":0,"completed_count":1,"sequence_id":1,"last_error":"OK"}', body)
        self.assertNotIn(b"servo", body)
        self.assertNotIn(b"angle", body)

    def test_mechanical_motion_idle_three_titan_combinations(self):
        # 1. 验证三种组合在 /api/v1/sign/status 中的安全下发
        cases = (
            (True, {"state": 0}, b'"link_online":true', b'"state":0'),
            (None, {"state": 0}, None, b'"state":0'),
            (False, {"state": 0}, b'"link_online":false', b'"state":0'),
        )
        for link_online, motion, expected_link, expected_motion in cases:
            with self.subTest(link_online=link_online):
                conn = FakeConnection(b"GET /api/v1/sign/status HTTP/1.1\r\n\r\n")
                status_dict = {
                    "request_id": 9,
                    "state": "IDLE",
                    "reason": "ok",
                    "mechanical_motion": motion,
                }
                if link_online is not None:
                    status_dict["link_online"] = link_online
                server = PreviewServer(
                    socket_module=FakeSocketModule([conn]),
                    sign_status_provider=lambda s=status_dict: s,
                )
                self.assertTrue(server.start())
                server.poll()
                body = bytes(conn.sent)
                if expected_link:
                    self.assertIn(expected_link, body)
                else:
                    self.assertNotIn(b'"link_online"', body)
                self.assertIn(expected_motion, body)

        # 2. 验证前端 _CONTROL_PAGE 包含防止误导的核心逻辑与文案
        control = FakeConnection(b"GET /control HTTP/1.1\r\nHost: device:8080\r\n\r\n")
        server = PreviewServer(socket_module=FakeSocketModule([control]))
        self.assertTrue(server.start())
        server.poll()
        page = bytes(control.sent)
        self.assertIn("等待 Titan 状态".encode("utf-8"), page)
        self.assertIn("不可用（Titan 断开）".encode("utf-8"), page)
        self.assertIn(b"x.link_online===true", page)
        self.assertIn("titanText==='断开'".encode("utf-8"), page)

        # 3. 若运行环境存在 node，对页面内 showSign 核心判据的三种组合状态进行真实求值校验
        import shutil
        import subprocess
        node_bin = shutil.which("node")
        if node_bin:
            js_code = (
                "var tests = ["
                "{x: {link_online: true, mechanical_motion: {state: 0}}, expected: '就绪'},"
                "{x: {mechanical_motion: {state: 0}}, expected: '等待 Titan 状态'},"
                "{x: {link_online: false, mechanical_motion: {state: 0}}, expected: '不可用（Titan 断开）'},"
                "{x: {error_code: 'link_offline', mechanical_motion: {state: 0}}, expected: '不可用（Titan 断开）'}"
                "];"
                "for (var t of tests) {"
                "  var x = t.x;"
                "  var errLower = String(x.error_code || x.reason || '').toLowerCase();"
                "  var titanText = '未上报';"
                "  if (errLower.indexOf('link_offline') !== -1 || errLower.indexOf('titan_link_offline') !== -1) {"
                "    titanText = '断开';"
                "  } else if (typeof x.link_online === 'boolean') {"
                "    titanText = x.link_online ? '在线' : '断开';"
                "  } else {"
                "    titanText = '未上报';"
                "  }"
                "  var motionText = '未上报';"
                "  var m = x.mechanical_motion;"
                "  if (m && typeof m === 'object' && typeof m.state === 'number') {"
                "    if (m.state === 2) { motionText = '运行中'; }"
                "    else if (m.state === 1) { motionText = '排队中'; }"
                "    else if (m.state === 5) { motionText = (m.result === 1) ? '动作完成' : '已结束'; }"
                "    else if (m.state === 6) { motionText = '已取消'; }"
                "    else if (m.state === 7 || m.result === 2) { motionText = '动作故障'; }"
                "    else if (m.state === 0) {"
                "      if (x.link_online === true) { motionText = '就绪'; }"
                "      else if (titanText === '断开') { motionText = '不可用（Titan 断开）'; }"
                "      else { motionText = '等待 Titan 状态'; }"
                "    }"
                "  }"
                "  if (motionText !== t.expected) {"
                "    throw new Error('Expected ' + t.expected + ' but got ' + motionText);"
                "  }"
                "}"
                "console.log('NODE_VERIFIED_OK');"
            )
            result = subprocess.run([node_bin, "-e", js_code], capture_output=True, text=True, check=True)
            self.assertIn("NODE_VERIFIED_OK", result.stdout)

    def test_sign_status_safely_forwards_aitrust(self):
        conn = FakeConnection(b"GET /api/v1/sign/status HTTP/1.1\r\n\r\n")
        server = PreviewServer(
            socket_module=FakeSocketModule([conn]),
            sign_status_provider=lambda: {
                "request_id": 5,
                "state": "IDLE",
                "link_online": True,
                "aitrust": {
                    "version": 1,
                    "ready": True,
                    "class_id": 0,
                    "vision_age_ms": 250,
                    "seq": 10,
                    "generation": 1,
                    "rx_time_ms": 1000,
                    "expired": False,
                    "malicious_servo_payload": [1, 2, 3],  # 必须被白名单剔除
                },
            },
        )
        self.assertTrue(server.start())
        server.poll()
        body = bytes(conn.sent)
        self.assertIn(b'"aitrust":{"version":1,"class_id":0,"vision_age_ms":250,"seq":10,"generation":1,"rx_time_ms":1000,"ready":true,"expired":false}', body)
        self.assertNotIn(b"malicious_servo_payload", body)

    def test_aitrust_seven_states_and_decision_a_node_evaluation(self):
        # 1. 验证前端 HTML 包含端侧 AI 健康指标与说明
        control = FakeConnection(b"GET /control HTTP/1.1\r\nHost: device:8080\r\n\r\n")
        server = PreviewServer(socket_module=FakeSocketModule([control]))
        self.assertTrue(server.start())
        server.poll()
        page = bytes(control.sent)
        self.assertIn(b"healthAiTrust", page)
        self.assertIn(b"aitrustVal", page)
        self.assertIn("端侧AI参考".encode("utf-8"), page)
        self.assertIn("辅助判断，非安全认证".encode("utf-8"), page)

        # 2. 从真实 _CONTROL_PAGE 提取 <script> 并在 Node.js 中执行，直接检验页面真实脚本逻辑
        import shutil
        import subprocess
        node_bin = shutil.which("node")
        if node_bin:
            script_start = page.find(b"<script>") + len(b"<script>")
            script_end = page.rfind(b"</script>")
            self.assertGreater(script_start, 0)
            self.assertGreater(script_end, script_start)
            raw_page_script = page[script_start:script_end].decode("utf-8")

            driver_code = f"""
const assert = require('assert');

// 1. Mock DOM environment for _CONTROL_PAGE elements
const elements = {{}};
function getEl(id) {{
    if (!elements[id]) {{
        elements[id] = {{
            id: id,
            textContent: '',
            className: '',
            style: {{}},
            disabled: false,
            hidden: false,
            setAttribute: function(k, v) {{ this[k] = v; }},
            getAttribute: function(k) {{ return this[k] || null; }},
            querySelectorAll: function() {{ return []; }}
        }};
    }}
    return elements[id];
}}

global.document = {{
    getElementById: getEl,
    querySelectorAll: function() {{ return []; }}
}};

// 2. Monotonic clock control
let currentTime = 1000;
global.performance = {{
    now: () => currentTime
}};

// 3. Mock timers to capture watchdog and poll intervals
const intervals = [];
global.setInterval = function(fn, ms) {{
    const item = {{ fn, ms }};
    intervals.push(item);
    return item;
}};

// 4. Mock HTTP fetch endpoint
let currentSignStatus = null;
let currentTrainStatus = {{ can_submit: false, state: 'idle' }};
let fetchHanging = false;
let hangingReject = null;

global.fetch = function(url, options) {{
    if (fetchHanging) {{
        return new Promise((resolve, reject) => {{
            hangingReject = reject;
        }});
    }}
    if (url.includes('/api/v1/sign/status')) {{
        return Promise.resolve({{
            json: () => Promise.resolve(currentSignStatus)
        }});
    }}
    if (url.includes('/api/v1/train/status')) {{
        return Promise.resolve({{
            json: () => Promise.resolve(currentTrainStatus)
        }});
    }}
    return Promise.resolve({{
        json: () => Promise.resolve({{}})
    }});
}};

// 5. Execute the actual in-page script extracted from _CONTROL_PAGE
{raw_page_script}

async function run() {{
    const watchdogItem = intervals.find(i => i.ms === 200);
    const pollItem = intervals.find(i => i.ms === 500);
    assert(watchdogItem && typeof watchdogItem.fn === 'function', 'Watchdog interval not found');
    assert(pollItem && typeof pollItem.fn === 'function', 'Poll interval not found');

    const watchdog = watchdogItem.fn;
    const poll = pollItem.fn;

    async function stepPoll(statusData) {{
        currentSignStatus = statusData;
        poll();
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));
        await new Promise(r => setImmediate(r));
    }}

    await stepPoll({{state:'IMITATING',lesson_id:'word_thanks',link_online:true,
        motion_progress:{{completed_steps:1,total_steps:5,complete:false,prompt:'第一次弯拇指',feedback:'短暂未检测到手：已完成步骤保留',scope:'2d_sequence_prototype'}}}});
    assert(elements['phase'].textContent.includes('第 2/5 步'));
    assert(elements['phase'].textContent.includes('已确认 1 步'));
    assert(elements['phase'].textContent.includes('短暂未检测到手'));
    assert(elements['coachAdvice'].textContent.includes('第一次弯拇指'));
    await stepPoll({{state:'IMITATING',lesson_id:'word_thanks',link_online:true,
        motion_progress:{{completed_steps:0,total_steps:5,complete:false,prompt:'伸直拇指',scope:'2d_sequence_prototype'}}}});
    assert(elements['phase'].textContent.includes('第 1/5 步'));
    assert(elements['coachAdvice'].textContent.includes('伸直拇指'));

    // --- TEST 1: Decision A counterexample ---
    // ready=0, class_id=0 MUST NOT be green/ok under any circumstances
    currentTime = 1000;
    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: false, class_id: 0, generation: 1 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '未就绪');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val warn');
    assert.notStrictEqual(elements['healthAiTrust'].className, 'health-val ok');
    assert.strictEqual(elements['aitrustVal'].textContent, '未就绪');

    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: false, class_id: 1, generation: 2 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '未就绪');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val warn');

    // --- TEST 2: Normal trusted state ---
    // ready=true, class_id=0 -> 可信, green (health-val ok)
    currentTime = 2000;
    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: true, class_id: 0, generation: 3 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '可信');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val ok');
    assert.strictEqual(elements['aitrustVal'].textContent, '可信');

    // --- TEST 3: Request hang > 1500 ms expires green via monotonic watchdog ---
    fetchHanging = true;
    poll();
    currentTime += 1600; // monotonic clock advances > 1500 ms
    watchdog(); // watchdog fires
    assert.strictEqual(elements['healthAiTrust'].textContent, '已过期');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val warn');
    assert.notStrictEqual(elements['healthAiTrust'].className, 'health-val ok');
    assert.strictEqual(elements['aitrustVal'].textContent, '已过期');

    // Reset hanging request
    fetchHanging = false;
    if (hangingReject) {{
        hangingReject(new Error('timeout'));
        hangingReject = null;
    }}
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));

    // --- TEST 4: Remaining 7-state evaluations via real in-page script ---
    currentTime += 100;
    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: true, class_id: 1, generation: 4 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '存疑');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val warn');

    currentTime += 100;
    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: true, class_id: 2, generation: 5 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '异常');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val err');

    currentTime += 100;
    await stepPoll({{
        link_online: false,
        aitrust: {{ ready: true, class_id: 0, generation: 6 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '链路离线');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val err');

    currentTime += 100;
    await stepPoll({{
        error_code: 'link_offline',
        aitrust: {{ ready: true, class_id: 0, generation: 7 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '链路离线');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val err');

    currentTime += 100;
    await stepPoll({{
        link_online: true,
        aitrust: {{ ready: true, class_id: 0, expired: true, generation: 8 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '已过期');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val warn');

    currentTime += 100;
    await stepPoll({{
        link_online: true,
        aitrust: {{ state: 'not_reported' }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '未上报');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val unknown');

    currentTime += 100;
    await stepPoll({{
        aitrust: {{ ready: true, class_id: 0, generation: 9 }}
    }});
    assert.strictEqual(elements['healthAiTrust'].textContent, '未上报');
    assert.strictEqual(elements['healthAiTrust'].className, 'health-val unknown');

    console.log('REAL_PAGE_SCRIPT_VERIFIED_OK');
}}

run().catch(err => {{
    console.error(err);
    process.exit(1);
}});
"""
            result = subprocess.run(
                [node_bin, "-"],
                input=driver_code,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            self.assertIn("REAL_PAGE_SCRIPT_VERIFIED_OK", result.stdout)

    def test_level_report_uses_real_terminal_status_and_never_auto_starts(self):
        import shutil
        import subprocess
        from web_stream import _CONTROL_PAGE

        page = _CONTROL_PAGE.decode("utf-8")
        self.assertIn('data-level="beginner"', page)
        self.assertIn('data-level="intermediate"', page)
        self.assertIn('data-level="advanced"', page)
        self.assertIn('id="levelReport"', page)
        self.assertIn('id="levelAiResult"', page)
        self.assertIn('AI 训练分析 · 下次怎么练', page)
        node = shutil.which("node")
        if not node:
            return
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        driver = r"""
const assert=require('assert');
const elements={};
function el(id){if(!elements[id])elements[id]={id,textContent:'',className:'',style:{},disabled:false,hidden:false,getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;}};return elements[id];}
const level=el('beginner');level['data-level']='beginner';
global.document={getElementById:el,querySelectorAll(q){return q==='[data-level]'?[level]:[];}};
global.performance={now:()=>1000};
const intervals=[];global.setInterval=(fn,ms)=>{intervals.push({fn,ms});};
let sign={state:'IDLE'},aiMode='ok';const posts=[],aiRequests=[],downloads=[];
global.Blob=function(parts){downloads.push(String(parts[0]||''));};
global.URL={createObjectURL:()=>'blob:report',revokeObjectURL:()=>{}};
global.document.body={appendChild(){},removeChild(){}};
global.document.createElement=()=>({click(){}});
global.fetch=(url,opts)=>{if(url.includes('/api/v1/ai/course-advice')){aiRequests.push(JSON.parse(opts.body));
if(aiMode==='offline')return Promise.reject(new Error('offline'));
if(aiMode==='key')return Promise.resolve({ok:false,json:()=>Promise.resolve({error:'api_key_rejected'})});
if(aiMode==='timeout')return Promise.resolve({ok:false,json:()=>Promise.resolve({error:'provider_timeout'})});
if(aiMode==='down')return Promise.resolve({ok:false,json:()=>Promise.resolve({error:'provider_unavailable'})});
return Promise.resolve({ok:true,json:()=>Promise.resolve({advice:'下次先练 V 手势，观察两指间距。'})});}
if(opts&&opts.method==='POST'){posts.push({url,body:opts.body});return Promise.resolve({json:()=>Promise.resolve({state:'queued'})});}
return Promise.resolve({json:()=>Promise.resolve(url.includes('/api/v1/sign/status')?sign:{can_submit:false,state:'idle'})});};
""" + script + r"""
async function flush(){await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));await new Promise(r=>setImmediate(r));}
async function run(){await flush();level.onclick();await flush();
assert.strictEqual(posts.length,1);assert(posts[0].url.includes('/api/v1/sign/select'));
assert(!posts.some(p=>p.url.includes('/api/v1/sign/start')));
const poll=intervals.find(i=>i.ms===500).fn;
sign={state:'DEMONSTRATING',lesson_id:'basic_open_palm'};poll();await flush();
sign={state:'COMPLETE',lesson_id:'basic_open_palm',confidence:0.8,error_code:'OK'};poll();await flush();
assert(el('levelReport').textContent.includes('完成：1'));
assert(el('levelReport').textContent.includes('不是完整连续动作通过'));
assert(el('levelAiResult').textContent.includes('本次不足'));
assert(el('levelAiResult').textContent.includes('证据局限'));
assert(el('levelAiResult').textContent.includes('下次练习建议'));
assert.strictEqual(el('levelAiRecorded').textContent,'1 / 3 项');
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
assert.strictEqual(el('levelNext').disabled,false);
assert.strictEqual(el('levelNext').hidden,false);
assert.strictEqual(el('levelNext').textContent,'下一项：握拳（2/3）');
assert(el('courseGuideTitle').textContent.includes('张开手掌 已完成'));
assert(el('courseGuideHint').textContent.includes('下一项：握拳'));
assert(el('stepAlert').textContent.includes('下一项：握拳'));
assert.strictEqual(el('courseStep1').className,'passed');
assert.strictEqual(el('signStart').hidden,true);
el('levelNext').onclick();await flush();
assert.strictEqual(posts.length,2);assert(posts[1].body.includes('basic_fist'));
assert(el('courseGuideTitle').textContent.includes('第 2/3 项：握拳'));
assert.strictEqual(el('signStart').disabled,true);
assert(!posts.some(p=>p.url.includes('/api/v1/sign/start')));
sign={state:'IMITATING',lesson_id:'basic_fist'};poll();await flush();
sign={state:'TIMEOUT',lesson_id:'basic_fist',confidence:0,error_code:'TIMEOUT'};poll();await flush();
assert(el('levelReport').textContent.includes('训练超时'));
assert(el('levelReport').textContent.includes('未完成：1'));
assert(el('levelReport').textContent.includes('本次不足'));
assert(el('levelReport').textContent.includes('仅凭超时不能判断'));
assert(el('levelReport').textContent.includes('优先复练握拳'));
assert(el('courseGuideTitle').textContent.includes('训练超时'));
assert.strictEqual(el('levelNext').textContent,'下一项：V 形手势（3/3）');
level.onclick();await flush();
sign={state:'IMITATING',lesson_id:'basic_open_palm'};poll();await flush();
sign={state:'FAULT',lesson_id:'basic_open_palm',error_code:'VISION_STALE'};poll();await flush();
assert(el('levelReport').textContent.includes('不能据此评价动作能力'));
assert(el('levelReport').textContent.includes('检查连接、光照'));
level.onclick();await flush();
sign={state:'IMITATING',lesson_id:'basic_open_palm'};poll();await flush();
sign={state:'COMPLETE',lesson_id:'basic_open_palm',confidence:0.61,error_code:'LOW_CONFIDENCE'};poll();await flush();
assert(el('levelReport').textContent.includes('识别置信度不足'));
level.onclick();await flush();
sign={state:'IMITATING',lesson_id:'basic_open_palm'};poll();await flush();
sign={state:'COMPLETE',lesson_id:'basic_open_palm',confidence:0.95,error_code:'OK'};poll();await flush();
assert(el('levelReport').textContent.includes('没有明确的失败'));
assert.strictEqual(el('levelAiAdvice').disabled,false);
const postsBeforeAdvice=posts.length;
el('levelAiAdvice').onclick();await flush();
assert.strictEqual(posts.length,postsBeforeAdvice);
assert(!posts.some(p=>p.url.includes('/sign/start')||p.url.includes('/api/v1/train')));
assert.strictEqual(aiRequests.length,1);
assert.strictEqual(aiRequests[0].level,'beginner');
assert.deepStrictEqual(aiRequests[0].rows[0],{lesson_id:'basic_open_palm',state:'COMPLETE',duration_s:0,confidence_pct:95,error_code:'OK',samples:{observations:1,low_confidence:0,no_hand:0,wrong_gesture:0,vision_stale:0,max_stable_ms:0}});
assert.deepStrictEqual(Object.keys(aiRequests[0]).sort(),['level','rows']);
assert(!JSON.stringify(aiRequests[0]).match(/landmark|image|photo|关键点/i));
assert(el('levelReport').textContent.includes('下次先练 V 手势'));
assert(el('levelAiResult').textContent.includes('下次先练 V 手势'));
assert(el('levelAiResult').textContent.includes('证据局限'));
el('levelDownload').onclick();
assert(downloads.at(-1).includes('证据局限'));
assert(downloads.at(-1).includes('不是完整连续动作通过'));
assert(downloads.at(-1).includes('本次不足'));
assert(downloads.at(-1).includes('下次练习建议'));
assert(downloads.at(-1).includes('下次先练 V 手势'));
assert.strictEqual(el('levelAiBadge').textContent,'已生成');
assert.strictEqual(el('levelAiBadge').className,'ai-badge ready');
aiMode='offline';el('levelAiAdvice').onclick();await flush();
assert(el('levelAiStatus').textContent.includes('原有训练报告不受影响'));
assert(el('levelReport').textContent.includes('下次先练 V 手势'));
assert(el('levelAiResult').textContent.includes('下次先练 V 手势'));
el('levelNext').onclick();await flush();
sign={state:'IMITATING',lesson_id:'basic_fist',recognition_error_code:'LOW_CONFIDENCE',stable_ms:120};poll();await flush();
sign={state:'TIMEOUT',lesson_id:'basic_fist',error_code:'TIMEOUT'};poll();await flush();
assert(!el('levelReport').textContent.includes('下次先练 V 手势'));
assert(!el('levelAiResult').textContent.includes('下次先练 V 手势'));
assert.strictEqual(el('levelAiBadge').textContent,'待生成');
assert(el('levelReport').textContent.includes('低置信度 1 次'));
assert(el('levelAiStatus').textContent.includes('重新生成'));
el('levelAiAdvice').onclick();await flush();
assert.strictEqual(el('levelAiBadge').textContent,'暂不可用');
assert(el('levelAiResult').textContent.includes('下方规则报告'));
assert(el('levelReport').textContent.includes('本次不足'));
assert.strictEqual(el('levelDownload').disabled,false);
el('levelDownload').onclick();
assert(downloads.at(-1).includes('本次不足'));
assert(downloads.at(-1).includes('证据局限'));
aiMode='key';el('levelAiAdvice').onclick();await flush();
assert(el('levelAiStatus').textContent.includes('密钥被拒绝'));
assert(el('levelReport').textContent.includes('低置信度 1 次'));
aiMode='timeout';el('levelAiAdvice').onclick();await flush();
assert(el('levelAiStatus').textContent.includes('模型响应超时'));
aiMode='down';el('levelAiAdvice').onclick();await flush();
assert(el('levelAiStatus').textContent.includes('模型服务不可用'));
assert(el('levelReport').textContent.includes('本次不足'));
console.log('LEVEL_REPORT_OK');}
run().catch(e=>{console.error(e);process.exit(1);});
"""
        result = subprocess.run(
            [node, "-"], input=driver, capture_output=True, text=True,
            encoding="utf-8"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LEVEL_REPORT_OK", result.stdout)

    def test_course_guidance_full_route_retry_and_manual_confirmation(self):
        import shutil
        import subprocess
        from web_stream import _CONTROL_PAGE

        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for real-page guidance test")
        script = _CONTROL_PAGE.decode("utf-8").split("<script>", 1)[1].split("</script>", 1)[0]
        driver = r"""
const assert=require('assert'),elements={},posts=[],intervals=[];
function el(id){if(!elements[id])elements[id]={textContent:'',className:'',style:{},hidden:false,disabled:false,getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;}};return elements[id];}
const beginner=el('beginner');beginner['data-level']='beginner';
const advanced=el('advanced');advanced['data-level']='advanced';
const single=el('single');single['data-lesson']='basic_l_shape';
global.document={getElementById:el,querySelectorAll(q){return q==='[data-level]'?[beginner,advanced]:q==='[data-lesson]'?[single]:[];}};
let scrolls=0;el('analysis').scrollIntoView=()=>{scrolls++;};
global.performance={now:()=>1000};global.setInterval=(fn,ms)=>intervals.push({fn,ms});
let sign={state:'IDLE'};
global.fetch=(url,opts)=>{if(opts&&opts.method==='POST'){posts.push({url,body:JSON.parse(opts.body)});return Promise.resolve({json:()=>Promise.resolve({state:'queued'})});}
return Promise.resolve({json:()=>Promise.resolve(url.includes('/api/v1/sign/status')?sign:{can_submit:false,state:'idle'})});};
""" + script + r"""
async function flush(){for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));}
async function state(value){sign=value;intervals.find(i=>i.ms===500).fn();await flush();}
async function run(){await flush();beginner.onclick();await flush();
assert.strictEqual(el('courseGuide').hidden,false);
assert(el('courseStep1').textContent.includes('张开手掌'));
assert(el('courseStep2').textContent.includes('握拳'));
assert(el('courseStep3').textContent.includes('V 形手势'));
assert.strictEqual(el('courseStep4').hidden,true);
assert.strictEqual(el('levelNext').hidden,true);
await state({state:'LESSON_SELECTED',lesson_id:'basic_open_palm',can_start:true});
assert.strictEqual(el('signStart').textContent,'人工确认开始：张开手掌');
assert.strictEqual(el('signStart').disabled,false);
assert(el('courseGuideHint').textContent.includes('请点击下方'));
el('signStart').onclick();await flush();
assert.strictEqual(posts.filter(p=>p.url.includes('/sign/start')).length,1);
await state({state:'DEMONSTRATING',lesson_id:'basic_open_palm'});
assert(el('courseGuideHint').textContent.includes('先看参考示范'));
await state({state:'IMITATING',lesson_id:'basic_open_palm'});
assert(el('courseGuideTitle').textContent.includes('现在模仿张开手掌'));
await state({state:'COMPLETE',lesson_id:'basic_open_palm',can_start:true});
assert.strictEqual(el('signStart').hidden,true);
el('signStart').onclick();await flush();
assert.strictEqual(posts.filter(p=>p.url.includes('/sign/start')).length,1);
await state(sign);assert.strictEqual(el('levelAiRecorded').textContent,'1 / 3 项');
el('levelNext').onclick();await flush();
assert.strictEqual(posts.at(-1).body.lesson_id,'basic_fist');
// The previous item's status must not enable starting the newly selected item.
assert.strictEqual(el('signStart').disabled,true);
assert(el('detailTitle').textContent.includes('握拳'));
assert.strictEqual(el('levelReselect').hidden,false);
el('levelReselect').onclick();await flush();
assert.strictEqual(posts.at(-1).body.lesson_id,'basic_fist');
assert.strictEqual(posts.filter(p=>p.url.includes('/sign/start')).length,1);
await state({state:'LESSON_SELECTED',lesson_id:'basic_fist',can_start:false});
assert(el('courseGuideHint').textContent.includes('暂不能开始'));
assert.strictEqual(el('signStart').disabled,true);
await state({state:'LESSON_SELECTED',lesson_id:'basic_fist',can_start:true});
assert.strictEqual(el('signStart').textContent,'人工确认开始：握拳');
assert.strictEqual(el('levelReselect').hidden,true);
await state({state:'IMITATING',lesson_id:'basic_fist'});
await state({state:'TIMEOUT',lesson_id:'basic_fist'});
assert.strictEqual(el('courseStep2').className,'recorded');
assert(el('courseGuideTitle').textContent.includes('训练超时'));
el('levelNext').onclick();await flush();
await state({state:'IMITATING',lesson_id:'basic_v_sign'});
await state({state:'COMPLETE',lesson_id:'basic_v_sign'});
assert.strictEqual(el('levelNext').hidden,true);
assert.strictEqual(el('levelReportJump').hidden,false);
assert(el('courseGuideTitle').textContent.includes('达标 2/3'));
assert(el('courseGuideHint').textContent.includes('下载报告'));
const before=posts.length;el('levelReportJump').onclick();await flush();
assert.strictEqual(scrolls,1);assert.strictEqual(posts.length,before);
advanced.onclick();await flush();
assert.strictEqual(el('courseStep6').hidden,false);
assert(el('courseStep6').textContent.includes('求助信号'));
assert.strictEqual(el('levelReportJump').hidden,true);
assert(el('courseGuideTitle').textContent.includes('第 1/6 项'));
single.onclick();await flush();
assert.strictEqual(el('courseGuide').hidden,true);
assert.strictEqual(el('signStart').hidden,false);
assert.strictEqual(el('signStart').textContent,'人工确认开始');
console.log('COURSE_GUIDANCE_OK');}
run().catch(e=>{console.error(e);process.exit(1);});
"""
        result = subprocess.run([node, "-"], input=driver, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COURSE_GUIDANCE_OK", result.stdout)

    def test_workbench_layout_keeps_unique_controls_and_camera_before_reports(self):
        from html.parser import HTMLParser
        from web_stream import _CONTROL_PAGE

        class LayoutParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = []
                self.parents = {}
                self.stack = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                identity = attrs.get("id")
                if identity:
                    self.ids.append(identity)
                    self.parents[identity] = tuple(self.stack)
                if tag not in {"meta", "img", "br", "link", "input", "hr"}:
                    self.stack.append((tag, identity, attrs.get("class", "")))

            def handle_endtag(self, tag):
                for index in range(len(self.stack) - 1, -1, -1):
                    if self.stack[index][0] == tag:
                        del self.stack[index:]
                        break

        page = _CONTROL_PAGE.decode("utf-8")
        parser = LayoutParser()
        parser.feed(page)
        self.assertEqual(len(parser.ids), len(set(parser.ids)), "duplicate IDs break real DOM updates")
        self.assertLess(parser.ids.index("streamImg"), parser.ids.index("analysis"))
        self.assertLess(parser.ids.index("coachAdvice"), parser.ids.index("analysis"))
        self.assertTrue(any("col-left" in classes for _, _, classes in parser.parents["signStart"]))
        self.assertLess(parser.ids.index("levelNext"), parser.ids.index("card_basic_open_palm"))
        self.assertTrue(any(identity == "courseGuide" for _, identity, _ in parser.parents["levelNext"]))
        self.assertTrue(any("col-right" in classes for _, _, classes in parser.parents["fingerCoach"]))
        self.assertTrue(any(identity == "analysis" for _, identity, _ in parser.parents["levelAiAdvice"]))
        self.assertTrue(any(identity == "analysis" for _, identity, _ in parser.parents["historySummary"]))
        self.assertIn('href="#workspace"', page)
        self.assertIn('href="#analysis"', page)
        self.assertIn("prefers-reduced-motion", page)
        self.assertNotIn("fonts.googleapis.com", page)
        self.assertNotIn("cdn.jsdelivr", page)
        self.assertIn("实时画面暂不可用，训练控制未自动触发", page)

    def test_coach_geometry_transport_remains_bounded_and_read_only(self):
        import json
        status = {
            "state": "IMITATING", "lesson_id": "basic_v_sign",
            "recognition_error_code": "LOW_CONFIDENCE", "session_error_code": "OK",
            "shape_debug": {"finger_extension": [.95, .95, .9, .8],
                            "tip_gap": .3, "thumb_index_gap": .6,
                            "raw_landmarks": [1, 2], "servo_angle": 90},
        }
        for gap in (.3, float("inf"), float("nan"), True, -1, 11):
            with self.subTest(gap=gap):
                status["shape_debug"]["tip_gap"] = gap
                conn = FakeConnection(b"GET /api/v1/sign/status HTTP/1.1\r\n\r\n")
                server = PreviewServer(socket_module=FakeSocketModule([conn]),
                                       sign_status_provider=lambda: status)
                self.assertTrue(server.start())
                server.poll()
                safe = json.loads(bytes(conn.sent).split(b"\r\n\r\n", 1)[1])
                self.assertEqual(safe["recognition_error_code"], "LOW_CONFIDENCE")
                self.assertEqual(safe["session_error_code"], "OK")
                self.assertEqual("tip_gap" in safe["shape_debug"], gap == .3)
                self.assertEqual(safe["shape_debug"]["thumb_index_gap"], .6)
                self.assertNotIn("raw_landmarks", safe["shape_debug"])
                self.assertNotIn("servo_angle", safe["shape_debug"])

    def test_actual_page_coaching_history_reload_comparison_and_manual_remedial(self):
        import shutil
        import subprocess
        from web_stream import _CONTROL_PAGE

        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js required for real page execution")
        script = _CONTROL_PAGE.decode("utf-8").split("<script>", 1)[1].split("</script>", 1)[0]
        driver = r"""
const assert=require('assert'),vm=require('vm');
const script=SCRIPT_VALUE;
const saved={};
function browser(storage=saved){
const elements={},posts=[],requests=[],timers=[];
function el(id){if(!elements[id])elements[id]={id,textContent:'',className:'',style:{},disabled:false,hidden:false,
children:[],getAttribute(k){return this[k]||null;},setAttribute(k,v){this[k]=v;},appendChild(v){this.children.push(v);}};return elements[id];}
const level=el('beginner');level['data-level']='beginner';
let time=1000,sign={state:'IDLE'};
const ctx={console,AbortController,Date,Math,Number,JSON,Promise,
document:{getElementById:el,createElement:()=>el('chip'+Math.random()),querySelectorAll:q=>q==='[data-level]'?[level]:[]},
performance:{now:()=>time},setTimeout:()=>1,clearTimeout:()=>{},setInterval:(fn,ms)=>timers.push({fn,ms}),
localStorage:{getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]},
fetch:(url,opts)=>{
if(url.includes('/ai/course-advice')){requests.push(JSON.parse(opts.body));return Promise.resolve({ok:true,json:()=>Promise.resolve({advice:'先复核 V 手势。'})});}
if(opts&&opts.method==='POST'){posts.push({url,body:JSON.parse(opts.body)});return Promise.resolve({json:()=>Promise.resolve({state:'queued'})});}
return Promise.resolve({json:()=>Promise.resolve(url.includes('/sign/status')?sign:{state:'idle',can_submit:false})});
}};
vm.runInNewContext(script,ctx);
return {el,level,posts,requests,storage,async poll(x){sign=x;timers.find(t=>t.ms===500).fn();await flush();},
watch(delta){time+=delta;timers.find(t=>t.ms===200).fn();}};
}
async function flush(){for(let i=0;i<4;i++)await new Promise(r=>setImmediate(r));}
const key='opensignhand_course_history_v1';
async function run(){
let b=browser();await flush();
assert(b.el('historyStatus').textContent.includes('尚未开启')||!b.el('historyStatus').textContent);
b.level.onclick();await flush();
const geometry={finger_extension:[.95,.93,.94,.88],tip_gap:.3};
await b.poll({state:'IMITATING',lesson_id:'basic_v_sign',shape_debug:geometry,recognition_error_code:'LOW_CONFIDENCE'});
assert(b.el('coachAdvice').textContent.includes('无名指'));
assert(b.el('coachAdvice').textContent.includes('小指'));
assert(b.el('coachAdvice').textContent.includes('收拢'));
assert(!b.el('coachAdvice').textContent.includes('食指的图像估计'));
await b.poll({state:'IMITATING',lesson_id:'basic_v_sign',shape_debug:{finger_extension:[.9,.9,.3,.3],tip_gap:.1}});
assert(b.el('coachAdvice').textContent.includes('分开两指'));
await b.poll({state:'IMITATING',lesson_id:'basic_l_shape',shape_debug:{finger_extension:[.9,.3,.3,.3],thumb_extension:.2}});
assert(b.el('coachAdvice').textContent.includes('拇指'));
await b.poll({state:'IMITATING',lesson_id:'basic_ok_pinch',shape_debug:{finger_extension:[.3,.9,.9,.9],thumb_index_gap:.8}});
assert(b.el('coachAdvice').textContent.includes('捏合'));
await b.poll({state:'IMITATING',lesson_id:'word_like',shape_debug:{finger_extension:[.3,.9,.9,.9],thumb_index_gap:.2}});
assert(b.el('coachAdvice').textContent.includes('仅看结束关键帧'));
assert(b.el('coachAdvice').textContent.includes('不等于课程已完成'));
for(const err of ['NO_HAND','INVALID_LANDMARKS','VISION_STALE','LINK_OFFLINE']){
await b.poll({state:'IMITATING',lesson_id:'basic_v_sign',shape_debug:geometry,recognition_error_code:err});
assert(!b.el('coachAdvice').textContent.includes('无名指'));}
await b.poll({state:'IMITATING',lesson_id:'basic_v_sign'});
assert(b.el('coachAdvice').textContent.includes('数据不足'));
await b.poll({state:'IMITATING',lesson_id:'basic_v_sign',shape_debug:geometry});b.watch(1500);
assert(b.el('coachAdvice').textContent.includes('已过期'));
await b.poll({state:'IMITATING',lesson_id:'basic_open_palm',stable_ms:120,recognition_error_code:'OK',session_error_code:'WRONG_GESTURE'});
assert.strictEqual(b.el('errorCode').textContent,'当前手型与目标不符');
await b.poll({state:'TIMEOUT',lesson_id:'basic_open_palm',confidence:.8,error_code:'TIMEOUT'});
assert.strictEqual(Object.keys(saved).length,0,'must not persist before opt-in');
b.el('historyToggle').onclick();assert(saved[key]);
assert.strictEqual(JSON.parse(saved[key]).sessions.length,1);
assert.strictEqual(JSON.parse(saved[key]).sessions[0].rows[0].samples.wrong_gesture,1);
assert(!saved[key].includes('shape_debug'));assert(!saved[key].includes('advice'));
await b.poll({state:'TIMEOUT',lesson_id:'basic_open_palm',confidence:.8,error_code:'TIMEOUT'});
assert.strictEqual(JSON.parse(saved[key]).sessions.length,1,'repeated terminal poll not duplicate');
b=browser();await flush();assert(b.el('historySummary').textContent.includes('首次记录'));
assert.strictEqual(b.el('levelRemedial').disabled,false);
b.el('levelRemedial').onclick();await flush();
assert.strictEqual(b.posts.length,1);assert(b.posts[0].url.includes('/sign/select'));
assert.strictEqual(b.posts[0].body.lesson_id,'basic_open_palm');
await b.poll({state:'IMITATING',lesson_id:'basic_open_palm',stable_ms:450});
assert.strictEqual(b.el('levelRemedial').disabled,true);
b.el('levelRemedial').onclick();await flush();assert.strictEqual(b.posts.length,1,'active course cannot replace plan');
await b.poll({state:'COMPLETE',lesson_id:'basic_open_palm',confidence:.95,error_code:'OK'});
assert(b.el('historySummary').textContent.includes('训练超时 → 本次 完成'));
assert(b.el('historySummary').textContent.includes('120 → 450'));
assert.strictEqual(JSON.parse(saved[key]).sessions.length,2);
b.el('levelAiAdvice').onclick();await flush();
assert.deepStrictEqual(b.requests[0].plan,['basic_open_palm']);
assert(!b.posts.some(p=>p.url.includes('/sign/start')),'no automatic actions');
b.level.onclick();await flush();
await b.poll({state:'IMITATING',lesson_id:'basic_open_palm'});
await b.poll({state:'FAULT',lesson_id:'basic_open_palm',error_code:'LINK_OFFLINE'});
assert.strictEqual(b.el('levelRemedial').disabled,true);
assert(b.el('historySummary').textContent.includes('不比较动作表现'));
b.el('historyClear').onclick();assert(!saved[key]);
assert(b.el('historySummary').textContent.includes('暂无记录'));
const bad={[key]:JSON.stringify({version:1,enabled:true,sessions:[{id:'bad',rows:[{lesson_id:'servo'}]}]})};
const corrupt=browser(bad);await flush();assert(corrupt.el('historyStatus').textContent.includes('格式无效'));
assert.strictEqual(corrupt.el('levelRemedial').disabled,true);
// Storage remains optional: quota/read failures must not affect manual training.
const denied=browser(new Proxy({}, {get(){throw new Error('privacy blocked');}}));await flush();
denied.level.onclick();await flush();
assert.strictEqual(denied.posts.length,1);
assert(denied.el('historyStatus').textContent.includes('不可读'));
const env=browser();await flush();env.level.onclick();await flush();
await env.poll({state:'IMITATING',lesson_id:'basic_open_palm',recognition_error_code:'NO_HAND'});
await env.poll({state:'TIMEOUT',lesson_id:'basic_open_palm',confidence:0,error_code:'TIMEOUT'});
assert.strictEqual(env.el('levelRemedial').disabled,true,'missing hand is not evidence of a weak gesture');
// History caps sessions at 20, validates before accepting persisted content.
for(let i=0;i<22;i++){
env.level.onclick();await flush();
await env.poll({state:'IMITATING',lesson_id:'basic_open_palm'});
await env.poll({state:'COMPLETE',lesson_id:'basic_open_palm',confidence:.95,error_code:'OK'});
}
env.el('historyToggle').onclick();assert.strictEqual(JSON.parse(saved[key]).sessions.length,20);
console.log('COACH_HISTORY_VERIFIED_OK');
}
run().catch(e=>{console.error(e);process.exit(1);});
"""
        import json
        driver = driver.replace("SCRIPT_VALUE", json.dumps(script))
        result = subprocess.run([node, "-"], input=driver, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COACH_HISTORY_VERIFIED_OK", result.stdout)

    def test_status_missing_availability_fails_closed(self):
        status = FakeConnection(b"GET /api/v1/train/status HTTP/1.1\r\n\r\n")
        server = PreviewServer(
            socket_module=FakeSocketModule([status]),
            train_status_provider=lambda: {
                "request_id": 1, "state": "idle", "reason": "ready_for_request",
            },
        )
        self.assertTrue(server.start())
        server.poll()
        response = bytes(status.sent)
        self.assertIn(b"200 OK", response)
        self.assertIn(b'"can_submit":false', response)
        self.assertIn(b'"availability_reason":"availability_unknown"', response)

    def test_default_capacity_serves_stream_and_two_short_clients_then_bounds_fourth(self):
        stream = FakeConnection(b"GET /stream HTTP/1.1\r\n\r\n")
        telemetry = FakeConnection(b"GET /telemetry HTTP/1.1\r\n\r\n")
        status = FakeConnection(b"GET /api/v1/train/status HTTP/1.1\r\n\r\n")
        fourth = FakeConnection(b"GET /control HTTP/1.1\r\n\r\n")
        server = PreviewServer(
            socket_module=FakeSocketModule([stream, telemetry, status, fourth]),
            telemetry_provider=lambda: b'{"schema_version":1}',
            train_status_provider=lambda: {
                "request_id": 0, "state": "idle", "reason": "no_request",
                "can_submit": False, "availability_reason": "bottle_not_stable",
            },
        )
        self.assertEqual(server.max_clients, 3)
        self.assertTrue(server.start())
        server.publish_jpeg(b"frame", 1)
        server.poll(max_accepts=4, max_client_writes=0)
        self.assertEqual(server.accepted, 3)
        self.assertEqual(server.dropped_clients, 1)
        self.assertTrue(fourth.closed)
        server.poll(max_client_writes=4)
        self.assertIn(b'{"schema_version":1}', bytes(telemetry.sent))
        self.assertIn(b'"can_submit":false', bytes(status.sent))
        self.assertIn(b"multipart/x-mixed-replace", bytes(stream.sent))

    def test_preview_root_embeds_the_same_origin_control_page(self):
        root = FakeConnection(b"GET / HTTP/1.1\r\n\r\n")
        server = PreviewServer(socket_module=FakeSocketModule([root]))
        self.assertTrue(server.start())
        server.poll()
        root_response = bytes(root.sent)
        self.assertIn(b"iframe src='/control'", root_response)
        self.assertNotIn(b"<img src='/stream'", root_response)
        self.assertNotIn(b'<img src="/stream"', root_response)

    def test_official_maix_adapter_writes_each_sequence_once_and_only_once(self):
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)
        self.assertFalse(adapter.started)
        self.assertTrue(adapter.start())
        first = FakeJpegImage()
        updated = FakeJpegImage()
        self.assertTrue(adapter.offer_frame(FakeFrame(first), 1))
        self.assertTrue(adapter.flush_latest())
        self.assertEqual(adapter.stream.writes, [first])
        self.assertFalse(adapter.flush_latest())
        self.assertEqual(adapter.stream.writes, [first])
        self.assertTrue(adapter.offer_frame(FakeFrame(updated), 2))
        self.assertTrue(adapter.flush_latest())
        self.assertEqual(adapter.stream.writes, [first, updated])
        self.assertFalse(adapter.flush_latest())
        self.assertEqual(adapter.stream.writes, [first, updated])
        self.assertEqual(adapter.images.dropped, 1)

    def test_official_image_store_rejects_bytes_to_avoid_wrong_api_type(self):
        images = LatestImageStore()
        self.assertFalse(images.publish(b"not-a-maix-image", 1))
        self.assertEqual(images.rejected, 1)

    def test_official_start_nonzero_err_fails_without_marking_started(self):
        FakeMaixHttp.start_result = 7
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)

        self.assertFalse(adapter.start())
        self.assertFalse(adapter.started)
        self.assertIsNone(adapter.stream)
        self.assertEqual(adapter.last_fault, "jpeg_streamer_start_failed:err=7")

    def test_official_err_none_enum_is_accepted_as_success(self):
        FakeMaixHttp.start_result = FakeErr.ERR_NONE
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)

        self.assertTrue(adapter.start())
        self.assertTrue(adapter.started)

    def test_official_write_nonzero_err_does_not_advance_sequence_or_count(self):
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)
        self.assertTrue(adapter.start())
        image = FakeJpegImage()
        self.assertTrue(adapter.offer_frame(FakeFrame(image), 1))
        FakeMaixHttp.write_result = 9

        self.assertFalse(adapter.flush_latest())
        self.assertEqual(adapter.written_sequence, 0)
        self.assertEqual(adapter.writes, 0)
        self.assertEqual(adapter.stream.writes, [image])
        self.assertFalse(adapter.flush_latest())
        self.assertEqual(adapter.stream.writes, [image])
        self.assertEqual(adapter.last_fault, "jpeg_streamer_write_failed:err=9")

    def test_official_close_stops_stream_and_resets_lifecycle_state(self):
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)
        self.assertTrue(adapter.start())
        stream = adapter.stream
        adapter.written_sequence = 12

        self.assertTrue(adapter.close())
        self.assertTrue(stream.stop_called)
        self.assertFalse(adapter.started)
        self.assertIsNone(adapter.stream)
        self.assertEqual(adapter.attempted_sequence, 0)
        self.assertEqual(adapter.written_sequence, 0)
        self.assertTrue(adapter.stop())

    def test_official_close_contains_stop_exception_and_still_resets_state(self):
        adapter = MaixJpegStreamerAdapter(maix_http=FakeMaixHttp)
        self.assertTrue(adapter.start())
        FakeMaixHttp.stop_exception = RuntimeError("stop failure")

        self.assertFalse(adapter.close())
        self.assertFalse(adapter.started)
        self.assertIsNone(adapter.stream)
        self.assertEqual(adapter.last_fault, "jpeg_streamer_stop_failed:RuntimeError")

    def test_missing_socket_capability_degrades_without_starting(self):
        self.assertFalse(detect_socket_capabilities(object())["socket_factory"])
        server = PreviewServer(socket_module=object())
        self.assertFalse(server.start())
        self.assertEqual(server.last_fault, "socket_capability_unavailable")


if __name__ == "__main__":
    unittest.main()
