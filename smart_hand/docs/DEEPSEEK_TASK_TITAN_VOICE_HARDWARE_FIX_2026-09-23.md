# Titan 语音真机验收后修复任务（交给 DeepSeek）

你只负责 Titan 被动语音采集与推理链路的以下两个真机问题。先读现有 `voice_audio.c/.h`、`voice_audio_titan.c/.h`、`voice_app.c/.h`、`voice_app_titan.c/.h`、相应测试和 2026-09-23 集成报告；不要改舵机、UART 协议、训练启动门控或 MaixCAM2。不要刷写；Codex 负责审查和真机复验。

## 已取得的真机证据

- 已刷候选固件：`D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex`，SHA-256 `60AD1D892CB861785EC3AF9216B03C2E438859235DB8FD41ED43A29A2367392A`。烧写后 158,304 个 HEX 明确字节读回一致。工程根目录同名 hex 是旧版，禁止使用。
- 刷写前的整片 1 MiB 程序 Flash 备份：`C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\outputs\Titan_Voice_Bringup_2026-09-23\pre_voice_flash.bin`，SHA-256 `65EF0A467D0FDF5D44597BAA4480A0DF7A43A948ADBADBA9394702D8C03565CF`。机械手 6 V 驱动板一直断电，Titan 单独上电。
- **现板已回退**：真机取证后已将上述备份写回 0x02000000 起始的完整 1 MiB 程序 Flash，并再次逐字节读回，结果 `RESTORE VERIFY OK: 1048576 bytes`。因此板上当前运行的不是待修复的语音候选固件；不要把后续现场状态误认为该候选固件的状态。
- SWD 读到 `g_ready=1`，语音状态为 `CAPTURING`；PDM `error_count=0`、`running=1`。一次快照中 `samples_captured=5,370,400`、`accepted_samples=32,000`、`overrun_count=5,338,400`。后续 `accepted_samples` 仍为 32,000，而 `overrun_count` 继续增长。
- 连续 5 秒计数增长 84,000（约 16,800 样本/秒）；连续 10 秒增长 167,200（约 16,720 样本/秒）。800 样本的回调粒度带来约 ±160/±80 样本/秒的端点量化误差，但两次均明显高于假定的 16,000 样本/秒。不要把配置里的 16 kHz 当实测值。
- SWD 读取的采集缓冲有变化的 PCM 字样本；但这**不等于**语音识别准确率已验证。pyOCD 的 AP#2/SVD 告警在读取、烧写和校验成功时也出现过，不要仅凭这些告警推断失败。

## 问题一：环形缓冲永久装满（优先修）

`voice_app_titan.c::voice_io_peek_window()` 只调用非消费式 `voice_ring_peek_latest()`；当前生产路径没有推进由消费者拥有的 `read_index`。`VOICE_RING_CAPACITY` 为 32,768，800 样本回调最多接受 32,000 个，之后每块都被拒绝。状态机的 overrun 隔离需要新的 `accepted_samples`，但这个计数再也不增长，因此长期卡在 `CAPTURING`。

请实现最小、可证明的消费者侧释放/取窗机制，保证连续运行时缓冲有空间，且送入特征前端的每个窗口在时间上连续。注意 ISR 只能写生产者游标；不能让 ISR 推进 `read_index`、不能仅增大缓冲、不能靠定期清空 overrun 计数掩盖问题。对复制窗口期间发生的生产者写入/溢出仍须 fail-closed。若调整 `peek_window` 的“非消费”契约，必须同步修改接口文档和测试；若新增取窗 API，给出并发所有权与窗口边界的证明。

至少测试：首次填窗、持续多个窗口、跨环回绕、复制期间的生产者推进、真实 overrun 后恢复、推理耗时超过一窗时的行为。加入一个能在旧实现上稳定失败的回归/变异测试；不能只测纯状态机 fake I/O，必须覆盖真实胶水层与环形缓冲组合。

## 问题二：采样率与模型假设不一致

先基于 FSP/时钟配置与真机计数定位实际时钟来源及分频，不要直接改模型常量掩盖偏差。目标是有证据地使 PCM 到特征前端的有效采样率为 16 kHz；可比较正确配置 PDM 时钟与有界、可测的重采样方案，选择改动更小且不会破坏 UART 实时性的方案。若目前不能证明精确值，就保持“未验证”，不得宣称 16 kHz 或真实识别率。

## 交付边界

1. 提交最小 diff，解释修复前后环形缓冲的生产/消费不变式、时间窗口连续性和 overrun 恢复；明确 16 kHz 的证据或仍缺的真机证据。
2. 运行相关主机测试、故障注入和真实设备工具链构建；报告命令退出码、ELF/map 变化、`Debug/rtthread.hex` 的新 SHA-256，并检查仓库与 Studio `src/` 源码哈希一致。
3. 不刷写、不接通舵机 6 V、不把语音接到机械动作。不要将合成语料对拍写成真实识别准确率。
4. 给 Codex 一份短验收清单：上电后 10 分钟 `accepted_samples` 持续增加、正常环境 `overrun_count` 不持续增加、`result_generation` 能更新、`pdm_error_count=0`、实测有效采样率接近 16 kHz；再做 MaixCAM2 UART ACK 并行测试。任何一项失败都不进入舵机上电测试。

备注：Titan 当前 RT-Thread 控制台为 `null`，不要把 `rt_kprintf` 当作可观察证据。可使用只读状态内存或经审查的诊断接口；不得临时加入会控制机械手的通路。
