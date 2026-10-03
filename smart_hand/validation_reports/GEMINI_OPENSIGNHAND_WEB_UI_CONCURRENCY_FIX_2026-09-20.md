# Gemini 最小返工：OpenSignHand 网页连接并发与按钮失效安全

## 主控复核结论

学习者电脑网页的布局、三张参考卡、状态中文映射、同源 `/stream` 和 27 项现有测试均已通过静态/主机测试，但当前版本暂不接受同步到 MaixCAM2，原因是现场连接并发和按钮恢复存在两个阻断项。

服务端 `PreviewServer` 默认 `max_clients=3`。当前页面会长期占用一个 `/stream` 连接，并通过 `Promise.all` 同时发起 sign 与 rehab 两个状态请求；用户恰好点击 POST 时可能成为第 4 个连接而被服务端丢弃。此外根页面已有外层 `/stream`，其 iframe `/control` 又会加载第二个 `/stream`，会进一步耗尽连接。

## 只允许修改

- `smart_hand/maixcam2/web_stream.py`
- `smart_hand/tests/test_web_stream.py`

禁止扩大范围；不要提高 `max_clients`，不要修改 UART、状态机、Titan、舵机、CSV 或 API 结构。

## 必须修复

### 1. 状态轮询改为串行

保留 500 ms 单飞轮询，但不能使用 `Promise.all` 同时打开两个短连接。

每轮应顺序执行：

1. `GET /api/v1/sign/status`，渲染 sign 状态；
2. 前一个请求完成后再 `GET /api/v1/train/status`，渲染兼容康复状态；
3. 无论任一步失败，最终都必须复位 `inflight=false`。

这样在直接访问 `/control` 时，最坏连接数为：一个 MJPEG 长连接 + 一个状态请求 + 一个用户 POST，共 3 个。

### 2. 根页面只能产生一个视频流

当前 `/` 页面同时包含外层 `<img src='/stream'>` 和 `<iframe src='/control'>`，而 `/control` 内已经自带 `<img src="/stream">`。

请把根页面改成只嵌入 `/control` 的全宽 iframe，或者直接提供进入 `/control` 的页面；根页面自身不得再包含独立的 `/stream` 图片。保留 `/control` 路径和现有 API。

### 3. POST 完成后的按钮必须继续 fail-closed

当前 `post()` 完成后执行 `setButtonsDisabled(false)`，会在下一次状态响应到达前短暂同时启用“开始”和“取消”。如果此时已有轮询在飞，`r()` 会直接返回，这个错误窗口会持续到下一轮。

要求：

- POST 开始时可禁用课程、开始、取消按钮；
- POST 完成后不得无条件启用开始/取消；
- 开始按钮只能由新获取的 `x.can_start===true` 解锁；
- 取消按钮只能由新获取的 `x.can_cancel===true` 解锁；
- 课程按钮可在 `posting=false` 且状态刷新后恢复；
- 设备状态未知或请求失败时，开始/取消保持禁用。

## 必须新增/修改的测试

1. `/control` 页面中不得出现 `Promise.all`；
2. 根页面保留 `iframe src='/control'`，但根页面响应本身不得包含 `<img src='/stream'`；
3. `/control` 页面仍包含且只包含一个 `src="/stream"`；
4. 静态检查不得出现 `setButtonsDisabled(false)` 这种无条件恢复开始/取消的逻辑；
5. 原 27 项测试继续通过；
6. 完整 OpenSignHand 回归继续通过。

## 验收命令

```powershell
python -m py_compile smart_hand\maixcam2\web_stream.py
python -m unittest smart_hand.tests.test_web_stream smart_hand.tests.test_sign_integration -v
python -m unittest smart_hand.tests.test_sign_core smart_hand.tests.test_sign_dataset_tools smart_hand.tests.test_sign_landmark_capture smart_hand.tests.test_sign_integration smart_hand.tests.test_web_stream smart_hand.tests.test_live_sidecar smart_hand.tests.test_maix_main -q
```

完成后只汇报修改摘要、实际修改文件、三条测试命令与完整结果、仍存风险。不要修改候选提交包；主控验收后统一同步。
