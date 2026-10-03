# Titan AITRUST 端侧 AI 遥测上报 —— 交付报告

日期：2026-09-23（18:30 修订版）
交付人：执行 agent（DeepSeek 会话）
裁决人：Codex / 用户
对应任务书：`TITAN_TRUST_DUAL_MODEL_TASKS_2026-09-23.md`（"发给 DeepSeek 的任务"一节）

> **未刷写。** 未接调试器、未烧写、未接通舵机 6 V 驱动板、未把语音或 AI 分类接到任何机械动作。

> **修订说明**：本文件 18:12 版之后有三处实质更新 —— ①§2.3 的待裁决项**已裁决为 (A)**；
> ②补上了**完备性批评**（§5.5）：它发现驱动层字段映射零保护等 5 条四个审查者都漏掉的问题，我已全部处理；
> ③修掉了源码里一句**说得过满的注释**（"遥测写入绝不会延迟 ACK"），改为明确要求真机测 ACK 延迟（§3.2）。
> **`hex` 哈希未变**（`4248FEC2…`），因为最后一轮只改了注释。

---

## 0. 一句话

把**已经存在**的 TitanTrust-Tiny 三分类结果，从只写 `rt_kprintf`（而 Titan 控制台是 `null`，输出被丢弃、不可观测）
改为按**冻结的** `AITRUST` 只读帧上报。纯编码策略放进本来就宿主可测的 `smart_hand_status_telemetry` 模块，
胶水留在 `smart_hand_uart.c` —— **没有新建任何固件源文件**（避开 `subdir.mk` 三清单陷阱与同步清单漏项）。

证据：**C 层 9/9 + 胶水层 12/12 变异体全部被抓/被拒**、**112 个宿主测试全绿**、**真机构建 exit 0**、
`data` 逐字节不变、`bss` +24 B（堆 −24 B）、**峰值栈不增加**（实测调用链 488 B < 既有 536 B）、
仓库与真机工程源码 3 文件全 MATCH、**并且用改动前源码重建出的 hex 精确等于上一轮候选 `B7780848`**（§5.3）。

> **最终候选（语音路径已按用户指令禁用）**：`Debug/rtthread.hex`
> **`C0A02E4C7F9C505ED9EA340ED05460ED343A29D764047F9F5CE99D776016D6CA`（358,808 B）** ——
> `VOICE_APP_ENABLE=0`，`__rt_init_voice_app_titan_init` 已从 MAP 中完全消失，堆 +299 KB。
> 详见 **§0.5**。这是本报告唯一的"待烧写"产物。

> **⚠️ "112 项全绿"的口径**：那 112 项是 §4.1/§4.2/§4.4 列出的**精选子集**（1 个 C 程序 + 12 个 unittest 模块）。
> 它**不等于** `host/run_all_checks.ps1` 全绿——该脚本 [1/8] 步当前仍是**红的**（`test_rehab_imitation`
> 6 项**既有**失败，与本批无关，且它 `throw` 后本批要跑的三步根本执行不到）。
> 详见 §4.4 的两条注。**不要把这两个口径混为一谈。**

**两轮独立对抗式审查合计提出 24 条**：第一轮 4 个维度审查者 19 条（12 条获裁决：4 成立 / 8 被驳倒），
第二轮的**完备性批评**又补了 5 条四个审查者都漏掉的问题。**成立的 9 条我已全部处理**，
其中 3 条是测试/闸门的真缺口（已修），1 条是头文件错误论证（已修），1 条是"待裁决项"（**已裁决为 A**）。

---

## 0.5 语音路径已禁用 —— **本批最终候选**

**指令（用户，2026-09-23）**：把 Titan 工程配置里的 `VOICE_APP_ENABLE` 设为 **0**，保留语音源码但不启动
有遗留问题的语音线程，重新构建 AITRUST 候选固件；交付新 HEX 哈希及 MAP 中语音自动初始化已消失的证据。

**改了什么**

| 位置 | 改动 |
|---|---|
| `D:\Micu\RTTWorkspace\titan_uart_test\Debug\src\subdir.mk`（`src/%.o` 规则） | `-DVOICE_APP_ENABLE=1` → **`-DVOICE_APP_ENABLE=0`**。这是全工程**唯一**的设置点（仓库侧 `voice_app_titan.h` 的 `#ifndef` 默认本就是 0） |
| `smart_hand/titan_rtthread/voice_app_titan.c` | 新增 `#include <stddef.h>`（放在开关**之外**）—— 见下面的发现 |
| 构建 | 必须 **`touch` 那 7 个语音源文件**强制重编译（本项目已知陷阱：改编译选项**不会**触发重编译，§5.6） |

**语音源码全部保留、一个都没删**：`voice_*.c/.h` 15 个文件仍在工程里、仍参与编译，只是不再有调用者。

### 过程中发现一个真缺陷：`VOICE_APP_ENABLE=0` 这条路径**从未被 ARM 编译过**

第一次用 `=0` 构建就直接报错：

```
../src/voice_app_titan.c:452:22: error: 'NULL' undeclared (first use in this function)
```

原因：`NULL` 只由 `#include <string.h>` 提供，而那个 include 位于 `#if VOICE_APP_ENABLE` **内部**；
`#else` 分支里的 `voice_app_status(NULL, out)` 因此无人声明 `NULL`。

**为什么宿主测试没抓到**：`tests/test_voice_app_titan_c.c` 里那条 `#if !VOICE_APP_ENABLE` 用例
（13 checks）编译时，**测试文件自己的 include 恰好把 `NULL` 带了进来**，所以宿主侧一路全绿。
这是"宿主测试通过 ≠ 真机构建通过"的又一个实例。

**修法（最小）**：把 `#include <stddef.h>` 移到 `#if` 之外，并在注释里记下原因。修后
`make all` **退出码 0、0 告警 0 错误**。宿主语音测试 32 项仍全绿（含 `=0` 那条路径）。

### 证据（用户点名要的）

| 检查 | 语音开启 `4248FEC2` | **关闭后 `C0A02E4C`** |
|---|---|---|
| `__rt_init_voice_app_titan_init` | **在**（`rtthread.map:5716`，**初始化表内**、有真实地址） | **完全不存在**（grep 零命中） |
| `voice_app_thread_entry` | 在 `.text` | 仅在 **`Discarded input sections`** 内（地址 `0x0`） |
| 语音深层符号（kws / features / audio，共 11 处） | 在 | 全部落进 `Discarded input sections`（地址 `0x0`） |
| ELF 字符串 `v_kws`（语音线程名） | 有 | **0** |
| ELF 字符串 `voice: passive integration`（语音启动日志） | 有 | **0** |
| **`AITRUST` 帧类型字符串** | 有 | **仍有（1）** |
| `smart_hand_aitrust_*` / `send_aitrust`（MAP，真实地址） | 在 | **仍在**（`0x0200456a` 等） |
| `__rt_init_smart_hand_comm_init`（初始化表） | 在 | **仍在**（`0x0200017c`） |

`Discarded input sections` 段起始于 `rtthread.map:136`，`Memory Configuration` 在 `:5533` ——
上表所有"地址 `0x0`"的语音符号都在**被回收段内**，不在镜像布局里。也就是说
**整条语音链路（audio + features + kws + model + app）都被 `--gc-sections` 回收了，不只是线程**。

### 体积与堆账

| 项 | 语音开启 `4248FEC2` | **关闭 `C0A02E4C`** | 变化 |
|---|---|---|---|
| `hex` 大小 | 447,393 | **358,808** | **−88,585** |
| `text` | 157,992 | **126,500** | −31,492 |
| `data` | 1,024 | **1,024** | **不变** |
| `bss` | 436,240 | **137,236** | **−299,004** |
| 堆（`0x22080000 − __RAM_segment_used_end__`） | 87,020 | **386,024** | **+299,004** |

`__RAM_segment_used_end__` 由 `0x2206AC14` 降至 **`0x22021C18`**（−299,004，与 bss 减量逐字节吻合）。
即**语音路径此前吃掉了约 299 KB 的 `.bss` 与 31 KB 的 `.text`**，现在全部归还给堆。

> 与交接文档 §5.13 记录的"集成前堆 386,060 B"相比，本轮是 **386,024 B，低 36 B**：
> 其中 24 B 是本次 AITRUST 新增静态量（§5.1），**剩余约 12 B 我没有逐项归因**（疑为对齐），如实记录。

### ⚠️ 一个必须提醒的可复现性风险

`Debug/src/subdir.mk` 是 **`genmakebuilder` 自动生成物**——**在 RT-Thread Studio 里刷新工程会被覆盖**，
`-DVOICE_APP_ENABLE=0` 会静默变回 1 或消失。烧写前请以本文档的 `hex` 哈希为准；
Studio 刷新后请**重新核对 MAP 里 `__rt_init_voice_app_titan_init` 是否确实不存在**（§0.5 的表）。

---

## 1. 冻结接口的逐字段实现对照

| 冻结项 | 实现 | 线上证据（可复跑） |
|---|---|---|
| 帧类型 `AITRUST` | `send_message("AITRUST", ...)` | 字面量 `$AITRUST,0,1,1,0,250*0497` |
| **4 个 uint32，顺序** `version, ready, class_id, vision_age_ms` | `smart_hand_aitrust_pack()` | 同上；最坏 `$AITRUST,65535,1,1,2,4294967295*574D` |
| `version=1` | `SH_AITRUST_VERSION 1u` | `args[0] == 1` |
| `class_id`：0=可信 / 1=存疑 / 2=异常 | `titan_trust_class_t` **直通**；越界 clamp 到 2 | **已裁决 (A)**：`ready=0` 时该字段只作**原始模型值**传输，接收方一律显示「未就绪」，见 §2.3 |
| `ready=0` 时类别无意义 | 文档化 + 接收侧以 `ready` 为唯一门 | §2.3 |
| 沿用 `$TYPE,SEQ,ARGS*CRC16\r\n` | 复用既有 `shp_encode()`，协议层零改动 | CRC 由**独立实现**（Python）复核一致 |
| 16 位序号 | 复用 `smart_hand_protocol.h` 的 `uint16_t sequence` | `$AITRUST,65535,...` 断言 |
| **128 字节上限** | 最坏情况 **38 字节** | `assert(length < SHP_MAX_FRAME_SIZE)` + 整帧硬字面量 |
| **最多每 500 ms 一帧** | `smart_hand_aitrust_due()`，`SH_AITRUST_PERIOD_MS 500` | 断言 499/500 ms 边界 + **回绕**；循环 50 ms 唤醒 → 实际 500–550 ms |
| **不用 ACK** | 单向；写失败只计数不重试 | §3.2 |
| **不参与请求重试** | 无重试、无 pending、无状态机 | §3.2 |
| **不改 STATUS v1 / SIGNSTAT / TRAINSTAT** | 三者代码路径**零改动** | 整帧字面量钉住 `$STATUS,3,1,11,7,1,0,2,1,255*D0A0` |

**为什么没有把 `AITRUST` 加进 Titan 自己的解析器**：它是 Titan → MaixCAM2 单向只读帧，Titan 从不接收。
若加进 `parse_type()` 而不加对应 `case`，帧会落到 `handle_message()` 的 `default` 分支发
`ACK=UNSUPPORTED_TYPE` —— 那就**违反"不用 ACK"**，而且那个 ACK 会带着 `AITRUST` 的序号，可能在对端被误配到
某个 pending 请求上。

> **但这条有个代价（审查者指出，我复核成立）**：收到未知类型时 `parse_complete_frame` 返回 -1，
> rx 线程会 `++g_stats.invalid_frames` **并调用 `titan_trust_runtime_note_invalid()`** ——
> 后者喂的正是模型特征 `features[6]`。**任何把 Titan 自己的字节回显回来的接法，会让 Titan 把自家遥测
> 当成非法帧，并扰动自己的分类输入**，同时抬高既有的 `invalid_frames == 0` 验收判据。
> 无安全后果（分类不接门控），但**验收时不要挂回环探针**，见 §9 第 1 条。

---

## 2. 问题一（`ready=0` 与"无有效视觉帧"）的处理与证据

### 2.1 `ready` 是**合取**，这是必须的而非防御性的

`titan_trust_runtime_evaluate()` 在视觉候选过期后**不会**把 `ready` 清零：`have_last` 与 `valid_samples`
都不清零（`titan_trust_runtime.c:114-125`），而 `smart_hand_vision_state_expire()` 只清自己的
`have_vision`/`last_vision_ms`（`smart_hand_vision_state.c:12-21`）。

所以只报 `model_ready` 会**对着已经过期的视觉广告"就绪"**——那正是必须读作"未就绪"的情形。实现为：

```c
ready = (in->model_ready != 0u && in->have_vision != 0u) ? 1u : 0u;
```

**合取的两半各自被独立固定**：`(model_ready=1, have_vision=0)` 钉住 `have_vision`；
`(model_ready=0, have_vision=1)` 钉住 `model_ready`。两者缺一，对应变异体就会逃逸（§4.3 的 M1 与 M8）。

### 2.2 `vision_age_ms` 的缺省与饱和策略（任务书要求写进交付说明）

语义：**仅是 Titan 最近一次真正收到的 VISION 载荷的年龄**，不是端到端延迟，也不代表任何准确率。

| 情形 | 取值 | 理由 |
|---|---|---|
| **从未收到过** VISION 载荷 | `SH_AITRUST_AGE_UNKNOWN = 0xFFFFFFFF` | 没有年龄可报。用 `0` 会被读成"刚刚到达"→ 可能被渲染成"当前"，**是危险方向**；故向上饱和 |
| 收到过，年龄 > `SH_AITRUST_AGE_SATURATE_MS = 60000` | 饱和到 `60000` | 有界，且让页面有确定的"很旧"值 |
| 时钟非单调（`now < last`） | 无符号回绕成大值 → 被上面同一条 clamp 吸收 → `60000` | **不会**回绕成一个小而"更新鲜"的数 |

时间戳由 `smart_hand_uart.c` 自己保存（`g_vision_seen` / `g_vision_last_seen_ms`），**不能**用
`g_vision_state.last_vision_ms`：后者在候选过期时被清零，年龄会从零重新开始。

> 审查者曾主张这个哨兵是"单方面引入的协议值"，**被独立验证者驳倒**：冻结任务书**明文要求**
> 实现方给出"明确的缺省与饱和策略，写进交付说明"；而"超过 1500 ms 显示已过期"约束的是
> **网页本机接收计时**，不是这个字段的上界（§5.4）。

### 2.3 `ready=0` 时 `class_id` 的取值 —— **已裁决：选 (A)，保留现有协议** ✅

**裁决内容（用户，2026-09-23）**：

> 选 A，保留现有协议。`ready=0` 时 `class_id` **只作为原始模型值传输**，接收方**一律显示「未就绪」**；
> 即使是 `ready=0, class_id=0`，也**绝不能显示绿色「可信」**。
> 已把这条明确写入共用任务书 `TITAN_TRUST_DUAL_MODEL_TASKS_2026-09-23.md`，**Gemini 须用该反例测试页面**。

**这意味着我的实现不需要改动**：直通模型值正是 (A)，也正是当前代码与测试所固化的行为。
`ready` 是唯一门，由接收侧严格执行。

**这条风险的完整论证（供对端与验收参考）**：

- **它确实可达**：连喂 ≥3 帧 VISION 使模型判 `TRUSTED` → 停发 VISION 满 750 ms → `have_vision` 被清而
  `model_ready` 仍为 1 → 下一个 500 ms 周期发出 **`$AITRUST,7,1,0,0,2000*45BF`**，即
  `version=1, ready=0, class_id=0, age=2000`。**三个互不通信的验证者各自用真实模型权重复算，全部确认为真。**
- **可落绿的窗口经实测收窄**：验证者按 `titan_trust_model.c` 的真实权重复算，`TRUSTED` 只延伸到
  **age ≈ 800–945 ms**，之后翻成 `UNCERTAIN(1)`；而视觉在 age ≥ 750 ms 过期、`AITRUST` 每 500 ms 才尝试一次。
  所以**可落绿的只有过期后约 750–945 ms 这个窄带**（且要求该窗近乎零运动）。
  窗口比最初声称的小，但**确实可达，方向也正是最坏的那个（绿）**。
- **为什么当初不自行钳到 `ANOMALOUS`**：那会在线上放一个**并非模型输出**的类别值（伪造数据），
  且与"`ready=0` 时类别无意义"的契约表述相冲突。裁决 (A) 确认了这个判断。
- **接收侧的硬要求**：`ready=0`、视觉过期、链路离线三种情况下颜色**都不得为绿**；
  且必须有 `ready=0 且 class_id=0` 的**反例测试**（用户已写入共用任务书）。

> 验证者的附带观察，值得对端记下：在过期这一段，分类**几乎只由 `features[8] = age` 决定**，`age ≥ 2000` 后饱和。
> 即 `class_id` 在"无当前视觉"时信息量很低——这反过来支持"该字段在 `ready=0` 时不应被赋予含义"。

---

## 3. 非阻塞与安全边界

### 3.1 调用点收敛性（grep 实证）

- `send_aitrust()` 全工程**唯一调用点**：`smart_hand_uart.c` 的 `rx_thread_entry` 50 ms 循环。
- 所有 `smart_hand_aitrust_*` 调用只在 `send_aitrust()` 内部与启动初始化。
- 我新增的 `send_aitrust()` 区间内**没有**任何 `servo_*` / `safety_gate` / 训练入口调用。
- **未接入动作授权或自动开始逻辑**：`g_titan_trust_result` 只被**读**。
- **无数据竞争**：`g_titan_trust_result` 的唯一其他写入者是 `sh_status()`，而它在**本固件里不可达**
  （`MSH_CMD_EXPORT` 展开为空、`rtconfig.h` 无 `RT_USING_FINSH`；独立验证者另证 `msh.o`/`finsh.o`/`shell.o`
  的 `.text` 全为 `0x0`、`sh_status` 的 544 字节被 GC 丢弃）。所有可达写入者都在同一个 rx 线程上。
  **若将来启用 MSH，这条竞争就会成立**，届时最便宜的修法是让 `send_aitrust` 用局部结果对象。

### 3.2 写失败不阻塞链路 —— **以及一句被改正的过满注释**

- `note_attempt()` 在**写之前**记账，且**成功与失败都记**，所以 500 ms 是**尝试**的下限：
  一次失败不会在下一个 50 ms 唤醒时重试。
- 失败只计数：`send_message()` 既有的 `g_stats.tx_failures`，加上本模块自己的 `failed_frames`。
- **序号只在真正发出的帧上推进**，因此对端看到的序号是连续的，出现缺口就是真丢帧。

> **⚠️ 已改正的过满表述**：源码注释原写"a busy UART can **never** delay an ACK, a STATUS or the motion link"。
> 用户指出这说得过满，**认定正确**：`send_aitrust` 跑在 `sh_uart` 线程上、走**同一条轮询 TX**
> （`config.tx_bufsz = 0`），38 字节帧在 115200 下**确实要占用线上约 3.3 ms**，这段时间 ACK/STATUS 用不了。
> 现已改为分两段写清楚：**保证的是**无 ACK／无重试／无队列／每 500 ms 最多尝试一次；
> **不保证、必须真机测的是**该帧带来的 ACK 延迟。头文件里对应的那句也一并改了。
> 已列入 §9 验收清单第 11 条。

> **另一条遗留（审查者提出，我采纳，未改）**：`AITRUST` 写失败与 ACK/STATUS 写失败**共用同一个
> `tx_failures`**，而既有验收文档把"`tx_fail` 稳定为 0"当作 ACK/STATUS 链路健康判据。
> 本次改动**静默改变了该计数的语义**。因 `sh_status` 不可达，当前**无实际影响**；若将来启用 MSH 需拆分。

### 3.3 栈：峰值**不因本次改动增加**（`-fstack-usage` 实测）

| 调用链 | 峰值 |
|---|---|
| 既有最深（VISION 路径）：`rx_thread_entry`(208) → `handle_message`(88) → `update_titan_trust`(32) → `titan_trust_runtime_evaluate`(64) → `titan_trust_predict`(144) | **536 B** |
| **本次新增**：`rx_thread_entry`(208) → `send_aitrust`(40) → 同上尾部 | **488 B** |

新链路在每一层都不比既有链路深（`send_aitrust` 40 < `handle_message` 88），故线程栈（2048 B）的
**峰值需求不变**。未覆盖：`rt_device_write` 之下的 RT-Thread 串口/FSP 层帧，以及**真机栈水位**仍未测量。

---

## 4. 测试与变异

### 4.1 策略层：宿主 C 测试（`tests/test_smart_hand_status_telemetry_c.c`）

沿用该文件家族既有习惯（纯 `assert`），**未重构驱动**。

```
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"     # ← 注意是仓库上一级
cd smart_hand
gcc -std=c99 -Wall -Wextra -Werror -Ititan_rtthread \
    tests/test_smart_hand_status_telemetry_c.c \
    titan_rtthread/smart_hand_status_telemetry.c \
    titan_rtthread/smart_hand_protocol.c \
    -o tests/test_smart_hand_status_telemetry_c.exe     # 退出码 0
./tests/test_smart_hand_status_telemetry_c.exe          # 退出码 0
→ smart_hand_status_telemetry C tests passed (STATUS v1 + AITRUST v1)
```

断言 **77** 条 = 既有 **23** + 新增 **54**（`grep -c 'assert('`）。任务书要求 3 的七项覆盖：

| 要求 | 覆盖它的断言 |
|---|---|
| 帧参数 | `args[0..3]` 在 ready 场景下逐项比对 |
| CRC | 完整帧字面量（含 CRC）+ 本工程 CRC 对同一 body 复算一致 + 改一字节即不匹配 |
| 周期 | 未发过即 due；499 ms 不 due；500 ms due；失败后仍等满 500 ms；**回绕后仍正确** |
| 无视觉 | 从未收到 → `ready=0`、age = UNKNOWN |
| 视觉过期 | `model_ready=1` 但 `have_vision=0` → `ready=0`、age = 真实年龄 |
| 发送失败 | `failed_frames` 计数、**序号不推进**、下一帧仍等满周期 |
| 原有 STATUS v1 不变 | `$STATUS,3,1,11,7,1,0,2,1,255*D0A0` 整帧字面量（含 CRC） |

另含：帧长上限（最坏 38 B < 128）、`class_id` 越界 clamp、时钟回退不产生"更新鲜"的年龄、
两个指针参数的 NULL 守卫、以及 `ready` 合取**两半各自**的独立固定。

### 4.2 胶水层：源码契约测试（`tests/test_aitrust_uart_glue_contract.py`，**新增文件**）

**为什么必须新增它**：`AITRUST` 的**策略**宿主可测，但**胶水**不可 —— `smart_hand_uart.c` 依赖 RT-Thread
与串口设备，项目既有约定又禁止为测试去 stub 驱动。审查者**实测证明** `smart_hand_uart.c` 里
决定行为的若干点处于**零保护**状态：改掉它们，**其余全部测试依旧全绿**。

**修法沿用本项目自己的既有手法**：像 `tests/test_titan_uart_polling_tx_contract.py` 钉 `tx_bufsz` 那样，
从**源码文本**上钉住不变式（去注释/去字面量后按偏移断言）。只读、离线、变异体在内存里构造。

```
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"     # ← 仓库上一级
python -m unittest smart_hand.tests.test_aitrust_uart_glue_contract -v
→ Ran 23 tests ... OK     EXIT=0
```

覆盖两组不变式：

**（一）次序**（第一轮审查者发现）：闸门先于写、记账先于写、`note_sent` 受 RT_EOK 守卫、
失败路径确实到达 `note_failed`、**唯一调用点且在 rx 线程内**、启动时初始化 link 状态、
`send_aitrust` 不触碰运动/安全路径。

**（二）字段来源**（**完备性批评**发现，见 §5.5 C1）：`smart_hand_uart.c` 里那五行
`input.model_ready = g_titan_trust_result.ready;` … `input.last_vision_ms = g_vision_last_seen_ms;`
**才是决定线上 `ready`/`class_id`/`vision_age_ms` 的地方**（packer 只是透传），
而它们**一个字都没被断言过**。现在逐个钉死来源，并额外要求：输入结构体先清零、
任何字段的右值都不得是**常量**（硬编码即静默改写冻结字段）。

### 4.3 变异测试（机械证明，不是自述）

变异只打在**源码副本**上（仓库树不被写入）。

**C 层（策略）—— 9 个，全部被抓：**

| 变异体 | 还原的缺陷 | 结果 |
|---|---|---|
| M1 | `ready` 只取 `model_ready`，忽略视觉是否新鲜 | **CAUGHT** |
| M2 | 从未收到视觉时不留 UNKNOWN 分支 | **CAUGHT** |
| M3 | 去掉年龄饱和 | **CAUGHT** |
| M4 | `due()` 恒真 | **CAUGHT** |
| M5 | 去掉 `class_id` clamp | **CAUGHT** |
| M6 | 写失败也推进序号 | **CAUGHT** |
| M7 | 改 `shp_encode` 的字段分隔（STATUS v1 线上不再逐字节相同） | **CAUGHT** |
| M8 | `ready` 丢掉 `model_ready` 一半 | **CAUGHT**（修复前曾逃逸） |
| M9 | `due()` 改成 `now >= last + PERIOD`（回绕不安全） | **CAUGHT** |
| M10 | 去掉 `args == NULL` 守卫 | **CAUGHT**（`rc=0xC0000005` 访问违例） |

**胶水层 —— 12 个，全部被拒：** 记账挪到写之后 / 删掉闸门 / 闸门挪到写之后 / 去掉 RT_EOK 守卫 /
增加第二个调用点 / 在 sender 内触碰安全门 / **五个字段各自硬编码** / **去掉输入清零**。

#### M8 与 5 个字段变异体：三处由审查发现、修复前**确实逃逸**的缺口（均已修）

每一处都用"同一变异体跑修复前后两版"的方式留下了硬证据：

| 缺口 | 修复前 | 修复后 |
|---|---|---|
| `ready` 丢掉 `model_ready`（M8） | `SURVIVED (rc=0)` | `CAUGHT (rc=3)` |
| **驱动层 5 个字段硬编码**（完备性批评 C1） | **`5/5 SURVIVED`** | **`5/5 CAUGHT`** |
| 驱动层去掉输入清零 | `SURVIVED` | `CAUGHT` |

这正是本项目"变异测试是惯例"的价值：没有它，这些缺口会以"有测试"的样子留下来。

### 4.4 相关宿主测试全套

```
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"     # ← 仓库上一级
python -m unittest smart_hand.tests.test_aitrust_uart_glue_contract \
    smart_hand.tests.test_titan_linkage_check smart_hand.tests.test_protocol_status_proposal \
    smart_hand.tests.test_telemetry_runtime smart_hand.tests.test_telemetry_schema \
    smart_hand.tests.test_voice_app smart_hand.tests.test_voice_audio \
    smart_hand.tests.test_voice_audio_titan smart_hand.tests.test_voice_memory_budget \
    smart_hand.tests.test_servo_group_recovery smart_hand.tests.test_run_one_cycle_d2 \
    smart_hand.tests.test_drv_usart_v2
→ Ran 112 tests ... OK     EXIT=0
```

> **工作目录注意（完备性批评 C4，已修）**：上面两条 `python -m unittest smart_hand.tests.*` 必须在
> **仓库的上一级** `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网` 执行；而 §4.1 的 `gcc` 行在
> `smart_hand/` 下执行。本报告 18:12 版把两种 cwd 混在一起、按文中 cwd 复跑会得到
> `FAILED (errors=1)`。现已逐条标明 cwd。**上一版此处不可复现，是我的失误。**

> **另注（完备性批评 C5）**：`host/run_all_checks.ps1` 的 **[1/8] 步当前是红的**，
> 原因是 `test_rehab_imitation` 有 6 项**既有**失败（与 `maixcam2/rehab_imitation.py`，Aug 22 的代码，
> 与本批次无任何耦合）。脚本 `throw` 后**后面 7 步全部不执行**，因此那个入口**跑不到**本批的 C 测试、
> 胶水契约测试与同步检查。**验收请用上面 §4.1/§4.2/§4.4 的命令**，不要用 `run_all_checks.ps1` 当判据，
> 否则会把既有红灯误记成 AITRUST 回归。

---

## 5. 构建与产物

```
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

| 项 | 结果 |
|---|---|
| `make all` 退出码 | **0** |
| 编译告警 | **1 条，且为既有**：`smart_hand_uart.c:874: 'sh_status' defined but not used` |
| 编译错误 | 无 |

> **告警基线的证明**：把改动前的 `smart_hand_uart.c` 用**完全相同**的 ARM 参数单独编译，同样报该告警。
> 该行与 `MSH_CMD_EXPORT` 我都没碰过，故它是**本次改动之前就存在**的。

### 5.1 产物（语音启用版 `4248FEC2` —— **已被 §0.5 的 `C0A02E4C` 取代，仅作对照保留**）

> 下表是**语音仍启用**时的 AITRUST 候选。用户随后指令禁用语音路径，最终候选见 **§0.5**。
> 保留本节是因为它是 §0.5 体积/堆对比的基线，也是用户先前核对过的那一份。

| 项 | 基线（语音批次候选） | **本轮** |
|---|---|---|
| `Debug/rtthread.hex` 大小 | 445,442 | **447,393** |
| `Debug/rtthread.hex` SHA-256 | `B7780848B4274ECAACA51164FE484B348899690CC5B0EE0A4D9C4A4B7C2934FB` | **`4248FEC2C8D352E1180BEFD50D81750E218921C23AC88FBACAF44DCB1470BF85`** |
| `Debug/rtthread.elf` 大小 / SHA-256 | 2,768,048 / `E14F3C9A…EF3B1` | **2,772,064 / `8067AED874C2F21756771DDD71FF4B7A58085177E07F87BDEDB9C5BE271D7260`** |
| `Debug/rtthread.map` 大小 / SHA-256 | 1,049,384 / `CEF5FAF2…4A92078` | **1,052,112 / `9427ECE16158B81EF7BCA3971AD64DFDEE08BB6DA475FCDD85926A6364F3B904`** |
| `text` | 157,296 | **157,992（+696）** |
| `data` | 1,024 | **1,024（不变）** |
| `bss` | 436,216 | **436,240（+24）** |
| 产物时间 | — | 2026-09-23 18:20:41 |

**内存账**：`__RAM_segment_used_end__` 由 `0x2206ABFC` 变为 **`0x2206AC14`**（+0x18 = 24 B），
正好等于新增静态量（`g_aitrust_link` 16 B + `g_vision_seen`/`g_vision_last_seen_ms` 8 B）。
故 **堆 87,044 → 87,020 B（−24 B，−0.028%）**。`board.h` 的 `RA_SRAM_SIZE` 与 `fsp.ld` **未动**。

> **⚠️ 别用 ELF/map 哈希判断"代码变没变"——本轮我自己验证了两次这条告诫。**
> 最后两轮改动都**只动注释**（改正头文件错误论证、改正过满的 ACK 表述），结果是：
> `rtthread.hex` **SHA-256 完全不变**（`4248FEC2…`）、`text`/`data`/`bss` 全不变，
> 但 ELF 与 map 的哈希变了（`-g -gdwarf-2` 的行号表随注释增删位移）。
> **判断"代码是否变了"看 `hex` 与 `text`，不要看 ELF/map 哈希。**

### 5.2 集成未静默失效（两道闸门，均已加固）

- **map 核对**：`smart_hand_aitrust_pack` / `_vision_age_ms` / `_due` / `_link_init` /
  `_note_attempt` / `_note_sent` / `_note_failed` / `send_aitrust` / `smart_hand_status_pack`
  **全部存在于 `.text`**；`__rt_init_smart_hand_comm_init` **仍在初始化表**中。
- **闸门加固（完备性批评 C3）**：`host/titan_linkage_check.py` 原来**完全不含** AITRUST 符号，
  且 `smart_hand_status_telemetry.c` 不在它的 staleness 源码列表里——即"telemetry.c 被静默漏编译"
  时该检查**照样全绿**。现已把上述 9 个符号加进 `REQUIRED_FUNCTION_GROUPS`，并把 telemetry 的
  `.c`（我加）与 `.h`（**用户在其上补加**，见 §8.1）都加进 `default_studio_sources`。实测：9 个符号确实都在 map 里（非空断言），
  **故意加一个不存在的符号会立刻报 missing**，且**合成一个比 MAP 新的源文件会让 `map_is_stale` 返回 True**
  （证明闸门不是空的）。

**备份**：上一轮候选三件套存 `outputs/Titan_AITRUST_Telemetry_2026-09-23/candidate_b7780848/`；
整片回退备份 `pre_voice_flash.bin`（`65EF0A46…`）**仍在原位，未动**。

### 5.3 仓库 ↔ 真机工程一致性（含**追溯证明**）

部署前我在一份**手工清单**上比对，结论是无差异；**但完备性批评 C2 指出这份清单不是工程的那道闸门**：
`host/check_titan_sync.ps1` 的 `$fileNames`（38 条）**本来不含 `smart_hand_status_telemetry.c/.h`**，
而这两个文件正是我改并部署的。也就是说：**"工具报 MATCH"这件事当时覆盖不到它们**，
而我 `cp` 覆盖工程侧副本之前**没有先比对这两个文件**——若它们曾分叉，我会**静默覆盖**。这是流程缺口。

**我做了追溯证明来回答"到底有没有静默覆盖"**：

```
用【改动前】源码（uart.c 由本次 5 处编辑反向还原；telemetry.c/.h 取 git HEAD，已验证相对 HEAD 是纯新增 123/0、140/0）
重新部署进工程树并 make all：

  产出 hex = b7780848b4274ecaaca51164fe484b348899690cc5b0ee0a4d9c4a4b7c2934fb
  上一轮候选 = b7780848b4274ecaaca51164fe484b348899690cc5b0ee0a4d9c4a4b7c2934fb
  → 逐字符相同
```

**这证明改动前的两棵树在代码层面是等价的**（注释差异会被编译器丢弃，代码差异必然改变 hex），
所以**没有发生静默覆盖**。实验后已还原工程树并重建，`hex` 精确回到 `4248FEC2…`。

**闸门已加固**：把 `smart_hand_status_telemetry.c/.h` 加进 `check_titan_sync.ps1` 的清单
（现 40 条），此后该类分叉会被工具挡下。

**当前状态**（部署后，仓库 → 工程，**单向**）：

```
cb372aaa9fee5101676b35a018676384aefa58557b0af2b23ee3a548cb2e328a  smart_hand_status_telemetry.h
b9ba71b09d7c459b848f16b4f7af810872defb570cee3f25dccbdfeced30c630  smart_hand_status_telemetry.c
6c28996ad6ede837da82d293ef0f1cf74a07136b70a166348284e08ffe6aede0  smart_hand_uart.c
d1606f0177455dd850dac291f34c1b5b20a4c588be9da6694aa2b7eecad5059c  voice_app_titan.c   ← §0.5 的 stddef 修正
384aa6c11d091b35cd4513190823f9fefd97edf3bd689e714e8bc8a6a01465ae  tests/test_smart_hand_status_telemetry_c.c
0d89a631d254a7b73d60a105bf33c5f3b5018a7bc4a0e13b8615b44907c6d617  tests/test_aitrust_uart_glue_contract.py
52d789f7c37c9dd48e38262896f34b6eccd2cf1245a4683d390c34ef394595eb  host/run_all_checks.ps1
72dccf42ea6660a2ba27a3a86da4f26a2cfd0eed01d2ad60a492a62dc5e423d5  host/check_titan_sync.ps1
8f3e862054ab17d20fb42347346ff3e0ae7c785f2f2a423a4b277739385bb0ed  host/titan_linkage_check.py   ← 我改的版本
7a036f79eca72c2a3837f7a52702e04532d48221838a2442b319f06cd7b2e052  host/titan_linkage_check.py   ← **当前**（含用户补的 .h，见 §8.1）
```

---

## 5.4 第一轮：4 个维度的对抗式审查

**方法**：4 个互不通信的审查 agent 各负责一个维度（①冻结契约逐字段、②安全边界、③测试充分性、
④嵌入式/C 正确性），每条发现再交给**独立怀疑者**证伪（默认驳回，读了源码确认才成立）。全程只读。

**结果：19 条原始发现 → 12 条获得对抗裁决 → 4 条成立、8 条被驳倒**
（另有 1 条裁决返回格式损坏无法采信；剩下 7 条从未获得裁决，见"局限"）。

### 成立的四条

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| 1 | medium | `ready=0` 时线上 `class_id` 仍可能是 `0`（可信），且头文件的 fail-closed 承诺在该支**不成立** | 已列为待裁决项 → **用户裁决 (A)**（§2.3）；错误论证已改正 |
| 2 | high | `ready` 合取里的 `model_ready` **完全没被测试固定**；删掉它测试照样全过 | **已修** + 变异实验证明（§4.3 M8） |
| 3 | medium | `AITRUST` 的 **500 ms 闸门与写失败次序**零保护 | **已修**：新增源码契约测试（§4.2） |
| 4 | medium | 头文件里"`ready=0` 时线上是 fail-closed 的 `ANOMALOUS` 默认值"这段**论证是错的** | **已改正**（纯注释，`hex` 逐字节不变） |

### 被驳倒的条目（8 条裁决）

`vision_age_ms` 哨兵"单方面引入协议值" / 哨兵"无测试固定" / `class_id` 1-2 映射"无测试固定" /
`model_ready` 缺口（验证者在我**已修之后**复核）/ `candidate_b7780848` 会被误当验收对象 /
AITRUST 计数是"死计数器" / 128 字节上限与序号位宽等告警 / 另一条重复裁决。
驳回理由摘要见诸验证意见：大多是**事实性误判**（例如哨兵其实被最坏帧硬字面量钉住，
改哨兵即变红），或**对未启用构建配置的假设性推断**。

### 我自己驳倒的一条（审查者提出，独立验证者也独立驳倒）

**"`g_titan_trust_result` 存在撕裂读，可造出假绿帧"** ——不成立：MSH/FINSH **整个没被链接进固件**
（见 §3.1），`sh_status()` 没有调用者，唯一外部写入者不存在。若将来启用 MSH，该竞争才成立。

### 审查本身的局限（如实说明）

**我的审查工作流把"每条发现都送去证伪"写成了"每个维度只送前 3 条"**（`res.findings.slice(0, 3)`）。
所以 **19 条里有 7 条从未获得对抗裁决**。我另行单独复核了两条（回环风险、
`tx_failures` 语义被静默改变——两条都成立，已分别列入 §1 与 §3.2），其余以行号/风格类为主，
**没有**逐一实证。这是本批次审查的真实缺口，不应被读成"19 条都查过了"。

---

## 5.5 第二轮：完备性批评（**4 个审查者都漏掉的 5 条**）

审查工作流的最后一步是一个**完备性批评 agent**，专门问"前面漏了什么"。它找出 5 条，**我全部复核成立并处理**：

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| **C1** | **high** | **驱动层字段映射（`smart_hand_uart.c:226-230`）零保护**——它才是决定线上三个字段的地方，而 packer 只透传。批评者实测**5/5 变异体存活**；并正确指出**我的报告夸大了覆盖**（只列了闸门/记账/序号三点，给人"这一类已全覆盖"的印象） | **已修**：契约测试新增"字段来源"一组断言 + 6 个变异体；并用修复前后两版跑同一批变异体留证（**修前 5/5 存活 → 修后 5/5 被抓**）（§4.2、§4.3） |
| **C2** | medium | `check_titan_sync.ps1` 的清单**不含** `smart_hand_status_telemetry.c/.h`，而我拿这份清单当"无差异"的证据；且我在 `cp` 覆盖工程侧之前**没先比对**这两个文件 | **已修**：清单补入这两个文件（§5.3）；并做**追溯构建证明**改动前两棵树代码等价（`hex` 精确等于 `B7780848`），确认**没有静默覆盖** |
| **C3** | medium | `titan_linkage_check.py` 里**没有任何 AITRUST 符号**，也不把 `telemetry.c` 当"新"源码——telemetry.c 被静默漏编译时该闸门照样全绿；我报告 §5.2 的"全部在 .text"是**手工 grep** | **已修**：9 个符号进 `REQUIRED_FUNCTION_GROUPS`，该 .c 进源码列表；实测符号真实存在、且缺符号会变红（§5.2） |
| **C4** | low | 报告给的命令与其自述 cwd **互相矛盾**，按文中 cwd 复跑会 `FAILED (errors=1)` | **已修**：§4.1/§4.2/§4.4 逐条标明 cwd（§4.4 注） |
| **C5** | low | `run_all_checks.ps1` 的 [1/8] 步当前**是红的**（6 项既有 rehab 失败），throw 后本批的三步根本跑不到，易被误记成 AITRUST 回归 | 已在 §4.4 注明：**验收用本报告的命令，不要用该脚本当判据** |

> **C1 是这批审查里最有价值的一条。** 它没有查出"代码错了"，而是查出"**正确代码与错误代码都全绿**"——
> 这正是本项目"变异测试是惯例"要防的那类问题。它也顺带纠正了我对自己覆盖面的乐观表述。

---

## 5.6 复跑时的环境坑（本轮实际踩到）

| 现象 | 原因 / 解法 |
|---|---|
| `-include"D:/…/rtconfig_preinc.h"` 变成 `D:D:/Git/Micu/…`，报 `fatal error: Invalid argument` | **MSYS 会把紧跟 `-include` 的绝对 Windows 路径当 Unix 路径转换**。设 `export MSYS2_ARG_CONV_EXCL='*'` |
| 从临时目录编译 `smart_hand_uart.c` 报 `grip_policy.h: No such file` | 该文件靠**源文件所在目录**解析引号头文件；跨目录编译要补 `-I"<工程>/src"` |
| 前台 `sleep` 被拦 | 本环境禁止前台 sleep（改用 Monitor 的 until-loop 或 `run_in_background`） |
| `rm` 被 deny | 已知（交接文档 §5.15）。故本轮所有临时产物放在**唯一命名的新目录**下，不做删除 |
| 控制台中文乱码 | Python stdout 走 GBK 代码页。**把结果写进 UTF-8 文件再用 Read 读**，不要在 stdout 打印中文 |
| `git diff HEAD` **不能**当基线 | 工作区相对 HEAD 有约 **185 行先前未提交的改动**（实测：HEAD 657 行 / 改动前 842 行 / 改动后 927 行）。`smart_hand_uart.c` 的"改动前版本"是把本次编辑**反向还原**得到的；telemetry 两文件相对 HEAD 是**纯新增**，故可直接取 HEAD |

---

## 6. 未验证（**请勿当成已验证**）

| # | 项 | 状态 |
|---|---|---|
| 1 | **`AITRUST` 帧带来的 ACK 延迟** | **未验证，且用户已点名要真机测**（§3.2）。静态可算约 3.3 ms/帧，但"不影响 ACK/STATUS 时序"必须实测 |
| 2 | 真机上 `AITRUST` 是否真的按 ≤2 Hz 发出、页面是否按冻结要求渲染 | **未验证** |
| 3 | 真机上 `vision_age_ms` 的实际数值与 `ready` 的切换时序 | **未验证** |
| 4 | 真机栈水位 / 堆运行期水位 | **未验证**（§3.3 只给了静态帧对比） |
| 5 | 与 MaixCAM2 侧的**端到端**协议一致性 | **未验证**——Gemini 侧尚未实现接收（`maixcam2/protocol.py` 的 `MESSAGE_TYPES` 里没有 `AITRUST`） |
| 6 | `ready=0` 且 `class_id=0` 时页面**不显绿** | **未验证**——这是裁决 (A) 的关键反例，须由 Gemini 用页面测试覆盖 |
| 7 | 并发正确性 | **未验证**——宿主测试都是单线程；§3.1 的"无竞争"是**源码可达性论证** |
| 8 | `AITRUST` 写失败在现场的可观测性 | **未验证**——`sh_status` 不可达，只能靠 SWD 或"页面停止收帧" |
| 9 | ~~**上一轮遗留：语音溢出后旧样本推理路径**~~ | **已处置**（用户指令）：`VOICE_APP_ENABLE=0`，语音线程不再启动、整条链路被 gc-sections 回收，MAP 中 `__rt_init_voice_app_titan_init` 已消失（§0.5）。语音源码保留未删 |
| 10 | 10 分钟持续运行、断线/过期回退 | **未验证**——属实物验收 |

---

## 7. 任务书逐条对照（自查）

| # | 要求 | 状态 | 证据 |
|---|---|---|---|
| 1 | `ready=0` 与无有效视觉帧**按真实状态发**，不把默认 `ANOMALOUS` 冒充已验证异常 | ✅ | `ready` 为合取；无视觉/过期 → `ready=0`；直通分类值（裁决 (A) 确认） |
| 2 | `vision_age_ms` 明确的**缺省与饱和**策略，写进交付说明 | ✅ | §2.2 + 头文件 |
| 3 | 周期**不快于 500 ms** | ✅ | `due()`；断言 499/500 ms 与**回绕** |
| 4 | 写失败**只计数或记录**，不阻塞 ACK/STATUS/机械手链路 | ✅（**延迟另计，须真机测**） | §3.2；胶水契约测试 12 变异体；ACK 延迟已单列为待测项 |
| 5 | 旧协议字节与安全门不变 | ✅ | 协议层零改动；STATUS 整帧字面量钉住 |
| 6 | 不把 TitanTrust 分类接入动作授权或自动开始 | ✅ | §3.1 |
| 7 | 最小宿主测试：帧参数/CRC/周期/无视觉/视觉过期/发送失败/STATUS v1 不变 | ✅ | §4.1（54 条新断言）+ §4.2（23 项） |
| 8 | 复用现有测试习惯，**不为此重构驱动** | ✅ | 沿用既有 `assert` 风格与 `test_titan_uart_polling_tx_contract.py` 的源码契约手法 |
| 9 | 做真构建并核对新产物时间与 SHA-256 | ✅ | §5.1 |
| 10 | **不要烧写** | ✅ | 全程未烧写；用户再次确认**暂不烧写** |
| 11 | 真实工程与仓库镜像若有差异**列清楚**，不默默覆盖 | ✅ | §5.3：含**追溯构建证明**与闸门加固 |
| 12 | 简短报告：改动文件、命令与结果、固件哈希、未验证项 | ✅ | 本文件 |
| 13 | 合成训练指标只可称"自检"，不可称真实识别准确率 | ✅ | 本报告**未出现任何准确率数字** |
| 14 | 先读现有相关源码与测试 | ✅ | 全部读过 |
| 15 | 本轮**不继续折腾 PDM 语音** | ✅ | 未动任何 `voice_*` |
| 16 | 文件权限限定 `smart_hand/titan_rtthread/` 与对应 Titan 测试 | ⚠️ | 见 §8：四处越界，全部列出待裁决 |

---

## 8. 我改动了声明范围之外的**四处** —— **用户已全部接受** ✅

**裁决（用户，2026-09-23）**："这四处范围外改动我都接受：测试脚本补链接、胶水契约测试，
以及同步和链接两道闸门，都是这批遥测交付需要的验证。"

| 文件 | 改动 | 为什么必须动 |
|---|---|---|
| `smart_hand/host/run_all_checks.ps1` | 编译 C 测试的 `gcc` 行增加 `smart_hand_protocol.c`；两处标签改名 | 测试要钉**编码后的线上字节**（含 CRC），必须链接协议层；否则整套检查在这一步链接失败 |
| `smart_hand/tests/test_aitrust_uart_glue_contract.py`（**新文件**） | 胶水层次序 + 字段来源契约测试 | 审查**实测证明**这些点在 `smart_hand_uart.c` 里零保护，且无现成手法可覆盖。零成本、完全沿用本项目既有做法。**无新固件源文件、无构建系统改动** |
| `smart_hand/host/check_titan_sync.ps1` | 清单补入 `smart_hand_status_telemetry.c/.h`（38 → 40 条） | 完备性批评 C2 实测：这两个文件不在清单里，**唯一的自动化"仓库↔工程"闸门看不到它们**，分叉会静默通过 |
| `smart_hand/host/titan_linkage_check.py` | `REQUIRED_FUNCTION_GROUPS` 加 9 个 AITRUST 符号；`default_studio_sources` 加 telemetry 源码 | 完备性批评 C3 实测：该闸门完全不含 AITRUST 符号，`telemetry.c` 被静默漏编译时**照样全绿** |

### 8.1 用户在本批之上又补了一行（我复核通过）

用户自行把 `smart_hand_status_telemetry.h` 也加进了 `titan_linkage_check.py` 的新鲜度清单
（`default_studio_sources`，现为 8 项）——**这是对的**：头文件的改动同样会使 MAP 过期。

我的独立复核：

| 复核项 | 结果 |
|---|---|
| 清单是否含 `.c` 与 `.h` | **都含**（`['smart_hand_uart.c', 'smart_hand_status_telemetry.c', 'smart_hand_status_telemetry.h', …]`） |
| 新鲜度机制是否真的会拦（合成一个比 MAP 新的源文件） | `map_is_stale(...) = True` —— **闸门不是空的** |
| 真实检查 | `ok=True reason=ok stale=False` |
| 相关单测 | `Ran 7 tests … OK` |
| 该文件当前 SHA-256 | `7A036F79ECA72C2A3837F7A52702E04532D48221838A2442B319F06CD7B2E052` |

用户同时确认：30 项相关测试通过、当前 MAP 检查通过、三份 Titan 源文件与工程树一致、
**HEX 仍是 `4248FEC2…70BF85`**。

其余全部改动都在 `smart_hand/titan_rtthread/` 与对应的 Titan C 测试内。
**未动**：`smart_hand/maixcam2/`、网页、PDM/语音、舵机控制、`board.h` 的 `RA_SRAM_SIZE`、`fsp.ld`。

---

## 9. 给 Codex 的短验收清单

**驱动板保持断电**，Titan 上电，SWD **只读**取证：

1. **不要挂 UART 回环探针**：Titan 不认 `AITRUST`，回显会把自家遥测计成非法帧、并喂进模型特征 `features[6]`，
   同时抬高既有验收判据 `invalid_frames == 0`（§1 末尾）。
2. UART 抓包确认 **`AITRUST` 帧出现，且任意 1 秒内不超过 2 帧**。
3. 视觉正常喂入时：`ready=1`，`class_id ∈ {0,1,2}`，`vision_age_ms` 随视觉帧到来**回落**。
4. 停发 VISION 超过 750 ms：**`ready` 必须变 0**——这是 §2.1 的直接判据。
5. 断开视觉后 `vision_age_ms` **持续增长并封顶在 60000**，不会跳回小值。
6. **裁决 (A) 的关键反例**：在"刚过期（750–945 ms）"抓一帧，很可能看到 `ready=0 且 class_id=0`。
   与 Gemini 联调确认：那一帧在页面上**显示「未就绪」而不是绿色「可信」**。
7. 全程 **`STATUS` v1 的 8 个字段与频率不变**，`ACK` 行为不变，`SIGNSTAT`/`TRAINSTAT` 不变。
8. 全程**没有任何 AITRUST 相关的 ACK** 出现在线上。
9. 10 分钟持续运行 + 断线/重连，观察 `AITRUST` 不中断、不刷屏。
10. 与 MaixCAM2 侧联合：页面状态按冻结要求显示，**`ready=0`、过期、离线时颜色不得为绿**。
11. **新增：测 ACK 延迟**——在 `AITRUST` 开启与关闭两种配置下分别测 ACK/STATUS 的往返时延，
    确认 §3.2 所说的"每 500 ms 一次约 3.3 ms 占用"不把时序推到不可接受（用户点名要求）。
12. **新增：语音路径**——候选固件仍链接上一轮的"语音溢出后旧样本推理"路径（§6 第 9 条），
    在决定烧写前需先处理该遗留问题或明确禁用语音路径。

**任何一项失败都不进入舵机 6 V 上电测试。**

---

## 10. 一句话状态

**TitanTrust 三分类已从不可观测的 `rt_kprintf` 改为按冻结契约的只读 `AITRUST` 帧上报：纯策略并入宿主可测模块
（0 新固件文件、0 协议改动），54 条新断言 + 23 项胶水契约测试 + C 层 9/9 与胶水层 12/12 变异体全部被抓 +
112 个宿主测试全绿 + 真机构建 exit 0；`data` 逐字节不变、`bss` +24 B 已算清、峰值栈实测不增加、
`hex` 仍为 `4248FEC2…`。**

**裁决 (A) 已记录**：`ready=0` 时 `class_id` 只作原始模型值传输，接收方一律显示「未就绪」，
`ready=0 且 class_id=0` 绝不显绿；Gemini 须用该反例测页面。**本批实现无需改动。**

**两轮审查合计 24 条，成立的 9 条全部处理**：其中 **完备性批评找出的 5 条是四个审查者都漏掉的**，
最有价值的一条（C1）查出驱动层字段映射"正确代码与错误代码都全绿"——已用修复前后两版跑同一批变异体留证
（**修前 5/5 存活 → 修后 5/5 被抓**）。我已更正报告中三处自己写得不准确/不可复现的地方
（断言计数、cwd、覆盖面的乐观表述），并**改正了源码里一句说得过满的注释**（ACK 延迟，改为待真机测）。

**板子未刷写，用户已确认暂不烧写**（候选固件仍链接上一轮语音遗留路径，待 Gemini 完成接收与过期回退）；
舵机驱动板继续断电。

**范围外改动：四处已全部被用户接受**（§8）；用户另在 `titan_linkage_check.py` 上补加了 `.h` 的新鲜度检查，
我已独立复核通过（§8.1）。

---

## 11. 下一步（按用户指定的顺序）

| # | 步骤 | 负责 | 状态 |
|---|---|---|---|
| 1 | Gemini 交付 MaixCAM2 接收 + 网页「接收 / 过期回退」 | Gemini | **进行中**（本批不等它） |
| 2 | **两端联审**：Titan 与 MaixCAM2 的 `AITRUST` 端到端一致性；重点验裁决 (A) 的反例——`ready=0 且 class_id=0` 页面必须显示「未就绪」、不得显绿 | 双方 + 裁决人 | 待步骤 1 |
| 3 | ~~**处置语音遗留路径**~~ → **已完成**：`VOICE_APP_ENABLE=0`，语音线程不再启动 | Titan 侧 | ✅ **本批完成**（§0.5） |
| 4 | 真机验收：本报告 §9 的 12 条（含**新增的 ACK 延迟测量**） | Codex / 用户 | 待步骤 2 |
| 5 | 烧写（候选 = `C0A02E4C…D6CA`，358,808 B；**注意 §0.5 末尾的 subdir.mk 可复现性风险**） | 由裁决人决定 | **未开始** |

**本批（Titan 端 AITRUST 遥测 + 语音路径禁用）在我这一侧已收尾**；后续动作都依赖步骤 1（Gemini 交付）或步骤 2。
