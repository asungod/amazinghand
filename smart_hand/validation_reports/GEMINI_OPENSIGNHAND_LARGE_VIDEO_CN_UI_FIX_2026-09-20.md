# Gemini 最小前端任务：放大实时画面并减少用户界面英文

## 实际问题

真机浏览器截图已经证明 `/control` 页面、课程卡片和实时流能够工作，但存在两个体验问题：

1. `/stream` 原始画面约为 320×224，当前 CSS 只设置 `max-width:100%`，浏览器保留图像自然尺寸，导致右侧区域大面积黑边，学习者看到的实际画面太小；
2. 页面中的设备状态、识别标签、错误原因和请求状态仍可能直接显示英文内部代码。

OpenSignHand 品牌名、MaixCAM2、Titan 等专有名称可以保留英文，其余面向学习者的内容尽量中文化。

## 只允许修改

- `smart_hand/maixcam2/web_stream.py` 中 `_CONTROL_PAGE` 的 HTML/CSS/JS；
- `smart_hand/tests/test_web_stream.py` 中对应静态测试。

不要修改服务器路由、状态机、UART、Titan、分类器、CSV 或 API。不要修改 `outputs` 候选包，主控审核后统一同步。

## 修改要求

### 1. 实时画面按容器等比例放大

- 将实时流图片由自然尺寸显示改为 `width:100%; height:auto;`；
- 保持宽高比，不裁剪、不拉伸变形，不使用 `object-fit:fill`；
- 桌面宽屏下视频区域应成为页面主要视觉区域，当前约 320×224 的画面应放大填满右栏宽度；
- 窄屏仍上下排列并占满可用宽度；
- 视频容器不得设固定像素高度，避免不同画面比例被裁切；
- 保留断流占位和单一 `src="/stream"`。

### 2. 动态用户状态中文化

页面端只改变显示，不改变设备返回值。新增纯展示映射，并确保未知代码以安全的原始文本回退。

识别标签至少映射：

- `OPEN_PALM` → `张开手掌`
- `FIST` → `握拳`
- `V_SIGN` → `V 形手势`
- `UNKNOWN` / `NONE` → `未识别`

错误原因至少映射：

- `OK` / `NONE` / 空值 → `无`
- `HAND_NOT_FOUND` / `hand_not_found` → `未检测到手`
- `UNKNOWN_GESTURE` → `未识别到有效手型`
- `LOW_CONFIDENCE` → `识别置信度不足`
- `WRONG_GESTURE` / `TARGET_MISMATCH` → `当前手型与目标不符`
- `LINK_OFFLINE` → `Titan 连接断开`
- `VISION_STALE` → `视觉数据已过期`
- `TIMEOUT` → `训练超时`
- `CANCELLED` → `训练已取消`
- `INVALID_STATE` → `当前阶段不允许此操作`
- `EXTERNAL_FAULT` / `FAULT` → `设备状态异常`

请求状态至少映射：

- `queued_for_main` → `请求已接收，等待设备处理`
- `applied` / `accepted` → `操作已生效`
- `rejected` → `请求被拒绝`
- `expired` → `请求已过期，请重新操作`
- `request_busy` → `设备正忙，请稍后重试`
- `idle` → `就绪`

`lesson_id`、错误码和请求码不得直接拼入 `innerHTML`；继续只使用 `textContent`。

### 3. 静态文案修正

将“当前机械动作仅作参考”改为更符合当前真实状态的表述，例如：

> 当前课程由电脑网页提供参考动作，机械手本轮未参与示范。

不要暗示机械手已经产生动作。不要把三种基础手型写成正式中国手语词汇。

### 4. 不能破坏

- 保留串行状态轮询，禁止重新引入 `Promise.all`；
- 页面保持且仅保持一个 `/stream`；
- POST 后开始/取消按钮继续 fail-closed；
- 人工确认才能开始；
- 旧水瓶康复入口继续兼容；
- 零外部资源、零 CDN、零任意执行参数。

## 测试要求

更新测试，至少验证：

- 页面样式包含实时图像 `width:100%` 和 `height:auto`；
- 不包含会把视频拉伸变形的 `object-fit:fill`；
- 四种识别标签、主要错误原因和请求状态的中文映射存在；
- 动态文本仍只通过 `textContent`；
- `Promise.all` 仍不存在；
- `/control` 中 `src="/stream"` 仍恰好一个；
- 根页面仍不额外加载 `/stream`；
- 完整既有测试继续通过。

## 验收命令

```powershell
python -m py_compile smart_hand\maixcam2\web_stream.py
python -m unittest smart_hand.tests.test_web_stream smart_hand.tests.test_sign_integration -v
python -m unittest smart_hand.tests.test_sign_core smart_hand.tests.test_sign_dataset_tools smart_hand.tests.test_sign_landmark_capture smart_hand.tests.test_sign_integration smart_hand.tests.test_web_stream smart_hand.tests.test_live_sidecar smart_hand.tests.test_maix_main -q
```

完成后只汇报修改摘要、实际修改文件、三条测试命令与结果、仍存风险。不要扩大范围。
