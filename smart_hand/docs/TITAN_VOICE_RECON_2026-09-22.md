# Titan 端侧语音 KWS 侦察报告与方案裁决（2026-09-22）

对应任务书：`outputs/OpenSignHand_Hardware_Bringup_2026-09-21/DEEPSEEK_TITAN_EDGE_SPEECH_TASK_2026-09-22.md`

本报告是任务书 §3.1 要求的"开工前方案比较"的交付物，同时记录**与任务书陈述不符或任务书未覆盖的实测事实**。

所有结论均带 `文件:行号` 或命令输出证据。未在真机验证的一律标注为配置事实或未确认。

---

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 建议方案 | **PDM 有限词表语音意图识别**（任务书 §3.1 的首选），理由见 §3 |
| 是否用 NPU | **本阶段不用**。原因见 §4，TFLM 在两套构建系统里都编不了 |
| 建议推理落点 | Cortex-M85 CPU 端 int8 推理，Helium/MVE 可用（`-march=armv8.1-m.main+mve.fp+fp.dp`）|
| 采样率 | 配置为 16000 Hz（`configuration.xml` 显式值），**真机未实测** |
| 内存可行性 | Flash 充裕；RAM 受 `board.h` 硬上限约束，**任务书的 512 KB 工作区目标放不下**，需改为静态分配或扩大 SRAM 常量，见 §5 |
| 最大阻塞 | **无 MSH/串口调试终端**，任务书 §4-D 建议的"调试终端验证"路径不存在，见 §6 |
| 数据 | 仓库内**零音频数据资产**，不含任何中文关键词录音，见 §7 |

---

## 1. 与任务书陈述的核对

### 1.1 已证实的部分

| 任务书 §2 陈述 | 核对结果 | 证据 |
|---|---|---|
| 已生成 `g_pdm0` | ✅ 属实 | `ra_gen/hal_data.h:85 extern const pdm_instance_t g_pdm0;` |
| PDM unit 0、channel 2、16 位 PCM | ✅ 属实 | `configuration.xml`：`pdm.channel=2`、`pcm_width=pcm_width_16bits_0_14`；`ra_gen/hal_data.c:587-589 .unit=0, .channel=2, .pcm_width=PDM_PCM_WIDTH_16_BITS_0_14` |
| `PDM_CFG_DMAC_ENABLE` 为 0，不能假设 DMA 可用 | ✅ 属实，且更严重 | `ra_cfg/fsp_cfg/r_pdm_cfg.h:9 #define PDM_CFG_DMAC_ENABLE (0)`；`ra_gen/hal_data.c:594 .p_transfer_rx = NULL` |
| 已生成 Ethos-U55/`rm_ethosu` 实例与 NPU IRQ | ✅ 属实 | `ra_cfg/fsp_cfg/rm_ethosu_cfg.h:12-13 #define ETHOSU55 1 / #define ETHOSU_ARCH u55`；`ra_gen/common_data.c:5 struct ethosu_driver g_ethosu0;` |
| 当前无语音神经网络 | ✅ 属实 | `grep -ril "voice\|kws\|pdm" smart_hand/` 返回空 |
| 固件 text 125676 / data 1024 / bss 137200 | ✅ **逐字节吻合** | `arm-none-eabi-size Debug/rtthread.elf` → `125676 1024 137200` |

### 1.2 与任务书不符或任务书未覆盖的发现

**(A) 任务书的"待刷固件"哈希无法复核 —— 且源码在文档之后被改过**

`V_SIGN_DIRECTION_FIX_PENDING_FLASH_2026-09-22.md` 记录待刷固件 SHA-256 为 `F12600ADE0…`，但现存两个 hex 都对不上：

```
Debug/rtthread.hex -> 2754ca25b3fa0c89755d19db9ae14cd14cf216ec2f8bed5a1d05e3d63bb92259  (09-22 18:55)
根 rtthread.hex    -> 121262e133e6a54f3baf7d32204fbabf52f6ede367e4e00e9c165697e28db016  (09-21 12:52)
```

且 `servo_bus_readonly_rt.c` / `smart_hand_uart.c` 的 mtime 为 **09-22 15:29/15:34**，晚于文档写作时间 14:28；`Debug/rtthread.hex` 又在 **18:55** 被重建。

**结论：文档所称"2026-09-22 已刷写"的固件，无法从现存任何产物复核。** 用户首次实物验证前必须先确认手上刷的到底是哪一份。这是本次侦察最重要的可执行发现。

**(B) RAM 实际可用量远小于链接脚本 —— 512 KB 工作区目标不可行**

| 来源 | 值 |
|---|---|
| 链接脚本 RAM 区 | `0x22000000`，长 `0x174000` = 1,523,712 B |
| **RT-Thread 堆实际范围** | `HEAP_BEGIN=0x22021BF4` → `HEAP_END=0x22080000`，**仅 386,060 B** |

证据：`board/board.h:20-21 #define RA_SRAM_SIZE 512` / `RA_SRAM_END (0x22000000 + RA_SRAM_SIZE*1024)`；`board/board.h:30-34 HEAP_BEGIN/HEAP_END`；`Debug/rtthread.map:6194 __RAM_segment_used_end__ @ 0x22021bf4`。

任务书 §5 目标"运行时张量/工作区 ≤512 KB"= 524,288 B，**超出堆容量 138,228 B（35.8%）**。

**可用出路**（不违反安全边界）：
- 走**静态数组**（`.bss`），不经堆——厂商 NPU 例程正是这么做的：`Titan_Mini_npu_ai_face_detection/src/models/sub_0000_invoke.c:16 __attribute__((aligned(16))) uint8_t sub_0000_arena[442368];`（432 KiB，比堆上限还大，纯靠静态分配）；
- 或调整 `board.h:20 RA_SRAM_SIZE`，但该文件自注 `"The SRAM size of the chip needs to be modified"`，且 0x22080000 以上是否为可用连续 SRAM 无仓库证据，**不建议在无手册确认时改**；
- ITCM(0x00000000,128 KiB)/DTCM(0x20000000,128 KiB) 在当前 map 中占用为 **0**，理论可用但需确认总线属性。

**(C) 无 MSH 串口命令行 —— 任务书 §4-D 的验证路径不存在**

`rtconfig.h:53 #define RT_CONSOLE_DEVICE_NAME "null"`；`.config:104 # CONFIG_RT_USING_FINSH is not set`；`arm-none-eabi-nm Debug/rtthread.elf | grep -iE "msh|finsh|shell"` → **无输出**。

且两路串口已被占用为应用协议：uart1 → `servo_bus_readonly_rt.c`，uart2 → `smart_hand_uart.c`，且 `TX_BUFSIZE` 均为 0。

**后果**：任务书"新增 voice_intent 等只读状态，先通过调试终端验证"无法照做。语音只读状态只能：① 走既有 UART2 协议扩展，或 ② 仅通过主机侧单元测试 + 真机上电行为间接验证。**这是必须在实施前与用户确认的接口决策。**

**(D) 编译固定在 `-O0`**

`rtconfig.py:24 BUILD='debug'`、`:49-51 CFLAGS += ' -O0 -gdwarf-2 -g -Wall'`；`Debug/makefile:137` 亦硬编码 `-O0`。

任务书 §5 的"单次推理 <100 ms"在 `-O0` 下风险很高。**建议对新增语音源文件单独施加 `-O2`**（`-ffunction-sections` 已开，可按文件生效），但这需要改 `Debug/src/subdir.mk`，见 (E)。

**(E) 新增 `.c` 文件必须改自动生成文件，或被两套构建系统漏掉**

- CDT/make 路径：`Debug/src/subdir.mk` 用 `C_SRCS`/`OBJS`/`C_DEPS` 三张**显式清单**逐文件登记。只放文件不改它 → `make all` 既不编译也不链接。
- 该文件头明写 `"自动生成的文件。不要编辑！"`，且工程 nature 含 `genmakebuilder`，**手改会在 Studio 刷新时被覆盖**。
- SCons 路径反而友好：`SConscript:17 src = Glob('./src/*.c')` 自动收录——**但 SCons 的 `rtconfig.py:18 EXEC_PATH` 指向不存在的 `C:/RT-ThreadStudio`**（实测 Studio 装在 `D:`），需设 `RTT_EXEC_PATH` 环境变量。

**(F) 仓库根存在同名冗余副本陷阱**

`D:\Micu\RTTWorkspace\titan_uart_test\` 根目录的 `smart_hand_uart.c` / `servo_bus_readonly_rt.c/.h` 与 `src/` 下**逐字节相同**，但链接行只含 `./src/*.o`。**改根级副本会"编译成功但行为完全不变"。**

**(G) BSP 的 PDM 示例有 4× 帧错位缺陷 —— 不可照抄**

`tmp/titan_bsp/.../Titan_Mini_pdm/src/hal_entry.c` 与 FSP 驱动契约冲突：

驱动侧（`ra/fsp/src/r_pdm/r_pdm.c:269-279`）：
```c
FSP_ERROR_RETURN((0 == buffer_size % PDM_PRV_FIFO_SAMPLE_SIZE), ...);   // FIFO 条目 = sizeof(uint32_t)
uint32_t number_of_samples_in_buffer = buffer_size / PDM_PRV_FIFO_SAMPLE_SIZE;
FSP_ERROR_RETURN((0 == number_of_samples_in_buffer % number_of_data_to_callback), ...);
```
第 4 参 `number_of_data_to_callback` 是**回调粒度的 FIFO 条目数**（`r_pdm.h:210-213` 的真实形参名）。

示例侧（`hal_entry.c:167`）：缓冲 64000 B = 16000 条目，却传 `samples/4 = 4000` → **回调每 1/4 缓冲触发一次**；而示例在 `pdm_callback` 里收到第一个 `PDM_EVENT_DATA` 就把整个 16000 条目当满缓冲处理（`hal_entry.c:64-67, 196`）。

**照抄这个示例会得到 4 倍错位的音频帧。**

示例另有两处内部不一致：`README_zh.md` 把第 4 参写作 `samples`（与代码的 `samples/4` 矛盾）；`convert_pdm_to_dac` 按"1 个 int32 = 1 个采样点"迭代，而 `total_bytes = samples*2` 又按 int16 双声道算（差 2 倍）。

**(H) 任务书 §2 未提及：厂商 BSP 有真实 NPU 例程，且它绕过 TFLM**

`tmp/titan_bsp/.../project/Titan_Mini_npu_ai_face_detection/`：真实调用 `RM_ETHOSU_Open(&g_rm_ethosu0_ctrl, &g_rm_ethosu0_cfg)` 与 `ethosu_invoke_v3(&g_ethosu0, cms_data, ...)`，直接吃 **Vela 命令流**（`sub_0000_command_stream.c` / `sub_0000_model_data.c` 共约 2.67 MB），**不经过 `MicroInterpreter`**。该例程是否真机跑通，仓库内无日志可证。

---

## 2. TFLM 与 NPU 的真实状态（对应任务书 §4-C.1 的"先验证工具链"）

任务书要求"只有在模型转换、NPU 初始化和真机输出均可复现时，才可宣称 NPU 部署"。核查结果：

| 项 | 状态 | 证据 |
|---|---|---|
| TFLM 源码在树里 | ✅ 321 个文件 | `ra/npu/tflite-micro/tensorflow/lite/micro/micro_interpreter.cc` 等 |
| TFLM 依赖在树里 | ✅ | `ra/npu/{flatbuffers,gemmlowp,ruy}/` |
| TFLM **已编译** | ❌ | `Debug/ra/npu/` 下只有 3 个 `.o`，全是 ethos-u-core-driver |
| TFLM **已链接** | ❌ | `grep -c "MicroInterpreter\|tflite::micro" rtthread.map` = **0** |
| Ethos-U 驱动已编译链接 | ✅ | `Debug/ra/npu/ethos-u-core-driver/src/{ethosu_driver,ethosu_device_u55_u65,ethosu_pmu}.o`；map 含 `.bss.g_ethosu0`、`.text.ETHOSU_PMU_*` |
| TFLM signal 算子实现 | ❌ | `ra/npu/tflite-micro/signal/micro/kernels/` 只有 `rfft.h`/`irfft.h` 两个头，无 `.cc` |
| SCons 是否收 TFLM | ❌ | `ra/SConscript` 只 `Glob('./npu/ethos-u-core-driver/src/*.c')` 与 `./fsp/src/rm_ethosu/*.c` |
| CDT/make 能否编 C++ | ❌ | `Debug/makefile` 中 `grep "CXX\|\.cc\|\.cpp"` **零命中** |

**裁决：本阶段不使用 TFLM，不宣称 NPU 部署。**

理由：TFLM 全是 C++（`.cc`），而 CDT/make 无 C++ 规则、SCons 未收录。要引入就得给一个已冻结并通过真机验收的安全固件增加 C++ 工具链与 200+ 个 `.cc`，风险与收益不成比例。

**采用的路线**：沿用仓库**已被验证的先例**——`titan_ai` 的"Python 训练 → 导出 C 静态数组 → 自研小推理内核"，但把 `titan_trust` 的 float32 升级为 **int8 全量化**（`titan_trust` 实测是 float32，见 §3 注）。

后续若要做 NPU，正确入口是 **Vela 直通路径**（照 `Titan_Mini_npu_ai_face_detection`），而非 TFLM。

---

## 3. §3.1 三方案比较（带本仓库证据）

| 方案 | 定位 | 现有输入 | 数据成本 | 固件改造量 | 真机证据难度 | 比赛叙事强度 | 推荐度 |
|---|---|---|---|---|---|---|---|
| **(a) PDM 有限词表语音意图识别** | 教师/陪练者的离线辅助交互 | ✅ 板载 MEMS PDM 麦克风 + `g_pdm0` 已生成、驱动已编译链接 | 中（需自录 4–6 词的少量数据） | **低–中**：新增 ring buffer + 前端 + 小模型，不动协议与安全门 | 低（麦克风板载，无需额外接线） | 中高（"端侧离线语音，不联网"） | **优先做** |
| (b) 时序动作质量评分 | 与 OpenSignHand 主功能最匹配 | ✅ MaixCAM2 已有关键点提取（`gesture_features.py`、`sign_landmark_capture.py`） | **高**（需真实正确/错误示范数据，按人划分） | 中（新增 `SIGNFEAT` 消息 + 时序模型） | 中（需受试者与标注流程） | 高 | 第二阶段 |
| (c) 舵机异常趋势识别 | 预测性维护 | ⚠️ 舵机只读总线已通（`servo_bus_readonly_rt.c`），但**无真实异常样本** | **极高**（异常样本稀缺，且任务书禁止伪造） | 中–高 | 高（需长期运行采集） | 中 | 暂不做 |

**选择 (a)。** 依据：
1. 它是三者中**唯一能立刻产出 Titan 端真实 AI 证据**的——硬件（板载麦克风）与固件基建（`g_pdm0` + 驱动已链接）都已就绪，只差模型。
2. 数据成本最低：有限词表 KWS 只需 4–6 个词、每人若干遍，可用手机或电脑录音起步。
3. 改造面最小：不触碰 SIGN/TRAIN 协议、状态机、软限位、CRC、ACK、失联恢复。
4. 与 (b) 不冲突——(b) 需要的 MaixCAM2 关键点链路已存在，可后续叠加。

**注**：任务书称 titan_trust 为既有 AI 先例，实测其为 **float32 sklearn MLP，非 int8**，无 TFLite/Vela/scale/zero_point（`smart_hand/titan_ai/generated/titan_trust_model.c:8` `static const float g_feature_min[10]`；`README.md:54-57` 自述 "uses a small float32 MLP on Cortex-M85 first"）。本方案在其基础上做 int8 全量化。

---

## 4. 集成边界

### 4.1 可复用的既有机制

| 机制 | 位置 | 复用方式 |
|---|---|---|
| 只读遥测的定式 | `smart_hand_uart.c:342` `rt_kprintf("TITAN_AI advisory=1 ready=%u state=%s controls_servo=0\n", ...)` | 语音输出同样硬编码 `controls_servo=0` |
| 静态分配、零动态内存 | `smart_hand_uart.c:80-81 static titan_trust_runtime_t g_...` | 语音运行时同样用文件级 static 结构体 |
| fail-closed 契约 | `titan_trust_model.c:59-68`（NULL/非有限值 → ANOMALOUS） | 低置信度/溢出/陈旧 → `UNKNOWN` |
| 主机侧 C 测试模式 | `tests/test_protocol_c.c` 等：`gcc -I <dir> <test>.c <src>.c -o <test>.exe` | 语音前端与推理内核同样处理 |
| 仓库↔真机工程的同步校验 | `smart_hand/host/check_titan_sync.ps1`（逐文件 SHA256，不匹配即抛错） | 新增语音文件必须加入该脚本清单 |
| 构建命令（已 dry-run 验证） | `cd /d D:\Micu\RTTWorkspace\titan_uart_test\Debug` → PATH 加 gcc13.3 bin 与 env\tools\bin → `make all` | 产物落 `Debug/rtthread.hex` |

### 4.2 绝对不可改动（安全关键）

- 舵机软限位、`eight_servo_safety_gate`、`servo_safety_gate` 的门控逻辑
- 既有 `SIGN` / `SIGNSTAT` / `TRAIN` / `TRAINSTAT` 帧语义与 CRC/ACK/超时/失联恢复
- 训练状态机与"手势识别不自动开始、必须人工确认"的约束
- `titan_trust` 的既有输出契约
- 现有线程优先级关系：唯一应用线程 `sh_uart` 优先级 **18**（`smart_hand_uart.c:750-755`）。**语音线程优先级必须低于它**（数值更大）。

### 4.3 最小侵入挂载点

- 新增线程 `voice`，优先级 > 18，栈由静态数组提供，**不放在 UART 线程内联**（`sh_uart` 已承担接收与安全刷新，内联推理会拖慢它）。
- 音频回调只做"搬运 + 计数"（`voice_ring_push` / `voice_ring_note_error`），不做特征、不做日志、不做推理。
- 只读状态先只在本线程内维护 + 单元测试覆盖；**是否上报 MaixCAM2 需用户先决策**（见 §1.2(C) 的接口问题）。

---

## 5. 可离线交付 vs 必须真机

任务书 §7 三条验证路径的拆分：

| 验证路径 | 无硬件可做 | 必须用户上电 |
|---|---|---|
| **正常路径**：说词→正确意图、置信度、延迟、内存 | 前端特征、模型推理、延迟（主机侧同频估算由用户在真机确认）、内存（静态分析） | 真实识别率、真机推理耗时、真机 RAM 水位 |
| **失败路径**：静音/多人/敲击/音乐/非目标词/PDM 溢出 → UNKNOWN | 静音、非目标词、溢出计数的**单元测试**；PDM 错误码注入测试 | PDM 真实溢出行为、麦克风故障不阻塞 UART 的实测 |
| **集成边界**：与 UART 心跳/网页轮询并跑 10 分钟，`timeout=0`、`rx_errors=0` | 代码层面的优先级与静态内存审计 | **全部**，10 分钟并跑只能真机做 |
| **采样率是否为 16000** | 静态推导（配置值） | **必须实测**——见 §5.1 |
| **30 分钟无溢出** | — | 必须真机 |

### 5.1 PDM 采集的驱动事实（已从源码查实）

上一版报告曾据 BSP 示例推断"一个 32 位 FIFO 条目承载 2 个 16 位 PCM 采样点"——**这是错的**。查 RA8P1 SVD 与 FSP 源码后更正如下：

| 事实 | 值 | 证据 |
|---|---|---|
| 一个 FIFO 条目 = **一个** PCM 采样点 | `PDM_PRV_FIFO_SAMPLE_SIZE == sizeof(uint32_t)`，寄存器 `PDDRRCHn.DAT[19:0]` 即样本本体 | `ra/fsp/src/r_pdm/r_pdm.c:27`；SVD `R7KA8P1AD.svd` 中 `PDDRRCHn` 字段定义 |
| `R_PDM_Read` **不可用** | 函数体只有 `FSP_PARAMETER_NOT_USED` 三行，直接 `return FSP_ERR_UNSUPPORTED` | `ra/fsp/src/r_pdm/r_pdm.c:445-452` |
| 采集只能由数据中断搬运 | `pdm_dat_isr` 读 `PDDSR` 取 FIFO 条数，逐条读 `PDDRR` 写入目的缓冲 | `r_pdm.c:848-878` |
| 回调粒度 = FIFO 条目数 | 形参名 `number_of_data_to_callback`；须是 `1<<interrupt_threshold` 的倍数，且整除 `buffer_size/4` | `r_pdm.h:210-213`；`r_pdm.c:266-273` |
| 16 位模式数据右对齐有符号 | `PDM_PCM_WIDTH_16_BITS_0_14` = `{S, D[14:0]}`，取该 32 位字的低 16 位即可 | FSP 头注释；SVD `DBIS` 枚举 |
| `pcm_callback_args_t` 无溢出计数字段 | 只有 `p_context` / `event` / `error`，溢出必须应用侧自行累加 | `r_pdm_api.h:88-94` |
| 溢出错误码 | `PDM_ERROR_BUFFER_OVERWRITE = 1<<11`，且配置里 `overwrite_error` 已启用 | `r_pdm_api.h:71-78` |
| 中断 | `PDM_DAT2_IRQn=61`、`SDET=60`、`ERR2=62`，ipl 均为 12 | `ra_gen/hal_data.c:603-622` |

### 5.2 采样率：本机无法判定，必须实测

`configuration.xml` 显式配置 `pdm_output_sampling_freq = 16000`，但**有两处旁证表明它不能当作实测值**：

1. **PDM 的时钟源在整个仓库里没有任何配置**——`raClockConfiguration` 全表无 PDM 节点，`bsp_clock_cfg.h` 无 PDM 项，设备头文件中除 `CKDIV` 外无任何 PDM 时钟选择寄存器。
2. **`SINCRNG=5 / SINCDEC=124 / CKDIV=0` 与芯片复位默认值 `0x057C0000` 一字不差**（SVD 中 `SINCRNG` 字段明确标注 `(default)`）。配置器生成的"计算值"等于硬件默认值，说明它未必是针对 16000 Hz 反算出来的。

因此 `voice_audio_titan.c` 附带 `voice_audio_titan_probe()`：采集固定时长后输出实际采样点数、峰值、RMS、直流偏置、溢出计数与错误计数，用 `样本数 / 实测秒数` 反推真实采样率。

**这是本机唯一无法代替用户完成的环节，且它是前面所有离线结果适用性的前提**——若真实采样率不是 16000 Hz，特征频率轴整体偏移，必须按实测值重训。

---

## 6. 数据现状（本机可核实）

- 仓库内 `.wav/.pcm/.mp3/.flac` 仅有 BSP `wavplayer` 的 3 个**播放示例**文件，**无任何关键词录音**。
- `smart_hand/data/` 只有 CSV 模板，无音频。
- `grep -ril "voice|kws|pdm" smart_hand/` → 空。

**因此本阶段不产生任何真实准确率。** 训练管线用**明确标注的替代数据源**跑通并验证数值正确性，真实数据由用户按 `tools/voice_dataset/` 的录制规范采集后重跑同一脚本。任何合成数据上的指标一律标注 `synthetic` / `not_field_accuracy`，与 `titan_trust` 的 `training_metrics.json` 保持同一诚实口径（该文件已用 `field_accuracy_validated: false` / `hardware_inference_validated: false`）。

---

## 7. 待用户决策

1. **语音只读状态是否上报 MaixCAM2？** 若上报，需设计独立的、带版本号与 CRC 的固定字段消息（任务书 §4-D 要求），且不得复用舵机命令或改动现有帧语义。当前无 MSH 终端，不上报则真机上完全看不到语音状态。
2. **是否接受改变 `board.h:20 RA_SRAM_SIZE`？** 若坚持工作区走堆，必须先确认 0x22080000 以上为可用连续 SRAM；否则走静态分配（推荐，有厂商例程先例）。
3. **首轮真机验证前是否先统一固件版本？** 见 §1.2(A)，当前"已刷写"说法不可复核。
