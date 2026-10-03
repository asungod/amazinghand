# Titan 端侧语音 KWS 复现流程

从零重跑：录音 → 特征 → 训练 → int8 量化 → C 导出 → 主机验证 → 固件编译。

配套阅读：`TITAN_VOICE_RECON_2026-09-22.md`（为什么这么设计，以及与任务书陈述不符的实测事实）。

---

## 0. 当前交付状态（先读这段）

| 环节 | 状态 | 证据 |
|---|---|---|
| log-Mel 前端 C↔Python 一致性 | ✅ 已验证 | `tests/test_voice_features.py`，int8 输出逐位一致 |
| PCM 环形缓冲 | ✅ 已验证 | `tests/test_voice_audio_c.c`，含 12 万采样点跨边界完整性、交错生产/消费压力测试 |
| 环形缓冲 SPSC 所有权 | ✅ 已修复 | 生产者不再写 `read_index`；溢出 fail-closed 拒绝整块而非覆写未读数据 |
| PDM ISR 与线程的统计竞态 | ✅ 已修复 | 临界区内只做快照，浮点计算移到恢复中断之后；见 §4.2 |
| 启动时 ISR 游标竞态（P1） | ✅ 已修复 | `g_isr_block` 在 `R_PDM_Start()` **之前**清零，成功后不再触碰；见 §4.2.1 |
| PDM 回调粒度非法（曾致采集 0 样本） | ✅ 已修复 | 粒度 1000→800，并有 `_Static_assert` 编译期拦截；见 §4.3 |
| `INT16_MIN` 峰值丢失 | ✅ 已修复 | 峰值改为 `int32_t` 并先加宽再取负；实证见下方 |
| int8 推理引擎 vs TFLite 参考 | ✅ 已验证 | `tests/test_voice_kws.py`，分类判断 24/24 一致，logits 95.83% 逐位相同、最大差 1 |
| 训练/量化/导出管线 | ✅ 可运行 | `train_voice_kws.py --synthetic` |
| 全部源文件可被设备工具链编译 | ✅ 已验证 | 用工程真实旗标 `-fsyntax-only`，5 个文件 exit=0 零警告 |
| **真实关键词识别准确率** | ❌ **不存在** | 仓库内无任何录音，见 §1 |
| **真机采样率** | ❌ **未实测** | 见 §5 |
| **真机推理耗时 / RAM 水位** | ❌ **未实测** | 见 §6 |

**本流程产出的任何准确率，只要语料是合成的，就不是关键词识别结果。** 度量文件里 `field_accuracy_validated` 与 `hardware_inference_validated` 恒为 `false`。

---

## 1. 数据集规范

六个意图，目录名即类别名，顺序即固件里的类别顺序：

```
开始训练  取消训练  下一个  再来一次  求助  UNKNOWN
```

`UNKNOWN` 必须收录以下四类，缺一不可：

1. 静音（房间底噪，不是数字静音）
2. 非目标中文语音（同一说话人念其它词）
3. 实验室环境音（敲击、键盘、挪椅子、风扇）
4. 音乐/视频外放

采集要求：

| 项 | 要求 |
|---|---|
| 格式 | 16 kHz、单声道、16-bit PCM、WAV |
| 时长 | 每段 ≥ 1.0 s（前端窗口为 1.0 s，不足会被零填充） |
| 目标词 | 每词每人不少于 20 遍，至少 3 名发音人 |
| UNKNOWN | 总量不少于目标词总量的 50% |
| **划分** | **必须按说话人划分**训练/验证/测试，同一人的任意两段不得跨集合 |
| 距离 | 覆盖 20 cm / 50 cm / 1 m 三档，模拟实际摆位 |
| 标注 | 文件名必须带说话人编号，格式 `<说话人>_<距离>_<序号>.wav`，如 `spk01_near_003.wav`（`train_voice_kws.py` 按此解析，解析不了的文件名会直接报错） |

生成文件布局：

```
<dataset>/
  开始训练/spk01_near_001.wav ...
  取消训练/...
  下一个/...
  再来一次/...
  求助/...
  UNKNOWN/...
```

细分规范与采集脚本见 `tools/voice_dataset/README.md`。

---

## 2. 环境

训练需要 TensorFlow，**不要装在 Anaconda base 里**。本机已验证的环境：

```powershell
python -m venv D:\voice_kws_env
D:\voice_kws_env\Scripts\python.exe -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
D:\voice_kws_env\Scripts\python.exe -m pip install tensorflow-cpu numpy scipy scikit-learn soundfile `
    -i https://pypi.tuna.tsinghua.edu.cn/simple
```

已验证版本：Python 3.11.7、TensorFlow 2.21.0、numpy 2.4.6。

---

## 3. 训练与导出

管线自检（合成语料，只验证管线通不通，**不产生任何有意义的准确率**）：

```powershell
cd smart_hand\titan_ai\voice
D:\voice_kws_env\Scripts\python.exe train_voice_kws.py --synthetic --epochs 15
```

真实语料：

```powershell
D:\voice_kws_env\Scripts\python.exe train_voice_kws.py --dataset <数据集目录> --epochs 60
```

产物（均在 `smart_hand/titan_ai/voice/generated/`）：

| 文件 | 大小（自检语料） | 用途 |
|---|---|---|
| `voice_kws_int8.tflite` | 25,360 B | 参考模型，用于验证 |
| `voice_model_data.h` | ~5 KB | 形状、scale、zero point、requant 乘数 |
| `voice_model_data.c` | ~75 KB | int8 权重、int32 偏置 |
| `voice_training_metrics.json` | — | 诚实口径的度量 |

导出器会**拒绝**任何偏离既定拓扑的模型（`_validate_topology`），因为 C 引擎只实现那一种结构。

---

## 4. 验证

```powershell
cd <项目根>
# 前端 + 环缓冲（不需要 TensorFlow）
python -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_audio -v

# 推理引擎 vs TFLite（需要 TensorFlow）
D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws -v
```

预期：前者 6 项通过；后者 5 项通过，并打印一行形如

```
int8 logit agreement: exact 95.83%, max |diff| 1, mean |diff| 0.0417
```

**容差说明**：`max |diff| ≤ 1` 是刻意接受的。0.08% 的元素相差一个量化步长，来自 TFLite `SaturatingRoundingDoublingHighMul` 的 nudge 舍入；少于一个步长的差异不可能改变分类。分类判断（argmax）要求 100% 一致，这条是硬性断言。

> 验证脚手架有一个易踩的坑：TFLite 解释器默认会**复用中间张量缓冲区**。比较中间层输出时必须传 `experimental_preserve_all_tensors=True`，否则读到的是被后续算子覆盖过的数据，比对结果毫无意义（本次开发中此坑一度造成"引擎 0% 一致"的假象，实际引擎是对的）。

### 4.1 环形缓冲的并发契约

`voice_ring_push` 是**生产者**（PDM 数据中断）函数，`voice_ring_read` / `voice_ring_peek_latest` 是**消费者**（线程）函数。

- **`read_index` 只由消费者写；`write_index` 只由生产者写。** 早期版本让生产者在溢出时推进 `read_index` 来腾地方，那是非法的 SPSC 操作——它会在消费者脚下改写尚未读完的音频。`test_producer_never_touches_read_index` 正是守这条。
- **溢出 fail-closed**：放不下时拒绝**整块**并计入 `overrun_count`，绝不覆写未读数据，也不做部分写入（部分写入会把两个不相邻的时刻拼接起来，对前端比一个干净的缺口更糟）。调用方必须把非零返回值当作**数据缺口**处理，而不是可重试的条件。
- 压力测试 `test_interleaved_producer_consumer_stress` 是**单线程交错模拟**，用影子 FIFO 逐样本校验顺序，并验证守恒关系 `accepted == consumed + available`。它证明了逻辑正确性，**不证明真实抢占下的内存序**——后者需要真机或用带内存屏障的实现在多核/中断环境验证。

**fail-closed 的一个必须正视的后果。** 消费者一旦持续落后，环会稳定停在满状态，此后**每一块都被拒绝**，`overrun_count` 持续增长而环内数据不再更新。消费者恢复后读到的是**陈旧**音频（最坏 2.05 s 前），而不是最新音频。

因此消费者侧**必须**做两件事，缺一不可：

1. 用 `voice_ring_peek_latest()` 取窗口后，检查样本的**新鲜度**（`fresh_ms`，对应任务书 §4-D 的只读状态字段），超过阈值一律输出 `UNKNOWN` 并**不得触发任何机械动作**；
2. 把 `overrun_count` 的增加当作**本窗口不可信**的信号，而不是可忽略的统计噪声。

换句话说：fail-closed 保住了数据完整性，但把"这份音频是否还代表当下"的责任明确交给了消费方。这不是缺陷，是取舍——旧实现用覆写未读数据换来了"永远有最新音频"，代价是消费者脚下的数据可能被改写。

### 4.2 统计量快照：临界区内只做快照

`voice_capture_stats_t` 由 PDM 中断持续更新，线程侧直接结构体拷贝会撕裂（可能拿到"回调之后的 `samples_captured`"配上"回调之前的 `rms`"）。

`voice_audio_titan_stats()` / `_rms()` / `_reset_stats()` 都用 `rt_hw_interrupt_disable()` / `rt_hw_interrupt_enable()` 包住，但**临界区内只做快照**——结构体拷贝加三个标量读取。`uint64 → float` 转换（本工程走 libgcc 软浮点）、浮点除法和 `sqrtf()` **全部移到恢复中断之后**执行，PDM 中断和舵机总线都不会为浮点运算等待。

**一致性约束**：四个值（`g_stats`、`g_square_accumulator`、`g_sample_accumulator`、`g_level_samples`）必须在**同一个**临界区内读完。分两次读会把某一时刻的累加和与另一时刻的样本数配对，算出从未存在过的均值。

选择临界区而非序列锁的理由：写者是**中断**，可以在读者任意一步抢占它，序列锁的读者必须对一个中断也在更新的计数器重试；对这么小的结构，遮蔽中断更简单且可证明正确。

### 4.2.1 启动时的 ISR 游标竞态

`g_isr_block` 是中断自己的缓冲游标，**必须在 `R_PDM_Start()` 之前清零**，不能之后。

原因：`R_PDM_Start()` 在返回前就已经使能数据中断，所以它交还控制权时，游标可能已被一或多次真实回调推进过。此时再清零会让下一个回调**重放已经交付过的块**；而在停止后重启的场景下，最初几次回调还会去读上一次会话遗留的块。

**冷启动看起来正常，纯属静态零初始化的巧合**——这正是它值得被测试钉死、而不是靠推理放过的原因。

修复后 `g_isr_block` 只在 PDM 空闲时清零一次，`R_PDM_Start()` 成功后只发布 `g_running`，绝不再碰游标。该行为由 `smart_hand/tests/test_voice_audio_titan_c.c` 的桩测试守住（覆盖冷启动、停止后重启、Start 失败、以及"回调先于 Start 返回"）。

---

### 4.3 PDM 回调粒度的硬约束（曾导致采集完全起不来）

`VOICE_CALLBACK_GRANULARITY` **不是自由取值**。`R_PDM_Start` 在配置硬件前有一道**无条件**检查（`r_pdm.c:266`，不受 `BSP_CFG_PARAM_CHECKING_ENABLE` 影响）：

```c
uint32_t stages_per_interrupt = 1U << p_extend->interrupt_threshold;
FSP_ERROR_RETURN((0 == (number_of_data_to_callback % stages_per_interrupt)), FSP_ERR_INVALID_SIZE);
```

本工程 `interrupt_threshold = PDM_INTERRUPT_THRESHOLD_16`（=4，即 16 stages），缓冲 16000 条目。**粒度必须同时是 16 的倍数且整除 16000**，合法值只有 `{16, 80, 160, 400, 800, 1600, 2000, 4000, 8000, 16000}`。

早期实现用了 `1000`。因为 `1000 % 16 == 8`，这个参数**每一次调用都会失败**——不是偶发，是从一开始就完全采不到样本。`R_PDM_Start` 直接返回 `FSP_ERR_INVALID_SIZE`，而症状只是"probe 返回负值"，没有任何线索指向粒度。

现在有两个 `_Static_assert` 在**编译期**堵死这类错误，并在注释里写清法律依据：

```c
#define VOICE_PDM_STAGES_PER_INTERRUPT (1U << PDM_INTERRUPT_THRESHOLD_16)
_Static_assert((VOICE_CALLBACK_GRANULARITY % VOICE_PDM_STAGES_PER_INTERRUPT) == 0U, ...);
_Static_assert((VOICE_CAPTURE_SAMPLES % VOICE_CALLBACK_GRANULARITY) == 0U, ...);
```

改回 1000 会立刻编译失败并给出可读原因。

---

## 5. 固件编译与烧写

编译（dry-run 已验证可解析）：

```powershell
cd /d D:\Micu\RTTWorkspace\titan_uart_test\Debug
set PATH=D:\RT-ThreadStudio\repo\Extract\ToolChain_Support_Packages\ARM\GNU_Tools_for_ARM_Embedded_Processors\13.3\bin;D:\RT-ThreadStudio\platform_env_released\env\tools\bin;%PATH%
make all
```

产物落在 `Debug\rtthread.hex`。

> ### ⚠️ 工程根目录还有一个同名 `rtthread.hex`，内容是旧的，不要刷它
>
> 工程里有两套构建系统，产出两份同名 hex：
>
> | 路径 | 状态 |
> |---|---|
> | `titan_uart_test\Debug\rtthread.hex` | ✅ **构建产物，认这个** |
> | `titan_uart_test\rtthread.hex` | ⛔ 陈旧（SCons 的 `POST_ACTION` 在工程根生成），2026-09-21 的旧版 |
>
> **每次烧写前先核对 SHA-256。** 文件名一样、内容不同，刷错就是刷回旧固件。

### 5.1 加源文件的两个陷阱

- **必须改 `Debug/src/subdir.mk`**，在 `C_SRCS` / `OBJS` / `C_DEPS` 三张清单各加一行，否则 `make all` 既不编译也不链接新文件。该文件头写着"自动生成的文件。不要编辑！"，在 Studio 里刷新工程会被覆盖。
- 更稳的路径是 SCons：`SConscript:17` 用 `Glob('./src/*.c')` 自动收录。但 `rtconfig.py:18` 的 `EXEC_PATH` 指向不存在的 `C:/RT-ThreadStudio`，需设 `RTT_EXEC_PATH` 环境变量指到 `D:` 那份。
- **根目录的同名副本不参与编译**：`titan_uart_test\` 下的 `smart_hand_uart.c` / `servo_bus_readonly_rt.c` 与 `src/` 下逐字节相同，但链接行只含 `./src/*.o`。改错副本会"编译成功但行为完全不变"。

### 5.2 内存

| 区域 | 容量 | 已用 | 备注 |
|---|---|---|---|
| FLASH | 1,048,576 B | 126,700 B | 模型 25 KB 放得下 |
| RAM 静态 | — | bss 137,200 B | 语音新增 static 约 62 KB（两个 31,360 B 缓冲） |
| **RT-Thread 堆** | **386,060 B** | — | 被 `board.h:20 RA_SRAM_SIZE=512` 卡死 |

**语音模块一律用静态数组，不要走堆。** 厂商 NPU 例程同样如此（`sub_0000_arena[442368]` 是静态数组，比堆上限还大）。

### 5.3 烧写与首次上电

烧写工具：`D:\Micu\tools\pyocd-ra8p1`。

首次上电顺序（**机械手 6 V 电源保持关闭**）：

1. 调用 `voice_audio_titan_probe(10000, &stats)`，记录：`samples_captured`、`callbacks`、`peak`、`rms`、`dc_offset`、`overrun_count`、`error_count`。
2. 用 `samples_captured / 实测秒数` 反推**真实采样率**。配置值是 16000 Hz，但 SINCRNG/SINCDEC/CKDIV 恰好等于芯片复位默认值，所以配置值不能当作实测值。
3. 对比 `dc_offset`：PDM 麦克风通常有明显直流偏置，前端已做逐帧去均值，但偏置过大会压缩有效位。
4. 检查 `overrun_count` 与 `error_count` 是否为 0。

只有在第 2 步确认采样率之后，前面所有离线结果的适用性才算成立——如果真实采样率不是 16000 Hz，特征频率轴会整体偏移，必须按实测值重训。

---

## 6. 仍需真机完成的事（本机无法代替）

- 真实采样率、峰值/RMS/直流偏置、30 分钟无溢出
- 真机推理耗时（当前编译为 **`-O0`**，`Debug/src/subdir.mk` 硬编码；建议对语音源文件单独加 `-O2`）
- 真机 RAM 水位与栈深度
- §7 三条路径的真机部分：正常路径识别率、失败路径（静音/多人/敲击/音乐 → `UNKNOWN`）、集成边界（与 UART 心跳、网页轮询并跑 10 分钟，`timeout=0`、`rx_errors=0`）
- **语音只读状态如何上报**：当前固件 `RT_CONSOLE_DEVICE_NAME="null"` 且 FINSH 未开，**没有任何调试终端**，`rt_kprintf` 输出会被丢弃。要么扩展 UART2 协议（需新增独立带版本号与 CRC 的消息），要么语音状态在真机上不可见。这是必须先决策的接口问题。

---

## 7. 文件清单

```
smart_hand/titan_rtthread/
  voice_config.h              契约常量（采样率、窗长、mel 数、帧数）
  voice_features.h/.c         float32 log-Mel 前端，零依赖，可主机测试
  voice_audio.h/.c            无锁 SPSC PCM 环形缓冲，可主机测试
  voice_audio_titan.h/.c      FSP PDM 绑定 + 真机探测（需设备工具链）
  voice_kws.h/.c              int8 推理引擎（conv/dwconv/avgpool/fc）
smart_hand/titan_ai/voice/
  voice_features_ref.py       前端 Python 镜像（训练必须用它，不能用 librosa）
  voice_quant.py              TFLite requantisation 算术的 Python 移植
  train_voice_kws.py          训练 → int8 TFLite → C 导出
  generated/                  导出产物
smart_hand/tests/
  test_voice_features_c.c / .py   C↔Python 特征一致性
  test_voice_audio_c.c   / .py    环形缓冲
  test_voice_kws_c.c     / .py    引擎 vs TFLite
```
