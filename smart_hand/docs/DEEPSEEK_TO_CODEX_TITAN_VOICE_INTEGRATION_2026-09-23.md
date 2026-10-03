# DeepSeek → Codex 交付：Titan 语音模块第一阶段「被动集成」

任务书：`DEEPSEEK_TASK_TITAN_VOICE_PASSIVE_INTEGRATION_2026-09-23.md`
日期：2026-09-23

**明确声明**：**未烧写**、**未验证真实识别率**、**未启用语音控制**。本批只交付源码、测试、资源报告和候选固件。

---

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| 语音模块进入真实固件 | ✅ `__rt_init_voice_app_titan_init` 已在 init 表，链接确认 |
| 语音线程 | ✅ 静态 8 KB 栈，优先级 22（低于 `sh_uart` 的 18） |
| `voice_kws_t` 静态存储 | ✅ 文件级 static，未上线程栈 |
| 未改 SRAM 配置 | ✅ `board.h` / `fsp.ld` / `RA_SRAM_SIZE` 未动 |
| 未用语音触发机械手 | ✅ 无任何舵机调用，状态无人消费 |
| 未扩展 MaixCAM2 协议 | ✅ |
| **Flash 增量** | **+27,485 B**（text 11,136 + rodata 16,349） |
| **RAM 增量（.bss）** | **+298,954 B** |
| **RT-Thread 堆** | **386,060 → 87,044 B（−77%）** |

---

## ⚠️ 烧写前必读：工程根目录的 hex 仍是旧版

| 路径 | 状态 | SHA-256 |
|---|---|---|
| `titan_uart_test\Debug\rtthread.hex` | ✅ **唯一候选产物** | `60ad1d892cb861785ec3af9216b03c2e438859235db8fd41ed43a29a2367392a` |
| `titan_uart_test\rtthread.hex` | ⛔ **陈旧，勿刷** | `121262e133e6a54f3baf7d32204fbabf52f6ede367e4e00e9c165697e28db016` |

---

## 1. 实际修改 / 新增文件

### 在真机工程中（`D:/Micu/RTTWorkspace/titan_uart_test/`）

| 文件 | 动作 |
|---|---|
| `src/voice_*.c/.h`（15 个） | **新增**（从仓库 `smart_hand/titan_rtthread/` 部署） |
| `src/servo_bus_readonly_rt.c` | 同步为与 `src/` 一致（见 §2） |
| `Debug/src/subdir.mk` | 三张清单加入 7 个语音 `.c`；`src/%.o` 规则加 `-DVOICE_APP_ENABLE=1` |
| `rtthread.hex`（工程根） | ❌ **未动**，仍是旧版 |

### 在仓库中

| 文件 | 动作 |
|---|---|
| `smart_hand/titan_rtthread/voice_app.{c,h}` | 新增（状态机核心，纯逻辑） |
| `smart_hand/titan_rtthread/voice_app_titan.{c,h}` | 新增（RT-Thread 胶水 + 线程） |
| `smart_hand/titan_rtthread/voice_model_data.{c,h}` | 新增（按 `titan_trust_model` 先例，作为部署权威副本） |
| `smart_hand/host/check_titan_sync.ps1` | 文件清单 +15 项语音文件 |
| `tools/check_firmware_single_source.py` | 新增（§2.3） |
| `smart_hand/tests/test_voice_app_c.c` / `.py` / `test_voice_app_titan_c.c` / `stubs_voiceapp/` | 新增 |
| `smart_hand/docs/…`（本报告） | 新增 |

**未修改**：任何既有固件逻辑（`smart_hand_uart.c`、`smart_hand_protocol.*`、`servo_group_readonly.*`、`eight_servo_*`、`titan_trust_*`）、`board.h`、`fsp.ld`、任何既有测试。

---

## 2. 根目录旧源码歧义处理结果

### 2.1 核实（核实前 SHA-256）

| 文件 | 根目录 | `src/` | 关系 |
|---|---|---|---|
| `servo_bus_readonly_rt.c` | `6fa965074fe4d0b65db085e5a6c90e3b282597e3fca6443ea2e1d791e7c795b1`（1662 行） | `a1c097a1b0d01df643d3f8024d4b1714c497555d4bfd0eba5a73fe231a99c282`（1681 行） | **内容不同**（根副本是 D2 修复前） |
| `servo_bus_readonly_rt.h` | `1f0c6d7f…4e7f930d` | 同 | 相同 |
| `smart_hand_uart.c` | `de6e19ce…a61a7de7` | 同 | 相同 |

构建系统**不引用**任何根目录副本（`grep` 无命中；CDT 只编 `../src/*`，SConscript 只 `Glob('./src/*.c')`）。

### 2.2 处理：同步（§0.1 选项一）

根目录副本已同步为与 `src/` **完全一致**。旧内容留证于 `tmp/root_copy_evidence/servo_bus_readonly_rt.c.PRE_D2`（SHA-256 同上）。

> `mv`（移出工程）被权限规则拒绝，我没有绕过，改用同步。

**§0.4 遵守**：只做 `src → 根`，从未反向回拷。

### 2.3 新增防复发检查（§0.3）

`tools/check_firmware_single_source.py`：逐个比对根目录与 `src/` 的同名 `.c/.h`，任何分叉即非零退出并打印两侧 SHA-256。

**反证已做**：故意在根副本尾部追加一行 → 退出码 1 并点名 `DIVERGED servo_bus_readonly_rt.c`；复原 → 退出码 0。

---

## 3. 集成架构与线程状态机

### 3.1 两层结构（沿用既有 `voice_audio.c` / `voice_audio_titan.c` 的拆分惯例）

```
voice_app.h / voice_app.c        纯逻辑状态机。零 RT-Thread / 零 FSP / 零堆 / 无阻塞。
                                 所有外设访问经注入的 voice_app_io_t 函数表。
voice_app_titan.h / voice_app_titan.c   RT-Thread 线程、真实 I/O 表、全部静态存储。
```

### 3.2 状态机

```
DISABLED / INIT / CAPTURING / INFERENCING / RESULT / AUDIO_ERROR / MODEL_ERROR
```

三条核心策略（写在 `voice_app.h` 头部，代码逐条实现）：

| 规则 | 内容 |
|---|---|
| **R1 窗口完整性** | `peek_window` 短返回 = ring 未填满 → **不推理**，留在 `CAPTURING` |
| **R2 overrun 拼接否决** | overrun 计数在拷贝**前后各读一次**（中途发生的 gap 只有这样才看得见）→ 丢弃本轮，并隔离到「新接受样本再攒满整窗」为止（用 `accepted_samples` 基线做精确下界） |
| **R3 不发布陈旧结果** | 每次失败先 `result_valid=0` 再改状态；`result_generation` **跨重启不重置**，消费者凭代数号区分新旧 |

### 3.3 启动方式

`INIT_APP_EXPORT(voice_app_titan_init)`，与既有 `servo_bus_readonly_init` / `smart_hand_comm_init` 一致。

### 3.4 编译期开关

`VOICE_APP_ENABLE` 默认 **0**（fail-closed：仅把文件加入构建不改变行为）。集成构建在 `Debug/src/subdir.mk` 的 `src/%.o` 规则里显式加 `-DVOICE_APP_ENABLE=1`。关闭时 `voice_app_titan.o` 只剩两个访问器，**bss 为 0、无线程**。

---

## 4. RAM / Flash / 栈预算（ELF + map 实测）

### 4.1 固件总体

| 项 | D2 版 | 集成后 | 变化 |
|---|---|---|---|
| `.text` | 125,804 | **157,280** | +31,476 |
| `.data` | 1,024 | 1,024 | 0 |
| `.bss` | 137,204 | **436,216** | +299,012 |
| `rtthread.hex` | 356,857 B | **445,397 B** | +88,540 |

### 4.2 语音模块分项（map 按目标文件汇总）

| 目标文件 | text | rodata | bss |
|---|---:|---:|---:|
| `voice_model_data.o` | 0 | **16,026** | 0 |
| `voice_kws.o` | 3,514 | 32 | 0 |
| `voice_features.o` | 2,464 | 0 | 0 |
| `voice_app.o` | 1,840 | 84 | 0 |
| `voice_audio_titan.o` | 1,312 | 0 | **131,222** |
| `voice_app_titan.o` | 1,188 | 207 | **167,732** |
| `voice_audio.o` | 818 | 0 | 0 |
| **合计** | **11,136** | **16,349** | **298,954** |

- **Flash 侧 = 27,485 B**（模型 int8 权重 16,026 B，其余为代码）
- **RAM 侧 = 298,954 B**，全部落 `.bss`（静态）

### 4.3 ⚠️ 关键：堆被压缩 77%

`HEAP_BEGIN = __RAM_segment_used_end__` 随 `.bss` 增长而上移，所以静态区吃掉的正是堆：

| | D2 版 | 集成后 |
|---|---|---|
| `__RAM_segment_used_end__` | 0x22021bf4 | **0x2206abfc** |
| 固件已用 RAM | 138,232 B | **437,244 B** |
| **RT-Thread 堆**（`0x2206abfc` → `0x22080000`） | 386,060 B | **87,044 B** |

**堆未耗尽，但只剩 87,044 B（−77%）。** 现有堆消费者只有两个线程栈（`sh_servo` 2048 B、`sh_uart` 2048 B）加 RT-Thread 内部对象，余量约 79 KB，**当前够用**。但这是**集成后必须持续盯住的指标**——后续任何走堆的分配都要先算这笔账。

链接脚本 RAM 区 1,523,712 B，扣掉固件已用后剩 **1,086,468 B**。

### 4.4 线程栈

| 项 | 值 |
|---|---|
| `VOICE_APP_THREAD_STACK` | **8192 B**（静态 `g_thread_stack`，**不走堆**） |
| 编译期下限 | `#error` 挡在 6144 B 以下 |
| 线程优先级 | 22（低于 `sh_uart` 的 18） |
| 栈内主要开销 | `voice_kws_predict()` 内 `int8_t features[3920]` + 调用链，实测约 4.6 KB |

### 4.5 未改 SRAM 配置

`board.h`、`fsp.ld`、`RA_SRAM_SIZE 512` **未动**。

---

## 5. 测试与变异结果

### 5.1 主机测试（全部真实编译运行）

```
策略层 test_voice_app_c.exe            12 用例 / 277 断言   通过
胶水层 test_voice_app_titan_c.exe      启用 6 用例 / 90 断言  通过
                                       禁用 1 用例 / 13 断言  通过（bss=0）
Python 包装 test_voice_app             Ran 13 tests  OK
全语音回归                              Ran 61 tests  OK (skipped=6)
```

覆盖任务书 §4 的七条：正常启动采满窗口 / 窗口未满不推理 / overrun 丢弃并恢复 / 推理失败不发布旧结果 / `capture_start` 失败进 `AUDIO_ERROR` / 停止后重启恢复 / 禁用时状态为 `DISABLED`。

胶水层额外验证：线程参数符合要求、真实窗口能产出结果、ring overrun 阻断发布、快照后中断屏蔽配平、采集启动失败可存活。

### 5.2 变异测试（4 个，全部被抓）

| 变异 | 删除的规则 | 被抓用例 |
|---|---|---|
| M1 | R1 窗口未满不推理 | `2-short-window-is-not-inferred` FAILED（19 项） |
| M2 | R2 overrun 丢弃 | `3-overrun-discards-and-recovers` + `9-` + `10-` 共 50 项 |
| M3 | R3 推理失败仍保留旧结果 | `4-inference-failure-publishes-no-stale-result` FAILED |
| M4 | 决策可用性校验 | `5-unusable-decision-is-model-error` FAILED（6 项） |

框架防伪：needle 必须恰好命中 1 次、变异后源码必须真的改变、变异体必须编译成功（编译失败算失败而非通过）。

### 5.3 子 agent 发现的我的测试缺陷（**未修，转报**）

`smart_hand/tests/test_voice_audio_titan.py` 的 `CASE_LINE` 正则 `^\[case\] (\S+): (ok|FAILED) \((\d+) checks\)$` **匹配不上 FAILED 行**——失败行格式是 `(3 failures, 23 checks)`。后果：该套件 `test_every_case_reports_ok` 里 `failed` 列表恒为空，**失败分支是死代码**（整体仍靠 returncode 与 `"FAIL "` 兜住，不算全盲）。**建议择机修。**

---

## 6. clean build 命令、产物 mtime 与 SHA-256

```bash
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug
make all
```

> PATH 里是 `platform/env_released`（**斜杠**）。写成 `platform_env_released`（下划线）会 `make: command not found`——这个目录不存在。

**`make` 退出码 0，零告警零错误**（唯一告警是既有的 `smart_hand_uart.c:777 'sh_status' defined but not used`，因 FINSH 关闭）。

```
text 157,280 / data 1,024 / bss 436,216

Debug/rtthread.elf  10e3f6059f3fa8a7cf6046e95bb17235f8125e135197aa2904d74379313651f0
Debug/rtthread.hex  60ad1d892cb861785ec3af9216b03c2e438859235db8fd41ed43a29a2367392a   (445,397 B)
```

**唯一候选产物是 `Debug/rtthread.hex`。工程根 `rtthread.hex` 仍是 2026-09-21 的旧版，不得烧写。**

---

## 7. 未验证的真机项目

1. **真实采样率**仍是 `configuration.xml` 的配置值声明（16 kHz），**未实测**；`SINCRNG/SINCDEC/CKDIV` 与芯片复位默认值一字不差，尤其需要实测确认。
2. **未烧写**、未上电。
3. **并发**：所有测试都是单线程。`voice_app_titan_status()` 的中断屏蔽从未对抗真实并发写者。
4. **FSP PDM 绑定与状态机从未联测**：胶水测试把 `voice_audio_titan_*` 打了桩，真绑定由另一套测试覆盖，两者没有一起跑过。
5. **推理耗时**：`last_inference_ms` 只断言 `< 60000`，主机 `-O0` 与 RA8 无对应关系，无周期预算验证。
6. **堆水位**：87,044 B 是静态计算值，未在运行期观测。
7. `voice_app_titan_deinit()` 在**线程正在 poll 中途**被调用的情况未覆盖。
8. `field_accuracy_validated` / `hardware_inference_validated` 恒为 0——**未验证真实识别率**。

---

## 8. 过程记录：本批我犯的两个错误（都已修复）

1. **写坏了 `Debug/src/subdir.mk`**。该文件是**混合换行**，且 `C_SRCS` 用 `../src/` 前缀而 `OBJS`/`C_DEPS` 用 `./src/`；我的插入脚本只认后者，把 `C_SRCS` 原有 17 条替换掉了，而我当时的复核命令也找错前缀，显示出"0 条"反而掩盖了问题。**修复**：改为从 `src/*.c` 权威集合**确定性重建**三张清单（不再做插入），并统一换行为 LF。已用 `make -n all` 验证。

2. **`INIT_APP_EXPORT` 插错分支**。`voice_app_titan.c` 是 `#if ENABLE … #else … #endif` 结构，我锚定最终 `#endif` 插入，结果落在 **`#else`（禁用）分支**里。后果极具迷惑性：启用构建下该行被跳过 → 无人调用 `voice_app_titan_init` → `--gc-sections` 整个模块回收 → **固件体积与集成前逐字节相同**，而编译、链接全部"成功"。**修复**：移入启用分支（`#else` 之前）。修复后 `__rt_init_voice_app_titan_init` 进入 init 表，体积才发生实质变化。

> 教训：**"编译成功 + 链接成功 + 退出码 0"不等于集成生效。** 判断集成是否真的发生，要看 init 表符号与体积变化。

---

## 9. 遗留（不在本批内）

1. `tools/voice_memory_budget.py` 的源码/结构体清单是硬编码的，**不认 `voice_app.c` / `voice_app_titan.c` / `voice_app_t`**，其 `static_total` 仍是集成前的值。集成后 ELF 实测已成为权威，但该工具应更新以免误导。
2. `smart_hand/host/check_titan_sync.ps1` 的清单已加 15 项语音文件，**但我无法运行它**（PowerShell 执行被 deny 规则拦下，未绕过）——请自行运行确认仓库与 `src/` 一致。
3. §5.3 的 `CASE_LINE` 正则缺陷。
4. D1 排障时发现的 servo 模块另两处（TRAINSTAT 幻影成功、无忙标志回 `ACCEPTED`）仍未处理。
