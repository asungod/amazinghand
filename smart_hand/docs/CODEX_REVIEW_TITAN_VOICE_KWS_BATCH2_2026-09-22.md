# Codex 对 Titan Voice KWS 第二批交付的审核意见

日期：2026-09-22

## 审核结论

第二批修正**有条件通过**。`voice_audio.c`、特征前端、分类器和数据划分测试可以接受；当前仍不得并入真机主工程、不得烧写，也不得宣称 Titan 已实现端侧语音识别。

进入真机前必须完成下列 P1 修正与适配层测试。

## P1：修正 PDM 启动时的 ISR 游标竞态

文件：`smart_hand/titan_rtthread/voice_audio_titan.c`

当前 `voice_audio_titan_start()` 在 `R_PDM_Start()` 成功返回后才设置：

```c
g_isr_block = 0U;
```

但同一文件注释已承认，数据中断可能在 `R_PDM_Start()` 返回前发生。于是首次中断可能读取上一次会话遗留的 `g_isr_block`；更坏的是，中断已经将游标加一后，线程又把它清零，导致下一块重复或错位。首次冷启动因静态零初始化可能碰巧正常，停止后再次启动则存在真实风险。

要求：

1. 在 PDM 尚未启动、不会产生数据回调时完成 `g_isr_block = 0U`；
2. 不得在 `R_PDM_Start()` 成功后再次清零该游标；
3. 保持失败路径关闭 PDM，且 `g_running/g_stats.running` 不得被发布为运行；
4. 增加可在主机运行的 FSP/RT-Thread 桩测试，让模拟 `R_PDM_Start()` 在返回前主动触发一次回调；
5. 测试至少覆盖：冷启动、停止后重启、Start 失败、回调先于 Start 返回。旧实现必须被该测试稳定抓住。

## P2：缩短关中断窗口

`voice_audio_titan_stats()` 和 `voice_audio_titan_rms()` 当前在关中断期间执行 `uint64 -> float`、浮点除法和 `sqrtf()`。这不一定立即失效，但没有必要让 PDM 和舵机通信共同承受这段延迟。

要求在短临界区内只快照：

- `g_stats`
- `g_square_accumulator`
- `g_sample_accumulator`
- `g_level_samples`

恢复中断后再计算 RMS 与直流偏置。不得返回相互跨时刻拼接的数据。

## P3：补齐 Titan 适配层覆盖

当前主机测试覆盖 `voice_audio.c`，但未覆盖最容易出硬件问题的 `voice_audio_titan.c`。第三批至少要对下列接口建立桩测试：

- `R_PDM_Open/Start/Stop/Close`
- `rt_hw_interrupt_disable/enable`
- PDM 数据与错误回调
- `voice_audio_titan_start/stop/reset_stats/stats/probe`

还应验证 800 样本粒度、16 阶段整除约束、一秒缓冲回绕、错误事件计数和重启后的块序列。

## 文档小修正

“1000 只可被 8 整除，因而对 16 个值中的 8 个失败”表述不准确。实际是 `1000 % 16 == 8`，因此该参数每次调用都会无条件失败。请改成这一直接表述。

## 稀疏 Mel 决策

本批**暂不实施稀疏 Mel**。约 39 KB 的节省有价值，但当前内存预算没有证明它是阻塞项，而真实 PDM 采集、采样率和适配层尚未通过。此时改特征表示会同时改变生成器、C 前端和数值契约，增加定位真机问题的变量。

待基础采集和一次真机推理闭环通过后，可单独立项优化，验收条件为：

1. 保留稠密实现作为参考；
2. 稀疏表由脚本确定性生成，不手工录入；
3. 对完整测试语料，稀疏与稠密前端的 int8 特征逐位一致；
4. 分类决策逐例一致；
5. 给出 Flash、静态 RAM、峰值工作区和推理耗时的前后实测；
6. 任一项不一致则继续使用稠密版本。

## 既定架构决策

1. 暂不修改 `RA_SRAM_SIZE`，维持静态工作区方案；
2. 语音状态以后可以通过独立、版本化、带 CRC 的只读状态帧上报 MaixCAM2，但只能作为提示，不得绕过网页人工确认或直接触发机械手；
3. 先统一并记录当前机械手固件哈希，再建立语音集成分支；
4. 在真实采样率、真机推理、连续运行和真实说话人数据完成前，材料中只能写“语音扩展模块开发中”。

## 本次独立复核结果

- `python -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_audio smart_hand.tests.test_voice_split smart_hand.tests.test_voice_memory_budget -v`
  - `Ran 40 tests`，`OK (skipped=1)`
- `D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws -v`
  - `Ran 5 tests`，`OK`
  - int8 logits：95.83% 逐位一致，最大差 1；全部样本 argmax 一致

这些结果证明主机侧算法合同成立，不等价于 Titan 适配层、真机音频链路或 NPU 部署已经通过。
