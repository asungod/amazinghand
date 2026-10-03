# 交接文档：Titan 语音模块 + UART D1/D2 修复

日期：2026-09-23（14:40 修订版）
交接人：DeepSeek 会话（受 Codex 审核）
接手人：下一个 agent

> **修订说明**：本文件 14:22 的首版写于真机取证之前。**首版有三处关键错误**：说"未烧写、真机证据为零"、把"上电验收"列为下一步、遗漏了真机发现的头号缺陷。已按 `DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md`（14:29 写，比我晚）与磁盘证据全部更正。**如果你读到的是旧版，丢弃它。**

---

## 0. 三十秒上手

**当前最紧要的一件事**：真机验收发现环形缓冲**永久装满**——这是语音链路现在**跑不起来**的直接原因，也是本批唯一优先项。详见 §2。你的任务书是 `smart_hand/docs/DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md`。

### 板子现在的状态（务必先读）

**板上运行的*不是*语音候选固件。** 时间线：

1. `60AD1D89…` 候选固件（D1 + D2 + 语音）**已烧写**，烧写后 158,304 个 HEX 明确字节读回一致；
2. 通过 SWD 取得真机证据（见 §2）；
3. 真机取证后**已用备份整片回退**：写回 `0x02000000` 起始的完整 1 MiB，`RESTORE VERIFY OK: 1048576 bytes`。

所以现场任何现象都**不能**当作该候选固件的表现。备份与取证产物在 `outputs/Titan_Voice_Bringup_2026-09-23/`。

**机械手 6 V 驱动板全程断电，Titan 单独上电**——这个状态必须保持，直到环形缓冲问题修好并通过你的主机测试。

### 命令

```bash
# 项目根（仓库）
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"

# 主机测试（不需要 TensorFlow）
python -m unittest smart_hand.tests.test_voice_app smart_hand.tests.test_voice_features \
    smart_hand.tests.test_voice_audio smart_hand.tests.test_voice_audio_titan \
    smart_hand.tests.test_voice_split smart_hand.tests.test_voice_memory_budget \
    smart_hand.tests.test_servo_group_recovery smart_hand.tests.test_run_one_cycle_d2 \
    smart_hand.tests.test_drv_usart_v2

# TFLite 对照（需要 TensorFlow venv）
/d/voice_kws_env/Scripts/python.exe -m unittest smart_hand.tests.test_voice_kws

# 构建真机固件
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

**唯一候选产物**

```
路径    D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex
SHA-256 60ad1d892cb861785ec3af9216b03c2e438859235db8fd41ed43a29a2367392a   (445,397 B)
elf    10e3f6059f3fa8a7cf6046e95bb17235f8125e135197aa2904d74379313651f0
size   text 157,280 / data 1,024 / bss 436,216        mtime 2026-09-23 10:11
```

**工程根 `titan_uart_test\rtthread.hex` 是 2026-09-21 的旧版（`121262e133e6…`），不得烧写。** 详见 §4 陷阱 1。

---

## 1. 这个项目是什么

OpenSignHand：MaixCAM2（视觉/手势）→ UART → Titan Mini（RA8P1 单片机，实时安全门控）→ 舵机驱动的灵巧手，用于手部康复训练与手语教学。

- **Titan 承担**：UART 协议、CRC、ACK、状态机、舵机动作表、安全门控
- **语音模块**是在 Titan 上新增的**端侧有限词表语音意图识别**（PDM 麦克风 + int8 KWS）
- **仓库**（`嵌赛物联网/smart_hand/`）是唯一正式源码；**真机工程**（`D:/Micu/RTTWorkspace/titan_uart_test/`）是部署目标

---

## 2. ⚠️ 真机证据与两个待修问题（**这一节是本文件最重要的部分**）

### 2.1 实测采样率与假定不符

| 项 | 值 |
|---|---|
| 连续 5 秒计数增长 | 84,000 → **≈16,800 样本/秒** |
| 连续 10 秒计数增长 | 167,200 → **≈16,720 样本/秒** |
| 配置假定值 | 16,000 |

800 样本的回调粒度带来约 ±160/±80 样本/秒的端点量化误差，但**两次都明显高于 16,000**。

**不要把配置里的 16 kHz 当实测值。** `configuration.xml` 的 `pdm_output_sampling_freq = 16000` 是配置声明；而 `SINCRNG=5 / SINCDEC=124 / CKDIV=0` **与芯片复位默认值一字不差**，这本身就是可疑信号。

**影响**：若有效采样率真是 ≈16.7 kHz，特征频率轴整体偏移 ≈4.4%，**离线训练出的模型在真机上适用性存疑**。任务书要求先定位实际时钟来源与分频，**不要直接改模型常量掩盖偏差**。

### 2.2 🔴 环形缓冲永久装满（**头号缺陷，优先修**）

**现象**（SWD 实测）：`g_ready=1`、状态长期停在 `CAPTURING`；`samples_captured=5,370,400` 而 **`accepted_samples` 冻结在 32,000**，`overrun_count` 涨到 **5,338,400** 并持续增长；`pdm_error_count=0`、`running=1`。

**根因**（**这是我这一路的架构缺陷，不是别人的 bug**）：

```
voice_app_titan.c::voice_io_peek_window()
        ↓ 只调用
voice_ring_peek_latest()          ← 非消费式，只读不推进 read_index
```

`voice_app.c` 的接口契约把 `peek_window` 定义成**非消费**的，而胶水层就照着映射到了 `voice_ring_peek_latest`。结果是**生产路径从来没有任何消费者推进 `read_index`**：

- `VOICE_RING_CAPACITY = 32,768`，800 样本/回调 → 最多接受 32,000 个
- 之后**每一块都被 fail-closed 拒绝**（这正是 R2 溢出保护的预期行为）
- 而 R2 的隔离条件是"**新**接受样本重新攒满一整窗"——`accepted_samples` 再也不增长 → **永远出不来**

我在复现文档里甚至写过这个 fail-closed 后果（"消费者持续落后时环会稳定停在满状态，此后每一块都被拒绝"），**但我没有把消费者接到会真正消费的路径上**。

**为什么主机测试没抓到**：集成层的 277 条断言用的是**注入式假 I/O**，`peek_window` 是测试自己实现的，环形缓冲根本没参与。任务书现在明确要求：**"不能只测纯状态机 fake I/O，必须覆盖真实胶水层与环形缓冲组合"**。

**修复约束**（任务书原文）：
- 实现**最小、可证明的**消费者侧释放/取窗机制，保证连续运行时缓冲有空间，且送入前端的每个窗口**时间上连续**；
- ISR **只能写生产者游标**；不能让 ISR 推进 `read_index`、不能只靠增大缓冲、不能靠定期清空 overrun 计数掩盖问题；
- 复制窗口期间发生的生产者写入/溢出仍须 **fail-closed**；
- 若调整 `peek_window` 的"非消费"契约，**必须同步改接口文档与测试**；若新增取窗 API，给出**并发所有权与窗口边界的证明**。

**必须覆盖的测试**（任务书原文）：首次填窗、持续多个窗口、**跨环回绕**、**复制期间的生产者推进**、**真实 overrun 后恢复**、**推理耗时超过一窗时的行为**。并加一个**能在旧实现上稳定失败**的回归/变异测试。

### 2.3 真机证据的边界

SWD 读到的采集缓冲有**变化的 PCM 字样本**——但这**不等于**语言识别准确率已验证。`field_accuracy_validated` / `hardware_inference_validated` **仍为 0**。

另有提示：pyOCD 的 AP#2/SVD 告警在读取、烧写、校验**成功时也出现过**，不要仅凭这些告警推断失败。

---

## 3. 红线（违反即返工）

| 禁止 | 原因 |
|---|---|
| 改 `board.h` 的 `RA_SRAM_SIZE`、`fsp.ld` | 内存算过账，动它会让堆与静态区失衡（见 §5.13） |
| 让语音结果直接驱动舵机、或绕过网页人工确认 | 语音只是**提示**，安全门仍权威 |
| 改现有 UART 帧 / CRC / ACK / 超时 / 门控语义 | 已验收的通信契约 |
| 用关键词自动开始训练 | 必须人工确认 |
| 宣称已用 Titan NPU | **不是**。当前是 Cortex-M85 **CPU int8 自研推理**（TFLM 编不进来，见 §5.14） |
| 编造准确率，或把合成语料对拍写成真实识别率 | 本项目对诚实口径要求极高 |
| 从工程根的旧副本回拷覆盖 `src/` | 会静默回退已审核的修复（§5.2） |
| 删除 `RT_ASSERT` 来掩盖问题 | D1 只把**可达**那条换成丢弃路径，其余 13 处断言全保留 |
| 用 `rt_kprintf` 当可观察证据 | Titan 控制台是 `null`，输出会被丢弃 |
| **本批刷写** | 由 Codex 负责真机复验；且先修好环形缓冲 |

---

## 4. 交付物清单

### 4.1 语音算法与控制（仓库 `smart_hand/titan_rtthread/`，15 个文件）

| 文件 | 职责 |
|---|---|
| `voice_config.h` | 契约常量单一来源（16 kHz、25 ms 窗、10 ms 步长、40 mel、98 帧） |
| `voice_features.{c,h}` | float32 log-Mel 前端，零依赖，可主机测试 |
| `voice_audio.{c,h}` | 无锁 SPSC PCM 环形缓冲（生产者=PDM 中断，消费者=线程） |
| `voice_audio_titan.{c,h}` | FSP PDM 绑定 + 真机探测 `voice_audio_titan_probe()` |
| `voice_kws.{c,h}` | int8 推理引擎（conv2d / dwconv / avgpool / fc） |
| `voice_model_data.{c,h}` | 导出的 int8 权重 + scale/zero_point/requant 乘数 |
| `voice_app.{c,h}` | **集成层状态机，纯逻辑**，零 RT-Thread/零堆 ← **§2.2 的契约在这里** |
| `voice_app_titan.{c,h}` | RT-Thread 线程 + 真实 I/O 表 + 全部静态存储 ← **§2.2 的缺陷在这里** |

### 4.2 训练与导出（`smart_hand/titan_ai/voice/`）

| 文件 | 职责 |
|---|---|
| `voice_features_ref.py` | 前端 Python 镜像。**训练必须用它**，不能用 librosa——否则训练与固件特征分布不一致 |
| `voice_quant.py` | TFLite requantisation 算术的 Python 移植 |
| `train_voice_kws.py` | 训练 → int8 TFLite → C 导出 |
| `generated/` | 产物：`voice_kws_int8.tflite`（25,360 B）、`voice_model_data.{c,h}`、`voice_training_metrics.json` |

### 4.3 测试（`smart_hand/tests/`）

策略层与胶水层的 C 测试 + Python 包装，另有固件驱动与 servo 的桩测试。清单见 §0 命令。

### 4.4 文档（`smart_hand/docs/`）

| 文档 | 内容 |
|---|---|
| **`DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md`** | **你的任务书**（问题一/问题二、交付边界、验收清单） |
| **本文件** | 交接总览 |
| `DEEPSEEK_TO_CODEX_TITAN_VOICE_INTEGRATION_2026-09-23.md` | 被动集成交付报告（资源预算、变异结果） |
| `DEEPSEEK_TO_CODEX_TITAN_UART_D2_FIX_2026-09-23.md` | 舵机总线永久静默修复 |
| `DEEPSEEK_TO_CODEX_TITAN_UART_D1_FIX_2026-09-22.md` | UART 启动窗口修复 |
| `DEEPSEEK_TO_CODEX_TITAN_VOICE_KWS_BATCH{,2,3}_2026-09-22.md` | 语音算法三批交付 |
| `TITAN_VOICE_RECON_2026-09-22.md` | 侦察报告 + 三方案裁决（**先读这份理解为什么这么设计**） |
| `TITAN_VOICE_MODEL_REPRODUCE.md` | 从录音到固件的复现流程 + 数据集规范 |

### 4.5 工具（`tools/`）

| 文件 | 用途 |
|---|---|
| `voice_memory_budget.py` | 静态内存预算（已适配"集成前/后"两种口径） |
| `check_firmware_single_source.py` | 检查工程根与 `src/` 同名副本是否分叉 |
| `voice_dataset/` | 语料采集规范与录音脚本 |

---

## 5. 陷阱清单（**每条都是我实际踩过的**）

### 5.1 工程里有两份同名 `rtthread.hex`，内容不同

两套构建系统：CDT/make 产物落 `Debug/`，SCons 的 `POST_ACTION`（`rtconfig.py:56`）在工程根再生成一份，**互不覆盖**。**只认 `Debug/rtthread.hex`**，烧写前核对 SHA-256。

### 5.2 `src/` 是唯一被编译的源码目录

CDT 编 `../src/*.c`，SConscript `Glob('./src/*.c')`。工程根同名副本**从不参与编译**——改它"编译成功但行为完全不变"。`tools/check_firmware_single_source.py` 守这条。**只做 src→根同步，永不反向。**

### 5.3 `Debug/src/subdir.mk` 是三张平行清单，且混合换行

`C_SRCS` 用 `../src/` 前缀，`OBJS`/`C_DEPS` 用 `./src/`。文件混用 CRLF/LF。

- 新源文件必须**同时**进三张清单，否则**静默不编译不链接**（无报错）
- 是 `genmakebuilder` 自动生成物，在 Studio 里刷新会被覆盖
- **不要写"插入"脚本**——我写过一个只认 `./src/` 前缀的版本，把 C_SRCS 原有 17 条替换掉了。正确做法是**从 `src/*.c` 权威集合确定性重建**（`tmp/wire_voice_sources.py` 是修好后的版本，幂等）

### 5.4 改编译选项**不会**触发重编译

往 recipe 里加 `-DVOICE_APP_ENABLE=1` 后 `make` 认为 `.o` 是最新的。必须 `touch src/voice_*.c`。

### 5.5 ⚠️ "编译成功 + 链接成功 + exit 0" ≠ 集成生效

`voice_app_titan.c` 是 `#if ENABLE … #else … #endif` 结构。`INIT_APP_EXPORT` 若插在 `#else` 之后（禁用分支末尾），后果是：启用构建下那行被跳过 → 无人调用 `voice_app_titan_init` → `--gc-sections` 回收整个模块 → **固件体积与集成前逐字节相同**，而编译链接全部"成功"、exit 0、零告警。

**判断集成是否真的发生，看两样**：`__rt_init_<模块>_init` 是否在 init 表（`grep rtthread.map`），以及**体积是否变化**。

### 5.6 PATH 里是 `platform/env_released`（斜杠）

写成 `platform_env_released`（下划线）会 `make: command not found`——**那个目录不存在**。

### 5.7 `make all | tail` 后面的 `$?` 是 `tail` 的退出码

不要用它判断构建成败。看产物 mtime 与 SHA-256。

### 5.8 TFLite 解释器默认**复用中间张量缓冲区**

比较中间层输出必须传 `experimental_preserve_all_tensors=True`，否则读到的是被后续算子覆盖过的数据。**这个坑一度让我误判"引擎 0% 一致"，实际引擎是对的。**

### 5.9 TFLite int8 卷积必须减输入零点

`acc = bias + Σ w·(input_q − input_zero_point)`。本模型 `input_zp = −128`，漏掉这一项结果全错，**只有端到端比对能发现**。

### 5.10 `R_PDM_Start` 的回调粒度有硬约束

必须是 `1 << PDM_INTERRUPT_THRESHOLD_16`（=16）的倍数**且**整除 `buffer_size/4`。合法值只有 `{16,80,160,400,800,1600,2000,4000,8000,16000}`。

早期用了 `1000`（`1000 % 16 = 8`）→ **每次调用都失败**，一个样本都采不到，而症状只是"probe 返回负值"。现已加 `_Static_assert` 编译期拦截。

### 5.11 `R_PDM_Read` 不可用

`ra/fsp/src/r_pdm/r_pdm.c` 中 `R_PDM_Read` 直接 `return FSP_ERR_UNSUPPORTED`（函数体在 445 行起，`return` 在 **451 行**）。数据只能由数据中断搬运。

### 5.12 `pdm_error_t` 是位掩码，`PDM_ERROR_BUFFER_OVERWRITE = (1UL<<11)`

用 `uint8_t` 存会截断成 0 == `PDM_ERROR_NONE`，**缓冲覆写这个最该被看见的错误完全隐形**。已改 `uint32_t`。

### 5.13 内存：`HEAP_BEGIN` 随 `.bss` 上移

`board.h` 的 `RA_SRAM_SIZE = 512` 把堆上限卡在 `0x22080000 − __RAM_segment_used_end__`。静态区增长 = 堆等量减少。集成后 `__RAM_segment_used_end__ = 0x2206abfc` → 堆 **386,060 → 87,044 B（−77%）**。**任何新增走堆的分配都要先算这笔账。**

### 5.14 语音模块**不是** NPU

`ra/npu/tflite-micro/` 在源码树里，但 `ra/SConscript` 只收 `ethos-u-core-driver`，`Debug/makefile` **完全没有 C++ 规则**。TFLM 编不进来。当前是 CPU int8。`rm_ethosu` 驱动虽已链接，但只是空壳实例。

### 5.15 权限限制（**不要绕过**）

- **PowerShell 执行被 deny** → `smart_hand/host/check_titan_sync.ps1` **只能由用户运行**
- **`rm` 被 deny** → 临时文件清理交用户
- 文件 `mv` 出工程被 deny（我曾改用"同步"解决）

遇到这些**如实上报给用户，不要换工具绕过**。

---

## 6. 关键设计决策（为什么是这样）

| 决策 | 理由 |
|---|---|
| 前端 float32、量化整数 | 浮点阶段容差可比（实测最大差 1.14e-05，比量化步长小 5461 倍）；**int8 输出逐位一致**才是硬契约 |
| 环形缓冲**溢出 fail-closed**（拒绝整块而非覆写未读数据） | 生产者写 `read_index` 是非法的 SPSC 操作。**⚠️ 但代价就是 §2.2 那个缺陷：没有消费者释放时环会永久满。设计 fail-closed 时**必须**同时设计消费侧的释放路径** |
| 语音线程栈 8 KB **静态**、`voice_kws_t` 62,727 B **静态** | 堆只剩 87 KB |
| `VOICE_APP_ENABLE` 默认 **0** | fail-closed：仅把文件加进构建不改变固件行为 |
| 三层策略 R1/R2/R3 | R1 窗口未满不推理；R2 overrun 丢弃且隔离到重新攒满；R3 失败先 `result_valid=0`，`result_generation` 跨重启不重置 |
| `abort_cycle()` 与新计数器 `aborted_cycles` | **不复用 `invalid_cycles`**——后者语义是"完成了但数据不可信"，中止的周期根本没产生数据 |

---

## 7. 已验证 vs 未验证（**交接时不要混淆**）

### 已验证（主机侧，可复跑）

| 项 | 证据 |
|---|---|
| 前端 C↔Python int8 逐位一致 | `test_voice_features.py` |
| 环形缓冲（含 12 万采样点跨边界、交错压力） | `test_voice_audio_c.c` |
| 推理引擎 vs TFLite：分类 24/24 一致，logits 95.83% 逐位相同、max\|diff\|=1 | `test_voice_kws.py` |
| D1 补丁：空 FIFO 丢弃、发布后逐字节不变 | `test_drv_usart_v2_c.c`（294 断言） |
| D2：abort 后下一周期可恢复 + 接线正确 | `test_run_one_cycle_d2_c.c`（**134 断言**）；另有 `test_servo_group_recovery_c.c` 用裸 `assert.h`，**不报数** |
| 集成层三条策略（**假 I/O**） | `test_voice_app_c.c`（277 断言） |
| 胶水层线程参数/真实窗口/禁用态 | `test_voice_app_titan_c.c`（90 + 13 断言） |
| 全部源文件可被真机工具链编译、固件可链接 | §0 的构建命令 |

**变异测试的准确口径**（别照抄印象里的数字）：

| 范围 | 编码进测试套件的变异框架 | 位置 |
|---|---|---|
| D1（UART 驱动） | **3 个** | `test_drv_usart_v2.py` 的 `MUTANTS` |
| D2（`run_one_cycle` 接线） | **4 个** | `test_run_one_cycle_d2.py` 的 `MUTANTS` |
| 语音集成层 | **4 个** | `test_voice_app.py` 的 `test_m1..test_m4` |
| **语音算法/环形缓冲** | **0 个** | **没有自动化变异装置**——那几个批次的变异是当时手工复做的，未落盘 |

### 未验证（**必须真机**）

1. **§2.2 的环形缓冲缺陷修复后能否连续运行** —— 当前跑不起来。
2. **有效采样率的准确值** —— 实测 ≈16,720–16,800，**不是** 16,000；精确值与时钟来源未定位。
3. **真实识别率** —— SWD 读到的 PCM 字样本**不等于**识别准确率。仓库零音频资产，所有离线数字出自合成自检。
4. **推理耗时 / 堆运行期水位 / 栈水位**。
5. **并发** —— 所有测试都是单线程。
6. `voice_audio_titan.c` 里"驱动在缓冲末尾回绕"的假设，源码可从 `r_pdm.c:731-757` 证成，但**未经真机确认**。

---

## 8. 已知遗留问题

| # | 问题 | 严重度 | 位置 |
|---|---|---|---|
| 1 | **环形缓冲永久装满**（§2.2） | 🔴 **最高** | `voice_app.c` 契约 + `voice_app_titan.c` |
| 2 | **有效采样率与假定不符**（§2.1） | 🔴 高 | 时钟配置/重采样 |
| 3 | `mel_weight[40][257]` 是 **95.4% 为零**的稠密矩阵（41,120 B）。稀疏化可省 **39,088 B** | 优化（**已裁决暂不做**） | `voice_features.h` |
| 4 | `g_servo_pair_commission_result` 被六条路径共用，可能让上位机收到**从未发生的 TRAIN SUCCEEDED** | 中 | `servo_bus_readonly_rt.c` |
| 5 | pair/group/index 四条分支**无忙标志**就调长阻塞函数，运动期间仍回 `ACCEPTED` 而非 `BUSY` | 中 | 同上 |
| 6 | `eight_servo_safety_gate` 的 `arm/plan_once/note_bus_write/clear_fault` **全工程无调用点**（已实测 0 命中）→ `servo_bus_safety_gate_armed()` 恒返回 0 | 功能缺口 | `eight_servo_safety_gate.c` |
| 7 | `voice_memory_budget.py` 的源码清单仍不认 `voice_app*`（集成后 ELF 实测已成为权威） | 低 | `tools/` |

**注**：曾列入本表的 `test_voice_audio_titan.py` 的 `CASE_LINE` 正则缺陷**已被修复**（正则现在含 `(?:(\d+) failures, )?`，并有回归测试 `test_failed_case_line_is_parsed`），不再是遗留项。

---

## 9. 下一步

**你（接手 agent）的任务**：`DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md` 里的问题一与问题二。**不刷写、不接通舵机 6 V、不把语音接到机械动作。**

**Codex/用户的真机复验**（你修完之后）：

1. 上电后 **10 分钟** `accepted_samples` **持续增加**；
2. 正常环境 `overrun_count` **不持续增加**；
3. `result_generation` 能更新；
4. `pdm_error_count = 0`；
5. 实测有效采样率接近 16 kHz；
6. 再做 MaixCAM2 UART ACK 并行测试。

**任何一项失败都不进入舵机上电测试。**

---

## 10. 这个项目的工作流约定

- 主模型 **Codex** 负责裁决；执行 agent 每批交付后写 **`DEEPSEEK_TO_CODEX_*.md`** 报告，含：实际读取的文件、确认/未确认事项、修改文件与关键设计、测试命令与**完整结果**、残余风险与下一步
- 任务书由 Codex 写、放 `smart_hand/docs/`，名为 `DEEPSEEK_TASK_*.md`
- **报告里必须如实写"未读到"和"未验证"**——宁可写"不确定"也不要推断
- **变异测试是本项目惯例**：写完测试要证明它**真的能抓到 bug**（删掉被测的保护、确认测试变红）
- 改动控制代码前先解释必要性、风险与验证方法

---

## 11. 一句话状态

**D1/D2 已在同一份候选固件里并通过主机验证；语音链路已进固件、已上过一次真机并取得证据，但真机暴露了两个问题——环形缓冲永久装满（我的架构缺陷，头号优先）与有效采样率比假定高约 4.4%——板子现已回退到旧固件，等修好后由 Codex 复验再刷。**
