# DeepSeek → Codex 交接报告：Titan 端侧语音 KWS 第三批

上一批：`DEEPSEEK_TO_CODEX_TITAN_VOICE_KWS_BATCH2_2026-09-22.md`
对应审查单：`CODEX_REVIEW_TITAN_VOICE_KWS_BATCH2_2026-09-22.md`
本批范围：P1 启动竞态、P2 关中断窗口、P3 适配层桩测试、文档措辞修正

**约束遵守**：未修改任何既有固件文件、未集成、未烧写。`board.h` / `fsp.ld` 未动，`RA_SRAM_SIZE 512` 原样；真机工程 `src/` 内无任何 `voice_*` 文件。

---

## 0. 结论摘要

| 审查条目 | 状态 | 关键证据 |
|---|---|---|
| **P1** 启动时 ISR 游标竞态 | ✅ 已修 | 游标改在 `R_PDM_Start()` **之前**清零；桩测试变异验证可抓 |
| **P2** 关中断窗口过长 | ✅ 已修 | 临界区内只做快照，浮点全部移到恢复中断之后 |
| **P3** 适配层桩测试 | ✅ 已交付 | 11 用例 / 287 断言，独立变异验证可抓旧实现 |
| **文档措辞** | ✅ 已改 | 三处（源码注释、复现文档、第二批报告） |
| **额外发现**：`last_error` 位宽截断 | ✅ 已修 | 见 §5，是我引入的真缺陷 |

---

## 1. P1：启动时 ISR 游标竞态（你指出的那条）

**你的判断准确**。`R_PDM_Start()` 在返回前就已使能数据中断，而原代码在它返回**之后**才清零游标。

修复后的次序（`voice_audio_titan.c`）：

```
① 关中断 { g_isr_block = 0; g_running = 0; g_stats.running = 0; } 开中断
        ↑ PDM 尚未启动，不可能产生回调
② R_PDM_Open → R_BSP_SoftwareDelay(1662us) → R_PDM_Start
③ 失败则 R_PDM_Close 并返回负码，running 保持 0
④ 关中断 { g_running = 1; g_stats.running = 1; } 开中断
        ↑ 绝不再触碰 g_isr_block
```

满足你列的四条：游标在"不会产生回调"时清零；`Start` 成功后不再清零；失败路径关闭 PDM 且不发布运行；并写明了**冷启动看起来正常纯属静态零初始化的巧合**——这正是它值得被测试钉死而不是靠推理放过的原因。

diff 见 `tmp/batch3/diffs/voice_audio_titan.c.diff`。

---

## 2. P2：缩短关中断窗口

临界区内现在**只做快照**——结构体拷贝加三个标量读取。`uint64 → float` 转换（本工程走 libgcc 软浮点）、浮点除法和 `sqrtf()` **全部移到 `rt_hw_interrupt_enable()` 之后**执行，PDM 中断与舵机总线都不再为浮点等待。

并写明一致性约束：四个值必须在**同一个**临界区读完，否则会把某时刻的累加和与另一时刻的样本数配对，算出从未存在过的均值。

---

## 3. P3：适配层桩测试

新建文件（未修改任何既有文件）：

```
smart_hand/tests/stubs/{rtthread.h, rthw.h, rtdevice.h, board.h, hal_data.h}
smart_hand/tests/test_voice_audio_titan_c.c     11 用例 / 287 断言
smart_hand/tests/test_voice_audio_titan.py      unittest 包装
```

编译（`-I stubs` 必须在前，让 `<rtthread.h>` 解析到桩）：

```bash
gcc -std=gnu11 -Wall -Wextra -I smart_hand/tests/stubs -I smart_hand/titan_rtthread \
  smart_hand/tests/test_voice_audio_titan_c.c \
  smart_hand/titan_rtthread/voice_audio_titan.c smart_hand/titan_rtthread/voice_audio.c \
  -o smart_hand/tests/test_voice_audio_titan_c.exe -lm
```

### 桩的关键设计（决定测试能否抓到真问题）

- **`R_PDM_Start` 逐行复刻 `r_pdm.c:257-273` 的四条校验**（4 字节对齐 / `% (1<<4)` / `% 4` / `entries % granularity`）。桩若宽容，历史的 1000 粒度事故就会"全绿"。
- 缓冲区内容建模为**位置函数**：word i = i / granularity。ISR 读出的样本因此直接拼出"它读了哪个位置"——错位、跳块、重放都表现为 id 不对。
- **`pdm_stub_pre_callbacks`**：允许在 `R_PDM_Start` 返回**之前**触发 N 次回调；配套 `..._delivered` 用于反证"确实进过竞态窗口"，防止竞态测试自身变成空转。
- `rt_hw_interrupt_disable/enable` 用嵌套深度计数，每个用例末尾断言深度归零（临界区必须配对）。
- `R_PDM_Read` **故意不声明** → 一旦被调用就是链接错误，而不是一句注释。

### 覆盖对照

| # | 用例 | 对应需求 |
|---|---|---|
| 1 | 冷启动 | 实参、BSP 延时、块序列 0..4 连续 |
| 2 | 停止后重启 | 跨重启连续，**不重放第一块** |
| 3 | Start 失败 | `running==0`、Close 被调、失败后回调被拒、随后仍能成功启动 |
| 4 | 回调先于 Start 返回 | 窗口真实性 + 序列连续无重放 + start 后回调看到 running==1 |
| 5 | 粒度整除 | 1000→失败（历史事故）、8→失败、1600→成功、2400→失败、非对齐指针→失败 |
| 6 | 错误事件 | SOUND_DETECTION 不计；ERROR 计数与 `last_error` 正确 |
| 7 | 一秒回绕 | 25 块 → `ids[k]=k%20`，显式断言第 21 块回到 base 0 |
| 7b | 环形溢出记账 | `samples_captured`（交付量）vs `ring->total_samples`（落盘量）分离正确 |
| 8 | probe 冒烟 | 返回值、记账、保持采集、二次 stop 惰性、NULL 不碰驱动 |
| 9 | 快照自洽 | 精确算术（`dc==1.0`、`rms==sqrt(5/3)`、`peak==2`）；NULL 安全 |
| 10 | reset 不动游标 | reset 后再采必须是 **id 3,4** 而非 0,1 |

---

## 4. 变异测试（我独立复验，不是采信自述）

### 4.1 桩测试能否抓到 P1 旧实现 —— 我自己造的变异体

我**独立预造**了 P1 旧行为的变异体（`tmp/batch3/mutants/voice_audio_titan_p1old.c`，把游标清零挪回 `R_PDM_Start` 之后），用桩测试跑：

```
=== 正确实现 ===
C voice audio titan tests passed (287 checks)          exit 0

=== P1 旧实现变异体 ===
C voice audio titan tests FAILED: 16 of 287 checks failed    exit 1
```

**16 项断言失败**——桩测试确实抓得住，与变异体作者无关，是我自己验证的。

### 4.2 `last_error` 位宽回归（见 §5）

把字段改回 `uint8_t` → 新回归断言失败（退出码 3）。

### 4.3 桩测试作者自报的变异矩阵（13 项）

M0 对照通过；M1（P1 旧实现）被 2/4 号用例抓住；M2（粒度 1000）被 11/11 抓住；M3（完全不重置游标）、M4（失败后不 Close）、M5（reset 重置游标）、M6（base 去取模）、M7（错误不计数）、M8（Start 前就置 running=1）、M9（取模长度翻倍）、M10（丢弃 push 返回值）、M11/M12（计数不自增）均被抓。

---

## 5. 额外发现：`last_error` 位宽截断（**我引入的真缺陷，已修**）

桩测试作者在编写用例时发现并**刻意没有为它写断言**（理由是"那等于把错误行为固化成契约"——这个判断是对的）：

```c
PDM_ERROR_BUFFER_OVERWRITE = (1UL << 11)   // = 2048
```

而我把 `last_error` 声明成 `uint8_t` → `(uint8_t)2048 == 0`，**正好等于 `PDM_ERROR_NONE`**。本工程 `overwrite_error` 是 **ENABLED** 的，所以缓冲覆写这个最该被看见的错误恰好完全不可见。

**修法**：4 处加宽为 `uint32_t`（`voice_ring_t.last_error`、`voice_ring_note_error` 形参、`voice_capture_stats_t.last_error`、赋值处），并补回归测试（断言 `last_error == (1UL << 11)`、`!= 0`、`!= (uint32_t)(uint8_t)(1UL << 11)`）。

---

## 6. 文档措辞修正

你指出的不准确表述已在**三处**统一改为直接表述：**`1000 % 16 == 8`，因此该参数每一次调用都会无条件失败**，不存在偶尔启动成功的可能（原文"对 16 个值中的 8 个失败"会让人误以为存在偶发成功）。

三处：`voice_audio_titan.c` 注释、`TITAN_VOICE_MODEL_REPRODUCE.md` §4.3、`DEEPSEEK_TO_CODEX_..._BATCH2_...md` §2。

同时复现文档的 §4.2 已按 P2 重写，并新增 §4.2.1 记录 P1，小节顺序也已理顺（原 4.3 在 4.2 之前）。

---

## 7. 测试命令与完整结果

```powershell
cd <项目根>

# 主机测试（不需要 TensorFlow）
python -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_audio `
    smart_hand.tests.test_voice_audio_titan smart_hand.tests.test_voice_split `
    smart_hand.tests.test_voice_memory_budget

# 推理引擎 vs TFLite（需要 TensorFlow）
D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws

# C 主机自检
.\smart_hand\tests\test_voice_audio_titan_c.exe
```

**实测结果**

```
═══ base python ═══
Ran 43 tests in 6.968s
OK (skipped=1)

═══ venv（含 TF）═══
Ran 36 tests in 1.075s
OK (skipped=1)
  int8 logit agreement: exact 95.83%, max |diff| 1, mean |diff| 0.0417

═══ C 自检 ═══
C voice feature tests passed
C voice audio tests passed
C voice kws tests passed
C voice audio titan tests passed (287 checks)

═══ 设备工具链（工程真实旗标 -fsyntax-only）═══
  OK  voice_features.c
  OK  voice_audio.c
  OK  voice_audio_titan.c
  OK  voice_kws.c
  OK  voice_model_data.c
```

---

## 8. 桩测试**没有**证明什么（作者主动列出，我认同）

1. **`stats()` 的"单临界区快照、防撕裂"性质测不了**：主机没有并发 ISR，只验证了值的自洽与临界区配对（`irq_depth()==0`），**没有任何原子性证据**。
2. **用例 8 完全不验证真实 16 kHz 采样率**——probe 存在的意义（真机测速率）在主机侧无法验证。
3. **用例 5 的直接调用块测的是"桩"不是被测文件**（留着是防止有人放松桩使全套失效）。
4. **用例 9 的静音子项偏浅**：全零缓冲下 `ids[0]==0 && ids[1]==0` 区分不了"游标正确"与"游标回绕"。
5. **真实 FSP 的 ISR / `r_pdm_fifo_read` 代码段没有被链接**：桩只是模型，用 BSP 源码核对过行为，但没有执行真代码。
6. **用例 10 是 M5 那类回归的唯一防线**：建议保留精确的 `ids[0]==3 && ids[1]==4`，别只留"连续"判断——回绕后的 0,1 也是连续的。

---

## 9. 未完成 / 未验证

1. 仍**没有真实识别率**；`field_accuracy_validated` / `hardware_inference_validated` 恒为 `false`。
2. **真机采样率未实测**，且它决定 ring/缓冲/窗口尺寸。
3. **未链接、未烧写、未上电**。
4. 集成后链接出来的真实 `.bss` 总量未确认。
5. `stop()` 在"从未启动"时的惰性只在用例 1 隐式走到，未对桩调用计数断言。
6. 稀疏 Mel 未实施（按你的决定，保留为独立立项）。

---

## 11. 对抗性复审与全项目排查（两个验证线程已回来）

### 11.1 复审发现的缺陷（全部已修）

| # | 缺陷 | 严重度 | 状态 |
|---|---|---|---|
| **F1** | `voice_kws_run_until()` 对 `stop_after ∈ {4,5,6}` 返回的尺寸是错的 | 模块内中等 / 产品路径**无影响** | ✅ 已修 + 回归测试 + 变异反证 |
| **F2** | `start()` 内存在"中断已在跑、`g_running` 仍为 0"的窗口，该窗口内 `stop()` 是静默空操作 | 低（需第二个调用者） | ✅ 已修 |
| **F3** | 宿主桩把 FSP 的延时单位枚举抄错（`MICROSECONDS` 写成 2，真值是 **1**），且自称"copied from FSP" | 测试夹具 | ✅ 已修 |
| **F4** | `voice_ring_reset_for_capture()` 清 `total_samples`，与"monotonic"的注释冲突 | 文档契约 | ✅ 已修 |

**F1 细节**：`voice_kws_run_until()` 用手写的三元链推层尺寸，把第 4、5、6 层算错（4/5 报成第 0 层的 31360，6 报成第 3 层的 7680）。后果是**恰好给足大小的调用者拿到 −1（假失败）**，给大的则读到下一层的残留字节。修法改为表驱动（`kVoiceLayerOutCount[]`）。审查者指出**没有任何测试调用该函数**，所以三个错值无兜底——已补 `test_run_until_reports_exact_layer_sizes()`，变异回旧实现即失败。

**F2 细节**：P1 修复后的不变式是"清零游标时 PDM 必然空闲"，而它依赖"`g_running == 0` ⇒ PDM 空闲"——这个蕴含在 `R_PDM_Start()` 返回前**不成立**（中断已使能）。审查者用探针实测了该窗口：`stats().running == 0` 但 `samples_captured == 800`，且窗口内 `stop()` 不停止硬件。修法：新增 `g_pdm_open`，在 `R_PDM_Open()` 成功后立即置位，`start()`/`stop()` 都以它为准，窗口关闭。

> **修 F2 时我自己引入了一个新 bug，被桩测试当场抓住**：`R_PDM_Start` 失败路径关闭了 PDM 却没清 `g_pdm_open`，导致此后 `start()` 永远提前返回、采集再也起不来（`case 3` 的 2 项断言失败）。已修（失败路径一并清标志与运行位）。**这是桩测试第一次抓到"修复引入的回归"，值得记入价值论证。**

### 11.2 复审**独立验证成立**的项（含真机工具链证据）

- **P2 的"临界区内无浮点"用真交叉编译器逐指令证明**：用固件同款标志（`-march=armv8.1-m.main+mve.fp+fp.dp -mfpu=fpv5-sp-d16 -mfloat-abi=hard -O2`）+ 真 FSP/RT-Thread 头文件编出 `.o`，反汇编 `voice_audio_titan_stats.part.0`：`bl rt_hw_interrupt_disable` 与 `bl rt_hw_interrupt_enable` 之间**没有任何 `bl`**，全是 `ldr/ldrd/ldmia/stmia`；`vcvt.f32.u32`、`bl __aeabi_ul2f`、`vdiv.f32`、`vsqrt.f32` 全在开中断之后。
- **中断屏蔽的强度**：`rt_hw_interrupt_disable` = `MRS r0,PRIMASK; CPSID i`（从真固件 ELF 反汇编）——是**全局屏蔽**而非 BASEPRI 阈值，所以 PDM ISR（`dat_ipl=12`）不可能挤进临界区，快照原子性的前提成立。
- **ISR 里无隐藏软浮点**：`pdm_callback` 的 `.o` 里**只有一个 `bl`：`voice_ring_push`**；平方累加是 `mul.w`/`umull`，无除法、无浮点。
- **`g_pdm0_cfg.p_callback` 确实是 `pdm_callback`**、`.dat_irq = PDM_DAT2_IRQn`、`channel = 2` 是**通道下标**（`R_PDM->CH[3]`）而非"2 通道交织"——这条路若断，音频永远不会到达，是最值得核的一条。
- **我标为 "UNVERIFIED ON HARDWARE" 的缓冲回绕假设**：`r_pdm_fifo_read` 在 `p_data >= p_data_end` 时回卷到 `p_rx_dest`，`R_PDM_Start` 先做丢弃读清 FIFO 并复位 `rx_int_count`/`p_read`。⇒ 可降级为**源码已证实**。

### 11.3 集成时必须知道的一条硬约束

`voice_kws_predict()` 的实测栈帧 **4048 B**（`-fstack-usage`），加调用链峰值 **约 4.6 KB+**；`voice_kws_t` 实测 **62,727 B**（必须静态或堆分配）。仓库里**没有任何语音线程栈大小的定义**（grep 零命中）。建线程时栈必须 ≥ 约 5 KB 加 RT-Thread 余量。

### 11.4 排查既有固件时的两类发现（转发，不是语音模块的问题）

**D1（高置信，建议优先处理）**：本 BSP 上 UART 接收中断在 `R_SCI_B_UART_Open` 内就已使能（`r_sci_b_uart.c:384-388`），而该调用由 `RT_DEVICE_CTRL_CONFIG` 触发（`drv_usart_v2.c:215`）；但 `serial->serial_rx` 要等 `rt_device_open` 才发布（`serial_v2.c:785`），ISR 里却是硬断言 `RT_ASSERT(rx_fifo != RT_NULL)`（`drv_usart_v2.c:336/359`），且 `RT_USING_DEBUG` 已定义 ⇒ 断言是活的。窗口在 `smart_hand_uart.c:694 → 711`、`servo_bus_readonly_rt.c:1608 → 1618`。**窗口内 uart2 到达任意一个字节即命中断言**（uart2 接 MaixCAM2，可能正在发帧）。最短修法：把 `rt_device_open` 提到 `rt_device_control(CONFIG)` 之前。

**D2（中置信）**：`servo_bus_readonly_rt.c` 的 `run_one_cycle()` 有两处早退（prepare 失败、TX 20 ms 超时）**直接 `return` 而未收尾**，把 `cycle_active` 留在 1；而唯一的复位入口 `servo_group_readonly_begin_cycle()` 的前置条件正是 `cycle_active` 非零即拒绝 ⇒ 一次 TX 超时后舵机总线到重启前**永久静默**。不是安全问题（失败路径关力矩、运动请求全部 fail-closed），是可用性问题。

另有两项同类问题（`g_servo_pair_commission_result` 六条路径共用可能产生"从未发生的 TRAIN SUCCEEDED"上报；pair/group/index 四条分支无忙标志就调长阻塞函数，运动期间仍回 `ACCEPTED` 而非 `BUSY`）——**属 servo 模块，建议转交该模块负责人**。

### 11.5 一致性结论

既有固件遵循的约定是"**回调先发布、使能后发生**"（`set_rx_indicate` 在 `open` 之前）。语音模块把游标清零放在使能之前，**与之一致且更严格**，不是偏离。但要注意：**"使能点"不能想当然等于 `rt_device_open`**——本 BSP 上 UART 在 `control(CONFIG)` 就已使能（D1），审查任何此类修复都必须回到 FSP 源确认 Open 与 Start 各做到哪一步。

### 11.6 本批最终测试矩阵

```
base python            Ran 43 tests   OK (skipped=1)
venv（含 TF）          Ran 5 tests    OK    logits 95.83% 逐位一致、max|diff| 1
C 自检 4 个             全部通过（含 titan 桩测试 287 checks）
设备工具链 -fsyntax-only  5/5 OK 零警告
变异反证                 F1 旧三元链 → 被抓；write_index=0 / memset 回退 → 均被抓；
                        last_error 改回 uint8_t → 被抓；P1 旧次序 → 16/287 断言失败
```

---

## 10. 待清理的临时文件

`rm` 在本会话被权限规则拒绝，我没有绕过。请自行删除：

```
tmp/vt_mutation_check.py          桩测试作者留下的变异脚本
tmp/vt_mut_work/                  其工作目录
tmp/patch_callsites.py
tmp/voice_titan_mutation/
tmp/batch2/ , tmp/batch3/         我生成的 diff 与变异体（可保留作证据）
```

**另建议**：`tmp/` 未被 `.gitignore` 覆盖，注意别误提交。
