# 交接文档：Titan AITRUST 遥测上报 + 语音路径禁用

日期：2026-09-23（21:30 版）
交付人：Claude Code 会话（本批执行 agent）
接手人：**下一个 agent（DeepSeek harness / `dsh`）**
裁决人：用户 / Codex

> **修订记录（2026-09-23 深夜 · 接手 agent = dsh / DeepSeek harness）**
> §0.1 / §0.2 / §3.1 / §3.2 / §9.3→§9.4 / §10.1 / §11-1 / §15 已按**独立复核**改写。
> 核心更正：**板子已于 20:04:05 烧写为最终候选 `c0a02e4c`，20:05 读回校验通过**；
> 原文"板子未刷写本轮候选固件"在 20:04 之后即失效。复核方法与原始证据见 §0.2、§9.4。

> **本文件自包含。** 你不需要读上一批的对话、也不需要读 `DEEPSEEK_TO_CODEX_TITAN_AITRUST_TELEMETRY_2026-09-23.md`
> 才能开始工作——那份是给裁决人看的交付报告，本文是给你的操作手册。两者冲突时**以本文件的实测数字为准**，
> 但设计理由去看那份报告。

---

## 0. 三十秒上手

### 0.1 当前最紧要的一件事

**板上已经跑着本批最终候选 `candidate_c0a02e4c`**（2026-09-23 **20:04:05** 烧写；20:05 用
`host/verify_titan_flash.py` 逐段读回，**127,524 个有效字节全部一致**）。所以本批在写代码这一侧**已经收尾**，
而且**不再卡在"等烧写"上**：

1. **真机验收**（12 条，§10.2）**现在就可以开始**——板上就是待验收的那一份固件，不用再等谁去烧；
2. **两端联审**也已具备条件：20:26 的真机日志里已经出现 MaixCAM2 侧解析出的 `AITRUST` 帧（见 §9.4）。

**所以你现在最该做的事是：先读 §0.2（板上到底是什么）、§9.4（唯一的真机观测）、§5（红线），
然后确认用户要你干哪一件**，不要自己找活干。

### 0.2 板子状态：**已刷写，且已读回校验**（原"未刷写 / 状态存疑"的结论已过期）

> **本节已于 2026-09-23 深夜由接手 agent（dsh / DeepSeek harness）独立复核并改写。**
> 原文写着"板子未刷写本轮候选固件"，并据此要求接手方向用户确认——**那条结论在 20:04:05 之后就不再成立**。

**事件时间线（全部取自本机 Codex 会话原始记录，可复核）**：

| 时间 | 事件 |
|---|---|
| 19:57:52 | 用户 → Codex：**"已断电，你来执行烧录"** |
| 20:01:09 | Codex：`pyocd commander … -c 'savemem 0x02000000 0x100000 …pre_aitrust_flash_2026-09-23.bin'` |
| **20:03:19** | `Saved 1048576 bytes` ← **§0.2 用的那个 dump 就是这一步产出的：它是"烧录前备份"。它拍到的确是当时的板子内容（= `b7780848`），但 1 分钟后就被覆盖了** |
| **20:04:05** | Codex：`pyocd flash … Debug\rtthread.hex`（该 hex 的 SHA-256 = `C0A02E4C…`） |
| 20:05:07 | `host/verify_titan_flash.py` → **127,524 个有效字节全部一致** |
| 20:26 | MaixCAM2 侧真机日志出现 `AITRUST v=1 ready=0 class=ANOMALOUS age_ms=4294967295`（见 §9.4） |

**方法（下表仍然有效，但请只把它当作"烧录前快照"）**：把 `outputs/Titan_AITRUST_Telemetry_2026-09-23/pre_aitrust_flash_2026-09-23.bin`
（1 MiB 原始 dump，2026-09-23 20:03:19，SHA-256 `BB711AC7C2014C386BC5AF35B67A984D8047912251B0BA128C9DC310C089E197`）
与四个候选的 Intel HEX **按地址**逐字节比对（0x02000000 起，脚本：见 §4.7）：

| 候选 | 覆盖字节 | 相同 | 不同 | 结论 |
|---|---|---|---|---|
| `candidate_60ad1d89`（语音，环形缓冲未修） | 158,300 | 37,671 | 120,629 | 不一致 |
| **`candidate_b7780848`（语音 + 环形缓冲修复）** | 158,316 | **158,316** | **0** | **★ 完全一致 ★** |
| `candidate_4248fec2`（语音 + AITRUST） | 159,012 | 21,765 | 137,247 | 不一致 |
| `candidate_c0a02e4c`（AITRUST + 语音禁用，**本批最终候选**） | 127,520 | 19,743 | 107,777 | 不一致 |

**结论（20:03 快照）：当时板上跑的是 `candidate_b7780848`** —— 语音批次的环形缓冲修复候选
（**有语音线程、没有 AITRUST**）。它与 14:13 那份 `pre_voice_flash.bin`（`65EF0A46…`，**无语音无 AITRUST**）
相差 149,381 字节（14.2%），说明 14:13 之后板上内容变过。

**这不是"与旧文档矛盾"，而是旧文档之后又发生了一次刷写。** 旧交接文档
（`HANDOFF_TITAN_VOICE_AND_UART_2026-09-23.md`，14:37）说"已用备份整片回退"——那描述的是 **14:2x 的状态**，
当时成立；此后板子被刷成环形缓冲修复候选 `b7780848`，20:04 又被刷成本批最终候选。
三份文档各自对自己的时刻都是对的，中间只是少了一个未被记录的事件。

**`b7780848` 的刷写者与时刻未能确认（用户表示不记得，先不追究）。** 接手 agent 已逐项排除：
Codex 会话在 13:55–19:56 **无任何烧写命令**（17:43 明确"暂不批准烧写"、19:55 明确"我没有执行烧写"）；
AITRUST 批次的 Claude 会话**全会话 `pyocd` 命中 0**；环形缓冲修复批次的会话亦无烧写命令；
RT-Thread Studio 的 `.metadata/.log` 最后写入停在 09-22，且其自带 PyOCD（2021 版）不认识 `R7KA8P1KF`。
可确定的时间窗是 **约 16:00 – 20:03，且不在任何 agent 会话内**。

**接手 agent 的独立复核**（自写脚本按地址解析 Intel HEX，不使用 `objcopy`）**与上表逐项一致**：
`b7780848` 为 158,316/158,316 完全一致，其余三个候选的"相同/不同"字节数也逐一吻合。
附带确认：四个候选目录名 = 其 hex 文件 SHA-256 的前 8 位；在**原始 .bin**（而非 ASCII 的 hex）上做
特征串搜索是有效的——`pre_voice`(14:13) 的 `voice`/`kws` 命中为 0/0，`pre_aitrust`(20:03) 为 1/1。

**所以：不要再问"板上是什么"，也不要把 20:03 那份 dump 当成当前状态。当前状态见本节时间线与 §0.1。**

### 0.3 路径速查表

| 用途 | 路径 |
|---|---|
| **仓库（唯一正式源码）** | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\smart_hand\` |
| **真机工程（部署目标，只编 `src/`）** | `D:\Micu\RTTWorkspace\titan_uart_test\` |
| 真机构建目录 | `D:\Micu\RTTWorkspace\titan_uart_test\Debug\` |
| **唯一候选产物** | `D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex` |
| ⛔ 禁止烧写 | `D:\Micu\RTTWorkspace\titan_uart_test\rtthread.hex`（工程根同名旧版，09-21） |
| 本批交付报告 | `smart_hand\docs\DEEPSEEK_TO_CODEX_TITAN_AITRUST_TELEMETRY_2026-09-23.md` |
| **本文件** | `smart_hand\docs\HANDOFF_TITAN_AITRUST_AND_VOICE_DISABLE_2026-09-23.md` |
| 证据/备份 | `outputs\Titan_AITRUST_Telemetry_2026-09-23\` |
| 旧批次证据 | `outputs\Titan_Voice_Bringup_2026-09-23\` |
| 共用任务书（协议冻结处） | `smart_hand\docs\TITAN_TRUST_DUAL_MODEL_TASKS_2026-09-23.md` |

### 0.4 最短命令集

```bash
# ① 仓库根（注意：不是 smart_hand/）
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"

# ② 宿主测试（最小可信集）
python -m unittest smart_hand.tests.test_aitrust_uart_glue_contract \
    smart_hand.tests.test_titan_linkage_check smart_hand.tests.test_telemetry_runtime \
    smart_hand.tests.test_voice_app smart_hand.tests.test_voice_audio_titan \
    smart_hand.tests.test_protocol_status_proposal smart_hand.tests.test_drv_usart_v2

# ③ C 遥测测试
cd smart_hand && gcc -std=c99 -Wall -Wextra -Werror -Ititan_rtthread \
    tests/test_smart_hand_status_telemetry_c.c \
    titan_rtthread/smart_hand_status_telemetry.c \
    titan_rtthread/smart_hand_protocol.c \
    -o tests/test_smart_hand_status_telemetry_c.exe && ./tests/test_smart_hand_status_telemetry_c.exe
cd ..

# ④ 真机构建
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

---

## 1. 这个项目是什么

**OpenSignHand**：MaixCAM2（视觉/手势）→ UART → **Titan Mini（RA8P1 单片机 + RT-Thread，实时安全门控）** → 舵机驱动的灵巧手。
用于手部康复训练与手语教学。

**Titan 承担**：UART 协议、CRC、ACK、状态机、舵机动作表、安全门控。
本批新增/涉及的是 Titan 上的**端侧 AI 咨询（advisory）**：TitanTrust-Tiny 三分类，用来评价"视觉与链路输入是否可信"。
**它不识别手语、不控制舵机、不能替代安全门控。**

### 1.1 三条铁律（违反会静默出错）

| # | 铁律 | 为什么 |
|---|---|---|
| 1 | **仓库是唯一正式源码；真机工程只编 `src/`** | CDT 编 `../src/*.c`，SConscript `Glob('./src/*.c')`。工程根的同名副本**从不参与编译**——改它"编译成功但行为完全不变"。**只做 仓库→工程 单向同步，永不反向**（反向会静默回退已审核的修复） |
| 2 | **`Debug/src/subdir.mk` 是三张平行清单**（`C_SRCS` 用 `../src/` 前缀，`OBJS`/`C_DEPS` 用 `./src/`） | 新源文件必须**同时**进三张清单，否则**静默不编译不链接、无任何报错**。它是 `genmakebuilder` 自动生成物，**在 Studio 里刷新会被覆盖** |
| 3 | **判断"代码有没有变"看 `rtthread.hex` 与 `text`，不要看 ELF/map 哈希** | 编译带 `-g -gdwarf-2`，注释增删会让行号表位移 → ELF/map 哈希变而 hex 不变。本批我实测过两次 |

### 1.2 本批改动落在哪

- **仓库**：`smart_hand/titan_rtthread/`（3 个文件改、1 个改）+ `smart_hand/tests/`（1 改 1 新增）
  + `smart_hand/host/`（3 个闸门/脚本）
- **真机工程构建配置**：`D:\Micu\RTTWorkspace\titan_uart_test\Debug\src\subdir.mk`（编译选项，§2.2）
- **语音源码一个都没删**（15 个文件仍在，仍参与编译，只是没有调用者了）

---

## 2. 本批做了什么

### 2.1 AITRUST 只读遥测帧（主体工作）

**问题**：TitanTrust 三分类的结果此前只写 `rt_kprintf`。而 **Titan 的 RT-Thread 控制台是 `null`**，
输出被丢弃 —— 也就是说这个推理**不可观测**。

**做法**：按**冻结契约**（`TITAN_TRUST_DUAL_MODEL_TASKS_2026-09-23.md`）新增 Titan → MaixCAM2 的只读帧：

```
$AITRUST,<seq>,<version=1>,<ready>,<class_id>,<vision_age_ms>*<CRC16>\r\n
```

| 字段 | 含义 |
|---|---|
| `version` | 恒为 1 |
| `ready` | **1 仅当**"模型有完整窗口" **且** "它所描述的视觉仍然新鲜"（合取，见 §7.1） |
| `class_id` | 0=可信 / 1=存疑 / 2=异常。**`ready=0` 时该字段无意义**（见 §7.2 的裁决 (A)） |
| `vision_age_ms` | **仅**是 Titan 最近一次真正收到的 VISION 载荷的年龄。不是端到端延迟，不代表任何准确率 |

**硬约束**：≤1 帧 / 500 ms、**不用 ACK**、不参与请求重试、沿用既有 `$TYPE,SEQ,ARGS*CRC16\r\n` 容器、
16 位序号、128 字节上限（本帧最坏 38 字节）。
**不得改动** `STATUS` v1 / `SIGNSTAT` / `TRAINSTAT` 的字段、频率或含义。

**实现位置**（关键：分清"策略"与"胶水"）：

| 文件 | 角色 |
|---|---|
| `smart_hand_status_telemetry.{c,h}` | **纯策略，宿主可测**：`smart_hand_aitrust_pack()`、`smart_hand_aitrust_vision_age_ms()`、`smart_hand_aitrust_due()`、`note_attempt/sent/failed()`。零 RT-Thread、零 FSP、零堆 |
| `smart_hand_uart.c` | **胶水**：`send_aitrust()`，唯一调用点在 `rx_thread_entry` 的 50 ms 循环里 |

**为什么这么分**：`smart_hand_uart.c` 依赖 RT-Thread 与串口设备，**无法宿主编译**，
项目既有约定也禁止为测试去 stub 驱动。所以能测的部分必须挤进那个纯模块。

### 2.2 语音路径禁用（用户指令）

**指令原文**：把 Titan 工程配置里的 `VOICE_APP_ENABLE` 设为 0，保留语音源码但不启动有遗留问题的语音线程。

**改动**：`D:\Micu\RTTWorkspace\titan_uart_test\Debug\src\subdir.mk` 的 `src/%.o` 规则里
`-DVOICE_APP_ENABLE=1` → **`-DVOICE_APP_ENABLE=0`**。这是**全工程唯一**的设置点
（仓库侧 `voice_app_titan.h` 的 `#ifndef` 默认本就是 0）。

**后果**：语音线程不启动，整条语音链路被 `--gc-sections` 回收。
体积：hex **447,393 → 358,808（−88,585）**、text **157,992 → 126,500**、bss **436,240 → 137,236（−299,004）**、
**堆 87,020 → 386,024（+299,004）**、`data` 不变。

> **⚠️ 可复现性风险**：`subdir.mk` 是自动生成物，**在 Studio 里刷新工程会把它改回去**。
> 烧写前以 hex 哈希为准；Studio 刷新后**重新核对 MAP 里 `__rt_init_voice_app_titan_init` 是否确实不存在**。

### 2.3 过程中修掉的真缺陷（**值得单独记住**）

| # | 缺陷 | 为什么之前没被发现 |
|---|---|---|
| 1 | **`VOICE_APP_ENABLE=0` 这条路径从未被 ARM 编译过**：`voice_app_titan.c` 的 `#else` 分支用 `NULL`，而唯一提供 `NULL` 的 `#include <string.h>` 在 `#if` **内部** → 一关就 `error: 'NULL' undeclared` | 宿主测试 `test_voice_app_titan_c.c` 里那条 `#if !VOICE_APP_ENABLE` 用例编译时，**测试文件自己的 include 恰好把 `NULL` 带了进来**。**宿主通过 ≠ 真机通过** |
| 2 | **驱动层字段映射零保护**：`smart_hand_uart.c` 里那 5 行 `input.X = ...` 才是决定线上字段的地方，却没有任何测试 | 它们在那个**不被宿主编译**的文件里。**完备性批评实测 5/5 变异体存活**（详见 §8） |
| 3 | **两个自动化闸门看不到本批改的文件**：`check_titan_sync.ps1` 的清单不含 telemetry 的 `.c/.h`；`titan_linkage_check.py` 不含任何 AITRUST 符号 | 它们各自有一套**手工维护的清单**，没人加过 |

**三条都已修**（缺陷 1 见上面 §2.2；缺陷 2、3 见 §4.5/§4.6/§12）。

---

## 3. 产物与哈希（全部实测于 2026-09-23 21:2x）

### 3.1 最终候选（**已烧写并读回校验：2026-09-23 20:04:05**）

```
路径     D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex
大小     358,808 B
SHA-256  C0A02E4C7F9C505ED9EA340ED05460ED343A29D764047F9F5CE99D776016D6CA
时间     2026-09-23 19:47:29
elf      2,678,364 B  SHA-256 2DB0C7C5D4872420A9476C5EA8E5BF2B5CF9C6E87C4CBC055C1C6747339EB259
map      1,041,651 B  SHA-256 70F94C47BA76D7C1E21540EA1E11634BE5539B878EF96B09D46485F8DE37DCDA
text 126,500 / data 1,024 / bss 137,236
__RAM_segment_used_end__ = 0x22021C18  → 堆 = 0x22080000 − 0x22021C18 = 386,024 B
```

### 3.2 历史候选（对照用，都在 outputs 里）

| 候选 | hex 大小 | hex SHA-256（前 8 位） | 特征 | 说明 |
|---|---|---|---|---|
| `candidate_60ad1d89` | 445,397 | `60AD1D89…` | 语音，**环形缓冲未修** | 语音批次首次真机取证用的那份 |
| **`candidate_b7780848`** | 445,442 | `B7780848…` | 语音，**环形缓冲已修** | **← 20:03 烧录前备份拍到的就是它（§0.2）；它也是本批的对照基线** |
| `candidate_4248fec2` | 447,393 | `4248FEC2…` | 语音 **+ AITRUST** | 用户已核对过哈希的那份 |
| **`candidate_c0a02e4c`** | 358,808 | **`C0A02E4C…`** | **AITRUST + 语音禁用** | **← 本批最终候选** |

对照特征串（对 **ELF** 有效，对 Intel HEX 无效——hex 是 ASCII 编码的）：

| ELF | `AITRUST` | `v_kws`（语音线程名） | `voice: passive`（语音启动日志） |
|---|---|---|---|
| `candidate_b7780848` | 0 | 1 | 1 |
| `candidate_4248fec2` | 1 | 1 | 1 |
| `candidate_c0a02e4c` | 1 | **0** | **0** |

### 3.3 备份与证据（**别删**）

```
outputs/Titan_AITRUST_Telemetry_2026-09-23/
    candidate_b7780848/      rtthread.{hex,elf,map}   语音批次候选（= 实测板上的固件）
    candidate_4248fec2/      rtthread.{hex,elf,map}   语音+AITRUST
    candidate_c0a02e4c/      rtthread.{hex,elf,map}   ★ 本批最终候选
    pre_aitrust_flash_2026-09-23.bin   1,048,576 B  20:03:19
        SHA-256 BB711AC7C2014C386BC5AF35B67A984D8047912251B0BA128C9DC310C089E197
        （实测内容 = candidate_b7780848，见 §0.2）
    build.log / build_voice_off.log / build_prechange.log / build_restore.log
    my_diff_smart_hand_uart.patch      （改动前→后的最小 diff，+76/−0 行）

outputs/Titan_Voice_Bringup_2026-09-23/
    pre_voice_flash.bin     1,048,576 B  14:13:24
        SHA-256 65EF0A467D0FDF5D44597BAA4480A0DF7A43A948ADBADBA9394702D8C03565CF
        （语音批次之前的旧固件：无语音、无 AITRUST）
    candidate_60ad1d89/     语音批次第一次取证的候选
```

### 3.4 本批改动的源码文件（仓库侧 SHA-256）

```
cb372aaa9fee5101676b35a018676384aefa58557b0af2b23ee3a548cb2e328a  titan_rtthread/smart_hand_status_telemetry.h
b9ba71b09d7c459b848f16b4f7af810872defb570cee3f25dccbdfeced30c630  titan_rtthread/smart_hand_status_telemetry.c
6c28996ad6ede837da82d293ef0f1cf74a07136b70a166348284e08ffe6aede0  titan_rtthread/smart_hand_uart.c
d1606f0177455dd850dac291f34c1b5b20a4c588be9da6694aa2b7eecad5059c  titan_rtthread/voice_app_titan.c
384aa6c11d091b35cd4513190823f9fefd97edf3bd689e714e8bc8a6a01465ae  tests/test_smart_hand_status_telemetry_c.c
0d89a631d254a7b73d60a105bf33c5f3b5018a7bc4a0e13b8615b44907c6d617  tests/test_aitrust_uart_glue_contract.py   ← 新增
52d789f7c37c9dd48e38262896f34b6eccd2cf1245a4683d390c34ef394595eb  host/run_all_checks.ps1
72dccf42ea6660a2ba27a3a86da4f26a2cfd0eed01d2ad60a492a62dc5e423d5  host/check_titan_sync.ps1
7a036f79eca72c2a3837f7a52702e04532d48221838a2442b319f06cd7b2e052  host/titan_linkage_check.py
772a226485827ca78285575ed47173979468fae5b42b8c66bc2193e013b52ac6  docs/DEEPSEEK_TO_CODEX_TITAN_AITRUST_TELEMETRY_2026-09-23.md
```

`smart_hand_status_telemetry.h/.c/.c`+`smart_hand_uart.c`+`voice_app_titan.c` 这 4 个已**单向部署**到工程 `src/`，
仓库↔工程**全部 MATCH**（§4.6 有全量核对方法）。

---

## 4. 怎么复现每一条声明

**全部命令都在"仓库的上一级"跑**（`C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网`），
只有 `gcc` 那条要在 `smart_hand/` 里跑。**跑错目录会得到假失败**（§6 有解释）。

### 4.1 宿主测试（最小可信集）

```bash
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"
python -m unittest smart_hand.tests.test_aitrust_uart_glue_contract \
    smart_hand.tests.test_titan_linkage_check smart_hand.tests.test_telemetry_runtime \
    smart_hand.tests.test_telemetry_schema smart_hand.tests.test_protocol_status_proposal \
    smart_hand.tests.test_voice_app smart_hand.tests.test_voice_audio \
    smart_hand.tests.test_voice_audio_titan smart_hand.tests.test_voice_memory_budget \
    smart_hand.tests.test_servo_group_recovery smart_hand.tests.test_run_one_cycle_d2 \
    smart_hand.tests.test_drv_usart_v2
```

**期望**：`Ran 112 tests … OK`。数字构成：
`test_aitrust_uart_glue_contract` 23 项 + `test_titan_linkage_check` 7 项 + voice 32 项 + 其余。

> **⚠️ 口径**：这 **112 项是精选子集，不等于 `host/run_all_checks.ps1` 全绿**。
> 那个脚本的 `[1/8]` 步当前**是红的**（`test_rehab_imitation` 6 项**既有**失败，与本批无关，是 Aug 22 的代码），
> 它 `throw` 之后本批要跑的三步**根本执行不到**。**别用那个脚本当验收判据。**

### 4.2 C 遥测测试

```bash
cd smart_hand
gcc -std=c99 -Wall -Wextra -Werror -Ititan_rtthread \
    tests/test_smart_hand_status_telemetry_c.c \
    titan_rtthread/smart_hand_status_telemetry.c \
    titan_rtthread/smart_hand_protocol.c \
    -o tests/test_smart_hand_status_telemetry_c.exe
./tests/test_smart_hand_status_telemetry_c.exe
```

**期望**：`smart_hand_status_telemetry C tests passed (STATUS v1 + AITRUST v1)`，退出码 0。
断言 **77** 条 = 既有 23 + 本批新增 54（`grep -c 'assert(' tests/test_smart_hand_status_telemetry_c.c`）。

**注意**：`gcc` 用的是宿主的 `/d/mingw64/bin/gcc`（8.1.0）。必须**同时**链接 `smart_hand_protocol.c`，
因为测试要钉**编码后的线上字节**（含 CRC16）。

### 4.3 变异测试（本项目惯例：证明测试真的能抓到 bug）

**C 层（策略）9 个**、**胶水层 12 个**，全部被抓/被拒。核心三处"修复前确实逃逸、修复后被抓"的对照：

| 缺口 | 修复前 | 修复后 |
|---|---|---|
| `ready` 丢掉 `model_ready` 一半 | `SURVIVED (rc=0)` | `CAUGHT (rc=3)` |
| **驱动层 5 个字段各自硬编码** | **`5/5 SURVIVED`** | **`5/5 CAUGHT`** |
| 驱动层去掉输入结构体清零 | `SURVIVED` | `CAUGHT` |

变异体**只打在源码副本上**（仓库树不被写入）。胶水层的 12 个变异体已经**编进测试文件**，
跑 §4.1 就能覆盖（`MutationTests` 类）。C 层的 9 个变异在报告 §4.3 有清单，
脚本本身是临时的、**没有落盘**（诚实说明）。

### 4.4 真机构建

```bash
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

**期望**：退出码 0；**唯一告警**是 `smart_hand_uart.c:NNN: 'sh_status' defined but not used`。
**这条告警是既有的**，证据：把改动前的 `smart_hand_uart.c` 用**完全相同**的 ARM 参数单独编译，同样报它。
（根因：`MSH_CMD_EXPORT` 展开为**空**、`rtconfig.h` 无 `RT_USING_FINSH`，所以 `sh_status` 根本没有调用者。）

> **陷阱**：**改编译选项（如 `-D...`）不会触发重编译**，`make` 会认为 `.o` 是最新的。
> 必须 `touch` 受影响的 `.c` 文件。本批改 `VOICE_APP_ENABLE` 时就靠 `touch src/voice_*.c` 才重编上。

### 4.5 语音"已禁用"的证据（用户点名要的）

```bash
DBG=/d/Micu/RTTWorkspace/titan_uart_test/Debug
grep -c '__rt_init_voice_app_titan_init' $DBG/rtthread.map     # 期望 0
grep -c 'smart_hand_aitrust' $DBG/rtthread.map                 # 期望 >0（21）
strings $DBG/rtthread.elf | grep -cx 'v_kws'                   # 期望 0（语音线程名）
strings $DBG/rtthread.elf | grep -cx 'AITRUST'                 # 期望 1
```

| 检查 | 语音开启 `4248FEC2` | **关闭后 `C0A02E4C`** |
|---|---|---|
| `__rt_init_voice_app_titan_init` | 在初始化表（有真实地址） | **完全不存在** |
| `voice_app_thread_entry` | 在 `.text` | 仅在 `Discarded input sections`（地址 `0x0`） |
| 语音深层符号（kws/features/audio） | 在 | 全部落进被回收段 |
| `v_kws` / `voice: passive integration` | 有 | **0 / 0** |
| `AITRUST` / `smart_hand_aitrust_*` / `send_aitrust` | 有 | **仍在**（真实地址 `0x0200456a` 等） |
| `__rt_init_smart_hand_comm_init` | 在 | **仍在**（`0x0200017c`） |

**`Discarded input sections` 段起始于 `rtthread.map:136`，`Memory Configuration` 在 `:5533`** ——
凡是"地址 `0x0`"的语音符号都在被回收段内、不在镜像布局里。

### 4.6 仓库 ↔ 工程 全量同步核对

```bash
python - <<'PY'
import pathlib, re, hashlib
ps1 = pathlib.Path("smart_hand/host/check_titan_sync.ps1").read_text(encoding="utf-8-sig")
names = re.findall(r"'([A-Za-z0-9_.]+\.(?:c|h))'", ps1)
canon = pathlib.Path("smart_hand/titan_rtthread")
studio = pathlib.Path("D:/Micu/RTTWorkspace/titan_uart_test/src")
h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
diff = [n for n in names if h(canon/n) != h(studio/n)]
print(f"清单 {len(names)} 条；不一致 {len(diff)} 条", diff)
PY
```

**期望**：`不一致 0 条`。
另：工程 `src/` 里唯一不在同步清单内的是 **`hal_entry.c`**（RT-Thread 自己的板级文件，非项目所有）。

**闸门也要自检它会真的变红**（本批加固过）：
```bash
python smart_hand/host/titan_linkage_check.py     # 期望 ok=True
# 往 REQUIRED_FUNCTION_GROUPS 临时加一个不存在的符号 → 应报 missing
```

### 4.7 判定"板上跑的是哪个候选"（§0.2 用的方法，**以后可能还用得上**）

要点：**必须按地址解析 Intel HEX**，不能 `objcopy -O binary` 后直接比
（本批的 hex 覆盖了很远的高地址区，objcopy 会铺出 13 MB 的镜像、前 1 MiB 根本不是 0x02000000）。

**方法**：把候选 `.hex` 解成 `{地址: 字节}`，只比 `[0x02000000, 0x02100000)` 这一段与 1 MiB dump。

### 4.8 陷阱：`-include` 参数被 MSYS 改写

```bash
# 会失败：MSYS 把紧跟 -include 的绝对 Windows 路径当 Unix 路径转换
arm-none-eabi-gcc ... -include"D:/x/rtconfig_preinc.h" ...
#   -> fatal error: D:D:/Git/x/rtconfig_preinc.h: Invalid argument
# 解法：
export MSYS2_ARG_CONV_EXCL='*'
```

---

## 5. 红线（违反即返工）

| 禁止 | 原因 |
|---|---|
| **烧写** | 由裁决人决定。用户 2026-09-23 明确说 **"暂不烧写"** |
| **接通舵机 6 V 驱动板** | 当前状态就是断电，**必须保持**，直到验收全过 |
| 把语音/AI 分类接到机械动作、或绕过网页人工确认 | AI 只是**提示**，安全门仍权威 |
| 改现有 UART 帧 / CRC / ACK / 超时 / 门控语义 | 已验收的通信契约 |
| 改 `board.h` 的 `RA_SRAM_SIZE`、`fsp.ld` | 内存算过账；本批 `data` 逐字节未变 |
| 用改模型常量去"凑"采样率 | 掩盖偏差，本项目明令禁止 |
| 宣称 16 kHz、或宣称真实识别准确率 | 未验证。`field_accuracy_validated` / `hardware_inference_validated` **都为 0** |
| 烧写工程根的 `titan_uart_test\rtthread.hex` | 09-21 旧版 |
| 用 `rt_kprintf` 当可观察证据 | Titan 控制台是 `null`，输出被丢弃。**这也正是本批要做 AITRUST 帧的原因** |
| 从工程根的旧副本回拷覆盖 `src/` | 会静默回退已审核的修复 |
| 删 `RT_ASSERT` 来掩盖问题 | D1 只把**可达**那条换成丢弃路径，其余 13 处断言全保留 |
| **本批相关**：把 `subdir.mk` 的 `VOICE_APP_ENABLE` 改回 1 而不告知 | 会把有遗留问题的语音线程重新启动，且体积/堆会变 |
| **本批相关**：给 `AITRUST` 加进 `parse_type()` | 会让 Titan 去 ACK 它，违反"不用 ACK"（详见 §7.3） |

---

## 6. 陷阱清单（每条都是本批实际踩到的）

### 6.1 环境类

| 现象 | 原因 / 解法 |
|---|---|
| `-include"D:/…"` 变成 `D:D:/Git/…` | **MSYS 会转换紧跟 `-include` 的绝对 Windows 路径**。`export MSYS2_ARG_CONV_EXCL='*'` |
| 从临时目录编译 `smart_hand_uart.c` 报 `grip_policy.h: No such file` | 引号头文件按**源文件所在目录**解析；跨目录编译要补 `-I"<工程>/src"` |
| **`python -m unittest smart_hand.tests.X` 报 `FAILED (errors=N)`** | **必须在仓库的上一级跑**。在 `smart_hand/` 里跑，`smart_hand` 会被解析成仓库内那个**空的嵌套目录**。本批我自己踩过两次 |
| 前台 `sleep` 被拦 | 改用 Monitor 的 until-loop 或 `run_in_background` |
| `rm` 被 deny | 临时产物放**唯一命名的新目录**，不删除 |
| PowerShell 拿不到 stdout | 输出重定向到文件再读回 |
| PowerShell 执行被 deny（某些会话） | `smart_hand/host/check_titan_sync.ps1` **只能由用户跑**；如实上报，别绕过 |
| Python stdout 中文乱码（GBK 代码页） | **把结果写进 UTF-8 文件再用 Read 读**，别打 stdout |
| `git diff HEAD` **不能**当基线 | 工作区相对 HEAD 有约 **185 行先前未提交的改动**（实测：HEAD 657 行 / 改前后 842 / 改后 927）。要拿真基线就**反向还原自己的编辑**，或改动前先存盘 |

### 6.2 工程类

| 现象 | 原因 / 解法 |
|---|---|
| 工程里有两份同名 `rtthread.hex`，内容不同 | CDT/make 落 `Debug/`，SCons 的 `POST_ACTION`（`rtconfig.py:56`）在工程根再生成一份，互不覆盖。**只认 `Debug/rtthread.hex`** |
| 改 `subdir.mk` 的编译选项后 `make` 什么都不做 | **改选项不触发重编译**。必须 `touch` 受影响的 `.c` |
| "编译成功 + 链接成功 + exit 0" ≠ 集成生效 | `--gc-sections` 会回收没有调用者的模块，**固件体积与集成前逐字节相同**。判断集成是否发生：看 map 里符号 + **体积是否变化** |
| `R_PDM_Read` 不可用 | `ra/fsp/src/r_pdm/r_pdm.c` 里它直接 `return FSP_ERR_UNSUPPORTED` |
| `pdm_error_t` 是位掩码，`PDM_ERROR_BUFFER_OVERWRITE = (1UL<<11)` | 用 `uint8_t` 存会截断成 0 == `PDM_ERROR_NONE`，**最该被看见的错误会隐形**。已改 `uint32_t` |
| `HEAP_BEGIN` 随 `.bss` 上移 | `board.h` 的 `RA_SRAM_SIZE = 512` 把堆上限卡在 `0x22080000 − __RAM_segment_used_end__`。**静态区增长 = 堆等量减少** |
| 语音模块**不是** NPU | `ra/npu/tflite-micro/` 在源码树里，但 `ra/SConscript` 只收 `ethos-u-core-driver`，`Debug/makefile` **没有 C++ 规则**。当前是 **Cortex-M85 CPU int8 自研推理** |

---

## 7. 关键设计决策与理由（**改之前先读这节**）

### 7.1 `ready` 为什么是**合取**

```c
ready = (in->model_ready != 0u && in->have_vision != 0u) ? 1u : 0u;
```

`titan_trust_runtime_evaluate()` **在视觉候选过期后不会把 `ready` 清零**：
`have_last` 与 `valid_samples` 都不清零（`titan_trust_runtime.c:114-125`），
而 `smart_hand_vision_state_expire()` 只清自己的 `have_vision`/`last_vision_ms`。

**所以只报 `model_ready` 会对着已经过期的视觉广告"就绪"** —— 那正是必须读作"未就绪"的情形。
合取的两半各自被测试独立固定（`(1,0)` 钉 `have_vision`；`(0,1)` 钉 `model_ready`）。

### 7.2 `ready=0` 时 `class_id` 怎么填 —— **已裁决：选 (A)，保留现有协议**

**裁决原文（用户）**：`ready=0` 时 `class_id` **只作为原始模型值传输**，接收方**一律显示「未就绪」**；
即使是 `ready=0, class_id=0`，也**绝不能显示绿色「可信」**。已写入共用任务书，**Gemini 须用该反例测试页面**。

**所以实现是"直通"**（越界才 clamp 到 `ANOMALOUS`），**不做任何伪造**。三个备选方案当时评估过：
`0`=假可信（绿，最危险）、`2`=假异常、`1`=假存疑——**三个值里没有一个诚实的"无类别"**；
自己造第四值是**单方面改协议**，而 MaixCAM2 侧是另一个 agent 并行实现，严格校验会拒收 → 跨团队失配。

**风险仍然存在且可达**（三个独立验证者用真实模型权重复算确认过）：
连喂 ≥3 帧 VISION 使模型判 `TRUSTED` → 停发 VISION 满 750 ms → 下一个 500 ms 周期会发出
`$AITRUST,7,1,0,0,2000*45BF`（`ready=0` 但 `class_id=0`）。
**可落绿的窗口经实测约为过期后 750–945 ms**（age≥900 ms 就翻成 `UNCERTAIN`）。
**接收侧必须按 `ready` 判色**——这是裁决 (A) 的全部依赖。

### 7.3 为什么不把 `AITRUST` 加进 Titan 自己的解析器

它是 Titan → MaixCAM2 单向只读帧，Titan 从不接收。若加进 `parse_type()` 而不加对应 `case`，
帧会落到 `handle_message()` 的 `default` 分支发 `ACK=UNSUPPORTED_TYPE` —— **违反"不用 ACK"**，
而且那个 ACK 会带着 `AITRUST` 的序号，可能在对端被误配到某个 pending 请求上。

> **但这条有代价（审查者指出、我复核成立）**：收到未知类型时 rx 线程会 `++g_stats.invalid_frames`
> **并调用 `titan_trust_runtime_note_invalid()`**，后者喂的正是模型特征 `features[6]`。
> 即：**任何把 Titan 自己字节回显回来的接法，会让 Titan 把自家遥测当成非法帧并扰动自己的分类输入**，
> 同时抬高既有验收判据 `invalid_frames == 0`。**验收时不要挂 UART 回环探针。**

### 7.4 `vision_age_ms` 的缺省与饱和策略

| 情形 | 取值 | 理由 |
|---|---|---|
| **从未收到过** VISION | `SH_AITRUST_AGE_UNKNOWN = 0xFFFFFFFF` | 没有年龄可报。用 `0` 会被读成"刚刚到达" → 危险方向；故向上饱和 |
| 收到过，年龄 > `60000` | 饱和到 `60000` | 有界，让页面有确定的"很旧"值 |
| 时钟非单调（`now < last`） | 无符号回绕成大值 → 被同一条 clamp 吸收 | **不会**回绕成一个小而"更新鲜"的数 |

时间戳由 `smart_hand_uart.c` 自己保存（`g_vision_seen` / `g_vision_last_seen_ms`），
**不能**用 `g_vision_state.last_vision_ms`：后者在候选过期时被**清零**，年龄会从零重新开始。

### 7.5 500 ms 是"尝试"的下限，不是"成功"的下限

`smart_hand_aitrust_note_attempt()` 在**写之前**记账，**成功与失败都记**。
否则一次写失败会在下一个 50 ms 唤醒时重试 —— 那就是对承载 ACK 的同一条 UART 做**重试风暴**。
**序号只在真正发出的帧上推进**，所以对端看到的序号连续、缺口就是真丢帧。

### 7.6 写帧占用时间**不是零**（源码注释曾被改正过一次）

`send_aitrust` 跑在 `sh_uart` 线程、走**同一条轮询 TX**（`config.tx_bufsz = 0`），
38 字节帧在 115200 下**确实占用线上约 3.3 ms**，这段时间 ACK/STATUS 用不了。
写源码注释时曾写成"绝不会延迟 ACK"，**用户指出过满、已改正**。**ACK 延迟必须真机测**（§10.2 第 11 条）。

### 7.7 一条容易忘的既有设计

- **`abort_cycle()` 与新计数器 `aborted_cycles`**：**不复用 `invalid_cycles`**——后者语义是"完成了但数据不可信"，
  中止的周期根本没产生数据。
- **语音线程栈 8 KB 静态、`voice_kws_t` 62,727 B 静态**：堆只剩 87 KB（语音启用时）。
- **`VOICE_APP_ENABLE` 默认 0**：fail-closed，仅把文件加进构建不改变固件行为。

---

## 8. 两轮对抗式审查的结果（**本批的自我批判记录**）

### 8.1 第一轮：4 个维度审查者 + 独立证伪

**19 条原始发现 → 12 条获得对抗裁决 → 4 条成立、8 条被驳倒**（另有 1 条裁决返回格式损坏、7 条从未获裁决）。

**成立的 4 条**（都已处理）：
1. `ready=0` 时 `class_id` 仍可能是 `0`，且头文件当时那段 fail-closed 论证**在视觉链路上不成立** → 已列为待裁决项 → **裁决 (A)**；错误论证**已改正**。
2. `ready` 合取里的 `model_ready` **完全没被测试固定**（删掉它测试照样全过）→ **已修** + 变异对照。
3. `AITRUST` 的 **500 ms 闸门与写失败次序零保护** → **已修**（新增胶水契约测试）。
4. 头文件那段**错误论证** → 已改正（纯注释，`hex` 逐字节不变）。

**被驳倒的例子**（提醒你：审查者也会错）：说年龄哨兵"是单方面引入的协议值"、
说它"没有测试固定"、说 `class_id` 1/2 映射"没有测试固定" —— 都被实测推翻
（**最坏帧硬字面量 `$AITRUST,65535,1,1,2,4294967295*574D` 把哨兵和 class=2 都钉住了**，改任何一个即变红）。

**我自己驳倒的一条**：说 `g_titan_trust_result` 有撕裂读竞争 —— 不成立，因为 **MSH/FINSH 整个没被链接进固件**
（`MSH_CMD_EXPORT` 展开为空、`msh.o`/`finsh.o`/`shell.o` 的 `.text` 全为 `0x0`、`sh_status` 的 544 字节被 GC 丢弃），
`sh_status()` 没有调用者。**但若将来启用 MSH，这条竞争就成立**，届时最便宜的修法是让 `send_aitrust` 用局部结果对象。

### 8.2 第二轮：完备性批评 —— **4 个审查者都漏掉的 5 条**

| # | 严重度 | 发现 | 处置 |
|---|---|---|---|
| **C1** | **high** | **驱动层字段映射 `smart_hand_uart.c` 那 5 行零保护**（实测 **5/5 变异体存活**）；报告还**夸大了覆盖**（只列了闸门/记账/序号三点） | **已修**：契约测试新增"字段来源"一组 + 6 变异体；留了"修前 5/5 存活 → 修后 5/5 被抓"的对照 |
| C2 | medium | `check_titan_sync.ps1` 的清单**不含** telemetry 的 `.c/.h`，而报告拿它当"无差异"的证据 | **已修**：清单补入这两文件；并做了**追溯构建证明**（§9.3） |
| C3 | medium | `titan_linkage_check.py` **不含任何 AITRUST 符号**、不把 `telemetry.c` 当"新"源码 | **已修**：9 个符号进 `REQUIRED_FUNCTION_GROUPS`、`.c/.h` 进源码列表 |
| C4 | low | 报告给的命令与其自述 cwd **互相矛盾**，按文中 cwd 复跑会假失败 | **已修**：逐条标明 cwd |
| C5 | low | `run_all_checks.ps1` 的 `[1/8]` 步当前**是红的**（6 项既有 rehab 失败），易被误记成 AITRUST 回归 | 已在报告与本文件 §4.1 注明 |

> **C1 是这批审查里最有价值的一条。** 它查的不是"代码错了"，而是"**正确代码与错误代码都全绿**"。

### 8.3 审查自身的局限（如实）

- 我的审查工作流**每个维度只送了前 3 条去证伪**，所以 19 条里有 **7 条从未获得对抗裁决**。
  我另行单独复核了两条（回环风险、`tx_failures` 语义被静默改变——两条都成立），其余未逐一实证。
- 报告的断言计数曾写错两次（67/70 → 实测 77），**已更正**。**你接手时以实测为准。**

---

## 9. 已验证 vs 未验证（**交接时不要混淆**）

### 9.1 已验证（主机侧，可复跑）

| 项 | 证据 |
|---|---|
| AITRUST 帧的字段/顺序/CRC/最坏帧长 | C 测试整帧硬字面量（含 CRC），改一个字节即变红 |
| 500 ms 下限（含**时钟回绕**）与失败不重试 | C 测试 + M4/M9 变异 |
| `ready` 合取两半各自被固定 | C 测试 + M1/M8 变异 |
| `vision_age_ms` 缺省与饱和、时钟回退 | C 测试 + M2/M3 变异 |
| `class_id` 越界 clamp | C 测试 + M5 变异 |
| STATUS v1 线上字节未变 | 整帧字面量 + M7 变异（改 `shp_encode` 分隔符即变红） |
| **驱动层字段来源**（那 5 行） | 契约测试 + 6 变异体（修前 5/5 存活） |
| 胶水层次序（闸门/记账/序号/唯一调用点/不碰安全路径） | 契约测试 + 6 变异体 |
| 语音 `VOICE_APP_ENABLE=0` 宿主路径 | `test_voice_app` 等 32 项全绿 |
| 全部源文件可被真机工具链编译、固件可链接 | §4.4 |
| `data` 逐字节不变、`bss`/堆账 | §3.1 与 §2.2 |
| **峰值栈不增加** | `-fstack-usage` 实测：新链路 488 B < 既有最深 536 B |

### 9.2 未验证（**必须真机**）

1. **`AITRUST` 帧带来的 ACK 延迟** —— 用户点名要真机测。静态可算约 3.3 ms/帧，但"不影响时序"必须实测。
2. 真机上 `AITRUST` 是否真按 ≤2 Hz 发出、页面是否按冻结要求渲染。
3. `ready` 在真机的切换时序、`vision_age_ms` 的实际数值。
4. **`ready=0 且 class_id=0` 时页面不显绿**（裁决 (A) 的关键反例，须 Gemini 用页面测试覆盖）。
5. 与 MaixCAM2 侧的**端到端**协议一致性（`maixcam2/protocol.py` 的 `MESSAGE_TYPES` 里**还没有** `AITRUST`）。
6. 真机栈水位 / 堆运行期水位。
7. 并发正确性 —— 所有宿主测试都是**单线程**；"无竞争"是**源码可达性论证**，不是真机观测。
8. `AITRUST` 写失败在现场的可观测性 —— **`sh_status` 不可达**（§4.4 里那条既有告警的根因），只能靠 SWD 读 `g_aitrust_link` 或"页面停止收帧"。
9. 10 分钟持续运行、断线/过期回退。
10. **真实识别率** —— `field_accuracy_validated` / `hardware_inference_validated` **仍为 0**。

### 9.3 一条已经做完的追溯证明（供你复用方法）

我曾用 `cp` 覆盖工程侧副本，而当时**没有先比对 telemetry 那两个文件**
（因为同步闸门当时不含它们）。为了回答"到底有没有静默覆盖"，我做了：

```
用【改动前】源码（uart.c 由本次 5 处编辑反向还原；telemetry.c/.h 取 git HEAD，已证相对 HEAD 是纯新增 123/0、140/0）
重新部署进工程树并 make all：
    产出 hex = b7780848b4274ecaaca51164fe484b348899690cc5b0ee0a4d9c4a4b7c2934fb
    上一轮候选 = b7780848b4274ecaaca51164fe484b348899690cc5b0ee0a4d9c4a4b7c2934fb   ← 逐字符相同
```

**注释差异会被编译器丢弃、代码差异必然改变 hex**，所以这证明改动前两棵树**代码等价 → 没有静默覆盖**。
实验后已还原工程树并重建，hex 精确回到当时的候选。

### 9.4 唯一的真机观测（2026-09-23 20:26，样本极小）

烧写（20:04:05）之后，MaixCAM2 侧真机日志里出现了第一条 `AITRUST` 观测：

```
AUTH link=ON vis=OFF stale=0 act=NONE reason=invalid_payload pose=NO_ACTION submit=UNKNOWN
     gate=DISARMED   AITRUST v=1 ready=0 class=ANOMALOUS age_ms=4294967295
```

**怎么读这条**：

- `v=1` → 帧格式与冻结契约一致，**端到端链路是通的**（回答 §9.2 第 5 条的一半）。
- `age_ms=4294967295`（= `0xFFFFFFFF`）→ **从未收到过 VISION 载荷**。
- 按 §7.1，`ready = 模型窗口完整 ∧ 视觉新鲜`；视觉这一支为假 ⇒ `ready=0` 是**正确行为**，不是缺陷。
- `ready=0` 且 `class_id=ANOMALOUS` 正是 §7.2 裁决 (A) 要求"绝不能显示绿色"的组合；页面显示「未就绪」是对的。

**用户 20:41 的疑问（"端侧AI参考为什么总显示未就绪"）的答案就在这里：卡点在视觉输入侧
（`vis=OFF` / `reason=invalid_payload`），不在 AITRUST 链路。** 排查应从 MaixCAM2 的 VISION 帧入手。

> ⚠️ 这是**一次**观测、且当时视觉未接入，**不能**当作 §9.2 那些"必须真机"的项已经验证。

---

## 10. 下一步与依赖

### 10.1 依赖关系

```
[Gemini 交付：MaixCAM2 接收 + 网页过期回退]  ← 20:26 已见设备侧解析出 AITRUST 帧（§9.4）
        │
        ├──► ① 两端联审（重点验 §7.2 那个反例：ready=0 且 class_id=0 页面必须显「未就绪」、不得显绿）
        │
        └──► ② 真机验收 12 条（含 ACK 延迟）
                    │
                    └──► ③ 烧写 ✅ **已由 Codex 于 20:04:05 完成，20:05 读回校验通过**（§0.2）
```

**本批在写代码这一侧已收尾，烧写也已落地。** 你现在能真正推进的是：§10.2 的真机验收 12 条，
或 §11 里的开放项。

### 10.2 真机验收清单（12 条，**驱动板保持断电**，SWD 只读）

1. **不要挂 UART 回环探针**（原因见 §7.3 末尾）。
2. UART 抓包确认 `AITRUST` 帧出现，且任意 1 秒内**不超过 2 帧**。
3. 视觉正常喂入时：`ready=1`、`class_id ∈ {0,1,2}`、`vision_age_ms` 随视觉帧到来**回落**。
4. 停发 VISION 超过 750 ms：**`ready` 必须变 0**（§7.1 的直接判据）。
5. 断开视觉后 `vision_age_ms` **持续增长并封顶在 60000**，不跳回小值。
6. **裁决 (A) 的关键反例**：在"刚过期（750–945 ms）"抓一帧，很可能看到 `ready=0 且 class_id=0`；
   与 Gemini 联调确认页面显示「未就绪」而**不是绿色「可信」**。
7. 全程 `STATUS` v1 的 8 个字段与频率不变，`ACK` 行为不变，`SIGNSTAT`/`TRAINSTAT` 不变。
8. 全程**没有任何 AITRUST 相关的 ACK** 出现在线上。
9. 10 分钟持续运行 + 断线/重连，`AITRUST` 不中断、不刷屏。
10. 与 MaixCAM2 侧联合：页面状态按冻结要求显示，**`ready=0`、过期、离线时颜色不得为绿**。
11. **测 ACK 延迟**：AITRUST 开/关两种配置下分别测 ACK/STATUS 往返时延（§7.6）。
12. **确认语音路径确实没跑**：`__rt_init_voice_app_titan_init` 不在 MAP 里（§4.5），
    且真机上没有 `v_kws` 线程（可用 SWD 看线程列表）。

**任何一项失败都不进入舵机 6 V 上电测试。**

---

## 11. 开放项 / 需要裁决

| # | 项 | 说明 |
|---|---|---|
| 1 | ~~**板子到底是什么固件**（§0.2）~~ → **已解决** | 20:03 快照为 `candidate_b7780848`；**20:04:05 起板上是最终候选 `candidate_c0a02e4c`，20:05 读回校验通过**。旧文档"已整片回退"描述的是 14:2x 的状态，其后又发生过一次刷写。**唯一遗留：`b7780848` 的刷写者与时刻未确认**（不在任何 agent 会话内；用户不记得）。因此那一轮的**环形缓冲真机验证结果仍是空白**，不得当成已验证 |
| 2 | **`subdir.mk` 的耐久性** | 它是自动生成物，Studio 刷新会把 `VOICE_APP_ENABLE` 改回 1。要不要在仓库侧留一份可复核的构建配置说明？（需用户定，因为动的是构建配置） |
| 3 | **`tx_failures` 语义被静默改变** | AITRUST 写失败与 ACK/STATUS 写失败**共用同一个 `tx_failures`**，而既有验收文档把"`tx_fail=0`"当链路健康判据。因 `sh_status` 不可达，当前无影响；若启用 MSH 需拆分 |
| 4 | **C 层 9 个变异体没有落盘** | 胶水层 12 个已编进 `test_aitrust_uart_glue_contract.py`；C 层那 9 个是临时脚本，没进版本库 |
| 5 | **`test_rehab_imitation` 6 项既有失败** | 与本批无关（Aug 22 的代码），但它让 `run_all_checks.ps1` 的 `[1/8]` 步直接红掉，后面 7 步全不跑 |
| 6 | 语音模块的**其它 `=0` 路径**是否也有类似 `NULL` 的坑 | 我只修了 `voice_app_titan.c` 那处。**没有逐一排查**其它文件在关闭态下的编译性 |
| 7 | 上位机 `maixcam2/protocol.py` 仍不认 `AITRUST` | 属 Gemini 的工作；**列在这里是提醒你别以为端到端已经通了** |

---

## 12. 文件清单（本批改动）

### 12.1 新增

| 文件 | 作用 |
|---|---|
| `smart_hand/tests/test_aitrust_uart_glue_contract.py` | **胶水层源码契约测试**（23 项 / 12 变异体）。钉住 `smart_hand_uart.c` 里那些"零保护"的点：闸门先于写、记账先于写、`note_sent` 受 RT_EOK 守卫、唯一调用点在 rx 线程、**每个输入字段的来源**、输入结构体先清零、不碰运动/安全路径 |
| `smart_hand/docs/DEEPSEEK_TO_CODEX_TITAN_AITRUST_TELEMETRY_2026-09-23.md` | 本批交付报告（给裁决人） |
| **本文件** | 交接文档 |
| `outputs/Titan_AITRUST_Telemetry_2026-09-23/` | 证据与三份候选备份 |

### 12.2 修改

| 文件 | 改动 | 为什么 |
|---|---|---|
| `titan_rtthread/smart_hand_status_telemetry.h` | 新增 AITRUST 段（常量、输入结构体、API、**所有权与缺省/饱和策略的证明性注释**） | 协议实现 + 文档 |
| `titan_rtthread/smart_hand_status_telemetry.c` | 新增 AITRUST 实现（约 120 行） | 纯策略，宿主可测 |
| `titan_rtthread/smart_hand_uart.c` | 新增 `send_aitrust()` + 3 个静态量 + 视觉时间戳跟踪 + 循环调用 + 启动初始化；**+76/−0 行** | 胶水 |
| `titan_rtthread/voice_app_titan.c` | `#include <stddef.h>` 移到 `#if` 之外 | 修 §2.3 缺陷 1（`=0` 路径从未被 ARM 编译过） |
| `tests/test_smart_hand_status_telemetry_c.c` | 断言 23 → **77** | 覆盖任务书要求 3 的七项 + 帧长上限 + clamp + NULL + 回绕 + 合取两半 |
| `host/run_all_checks.ps1` | gcc 行补链接 `smart_hand_protocol.c`；标签改名 | 测试要钉编码后字节，不链接会**链接失败** |
| `host/check_titan_sync.ps1` | 清单补入 telemetry 的 `.c/.h` | 闸门看不到本批改的文件（完备性批评 C2） |
| `host/titan_linkage_check.py` | 加 9 个 AITRUST 符号 + telemetry 的 `.c/.h` 进源码列表 | 闸门看不到本批改的文件（C3） |
| **`D:\Micu\…\Debug\src\subdir.mk`**（工程侧，非仓库） | `-DVOICE_APP_ENABLE=1` → `=0` | 用户指令：禁用语音路径（§2.2） |

### 12.3 未改动（明确声明）

`smart_hand/maixcam2/`、网页、`board.h` 的 `RA_SRAM_SIZE`、`fsp.ld`、UART 帧/CRC/ACK/超时/门控语义、舵机路径、
`titan_trust_model.*`、`titan_trust_runtime.*`、`voice_config.h`、`voice_audio*`、`voice_features*`、`voice_kws*`、`voice_model_data*`。

---

## 13. 本项目的工作流约定（**请遵守**）

1. **主模型/裁决人负责裁决**；执行 agent 每批交付后写 `DEEPSEEK_TO_CODEX_*.md` 报告，含：
   实际读取的文件、确认/未确认事项、修改文件与关键设计、**测试命令与完整结果**、残余风险与下一步。
2. 任务书由裁决人写、放 `smart_hand/docs/`，名为 `DEEPSEEK_TASK_*.md`（或 `TITAN_*_TASKS_*.md` 这样的共用任务书）。
3. **报告里必须如实写"未读到"和"未验证"** —— **宁可写"不确定"也不要推断**。
4. **变异测试是本项目惯例**：写完测试要**证明它真的能抓到 bug**（删掉被测的保护、确认测试变红）。
   本批的教训：至少三处缺口是靠"跑同一个变异体在修复前后两版"才证明的。
5. 改动控制代码前**先解释必要性、风险与验证方法**。
6. **不要编造准确率，不要用合成语料对拍冒充真实识别率。**
7. 用户对**诚实口径要求极高**：把"配置声明"当"实测值"、把"宿主通过"当"真机通过"，都会被抓。

---

## 14. 怎么启动 `dsh`（DeepSeek harness）—— 含已知的坑

**这是另一个独立产品，与本会话的 Claude Code 无关。**

```powershell
# 可执行：C:\Users\zzh\AppData\Roaming\npm\dsh（含 .cmd/.ps1，已在 PATH）
dsh --version        # 0.1.5-rc.1
dsh --help           # 原话："boot a DeepSeek Harness profile"
```

### 14.1 启动

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"   # ← 会话按工作目录归档，要在这里起
dsh web                                              # = dsh --profile web，起浏览器 UI
```

**⚠️ 裸跑 `dsh` 不行** —— 实测报 `error: --profile <name> is required`，**必须带 profile**。

| profile | 状态 |
|---|---|
| `web` | **本地已有**（`~/.dsh/profiles/web`），起浏览器 UI |
| `headless` | **随包自带、可直接用**：`dsh --profile headless "任务"` → 只输出最终答复后退出 |
| `tui` / `rescue` | **不存在**，实测报 `profile "tui" does not exist`；要用 `dsh --profile rescue --from-default-profile web` 或 `dsh plugin --profile tui add <package>` 创建 |

### 14.2 ⚠️ 已知的坑：`EADDRINUSE 127.0.0.1:3080`

**症状**：`dsh web` 报 `listen EADDRINUSE: address already in use 127.0.0.1:3080`。
**原因**：**先前那个 `dsh web` 还在跑**（本机实测 PID 32304 是 `node.exe` 占着 3080）。
注意 `npx @deepseek-ai/dsh web` 是**同一个包、同一个默认端口**，撞的是同一个坑。

**三条路**：

```powershell
# A. 先试试它是不是还活着（那个实例仍在服务，返回 401 是它的 trust 栅栏）
start http://127.0.0.1:3080

# B. 换个端口起新的（非破坏性，推荐）
dsh web --port 8080          # 不加 --no-open 时它会自己用带令牌的 URL 打开浏览器

# C. 干掉旧的（会中断那个实例正在跑的任务）
Get-NetTCPConnection -LocalPort 3080 -State Listen | Select-Object OwningProcess
taskkill /PID <上面查到的PID> /F
dsh web
```

### 14.3 ⚠️ 另一个坑：**别手敲 `127.0.0.1:3080`**

浏览器直接打开裸地址会显示 **"authentication required; reopen the URL printed by `dsh web`"**。
**`dsh web` 启动时会打印一条带一次性令牌的 URL，只有那条能进**——这是它的 browser-trust 栅栏。
裸地址被故意拒绝，**没有开关能绕过**（`--trusted-host` 只是往栅栏里**额外加可信 authority**，
比如你用主机名或局域网 IP 访问时用，它不移除认证）。

**所以**：要么不加 `--no-open` 让它自己打开，要么从终端里**复制它打印的那行 URL**。
`~/.dsh/` 下**没有**日志能找回旧 URL，丢了只能重启。

### 14.4 其它

- 密钥在 `~/.dsh/.credentials.yaml`（refs：`DEEPSEEK_API_KEY`、`OPENCODE_GO_API_KEY`），**不需要设环境变量**。
- 默认模型在 `~/.dsh/settings.yaml` 的 `agent-default-model`：`provider: opencode-go`、`model: deepseek-v4-pro`。
- **安全提醒**：`~/.claude/settings.json` 里那把 Claude Code 用的 DeepSeek key 是**明文**，
  且已在一次会话记录中出现过，**建议轮换**。

---

## 15. 一句话状态

**AITRUST 只读遥测（`ready` 为合取、`vision_age_ms` 有明确缺省与饱和、≤2 Hz、无 ACK、不重试）已实现并通过
C 层 9/9 + 胶水层 12/12 变异体、112 个宿主测试；语音路径已按用户指令用 `VOICE_APP_ENABLE=0` 禁用
（MAP 里 `__rt_init_voice_app_titan_init` 完全消失，堆 +299 KB）；最终候选 `C0A02E4C…D6CA`（358,808 B）已构建、
仓库↔工程 47 条清单零不一致、`data` 逐字节不变。**

**两轮审查合计 24 条，成立的 9 条已全部处理**（含完备性批评发现的"驱动层字段映射零保护"——
实测修前 5/5 变异体存活、修后 5/5 被抓）。**板子已于 20:04:05 烧写为本批最终候选 `C0A02E4C…D6CA`，
20:05 逐段读回校验通过**（舵机驱动板保持断电）。

**⚠️ 你接手第一件事**：读 §0.2 —— 原文"板子未刷写 / 板上不是候选固件"**已经过期**。
板上现在跑的就是 `candidate_c0a02e4c`；§0.2 那张比对表是 **20:03 烧录前快照**，不要再拿它当"当前状态"。
