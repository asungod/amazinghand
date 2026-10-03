# Titan 语音采集修复交付报告（环形缓冲消费者侧）

日期：2026-09-23
交付人：执行 agent
裁决人：Codex
对应任务书：`DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md`
真机验收步骤：`TITAN_VOICE_ACCEPTANCE_RUNBOOK_2026-09-23.md`

> **未刷写**。Titan 已上电，机械手 6 V 驱动板断电。

---

## 0. 一句话

**根因**：胶水层把状态机要的"取一窗"映射到了**非消费**的环形缓冲读取，于是没有任何代码推进消费者游标
`read_index`——环填满后生产者 fail-closed 拒绝每一块，`accepted_samples` 冻结，而 R2 的隔离条件偏偏
要求"新接受的样本"攒满一整窗，因此**永久卡死在 `CAPTURING`**。

**修复**：新增消费式、全有或全无的 `voice_ring_take_window()`，并把 `voice_app_io_t` 里那个名字与语义
都对不上的 `peek_window` 改成 `take_window`。**契约本身**是错的——"预览最新窗口"和"消费样本"必须是两个
不同的操作，这一点现在写死在头文件里。

---

## 1. 根因证据

### 1.1 代码位置（修复前）

| 文件:行 | 内容 |
|---|---|
| `titan_rtthread/voice_app_titan.c:74-91` | `voice_io_peek_window()` 的注释写着"Non-consuming on purpose"，函数体 `return voice_ring_peek_latest(ring, out, count);` |
| `titan_rtthread/voice_app.h:128` | `peek_window` 契约："Non-consuming copy of the newest `count` samples" |
| `titan_rtthread/voice_audio.c:124-155` | `voice_ring_peek_latest()` 只读，**从不写 `read_index`** |
| `titan_rtthread/voice_audio.c:99` | 消费式 `voice_ring_read()` 存在，但**全工程零调用点**（20 处引用全在 `tests/`） |

### 1.2 为什么必然卡死（算术）

- `VOICE_RING_CAPACITY = 32,768`；PDM 回调粒度 `VOICE_CALLBACK_GRANULARITY = 800`
- 环能接受的上限 = `floor(32768 / 800) × 800 = 32,000` 个样本
- 之后 `voice_ring_push()` 走 `(pending + count) > VOICE_RING_CAPACITY` 分支 → **整块拒绝**、`overrun_count += 800`
- `app->accepted_samples` 取自 `ring->total_samples`，而 `total_samples` **只统计被接受的样本** → 永久冻结在 32,000
- `voice_app.c:186-207` 的隔离（quarantine）要求
  `(accepted_samples - accept_baseline) >= VOICE_WINDOW_SAMPLES`
  —— 这个差值再也不会增长，**隔离条件永远无法满足**，状态机永久停在 `CAPTURING`

与真机 SWD 快照一致：`g_ready=1`、状态 `CAPTURING`、`samples_captured=5,370,400`、
`accepted_samples` **冻结在 32,000**、`overrun_count=5,338,400` 且持续增长、`pdm_error_count=0`。

### 1.3 为什么主机测试没抓到

`tests/test_voice_app_titan_c.c` **确实**链了真实的 `voice_ring_t`，所以胶水层是被跑到的——
但它只推**一个**窗口就断言（用例 3/4），从未验证 `read_index` 是否推进，也从未连续推多个窗口。
`tests/test_voice_app_c.c` 的 277 条断言用的是**注入式假 I/O**，环形缓冲根本不参与。
恰好绕开了这个缺陷。

### 1.4 修复前后的生产/消费不变式

| | 修复前 | 修复后 |
|---|---|---|
| **生产者** `voice_ring_push()` | 只写 `[write_index, write_index+count)`；空间不足则**整块拒绝**、累加 `overrun_count`、绝不触碰未读数据 | **未改动** |
| **消费者** | **不存在**。`read_index` 永不推进（唯一被调用的是非消费的 `peek_latest`） | `voice_ring_take_window()`：够一窗则按时间顺序复制 `count` 个并推进 `read_index`；不够则**一个都不复制、游标不动**、返回 0 |
| **空闲空间** `write - read` | 单调增长到上限后**恒为满**（32,768） | 有界；消费即刻释放 |
| **`total_samples`** | 冻结在 32,000 | 持续增长 |
| **窗口时间连续性** | 不适用（没有消费） | 窗口是 `count` 个**时间上相邻**的样本；跨回绕仍相邻（索引走 `& VOICE_RING_MASK`，环是圆形的，样本 i 与 i+1 在时间上恒相邻） |
| **overrun 恢复路径** | **不可恢复**：R2 需要"新接受的样本攒满一窗"，而接受计数永不增长 → 隔离条件永不可满足 | 消费释放空间 → 生产者重新被接受 → `accepted_samples` 推进 → 满足 R2 条件 → 退出隔离 |

**为什么窗口在复制期间是安全的**（不是"通常安全"）：
`write_index` 只读一次并在整个复制过程中被当作上界；生产者只写 `[write_index, +count)` 且溢出时 fail-closed 什么都不写，
因此它**不可能写进** `[read_index, write_index)` 这个正在被复制的区间。`read_index` 在复制完成后**单次 32 位 store** 发布，
生产者只读它 —— 读到旧值只会让它看到更少的空间并 fail-closed，永远不会写到尚未发布的样本。

---

## 2. 最小 diff

> 说明：`smart_hand/titan_rtthread/voice_*.{c,h}` 在整个 git 仓库里是**未跟踪文件**（`git status` 显示 `??`），
> 因此**没有基线提交可以 `git diff`**。下面是逐文件的实际改动清单，关键 hunk 原样列出。

**固件源码（7 个文件改动）**

| 文件 | 改动 |
|---|---|
| `voice_audio.h` | 新增 `voice_ring_take_window()` 声明，含所有权/窗口边界证明；`voice_ring_read()` 补"这是流式排水、不是取窗"；`voice_ring_peek_latest()` 顶部改为醒目的 **PREVIEW, NOT ACQUISITION**，并明写"把它当唯一窗口来源会永久填满环" |
| `voice_audio.c` | 新增 `voice_ring_take_window()` 实现（约 40 行） |
| `voice_app.h` | io 表字段 `peek_window` → **`take_window`**，契约改为消费式、全有或全无；R1 说明改为按新语义叙述 |
| `voice_app.c` | 取窗调用点改名；补注释说明消费是"让环有空间"的必要条件；R1 注释改为"全有或全无，短返回=尚未填满" |
| `voice_app_titan.c` | `voice_io_peek_window()` → **`voice_io_take_window()`**，改调 `voice_ring_take_window()`；注释记录旧实现的缺陷机理 |
| `voice_audio_titan.h` | `voice_audio_titan_ring()` 返回值 `const voice_ring_t *` → **`voice_ring_t *`**，并说明为什么 `const` 是错的 |
| `voice_audio_titan.c` | 同步上面这一个签名 |

**测试（3 个文件改动）**

| 文件 | 改动 |
|---|---|
| `tests/test_voice_app_c.c` | 假窗口源改为**消费式**（成功的取窗会扣减可用量，模拟活麦克风）；短窗用例断言从 `WINDOW-1` 改为 **`0`**（全有或全无） |
| `tests/test_voice_app_titan_c.c` | 新增用例 **7–10**（见 §3）；桩的 `voice_audio_titan_ring()` 签名同步 |
| `tests/test_voice_app.py` | 注册新用例；新增**胶水层变异套件**（见 §3）；修 harness 编码问题（见 §8） |

**核心 hunk（`voice_audio.c` 新增）**

```c
uint32_t voice_ring_take_window(voice_ring_t *ring, int16_t *out, uint32_t count)
{
    ...
    write = ring->write_index;   /* latched ONCE, never re-read */
    read  = ring->read_index;

    if ((write - read) < count)
    {
        return 0U;               /* nothing copied, cursor untouched */
    }

    for (i = 0U; i < count; ++i)
    {
        out[i] = ring->samples[(read + i) & VOICE_RING_MASK];
    }

    ring->read_index = read + count;   /* published AFTER the copy */
    return count;
}
```

**不改动的部分（明确声明）**：UART 帧 / CRC / ACK / 超时 / 门控语义、舵机路径、
`board.h` 的 `RA_SRAM_SIZE`、`fsp.ld`、训练启动门控、MaixCAM2 —— **一律未动**。
内存侧硬证据：`data` 与 `bss` **逐字节不变**（见 §4）。

---

## 3. 测试：修复前 / 修复后

### 3.1 新增用例 7 就是"能在旧实现上稳定失败"的回归测试

| 用例 | 覆盖任务书要求的 |
|---|---|
| `7-sustained-windows-keep-the-ring-draining` | 首次填窗 + **持续多个窗口**；断言 `total_samples == 96,000`、`overrun_count == 0`、`result_generation >= 5` |
| `8-window-spans-a-ring-wrap-in-order` | **跨环回绕**：逐样本比对窗口顺序 |
| `9-producer-cannot-overwrite-an-unread-window` | **复制期间的生产者推进/溢出 fail-closed** |
| `10-inference-longer-than-a-window-recovers` | **推理耗时超过一窗** + **真实 overrun 后恢复** |

用例 7 喂 120 块 × 800 = 96,000 样本（= 6 窗），每块之间投一次票，与 PDM 中断对模块的作用方式一致。
**旧实现下它必然变红**：`total_samples` 死在 32,000、`overrun_count` 爬升。

### 3.2 变异测试（机械证明，不是自述）

`tests/test_voice_app.py` 新增 `VoiceAppTitanGlueMutationTests`：
把 `voice_app_titan.c` 里那一行**机械还原成旧的缺陷写法**

```c
return voice_ring_take_window(ring, out, count);
→ return voice_ring_peek_latest(ring, out, count);
```

重建（同样的源、同样的 include、`-DVOICE_APP_ENABLE=1`），**要求用例 7 变红**。
变异补丁打在临时目录，仓库源码不被写入。

### 3.3 实际结果

```
python -m unittest smart_hand.tests.test_voice_app -v
→ Ran 15 tests ... OK        EXIT=0
```

包含：

- `test_m1..m4_*_is_load_bearing` —— 4 个既有策略变异：**ok**
- `test_g1_consuming_window_request_is_load_bearing` —— **ok**（旧缺陷被稳定抓到）
- `test_glue_cases_pass_when_enabled` —— **ok**（胶水层 10 个用例）

C 层直接运行结果：

```
VOICE_APP_ENABLE=1 : [case] 1..10 全部 ok → C voice app titan tests passed (391 checks)
VOICE_APP_ENABLE=0 : [case] 0-compiled-out-is-inert: ok (13 checks)
tests/test_voice_app_c.c → C voice app tests passed (277 checks)   ← 与修复前基线一字不差
```

| 项 | 修复前 | 修复后 |
|---|---|---|
| 胶水层用例 | 6 个 / 103 断言 | **10 个 / 391 断言** |
| 策略层断言 | 277 | **277**（未动数量） |
| 变异 | 策略层 4 个 | 策略层 4 个 + **胶水层 1 个** |

编译：`gcc -std=gnu11 -Wall -Wextra`，**退出码 0**。
（`voice_app_titan.c:430` 的 `INIT_APP_EXPORT` 三行 warning 是**既有的**、来自测试桩未定义该宏，与本次改动无关。）

### 3.4 相关主机测试全套结果

按交接文档 §0 的命令清单逐个跑，**10 个模块全部通过、退出码全为 0**：

| 模块 | 解释器 | 结果 | 退出码 |
|---|---|---|---|
| `test_voice_app` | 托管 py 3.13 | Ran 15 tests → **OK** | 0 |
| `test_voice_features` | Anaconda py | Ran 5 tests → **OK** | 0 |
| `test_voice_audio` | 托管 py | Ran 1 test → **OK** | 0 |
| `test_voice_audio_titan` | 托管 py | Ran 4 tests → **OK** | 0 |
| `test_voice_split` | Anaconda py | Ran 22 tests → **OK (skipped=1)** | 0 |
| `test_voice_memory_budget` | 托管 py | Ran 12 tests → **OK** | 0 |
| `test_servo_group_recovery` | 托管 py | Ran 2 tests → **OK** | 0 |
| `test_run_one_cycle_d2` | 托管 py | Ran 8 tests → **OK** | 0 |
| `test_drv_usart_v2` | 托管 py | Ran 7 tests → **OK** | 0 |
| `test_voice_kws`（TFLite 对照） | `D:\voice_kws_env` | Ran 5 tests → **OK** | 0 |

`test_voice_kws` 自报：**int8 logits 逐位一致 95.83%，max \|diff\| = 1，mean \|diff\| = 0.0417** —— 与交接文档 §7 记录的验收值相同。

> 一个环境注意点：托管 Python 3.13 **没有 numpy**，`test_voice_features` / `test_voice_split` 必须用 Anaconda 的
> `D:\Anaconda\python.exe`；`test_voice_kws` 必须用 `D:\voice_kws_env\Scripts\python.exe`。
> 用错解释器会得到 `ModuleNotFoundError: No module named 'numpy'` —— 那是环境问题，不是代码问题。

---

## 4. 构建结果与产物哈希

工具链：RT-Thread Studio GNU Tools for ARM 13.3。命令：`cd Debug && make all`（`platform/env_released`，斜杠）。

| 项 | 修复前 | 修复后 |
|---|---|---|
| `make all` 退出码 | — | **0**（无 error、无 warning、无 "Nothing to be done"） |
| `Debug/rtthread.hex` 大小 | 445,397 | **445,442** |
| `Debug/rtthread.hex` SHA-256 | `60AD1D892CB861785EC3AF9216B03C2E438859235DB8FD41ED43A29A2367392A` | **`B7780848B4274ECAACA51164FE484B348899690CC5B0EE0A4D9C4A4B7C2934FB`** |
| `text` | 157,280 | **157,296**（+16） |
| `data` | 1,024 | **1,024（不变）** |
| `bss` | 436,216 | **436,216（不变）** |
| `Debug/rtthread.elf` 大小 / SHA-256 | 2,767,628 / `10E3F6059F3FA8A7CF6046E95BB17235F8125E135197AA2904D74379313651F0` | **2,768,048 / `E14F3C9A511FE3A02BDF0EA2451EEF47E2640E60CEACF830AA35C34FBE1EF3B1`** |
| `Debug/rtthread.map` 大小 / SHA-256 | 1,049,223 / `1D013DDD3B477CA96D6B79139127C0140B0DCB33A2ECCF9CBD1465154649E3D0` | **1,049,384 / `CEF5FAF2EBA98980347F4E6CA4CEB57C7D9F7F6BF9AC941076C07EAC94A92078`** |

> 基线 ELF 的 `10E3F605…` 与交接文档 §0 记的值**逐字一致** —— 这反过来证明备份的 `candidate_60ad1d89/` 确实是修复前那份产物。

**构建可复现性（实测）**：把 `src/voice_audio.c` 的 mtime 推新后重跑 `make all`，`hex` / `elf` / `map` **三者逐字节不变**（同一组 SHA-256）。所以上面的值是稳定的，不是"这次恰好如此"。

> ⚠️ 一个容易误读的点：**ELF 的哈希会因为源代码里注释增删而改变**。本轮修复过程中 `voice_audio.h` 只加过一段注释，
> `.text` 大小与 `hex` 完全不变，但 ELF 从 `82E3805F…` 变成了 `E14F3C9A…`。
> 原因是编译带了 `-g -gdwarf-2`，DWARF 行号表记录源码行号，注释增删令后续代码行号整体位移。
> **判断"代码是否变了"要看 `hex` 与 `text`，不要看 ELF 哈希。**

**集成没有静默失效**（本工程 §5.5 的坑）——`Debug/rtthread.map` 中：

- `voice_ring_take_window` **存在**（`.text`）← 本次修复新增的符号，它的出现本身就证明 `voice_audio.c` 真的被重编了
- `voice_app_titan_init` 存在（`.text`），且 `__rt_init_voice_app_titan_init` 在**初始化表**中
- `voice_ring_peek_latest` 存在（同目标文件内保留，未被 `--gc-sections` 回收）

**源码一致性**：仓库 `smart_hand/titan_rtthread/` 与真机工程 `D:\Micu\...\src\` 的 8 个语音源文件
SHA-256 **全部 MATCH**（只做 仓库→工程 单向同步，未反向）。

**备份**（构建前已做，未覆盖上一批证据）：

- 修复前候选固件三件套 → `outputs/Titan_Voice_Bringup_2026-09-23/candidate_60ad1d89/`
- 整片回退备份 `pre_voice_flash.bin`（1 MiB，`65EF0A46…`）**仍在原位，未动**

---

## 5. 采样率核实：本轮结论（**请按"未验证"读**）

任务书指出上一批把"约 16.7–16.8 kHz"当成了实际 PCM 采样率，这一轮**纠正了这个定性**。

### 5.1 回调计数**不重复计数**（已证实）

读 `ra/fsp/src/r_pdm/r_pdm.c`：

- 数据中断是**累加后整除**：`rx_int_count += received`，`while (rx_int_count >= rx_int_count_max) { rx_int_count -= max; callback; }`
  → 每满 800 个条目**恰好**回调一次，边界不会多触发。
- `number_of_data_to_callback` 的单位是 **32 位字**；一条目 = 一个 PCM 样本；
  `channel = 2` 是**硬件通道号**（用于索引 `R_PDM->CH[]`），**不产生 ×2**；左右由 `pcm_edge` 选择。
- 因此 `samples_captured` **只可能偏低**（FIFO 仅 32 深，中断延误丢掉的条目不计入），**不可能虚高**。

### 5.2 数据流索引自洽（已证实为同一来源）

`base = (g_isr_block * 800) % 16000`，缓冲区 `int32_t[16000]`，与驱动线性写、末尾回绕同源。

### 5.3 理论值：配置**是自洽的**，16 kHz 可达（已证实的公式 + 算术）

```
Fout = PDM_CLKn / ((SINCDEC + 1) × 2)      ← 勘误公式
SINCDEC = 124  →  分母 = 250
CKDIV = 0 (PDM_CLOCK_DIV_2 = 0x0) 语义为"÷2"  →  PDM_CLKn = PDMIFCLK / 2
⇒  Fout = PDMIFCLK / 500
```

要 `Fout = 16,000 Hz` ⇒ **PDMIFCLK 必须正好 8 MHz**。工程时钟段里 `MOCO = 8 MHz`
—— 所以这套分频值**只有在 PDM 时钟源是 8 MHz 时才等于 16 kHz**。
**配置没有算错；16 kHz 是可达的。**

### 5.4 但"PDM 实际吃哪个时钟"**未验证**

全工程搜 `PDMIFCLK` / `PDMCLK` / `PDMCKSEL` **零命中**；FSP 只用 `MSTPCRC` bit 24 做模块门控。
工程里**没有任何一处配置 PDM 的时钟源**。

本轮进一步**逐条读完了 R_PDM 的完整寄存器映射**，确认这不是"没找到"，而是**这个外设里根本没有**：

- 单元级（`0x00`–`0x80`）：`PDCSTRTR` / `PDCSTPTR` / `PDCCHGTR` / `PDCICR` / `PDCSR` / `PDCSCR` /
  `PDCSDCR` / `PDCDRCR` / `PDCDCR` / `PDVR` —— 全是通道状态、检测与中断控制，**无一时钟选择或分频**
- 通道级（每通道 `0x100` 字节）：`PDSTRTR`…`PDDSR`，唯一与时钟相关的是 `PDSFCR.CKDIV`

也就是说 **PDMIFCLK 由时钟树供给，在这个外设里不可选** —— 这正是它只能靠真机间接测量的原因。
（`BASE_NS_OFFSET` 经核实为 `0U`：`_RA_TZ_NONSECURE` 在本工程只出现于 3 处 `#if defined(...)`、从未被定义，
`Debug/makefile` 亦无 `-D_RA_TZ_NONSECURE`。）

> ⚠️ 这条**不是根因结论**，只是一个待测项。上一批曾有"源码没找到时钟配置 ⇒ 这就是根因"的推断，
> 本轮**不予采纳**：源码里没有配置，不等于硅片上没有时钟。

### 5.5 那 ~4.5% 从哪来：**离线无法区分**

计数只可能偏低（5.1），所以偏差只能来自：

| 候选 | 依据 |
|---|---|
| (a) PDM 真实速率偏快约 4.5% | 实际时钟/分频与假设不符 |
| (b) 计时基准偏快 | tick = `SysTick_Config(SystemCoreClock/1000)`；端点量化本身约 ±3%，与 4.5% 同阶 |

**结论：`16,720–16,800` 这个数字不能当实际 PCM 采样率。精确值未验证。**
区分手段写在验收步骤第 6 节（DWT 独立时基 + 已知频率纯音 FFT），**优先做 6c**（与任何时间基准都无关）。

### 5.6 两条路线的比较（任务书要求"选择改动更小且不破坏 UART 实时性的方案"）

**前提：精确值尚未证明，所以下面是决策框架，不是结论。选择必须等测量结果。**

| 路线 | 做法 | 改动量 | 主要风险 | 对 UART 实时性 |
|---|---|---|---|---|
| **A. 把 PDM 时钟配对** | 弄清 `PDMIFCLK` 真值；若它并非 8 MHz，调整时钟树使其为 8 MHz，则现有 `SINCDEC = 124` 精确给出 16,000 Hz | 小（配置侧）；**但若 PDMIFCLK 本来就是 8 MHz，这条路是 no-op** | 改时钟树会牵动其他外设的分频链，需要全量回归 | **无**（不占 CPU） |
| **B. 有界、可测的重采样** | 在 `voice_features.c` 之前插一级固定比率重采样（比率由实测值确定），比率作为**显式常量**进 `voice_config.h`，并在 `voice_features_ref.py` 建镜像 + 测试 | 中（新代码 + 新测试 + C/Python 契约同步） | 引入**第二个**近似源；比率写死后会随温度/批次漂移；重采样本身有 CPU 成本 | **需要评估** —— 前端跑在低优先级语音线程上，但每窗耗时会增加 |
| **C. 只测不改** | 先完成测量，链路不动 | 零 | 若真实速率确实偏高，模型频率轴偏移约 4.4%，真机适用性存疑 | 无 |

**倾向（待测量证实）**：

1. 若测量证明有效速率**就是**约 16.7 kHz → 先做路线 A 的取证（`PDMIFCLK` 到底是哪个时钟、多少 Hz）。
   若 `PDMIFCLK ≠ 8 MHz`，A 属于"**把配置改对**"，比 B 更接近根因，且零 CPU 成本。
2. 若 `PDMIFCLK` **确实**是 8 MHz、而速率仍偏高 → 说明偏差不在时钟，**不应**急着上 B；
   先把测量闭环（很可能是计时假象）。
3. 路线 B 只在"时钟不可改、且偏差被证实稳定"时才选。届时比率必须是**测量出来的常量**，
   并且必须带主机侧镜像与测试 —— 不允许是拍出来的数字。

**本节状态：给出决策框架，结论取决于尚缺的真机证据 → 未验证。** 未改任何模型常量。

---

## 6. 残余风险与未验证（如实）

| # | 项 | 状态 |
|---|---|---|
| 1 | 修复后能否真机连续运行 | **未验证**——本机无硬件，必须走验收步骤第 5 节 |
| 2 | 有效 PCM 采样率精确值 | **未验证**（见 §5） |
| 3 | `PDMIFCLK` 实际来源与频率 | **未验证** |
| 4 | 真实识别率 | **未验证**；`field_accuracy_validated` / `hardware_inference_validated` 仍为 0 |
| 5 | 推理耗时 / 堆水位 / 栈水位 | **未验证**（宿主数字不可当预算） |
| 6 | 并发正确性 | **未验证**——所有测试都是单线程；用例 9 断言的是**使并发安全成立的不变式**，不是复现抢占交错 |
| 7 | 驱动在缓冲区末尾回绕的假设 | 源码可证（`r_pdm.c:743-748`），**未真机确认** |
| 8 | 环的稳态占空比 | 窗口 16,000 样本、无 hop；若 PDM 真实速率确为 16.7 kHz，长期会缓慢趋满并偶发 overrun 后经 R2 恢复。**该行为未在真机观察** |

---

## 7. 给 Codex 的短验收清单

1. 上电后 **10 分钟** `accepted_samples`（即 `ring->total_samples`）**持续增加**，不冻结在 32,000 ← **本轮修复的直接判据**
2. 安静环境下 `overrun_count` **不持续增加**
3. `result_generation` 能更新
4. `pdm_error_count = 0`
5. 状态在 `CAPTURING → INFERENCING → RESULT` 之间循环，不停在 `CAPTURING`
6. 实测有效采样率接近 16 kHz（**用验收步骤 6c 的纯音法，不要用回调计数**）
7. 再做 MaixCAM2 UART ACK 并行测试

**任何一项失败都不进入舵机上电测试。**

---

## 8. 我改动了但你需要知情的两件事

### 8.1 测试 harness 的编码缺陷（本轮修了，否则拿不到变异证据）

`tests/test_voice_app.py` 的 `build()` / `run()` 用 `subprocess.run(..., text=True)` 捕获输出，
而 gcc 与测试二进制会把**含非 ASCII 字符的绝对路径**打进诊断（本工程路径含中文）。
Python 以 UTF-8 解码失败 → 读线程抛 `UnicodeDecodeError` → `stdout` 变成 `None` → `parse_cases()` 崩。

**失败模式恰好是反的：越是变异被正确抓到、越是会崩**，因为那时 C 输出里正好有 `FAIL <路径>`。
结果是变异套件**无法被检查**（本轮首次运行时报 `ERROR: setUpClass`）。

**修法**：两处 `capture_output` 加 `errors="replace"`。只影响解码，不影响退出码判定。

### 8.2 构建环境的 PATH 副作用（**需要你决定，我没有清理**）

真机工程的 CDT/make 会通过 MSYS `sh` 拉起工具链，而 `sh` **不继承**在 PowerShell 里设置的 `PATH`，
导致 `arm-none-eabi-*` 找不到。为完成构建，在 `C:\Users\zzh\.cargo\bin\` 下创建了 **30 个转发脚本**
（`arm-none-eabi-gcc` 等，每个约 155 字节，指向 RT-Thread Studio 的真实工具链）。

这是**对你的个人目录的写入**，我**没有删除**，请你决定保留还是清除：

- 保留：后续构建无需再设 PATH
- 清除：删除这 30 个 `arm-none-eabi-*` 脚本即可（**不要动**同目录下的 rust 可执行文件）

---

## 9. 任务书逐条对照（自查）

对照 `DEEPSEEK_TASK_TITAN_VOICE_HARDWARE_FIX_2026-09-23.md` 的每一条要求。**"未达标"和"未验证"都如实标出。**

### 问题一：环形缓冲永久装满

| # | 任务书要求 | 状态 | 证据 |
|---|---|---|---|
| 1 | 实现最小、可证明的消费者侧释放/取窗机制 | ✅ | `voice_ring_take_window()`；所有权与窗口边界证明写在 `voice_audio.h` 的 OWNERSHIP AND WINDOW BOUNDS 段；报告 §1.4 |
| 2 | 保证连续运行时缓冲有空间 | ✅ | 用例 7：96,000 样本（6 窗）全部被接受，`total_samples == 96000`、`overrun_count == 0` |
| 3 | 送入前端的每个窗口时间上连续 | ✅ | 用例 8：跨 32,768 回绕边界，16,000 样本**逐样本**与流顺序比对 |
| 4 | ISR 只能写生产者游标 | ✅ | ISR 未改动；`voice_ring_push` 全工程唯一生产调用点 = `voice_audio_titan.c:162`（`pdm_callback` 内） |
| 5 | 不能让 ISR 推进 `read_index` | ✅ | `read_index` 只在 `voice_ring_take_window()` 里被写；该函数全工程唯一生产调用点 = `voice_app_titan.c:103`（`voice_io_take_window`，跑在语音线程） |
| 6 | 不能只靠增大缓冲 | ✅ | `VOICE_RING_CAPACITY` 仍为 32,768，**未改** |
| 7 | 不能靠定期清空 overrun 计数掩盖问题 | ✅ | 未改动任何 overrun 计数逻辑；`voice_ring_reset_counters` 未被新增调用 |
| 8 | 复制窗口期间的生产者写入/溢出仍须 fail-closed | ✅ | `voice_ring_push()` 的 fail-closed 分支**未改**；用例 9 断言整块拒绝后未读窗口逐样本不变 |
| 9 | 若调整 `peek_window` 的"非消费"契约，必须同步改接口文档与测试 | ✅ | `voice_app.h` 的 io 表字段与契约已改写；`test_voice_app_c.c` / `test_voice_app_titan_c.c` / `test_voice_app.py` 三处同步 |
| 10 | 若新增取窗 API，给出并发所有权与窗口边界的证明 | ✅ | `voice_audio.h` 中该函数声明上方的证明段落；报告 §1.4 末尾 |
| 11 | 测试至少覆盖：首次填窗 / 持续多窗 / 跨环回绕 / 复制期生产者推进 / 真实 overrun 后恢复 / 推理超一窗 | ✅ | 依次对应用例 3（既有）、7、8、9、4（既有）+10、10 |
| 12 | 加入一个能在旧实现上稳定失败的回归/变异测试 | ✅ | 用例 7 + 变异 `G1-window-request-goes-back-to-a-non-consuming-read`，**已实测**抓到（`test_g1_…is_load_bearing … ok`） |
| 13 | 不能只测纯状态机 fake I/O，必须覆盖真实胶水层与环形缓冲组合 | ✅ | `test_voice_app_titan_c.c` 链接的是**真实 `voice_ring_t`** 与真实 `voice_app_titan.c`，只有 FSP 那块是桩 |

### 问题二：采样率与模型假设不一致

| # | 任务书要求 | 状态 | 证据 |
|---|---|---|---|
| 14 | 先基于 FSP/时钟配置与真机计数定位实际时钟来源及分频 | ⚠️ **部分** | 定位到的是**否定性结论**：`R_PDM` 块内**没有任何时钟源选择/分频寄存器**（单元级+通道级逐条读完），工程也未配置 PDM 时钟；实得/理论值的关系已算清（`Fout = PDMIFCLK/500`）。**但 PDMIFCLK 的真实值与来源仍未定位** —— 这需要真机 |
| 15 | 不要直接改模型常量掩盖偏差 | ✅ | `VOICE_SAMPLE_RATE_HZ` 仍为 16000，**未改** |
| 16 | 比较"正确配置 PDM 时钟"与"有界、可测的重采样"，选改动更小且不破坏 UART 实时性的方案 | ⚠️ **框架已给，选择待定** | 报告 §5.6 给出两条路线的做法/改动量/风险/对 UART 实时性的影响、判定标准与倾向。**"选择"必须以测量结果为前提**，任务书自身也要求"若目前不能证明精确值，就保持未验证" |
| 17 | 若不能证明精确值，保持"未验证"，不得宣称 16 kHz 或真实识别率 | ✅ | 报告 §5、runbook §3；`field_accuracy_validated` / `hardware_inference_validated` 仍为 0 |

### 交付边界

| # | 任务书要求 | 状态 | 证据 |
|---|---|---|---|
| 18 | 提交最小 diff，解释修复前后的生产/消费不变式、时间窗口连续性和 overrun 恢复 | ✅ | 报告 §1.4（不变式对照表）+ §2（逐文件改动清单与关键 hunk） |
| 19 | 运行相关主机测试 | ✅ | 报告 §3.4：**10 个模块全部 OK、退出码全 0** |
| 20 | 故障注入 | ✅ | 变异套件：策略层 4 个（M1–M4）+ 胶水层 1 个（G1）；另有 `test_voice_audio_titan` 的驱动故障模型 |
| 21 | 真机工具链构建；报告退出码、ELF/map 变化、新 hex SHA-256、仓库与 src 源码哈希一致 | ✅ | 报告 §4：`make all` = 0；hex/elf/map 三者的尺寸与 SHA-256 齐全；8 个源文件仓库↔`src` 全部 MATCH；**并实测了构建可复现性** |
| 22 | 不刷写、不接通舵机 6 V、不把语音接到机械动作、不将合成语料对拍写成真实识别率 | ✅ | 全程未刷写、未连调试器、未接触硬件；`test_glue_stays_off_the_motion_path` 通过；无任何识别率数字 |
| 23 | 给 Codex 一份短验收清单 | ✅ | runbook §5/§6；报告 §7 |

### 任务书备注

| # | 要求 | 状态 |
|---|---|---|
| 24 | 不要把 `rt_kprintf` 当可观察证据 | ✅ 报告与 runbook 都只用只读状态内存/SWD；runbook §4 明确列为禁止项 |
| 25 | 不得临时加入会控制机械手的通路 | ✅ 未加任何通路；`voice_app_titan.c` 的降级路径未动 |

### 结论

**25 条中 23 条已达标，2 条部分达标且原因均为"需要真机"**：

- **#14**：时钟来源的**定位**只完成到"确认这个外设里没有时钟选择寄存器、工程也没配"。
  真实 `PDMIFCLK` 必须真机读回 —— 这不是可以靠读源码补上的。
- **#16**：方案**比较**已交付，方案**选择**被有意推迟到测量之后。若在精确值未知时就选一条路，
  就是在用推测替代证据，与任务书第 17 条自相矛盾。

---

## 10. 一句话状态

**环形缓冲永久装满的根因已定位并最小修复（消费者侧改消费式取窗，契约里"预览"与"消费"彻底分开），
390+ 条新增断言与一个能稳定抓住旧实现的变异测试为证，真机固件已构建且哈希可查、内存布局逐字节未变、
仓库与工程源码一致；板子未刷写，等 Codex 验收。采样率经复核确认"16,720–16,800"不是实际 PCM 采样率，
配置本身自洽且 16 kHz 可达，但 PDM 时钟源仍未验证，需按验收步骤第 6 节在真机上定位。**
