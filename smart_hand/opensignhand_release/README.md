# OpenSignHand：边缘 AI 辅助手语手型训练原型

OpenSignHand 是 AmazingHand 项目的开源整理版。它把摄像头端的手部视觉识别、有限手型训练流程、Titan Mini 的实时通信与安全状态校验连接起来，面向需要反复练习基础手型的用户、教师或家属提供一个可复现的边缘 AI 原型。

这里的“手语训练”只指当前已经实现或计划先验证的少量基础手型训练，不是完整手语词典、连续手语翻译器，也不是医疗器械或临床康复系统。初版课程原型只有：

- `OPEN_PALM`：张开手掌；
- `FIST`：握拳；
- `V_SIGN`：V 形手势。

## 真实边界

- 灵巧手本体来自 Pollen Robotics AmazingHand 的开源设计/成品或复刻，不把上游机械结构宣称为本项目原创；
- MaixCAM2 与 Titan Mini 是购买的开发板；
- 本项目的原创增量主要是 MaixCAM2 视觉接入、训练状态机、MaixCAM2↔Titan UART 协议、安全门控、质量评价与本地训练日志；
- Titan 当前没有部署手语网络或音频关键词网络。TitanTrust 目前是视觉/UART 时序的辅助可信度评估，不能写成 Titan NPU 已完成手语 AI 部署；
- 训练结果仅反映本次原型会话，不构成诊断、疗效判断或临床建议。

## 系统链路

```text
手部画面
  → MaixCAM2 本地视觉 AI / 手部姿态判断
  → 结构化 UART2 消息（序号、CRC、ACK）
  → Titan Mini RT-Thread 状态机与安全校验
  → SCS0009 总线
  → AmazingHand 既有安全动作链路 / 辅助示范（完整真机姿态待验证）
  → 位置/电压/温度/训练质量日志
```

所有会影响机械动作的操作都必须经过当前训练状态机和安全门。离线测试不会访问串口，也不会驱动舵机；真机动作必须由操作者人工确认。

## 目录说明

本目录是开源提交资料和复现说明的独立目录，不复制第三方压缩包、未知权重或人物视频。源代码仍位于上级 `smart_hand/` 工程中；正式发布前只应把已完成许可证核验、去除个人信息并通过测试的原创文件复制到提交包。

- `LICENSE`：本项目原创软件/文档的 Apache-2.0 许可全文；
- `NOTICE`：只覆盖本项目原创内容的声明；
- `THIRD_PARTY_NOTICES.md`：上游和第三方材料边界；
- `UPSTREAM.md`：上游来源、许可证和归属核对表；
- `REPRODUCE.md`：离线验证与真机复现边界；
- `SUPPORTED_LESSONS.md`：当前三种手型课程及扩展规则；
- `SAFETY_AND_LIMITATIONS.md`：安全、隐私和能力限制；
- `DATA_AND_MODEL_SOURCES.md`：数据、模型、许可证和校验清单；
- `docs/architecture.md`：系统架构与接口边界；
- `docs/demo_script.md`：3–5 分钟真实演示脚本；
- `docs/ppt_outline.md`：比赛展示/PPT 大纲；
- `tests/README.md`：测试与证据要求。

## 当前主要源文件

相对于本目录，已审阅的工程源文件包括：

- `../maixcam2/main.py`、`../maixcam2/protocol.py`、`../maixcam2/hand_rehab_tracker.py`；
- `../maixcam2/rehab_train.py`、`../maixcam2/rehab_imitation.py`、`../maixcam2/rehab_quality.py`、`../maixcam2/rehab_session_log.py`；
- `../titan_rtthread/smart_hand_uart.c`、`../titan_rtthread/smart_hand_protocol.c`、`../titan_rtthread/titan_trust_runtime.c`；
- `../titan_ai/README.md` 及其训练/生成记录。

若这些源文件尚未经过一次完整的许可证、敏感信息、依赖和真机证据审计，不应直接把整个上级目录当作公开发布包。

## 快速判断

看到“AI”时，应能指出它实际运行在哪里、输入输出是什么、有什么真实证据；看到“开源”时，应能指出上游许可证、原创增量和可复现步骤。不能用计划中的模型、尚未烧录的固件或未验证的准确率代替成果。
