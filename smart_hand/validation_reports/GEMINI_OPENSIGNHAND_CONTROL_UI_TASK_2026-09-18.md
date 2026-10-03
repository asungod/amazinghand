# Gemini 前端执行任务：OpenSignHand 设备同源控制页

## 项目背景

OpenSignHand 是由现有 AmazingHand 康复训练系统扩展出的有限词表手语训练 MVP。MaixCAM2 负责手部关键点与三种基础手型原型识别，Titan 只承担确定性通信/状态校验，开源灵巧手当前不宣称能够表达正式手语。已有康复模式必须继续兼容。

## 只允许修改的文件

`smart_hand/maixcam2/web_stream.py`

不要修改 Python 后端状态机、UART、Titan、机械手、CSV、测试之外的任何文件。不要引入外部依赖、CDN、字体或网络资源。

## 当前接口（不得自行更改）

- `GET /api/v1/sign/status`
- `POST /api/v1/sign/select`，JSON 正文只能是 `{\"lesson_id\":\"...\"}`
- `POST /api/v1/sign/start`，正文必须为空或 `{}`
- `POST /api/v1/sign/cancel`，正文必须为空或 `{}`
- 三个课程 ID：`basic_open_palm`、`basic_fist`、`basic_v_sign`
- 状态可能包含：`state`、`lesson_id`、`lesson_name`、`gesture_id`、`confidence`、`stable_ms`、`valid`、`error_code`、`can_start`、`can_cancel`、`requires_confirmation`、`request_state`、`request_reason`、`demo_mode`、`mechanical_pose`
- 所有 POST 都必须保持设备同源，浏览器端不得发送舵机角度或任何任意控制参数。

## 修改目标

只重构文件顶部的 `_CONTROL_PAGE` 内嵌 HTML/CSS/JS，使它能根据接口状态同时支持：

1. 当手语接口可用时，显示“OpenSignHand 手语训练”区域：
   - 三个课程按钮，中文只能表述为“基础手型：张开手掌 / 握拳 / V 形手势”，不得写成“你好/谢谢/帮助”等正式手语词义；
   - 显示当前课程、训练阶段、识别手型、置信度、稳定保持毫秒数、错误原因；
   - 显示“选择课程”“人工确认开始”“取消训练”交互；
   - 开始按钮仅在 `can_start===true` 时可用，取消仅在 `can_cancel===true` 时可用；
   - 页面明确写明：屏幕示范为主，检测到手势不会自动开始，必须人工确认；当前机械手不代表正式手语标准动作。
2. 保留旧“水瓶康复训练控制”功能，但折叠为兼容区域，不改旧接口和语义。
3. 每 500 ms 单飞轮询状态，避免请求重叠；POST 期间禁用相关按钮；失败时中文提示，不伪造在线/成功。
4. 所有动态文本必须使用 `textContent`，不得把设备返回值拼入 `innerHTML`。
5. 页面适配当前 iframe 的窄高度，简洁、中文、无动画堆叠。
6. `_CONTROL_PAGE` 仍必须是 UTF-8 bytes；不得改变 `/control`、流、遥测、API 处理逻辑。

## 必须补充/更新的测试

只允许修改 `smart_hand/tests/test_web_stream.py` 中与控制页静态内容和 sign API 相关的测试，至少验证：

- 页面包含三个课程 ID 和人工确认文案；
- 动态状态渲染使用 `textContent`；
- 页面不出现 servo/angle 参数提交；
- 旧 `/api/v1/train` 路径仍在；
- 现有同源 POST、拒绝跨域和队列语义测试继续通过。

## 验收命令

```powershell
python -m py_compile smart_hand\maixcam2\web_stream.py
python -m unittest smart_hand.tests.test_web_stream smart_hand.tests.test_sign_integration -v
```

完成后只汇报修改摘要、实际修改文件、测试命令与结果、仍存风险。不要扩大范围。
