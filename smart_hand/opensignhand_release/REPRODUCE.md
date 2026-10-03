# 复现说明

## 0. 复现边界

本文件把“离线软件验证”和“真实机械手验证”分开。离线命令不会打开串口，不会访问舵机，也不会证明真机动作；真机步骤必须由熟悉供电、急停和机械干涉风险的操作者在现场完成。任何不确定的动作都先断开舵机电源，使用只读探针确认链路后再继续。

当前 release 目录只提供说明和合规资料，不包含未经核验的厂商 SDK、未知权重、成品机械手文件或个人设备配置。

## 1. 离线复现

在项目根目录（即包含 `smart_hand/` 的目录）执行。推荐使用与提交记录一致的 Python 环境：

```powershell
python smart_hand\host\check_maix_deploy.py --expected-mode yolo11
python smart_hand\host\run_offline_rehearsal.py --output smart_hand\outputs\offline_rehearsal_latest.json
python -m unittest smart_hand.tests.test_generate_rehab_session_report -v
```

预期边界：

- 部署预检只检查文件、导入和配置，不连接 MaixCAM2；
- 离线演练应报告 `result=PASS`、`hardware_accessed=false`；
- 演练中的链路丢失路径应进入 `safe_stop_required`/`FAULT`；
- 模板校准文件不能被当作生产校准，因此 `physical_motion.authorized` 应保持 `false`；
- 测试报告生成器测试只验证 CSV/报告逻辑，不验证摄像头或机械动作。

如果上述边界发生变化，必须先更新本说明和测试证据，再更新比赛材料。

## 2. 真机复现前的准备

1. 复核本目录 `THIRD_PARTY_NOTICES.md`、`UPSTREAM.md` 和 `SAFETY_AND_LIMITATIONS.md`；
2. 对照当前工程版本记录 MaixCAM2、Titan Mini、手本体、固件和模型哈希；
3. 舵机电源默认断开，先确认 MaixCAM2 和 Titan 的 UART2/GND/TX/RX 连接；
4. MaixCAM2 当前生产入口为 `/dev/ttyS2`，协议波特率为 `115200`；不要把历史 UART4 探针当作生产入口；
5. 使用只读探针和低风险状态确认通信在线、ACK、超时、CRC 错误和视觉过期行为；
6. 只有在操作者确认手指、连杆、舵盘、软限位和电源均无卡滞风险后，才允许接入舵机电源。

## 3. 真机训练步骤

真机运行入口和 UI 可能随版本变化，不能凭本文件猜测设备端按钮坐标。应使用随当前冻结版本的部署包和屏幕提示：

1. 启动 MaixCAM2 视觉程序，确认模型已加载、画面稳定、目标/手部状态可见；
2. 启动 Titan 固件，确认 UART2 链路在线、ACK 正常、无故障锁存；
3. 先在无舵机或只读状态观察视觉和遥测；
4. 人工确认训练授权后，使用固定的三种课程之一；
5. 训练中一旦出现连杆顶开、舵机堵转、持续异响、异常发热、掉压或非预期动作，立即断开舵机电源；
6. 训练结束后保存原始 CSV、设备日志、固件/模型哈希和异常记录，原始文件只追加不覆盖。

当前已经有的通信证据只能证明对应报告中写明的范围。例如 `smart_hand/validation_reports/maixcam2_yolo11_titan_uart2_long_run_2026-08-15.md` 明确是无舵机长跑，不得扩写成完整机械抓握证据。

## 4. 固件与模型发布边界

Titan 工程的源码、对象和 MAP 时间可能不一致。发布或宣称真机部署前，需重新构建并保存 ELF、MAP、HEX/BIN、构建日志和 SHA-256；`titan_linkage_check.py` 的 `stale_map` 结果不能算通过。

TitanTrust 当前文档标明其训练数据为合成故障注入，且没有现场精度和硬件推理验证。Titan NPU 没有部署本项目的手语或音频网络。除非后续产生真实模型文件、调用证据、时延、内存和板端日志，否则不要使用“Titan NPU 已部署手语 AI”表述。

## 5. 常见失败与恢复

| 现象 | 先做什么 | 不能做什么 |
|---|---|---|
| 离线命令访问硬件 | 停止并检查是否误接串口 | 不把离线 PASS 当成真机 PASS |
| ACK 超时/CRC 错误 | 保持舵机断电，保存日志，检查 GND/TX/RX/波特率 | 不连续重试机械动作 |
| 视觉目标过期 | 等待状态恢复或重新授权 | 不绕过 Titan 门控强行发动作 |
| 连杆顶开/异响/堵转 | 立即断舵机电源 | 不为了凑次数继续实验 |
| MAP 早于源码 | 重新清理、构建并保存新证据 | 不手工编辑 MAP 或宣称已烧录 |
