# Titan 语音采集修复 —— 真机验收步骤（**尚未刷写**）

日期：2026-09-23
适用固件：`Debug\rtthread.hex`，SHA-256 `B7780848B4274ECAACA51164FE484B348899690CC5B0EE0A4D9C4A4B7C2934FB`（445,442 B）

> **状态：未刷写。** 本文件只描述"如果决定刷写，该怎么做、怎么判"。是否烧写由 Codex / 用户审核后决定。
>
> **板子现状**：Titan 已上电；**机械手 6 V 驱动板全程断电**。这个状态必须保持，直到第 5 节全部通过。

---

## 1. 本轮改了什么（一句话）

胶水层 `voice_io_take_window()` 从**非消费预览** `voice_ring_peek_latest()` 改为**消费式取窗**
`voice_ring_take_window()` —— 消费者真正推进 `read_index`。

其余一律未动：UART 帧 / CRC / ACK / 超时 / 门控语义、舵机路径、`board.h` 的 `RA_SRAM_SIZE`、`fsp.ld`
**全部零改动**。内存侧有硬证据：`data` 与 `bss` 逐字节不变（见第 2 节）。

---

## 2. 产物与哈希

| 项 | 值 |
|---|---|
| 修复前候选固件 | `Debug\rtthread.hex` 445,397 B，SHA-256 `60AD1D892CB861785EC3AF9216B03C2E438859235DB8FD41ED43A29A2367392A` |
| **本轮候选固件** | `Debug\rtthread.hex` **445,442 B**，SHA-256 **`B7780848B4274ECAACA51164FE484B348899690CC5B0EE0A4D9C4A4B7C2934FB`** |
| 修复前备份 | `outputs\Titan_Voice_Bringup_2026-09-23\candidate_60ad1d89\`（hex / elf / map 三件） |
| 整片回退备份 | `outputs\Titan_Voice_Bringup_2026-09-23\pre_voice_flash.bin`，1,048,576 B，SHA-256 `65EF0A467D0FDF5D44597BAA4480A0DF7A43A948ADBADBA9394702D8C03565CF` —— **别删** |
| 体积 | text 157,296（修复前 157,280，**+16**）/ data **1,024 不变** / bss **436,216 不变** |

⛔ 工程根 `titan_uart_test\rtthread.hex` 是 2026-09-21 的旧版（350,872 B，`121262E1…`），**禁止烧写**。

---

## 3. 先读：未验证事项（**不要当结论用**）

| 项 | 状态 |
|---|---|
| **有效 PCM 采样率的精确值** | **未验证** |
| **16,000 Hz 是否真的达到** | **未验证** |
| PDM 实际时钟源（PDMIFCLK 来自哪个时钟） | **未验证** |
| 真实识别率 | 未验证，`field_accuracy_validated` / `hardware_inference_validated` 仍为 **0** |
| 推理耗时 / 堆运行期水位 / 栈水位 | 未验证 |
| 并发正确性 | 未验证 —— 所有主机测试都是单线程 |
| "驱动在缓冲区末尾回绕"的假设 | 源码可证（`r_pdm.c:743-748`），**未经真机确认** |

### 3.1 关于"约 16,720–16,800 样本/秒"这个数字

**它不是实际 PCM 采样率**，而是"回调计数 ÷ 经过时间"。它由回调里 `samples_captured += 800` 累加得来。

已证实的事实（来自 `ra/fsp/src/r_pdm/r_pdm.c`）：

- 数据中断是**累加后整除**：`rx_int_count += received`，`while (rx_int_count >= 800) { rx_int_count -= 800; callback; }`，
  即每满 800 个 FIFO 条目**恰好**回调一次，边界不会多触发 —— **不存在重复计数**。
- 一个 32 位 FIFO 条目 = **一个** PCM 样本；`channel = 2` 是**硬件通道号**（用于索引 `R_PDM->CH[]`），
  **不产生 ×2**；左右由 `pcm_edge` 选择。
- 所以 `samples_captured` **只可能偏低**（FIFO 仅 32 深，中断延误时丢掉的条目不计入），**不可能虚高**。

于是那 ~4.5% 的偏差只可能来自两处，**且离线状态下无法区分**：

| 候选 | 说明 |
|---|---|
| (a) PDM 真实速率确实偏快 | 实际时钟/分频与配置假设不符 |
| (b) 计时基准偏快 | tick 由 `SysTick_Config(SystemCoreClock/1000)` 驱动（`rtconfig.h` 的 `RT_TICK_PER_SECOND = 1000`）；端点量化本身约 ±3%，与 4.5% 同阶 |

第 6 节的目的就是把这两者分开。

### 3.2 理论值：把上面的账算平

勘误公式：

```
Fout = PDM_CLKn / ((SINCDEC + 1) × 2)
```

本工程 `SINCDEC = 124`（`ra_gen\hal_data.h:81`）→ 分母 = **250**。
`CKDIV` 的语义是"PDM_CLKn 相对上级时钟的分频"，`PDM_CLOCK_DIV_2 = 0x0` 即 **÷2**（`ra\fsp\inc\instances\r_pdm.h:35-38`）
→ `PDM_CLKn = PDMIFCLK / 2`，于是：

```
Fout = PDMIFCLK / 500
```

要 `Fout = 16,000 Hz` ⇒ **PDMIFCLK 必须正好是 8 MHz**。

工程时钟段里 `MOCO = 8 MHz`（`configuration.xml` 时钟树），**所以这套分频值只有在 PDM 的时钟源是 8 MHz 时才等于 16 kHz**。
换句话说：**配置本身是自洽的、16 kHz 是可达的**，前提是 PDM 吃到 8 MHz。

但 —— **全工程没有任何一处配置 PDM 的时钟源**（搜 `PDMIFCLK` / `PDMCLK` / `PDMCKSEL` 无命中；
FSP 只用 `MSTPCRC` bit 24 做模块门控）。所以"PDM 实际吃哪个时钟"必须真机读回确认。
**这不是根因结论，只是一个待测项。**

---

## 4. 红线

| 禁止 | 原因 |
|---|---|
| 接通舵机 6 V 驱动板 | 语音只是提示，安全门仍权威；缓冲问题未验收前不得上电 |
| 把语音结果接到机械动作 | 必须人工确认，且本轮不含此路径 |
| 改 UART 帧 / CRC / ACK / 超时 / 门控 | 已验收的通信契约 |
| 改 `board.h` 的 `RA_SRAM_SIZE`、`fsp.ld` | 内存算过账；`data`/`bss` 本轮逐字节未变 |
| 改模型常量去"凑"采样率 | 掩盖偏差，本项目明令禁止 |
| 宣称 16 kHz 或宣称真实识别率 | 见第 3 节，均未验证 |
| 烧写工程根的旧 `rtthread.hex` | 09-21 旧版 |
| 用 `rt_kprintf` 当可观察证据 | Titan 控制台是 `null`，输出被丢弃 |

---

## 5. 刷写后：功能验收（**这一步决定能不能进第 6 步**）

用 SWD **只读**取证，连续观察 **10 分钟**。建议每 60 秒取样一次。

| # | 检查项 | 期望 | 判据 |
|---|---|---|---|
| 1 | `ring->total_samples`（即 `accepted_samples`） | **持续单调增长** | 10 分钟内不冻结。**这是本轮修复的直接判据**——修复前它会死在 32,000 |
| 2 | `ring->overrun_count` | 安静环境下**不持续增长** | 允许上电瞬间的少量；不允许单调爬升 |
| 3 | `result_generation` | 能**更新** | 说明有窗口被消费并完成推理 |
| 4 | `pdm_error_count` | **= 0** | 非 0 则采集中断有错 |
| 5 | `state` | 在 `CAPTURING → INFERENCING → RESULT` 之间**循环** | 不允许长期停在 `CAPTURING` |
| 6 | `pdm_last_error` | 应为 0（`PDM_ERROR_NONE`） | 注意 `PDM_ERROR_BUFFER_OVERWRITE` 是 bit 11，字段必须是 `uint32_t` 才看得见 |

**任何一项失败 → 停止，不进入第 6 步，不接通舵机 6 V，把数据回传给 Codex。**

> 提示：pyOCD 的 `AP#2 / SVD` 告警在读取、烧写、校验**成功时也会出现**，不要仅凭这些告警判断失败。

---

## 6. 采样率定位（**独立于回调计数**）

### 6a. 确认 FSP 真的把分频值写进了寄存器

寄存器定位（全部有出处，`R7KA8P1KF_core0.h` 路径下同）：

- `R_PDM_BASE = (0x40256000UL + BASE_NS_OFFSET)`（`:64847`）
- `BASE_NS_OFFSET = 0U`（`:64695`）—— 该分支在 `#if defined(_RA_TZ_NONSECURE)` 下才取另一值，
  而 `_RA_TZ_NONSECURE` **在本工程全文只出现在 3 处 `#if defined(...)` 判断里、从未被定义**
  （`bsp_mcu_family_cfg.h:62`、`R7KA8P1KF_core1.h:64894`、`R7KA8P1KF_core0.h:64692`），
  `Debug/makefile` 里也没有 `-D_RA_TZ_NONSECURE`。**故 `R_PDM_BASE = 0x40256000`。**
- 通道块 `R_PDM_CH_Type CH[3]` 位于单元 **+0x100**，`R_PDM_CH_Type` 大小 = `0x100`（`:63030`、`:3850`）
  → 通道 n 的块基址 = `0x40256000 + 0x100 + 0x100 × n`

**本工程使用的通道 = 2**（已确认，不再是假设）：

- `ra_gen\hal_data.c:587-588`：`.unit = 0`、**`.channel = 2`**
- 旁证：`hal_data.c:611/618` 用的中断向量是 `PDM_DAT2_IRQn` / `PDM_ERR2_IRQn`（带通道 2 后缀）
- FSP 以 `p_extend->channel` 索引 `R_PDM->CH[]`（`r_pdm.c:125`）

于是 **通道 2 的块基址 = `0x40256300`**，各寄存器绝对地址如下：

| 寄存器 | 块内偏移 | **绝对地址** | 用途 |
|---|---|---|---|
| `PDMDSR` | `0x20` | **`0x40256320`** | `SFMD` [6:4]（`:3642`）期望 4 = order-4 sinc |
| `PDSFCR` | `0x24` | **`0x40256324`** | `CKDIV` [3:0]、`SINCDEC` [23:16]、`SINCRNG` [28:24]（`:3663/3665/3666`） |
| `PDSR` | `0x14` | `0x40256314` | 通道状态：`STATE`/`SDF`/`DRF`/`BFOWDF`（缓冲覆写标志，bit 27）（`:3598-3611`） |
| `PDSCR` | `0x18` | `0x40256318` | 状态清除（`BFOWDFC` bit 27）（`:3617-3629`） |
| `PDDBCR` | `0xC0` | `0x402563C0` | `DATRITHR` [2:0] 接收中断阈值（`:3761/3765`） |
| `PDDRCR` | `0xE0` | `0x402563E0` | `DATRE` [0] 数据读使能（`:3808-3812`） |
| `PDDRR` | `0xE8` | `0x402563E8` | **数据读寄存器** `DAT` [19:0]（`:3830-3834`） |
| `PDDSR` | `0xEC` | `0x402563EC` | `DATNUM` [7:0] 缓冲区中数据条数（`:3841-3846`） |
| `PDSTRTR` / `PDSTPTR` | `0x00` / `0x04` | `0x40256300` / `0x40256304` | 软启动 / 软停止触发 |

（其余通道供参考：CH[0] 块基址 `0x40256100`、CH[1] `0x40256200`。）

**期望读回**：`PDMDSR.SFMD = 4`、`PDSFCR.CKDIV = 0`、`PDSFCR.SINCDEC = 124`、`PDSFCR.SINCRNG = 5`。

**能排除什么**：FSP 的配置没有生效（例如复位默认值留在寄存器里）。
**不能排除什么**：`PDMIFCLK` 的真值。

> **为什么这个块里找不到 PDM 的时钟选择寄存器**：这个单元的完整寄存器映射已逐条读过 ——
> 单元级只有 `PDCSTRTR`/`PDCSTPTR`/`PDCCHGTR`/`PDCICR`/`PDCSR`/`PDCSCR`/`PDCSDCR`/`PDCDRCR`/`PDCDCR`/`PDVR`，
> 通道级就是上表那些。**整块没有任何时钟源选择或分频寄存器**；唯一与 PDM 时钟相关的是模块停止位
> `MSTPCRC` bit 24（`ra\fsp\src\bsp\mcu\all\bsp_module_stop.h:329-331`）。
> 也就是说 PDMIFCLK 由**时钟树**决定，不在这个外设里可选 —— 这正是它只能靠真机间接测量的原因。

### 6b. 换一个独立于 RT-Thread tick 的时间基准

tick 可能偏快（见 3.1 (b)）。改用 **DWT 周期计数器**：

1. 使能：写 `DWT->LAR = 0xC5ACCE55`，然后 `DWT->CTRL |= 1`
2. 间隔 **≥30 秒**读两次 `DWT->CYCCNT`，同时读 `g_stats.samples_captured`
3. `Δt = ΔCYCCNT / SystemCoreClock`，`实测速率 = ΔN / Δt`

| 结果 | 结论 |
|---|---|
| `≈16,000` 而 tick 法 `≈16,700` | 问题在 tick / 端点量化，**采样率是 16 kHz** |
| 仍 `≈16,700` | PDM 确实偏快约 4.5%，需要动分频 |

### 6c. 不依赖任何时间基准的判据（**最有说服力，优先做**）

用扬声器播**已知频率的纯音**（例如 1,000 Hz），录制后用修复后的链路做 FFT 看峰值位置：

| 峰值落在 | 结论 |
|---|---|
| **1,000 Hz** | 真实速率 = 前端假设的 16 kHz，前端频率轴正确 |
| **约 1,045 Hz** | 实际约 16.7 kHz，前端频率轴整体偏移 ≈4.4% |

这一条与回调计数、与计时基准**都无关**，是唯一能直接判定"是不是 16 kHz"的手段。

### 6d. 判定标准

- 比值落在 **1 ± 0.5%** → 16 kHz，达标
- 稳定在 **1.045 左右** → 需要改 `SINCDEC`，或先确认 `PDMIFCLK` 真值
- **不能排除**：麦克风 / PDM 时钟抖动 —— 需要示波器量 PDMCLK 引脚

> 若三步仍不能给出精确值，**就保持"未验证"**，不要用推断填补，也不要改模型常量。

---

## 7. 只有第 5、6 节全过之后才考虑

1. MaixCAM2 UART ACK 并行测试
2. 舵机 6 V 驱动板上电测试（另行审核）

---

## 8. 本轮明确**不做**

- 不刷写（由 Codex / 用户决定）
- 不接通舵机 6 V
- 不把语音接到机械动作
- 不用改模型常量掩盖采样率偏差
- 不宣称 16 kHz、不宣称真实识别率
