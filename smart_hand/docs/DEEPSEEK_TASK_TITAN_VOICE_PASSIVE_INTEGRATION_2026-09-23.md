# DeepSeek 任务：Titan 语音模块第一阶段被动集成

日期：2026-09-23

## 审核结论与目标

D2 状态机修复通过，可以进入语音集成。第一阶段只做**被动集成**：真实工程能编译链接、语音线程和 PDM 采集链存在、资源预算可核验，但语音结果不得触发机械手、不得替代网页人工确认，本阶段不得烧写。

## 0. 集成前必须先处理源码歧义

当前工程同时存在：

- `D:/Micu/RTTWorkspace/titan_uart_test/servo_bus_readonly_rt.c`：旧副本，仍含 D2 修复前的永久静默路径；
- `D:/Micu/RTTWorkspace/titan_uart_test/src/servo_bus_readonly_rt.c`：Debug/make 实际编译的 D2 新版。

`Debug/src/subdir.mk` 已确认编译 `../src/servo_bus_readonly_rt.c`。集成前必须明确 `src/` 是唯一正式源码：

1. 将根目录旧副本同步为与 `src/` 完全一致，或移出工程并明确标为历史备份；
2. 在报告中记录两者处理结果与 SHA-256；
3. 增加一个轻量检查，禁止同名根目录/`src` 副本内容不一致时继续发布固件；
4. 不得从旧根目录副本回拷覆盖 `src/`。

## 1. 集成范围

将已审核的下列模块纳入真实固件构建：

- `voice_config.h`
- `voice_audio.c/.h`
- `voice_audio_titan.c/.h`
- `voice_features.c/.h`
- `voice_kws.c/.h`
- `voice_model_data.c/.h`

新增一个最小语音线程/集成层，职责限定为：

1. 初始化 PDM 采集；
2. 从 ring 取得完整窗口；
3. 运行特征提取和 int8 KWS；
4. 保存只读状态与诊断计数；
5. 允许编译期开关彻底关闭语音线程；
6. 失败时只标记不可用，不影响 UART、舵机轮询、手语训练和原康复模式。

## 2. 硬性资源约束

- `voice_kws_t` 实测约 62,727 B，必须使用静态存储或明确的长期分配，禁止放在线程栈；
- `voice_kws_predict()` 单函数栈帧约 4,048 B，语音线程栈先设为 **8 KB**，不得低于 6 KB；
- 不修改 `RA_SRAM_SIZE`，不修改 `board.h` 和 `fsp.ld`；
- 不实施稀疏 Mel；
- 不宣称使用 Titan NPU，当前仍是 CPU int8 自研推理路径；
- 构建后给出 `.text/.data/.bss`、语音线程栈、静态模型、工作区和剩余 RAM 的分项预算；
- 若链接或预算失败，停止，不通过删安全检查、缩减线程栈或改 SRAM 常量绕过。

## 3. 状态与安全边界

建议状态至少包含：

```text
DISABLED / INIT / CAPTURING / INFERENCING / RESULT / AUDIO_ERROR / MODEL_ERROR
```

只读诊断至少包括：

- 实际采样计数与预期采样计数；
- PDM error / overrun / dropped samples；
- RMS、峰值、直流偏置；
- 最近推理耗时；
- 最近类别、置信度或量化分数；
- 模型版本/哈希；
- `field_accuracy_validated=false`、`hardware_inference_validated=false`，直到真机证据完成。

严格禁止：

- 语音直接调用舵机动作接口；
- 语音绕过网页人工确认；
- 用关键词自动开始训练；
- 修改现有 UART 帧、CRC、ACK、超时与门控；
- 把合成数据精度写成真实识别率。

本阶段先不扩展 MaixCAM2 协议。语音状态保留在 Titan 只读结构或调试内存中，待真机采样与推理成立后再单独设计版本化 `VOICESTAT` 帧。

## 4. 启动、停止与故障恢复

必须测试：

1. 正常启动并采满一个窗口；
2. PDM Open/Start 失败时线程退出到 `AUDIO_ERROR`，其他系统继续运行；
3. 停止后重新启动，ISR 块序列不重复、不跳块；
4. ring overrun 时丢弃当前推理窗口并恢复，不使用拼接污染数据；
5. 推理失败时不发布旧结果为新结果；
6. 语音线程禁用时固件行为与 D2 版本一致；
7. 看门狗、UART1、UART2、舵机轮询不因语音计算饥饿。

## 5. 构建与验证要求

### 主机侧

- 现有语音、D1、D2 全量测试继续通过；
- 新增集成层状态机测试；
- 模拟 PDM 失败、ring overrun、推理失败和停止重启；
- 变异测试至少证明：删除人工隔离边界、复用旧结果、减小栈预算守卫会被抓住。

### 真实工具链

- 真实 ARM 工具链完整 clean build，不接受 `make | tail` 的退出码；
- 同时核对目标 `.o/.elf/.hex` 的 mtime 与 SHA-256；
- 用 map/size/stack-usage 报告资源；
- 唯一候选产物为 `Debug/rtthread.hex`；工程根旧 hex 必须显式标为陈旧或同步，不能让操作者误刷。

## 6. 本批停止点

本批只交付源码、测试、资源报告和候选固件，**不烧写**。Codex 审核通过后，用户在实验室再执行：

1. D1 冷启动 20 次；
2. D2 人为制造一次 TX 超时并确认下一周期恢复；
3. PDM 实测采样率、静音/说话 RMS 与 DC；
4. 真机单次和连续推理耗时；
5. 30 分钟运行中的溢出、栈水位、UART ACK 与舵机状态。

## 7. 交付格式

1. 实际修改/新增文件；
2. 根目录旧源码歧义处理结果；
3. 集成架构和线程状态机；
4. RAM/Flash/栈预算；
5. 测试与变异结果；
6. clean build 命令、产物 mtime 和 SHA-256；
7. 未验证的真机项目；
8. 明确声明：未烧写、未验证真实识别率、未启用语音控制。
