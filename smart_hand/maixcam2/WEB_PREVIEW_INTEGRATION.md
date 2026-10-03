# MaixCAM2 LAN 实时预览与遥测

`main.py` 内的 `LIVE_WEB_ENABLED` 默认为 `False`。默认路径不会导入 `live_sidecar`、创建 `PreviewServer`、打开 socket 或对相机帧执行 JPEG 编码，因此不改变既有视觉、UART、训练或安全闸门节拍。

## 启用与访问

1. 在部署到 MaixCAM2 的应用中，将 `LIVE_WEB_ENABLED = True`。这是唯一的启用开关；不要在浏览器、HTTP 请求或 UART 消息中加入控制开关。
2. 重启应用。`live_sidecar.LiveWebSidecar` 显式启动 `PreviewServer(host="0.0.0.0", port=8080)`；绑定/能力检测失败只打印故障并继续原主循环。
3. 在同一局域网可信设备上访问 `http://<MaixCAM2-IP>:8080/`，或由同一 base URL 分别读取：
   - `GET /stream`：最新一帧的 MJPEG 预览。
   - `GET /telemetry`：严格的 `amazinghand.maixcam2.telemetry` schema v1 JSON。
   - `GET /control`：设备同源的中文手动训练控件；可嵌入现有只读仪表盘的 iframe。

`/stream` 与 `/telemetry` 保持只读 CORS 接口。请在路由器/热点侧限制可信局域网客户端。`accepted` 只代表请求被 Titan 接收，绝不代表训练或动作已成功执行；网页 gate 字段也不声称覆盖全部写路径。

## 同源手动训练控制

`/control` 页面明确要求“检测水瓶后手动点击”，不会自动发起训练。它只轮询同源 `GET /api/v1/train/status`，避免与长连接 MJPEG 和父页只读 telemetry 竞争有限连接槽；该状态由主循环每轮以与实际发送前相同的安全判定给出 `can_submit` 与安全枚举 `availability_reason`，不由浏览器重复推断目标/Titan/gate。缺字段或 `can_submit` 不为严格 `true` 时按钮保持禁用；pending/submitted 同样禁用。默认紧凑布局面向约 160px iframe，不设置固定高度，窄屏可换行。它只可通过同源 `POST /api/v1/train` 锁存一个请求；请求必须为空 body、`Content-Length: 0`，且 `Origin` 必须严格等于 `http://<Host>`。`file://`、`Origin: null`、跨域页面、缺失 Origin 和包含 body 的请求都会拒绝，控制响应没有 `Access-Control-Allow-Origin: *`。`202 queued_for_main` 仅表示意图已交给主循环复核，不表示开始或成功；重复点击在 pending/submitted 时得到 `409`。训练控制器明确重新 ready 后，status 会转回 `idle/ready_for_request`（保留上一 request id，但不表示成功），允许用户发起下一次手动请求。默认 `PreviewServer` 仅有 3 个有界 client 槽：一个长 MJPEG、一个父页 telemetry、一个控制 status；第 4 个连接仍会立即拒绝。

主循环才会消费该单槽 intent，并在写 UART 前再次要求：TARGET 阶段、用户模仿 idle、稳定目标为 bottle（class 39）且达到当前 YOLO 阈值、Titan STATUS/link/VISION/action/pose/gate 全部通过、无当前 ACK timeout、以及 `TrainButtonController.enabled()`。任一失败只通过 `GET /api/v1/train/status` 报告安全枚举拒绝原因，不写 UART。完整 UART 写入后才调用既有 `note_sent()` 并标为 `submitted_to_titan`；后续 ACK/TRAINSTAT 仍是唯一的真实执行结果。HTTP handler 和 sidecar 不持有 serial、UART、控制器或舵机接口。

## 接入边界和实时行为

两个 `screen.show(frame)` 前都调用同一个 `offer(frame, now_ms)` hook，因而网页只会看到已经画完检测框、提示文字和本地按钮的帧。编码使用官方可用的 `frame.to_jpeg().to_bytes()`，但该复制可能耗时，所以 sidecar 最多每 200 ms 发布一次（默认最多 5 FPS）；编码、发布、socket 和状态快照异常仅记录本地 fault，不会外抛到视觉/UART 主循环。

每次主循环都执行一次 `poll(now_ms)`，它严格限制为至多一次 accept 和一次客户端写，并使用 `PreviewServer` 的非阻塞 socket/最新帧单槽。无客户端时立即返回；慢客户端不会建立帧队列。此正式网页后端刻意使用单端口 `PreviewServer`，以让 `/stream` 和 `/telemetry` 处于同一 base URL；不使用只提供 JPEG 的官方 `JpegStreamer` 作为网页服务端。

`TelemetryRuntimeAdapter`/`build_runtime_telemetry` 生成白名单 v1 数据。frame 的 sequence、available、stale、age、dropped 和 JPEG fault 来自单槽缓存；它表示网页发布帧的新鲜度。`health.stale.vision` 则只表示**新鲜 Titan STATUS 所报告的 VISION 候选新鲜度**：STATUS 过期/未知、`have_vision` 不为真或 `vision_stale` 不是布尔值时均 fail-stale 为 `true`。它不表示摄像头或 NPU 是否仍在运行，也不会被本地 `VisionScheduler` 的处理节拍覆盖。Titan RTT 仅来自 `AckMonitor.last_rtt_ms`。过期 STATUS 会清空 action、reason、gate。可可靠读取的 YOLO、手势、重复/目标、质量字段才会填入；未可靠获得的值为 `null`（或 schema 规定的 `UNKNOWN`/空闲状态），不会伪造 AI 数据或把历史错误计数当成当前故障。

应用按正常 `app.need_exit()` 退出时会 best-effort 关闭 listener。为避免把整个硬件主循环大范围缩进，未捕获的进程异常不另加 `finally`；操作系统进程退出会回收 socket。请先在实机确认 5 FPS JPEG 编码仍满足视觉/UART节拍，再在演示网络中长期启用。

不要使用 RTSP/RTMP/WebRTC 的 `bind_camera()`：它会与现有相机读取、叠加绘制和 `screen.show(frame)` 流程冲突。本阶段也不绑定第二个摄像头、不使用线程，且不增加外部依赖。
