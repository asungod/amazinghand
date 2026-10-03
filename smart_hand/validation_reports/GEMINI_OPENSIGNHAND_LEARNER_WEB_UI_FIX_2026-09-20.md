# Gemini 前端返工任务：OpenSignHand 学习者电脑网页主界面

## 项目背景与实际问题

OpenSignHand 是有限基础手型训练 MVP。MaixCAM2 摄像头必须正对学习者，因此设备自带屏幕位于学习者看不到的背面，只能作为调试屏。当前 `/control` 页面已经能选课、人工开始、取消和显示文本状态，但把“屏幕示范”理解为 MaixCAM2 本机屏幕不符合实际使用。

最终实际链路必须是：

```text
MaixCAM2 摄像头正对学习者
→ 学习者面前的电脑浏览器显示参考动作、实时画面和训练反馈
→ MaixCAM2 背面屏幕仅保留调试信息
```

## 修改范围

只允许修改：

- `smart_hand/maixcam2/web_stream.py` 中 `_CONTROL_PAGE` 的内嵌 HTML/CSS/JS；
- `smart_hand/tests/test_web_stream.py` 中对应的控制页静态和接口测试。

不要修改状态机、分类器、UART、Titan、舵机、CSV、遥测结构或其他 Python 逻辑。不要引入外部依赖、CDN、字体、远程图片或网络请求。

## 已有接口（不得改变）

- `GET /stream`：同源 MJPEG 标注流；
- `GET /api/v1/sign/status`；
- `POST /api/v1/sign/select`，JSON 只能为 `{"lesson_id":"..."}`；
- `POST /api/v1/sign/start`，正文只能为空或 `{}`；
- `POST /api/v1/sign/cancel`，正文只能为空或 `{}`；
- 课程 ID：`basic_open_palm`、`basic_fist`、`basic_v_sign`；
- `/api/v1/train` 兼容康复入口必须保留。

## 修改目标

把电脑端 `/control` 改成学习者真正可以使用的主界面，同时保持轻量和安全：

1. 页面顶部明确写明“电脑网页训练主界面”，不再暗示学习者观看 MaixCAM2 背面屏幕。
2. 主区域采用双栏布局，窄屏自动上下排列：
   - 左侧显示当前课程参考卡；
   - 右侧显示 `<img src="/stream">` 的同源实时标注画面。
3. 三张参考卡只描述基础手型，不写成正式手语词义：
   - 张开手掌：五指自然张开，掌心朝向摄像头；
   - 握拳：五指收拢，拇指自然覆盖或贴近弯曲手指；
   - V 形手势：食指和中指伸直分开，其余手指弯曲。
   可以使用系统 emoji `✋ / ✊ / ✌` 作为辅助图标，但文字说明必须始终存在，不能依赖不同系统的 emoji 外观作为唯一标准。
4. 根据后端状态突出当前步骤：
   - 未选择：提示先选课程；
   - `LESSON_SELECTED` / `DEMO_READY`：提示人工确认；
   - `DEMONSTRATING`：显示“正在展示参考动作（约 3 秒）”；
   - `IMITATING`：显示“现在请对着摄像头模仿”；
   - `COMPLETE`：显示完成；
   - `TIMEOUT` / `CANCELLED` / `FAULT`：显示明确中文结果。
   不要在前端自行推进状态或伪造倒计时，以服务端状态为准。
5. 显示识别标签、置信度、稳定保持毫秒数、有效/无效和错误原因；动态值只用 `textContent` 写入。
6. 课程、开始、取消按钮尺寸应适合比赛现场点击；检测到手势不得自动开始。
7. 视频加载失败时显示“实时画面暂不可用，训练控制未自动触发”，不得伪造在线状态；允许用户刷新页面恢复，不增加自动 POST。
8. 旧水瓶康复训练折叠在页面底部的兼容区域，接口和语义不变。
9. 页面保持零外部依赖，不发送舵机角度，不增加任何任意控制参数，不绕过状态机。
10. 考虑 MaixCAM2 资源约束：不要增加 Canvas 重绘、复杂动画、图表库或高频新轮询；保留现有 500 ms 单飞状态轮询。

## 不能破坏的功能

- 人工确认才能开始；
- 取消按钮只在 `can_cancel===true` 时可用；
- 开始按钮只在 `can_start===true` 时可用；
- POST 期间按钮禁用；
- 所有设备返回文本禁止用 `innerHTML` 插入；
- 原有 `/stream`、`/telemetry`、sign API、康复 API 和 CORS/同源策略不变。

## 测试要求

至少增加或更新测试，验证：

- 页面存在 `/stream` 图像和视频失败占位文案；
- 页面明确电脑浏览器是学习者主界面，MaixCAM2 屏幕仅调试；
- 三个课程 ID 和三条动作文字说明存在；
- 状态中文映射覆盖 `DEMONSTRATING`、`IMITATING`、`COMPLETE`、`TIMEOUT`、`CANCELLED`、`FAULT`；
- 动态设备文本仍通过 `textContent`；
- 页面不存在向舵机角度、servo、angle 等参数的提交；
- 旧 `/api/v1/train` 路径仍存在；
- 既有 sign API、请求体限制、同源 POST 和队列语义测试全部通过。

验收命令：

```powershell
python -m py_compile smart_hand\maixcam2\web_stream.py
python -m unittest smart_hand.tests.test_web_stream smart_hand.tests.test_sign_integration -v
```

完成后只汇报：修改摘要、实际修改文件、测试命令与结果、仍存风险。不要扩大范围，也不要修改候选提交包；候选包由主控审核后统一同步。
