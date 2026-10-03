# 交给 Codex 的提示词：Titan 语音采集修复 —— 审查 + 真机复验

> 用途：把本文件整体粘贴给 Codex（主模型）。它自带全部上下文，不依赖此前的对话。
> 执行 agent 已停工等待审查。**未刷写、未接通舵机 6 V、未把语音接到机械动作。**

---

你是本项目（OpenSignHand / Titan Mini）的主模型，负责裁决与真机复验。
执行 agent 已完成"采集缓冲永久装满"这一缺陷的最小修复，现停工等你审查。**是否烧写由你决定。**

## 0. 你要产出什么

1. **对最小 diff 的审查结论**（接受 / 需返工），逐条对应 §4 的审查点，**明确写出你独立核对过什么、以及你没核对什么**；
2. **真机复验结果**：按 `TITAN_VOICE_ACCEPTANCE_RUNBOOK_2026-09-23.md` 第 5、6 节执行，逐项给"通过 / 失败 / 未测"；
3. **有效采样率的结论**：是 16 kHz 还是不是，以及**你所依据的测量方式**（不接受用回调计数当结论）；
4. 按项目惯例写下一份 `DEEPSEEK_TO_CODEX_*` 或 `CODEX_*` 状态报告。

## 1. 背景（一句话）

OpenSignHand：MaixCAM2（视觉）→ UART → Titan Mini（RA8P1 + RT-Thread，实时安全门控）→ 舵机。语音模块是 Titan 上的端侧有限词表 KWS。
仓库 `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\smart_hand\` 是**唯一正式源码**；
真机工程 `D:\Micu\RTTWorkspace\titan_uart_test\` 是**部署目标**（只编 `src/`）。

**当前板子状态**：Titan 已上电；**机械手 6 V 驱动板断电**（必须保持）；板上运行的**不是**本轮候选固件。

## 2. 交付物与哈希（可直接核对）

| 项 | 路径 | 大小 | SHA-256 |
|---|---|---|---|
| **本轮候选固件** | `D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex` | 445,442 | `B7780848B4274ECAACA51164FE484B348899690CC5B0EE0A4D9C4A4B7C2934FB` |
| 修复前候选（对比基线） | 已备份至 `outputs\Titan_Voice_Bringup_2026-09-23\candidate_60ad1d89\` | 445,397 | `60AD1D892CB861785EC3AF9216B03C2E438859235DB8FD41ED43A29A2367392A` |
| 整片回退备份（**别删**） | `outputs\Titan_Voice_Bringup_2026-09-23\pre_voice_flash.bin` | 1,048,576 | `65EF0A467D0FDF5D44597BAA4480A0DF7A43A948ADBADBA9394702D8C03565CF` |
| 交付报告 | `smart_hand\docs\DEEPSEEK_TO_CODEX_TITAN_VOICE_RING_CONSUMER_FIX_2026-09-23.md` | 29,340 | `7CEFAFF3E5EF8B81D29585AA03D5EC2B0B7668862063E57593E02429D4EDB4B9` |
| 真机验收步骤 | `smart_hand\docs\TITAN_VOICE_ACCEPTANCE_RUNBOOK_2026-09-23.md` | 11,579 | `63936CC295F84475F35F259FE87B6BDEDE46E36BFEBD8894EA5BC40C8A5880AA` |

**改动过的固件源码**（仓库 `smart_hand\titan_rtthread\` 与真机 `src\` 的 SHA-256 **全部 MATCH**，只做单向同步）：

| 文件 | SHA-256 |
|---|---|
| `voice_audio.h` | `947B1153E40C9E54D673E9606B70836E1E8C4AA5B78F0FB8044F18FE69406E73` |
| `voice_audio.c` | `85E453BE120CEBE168BB2C5E43F49EE333E4275B76D6396390F606BDDDBB4326` |
| `voice_app.h` | `3C92B37111A032A1404F65BB8C0742F5B19599483C0D6DE4422D52EBBAE78A11` |
| `voice_app.c` | `5ACB57E3B2C176A76392971E3D7D5C9CC4D24D3EF14A510EA0220DF1007F08DC` |
| `voice_app_titan.c` | `66D4A7A79AB64791C037689AB10DB780C9A10772767E262F8B41F29E80FC1DE5` |
| `voice_audio_titan.h` | `5C1507A97EB881EF776A5DDF4A41B348B88A73C085E9D38127BB16456E15D0AF` |
| `voice_audio_titan.c` | `210426CA2EBFB8D5A1E89A514C70EBE89622F95FE1DA3EADF80A161017B3C7CB` |

`voice_app_titan.h` **未改动**（`1FBD31AF…` 保持原样）。

**改动过的测试**：

| 文件 | SHA-256 |
|---|---|
| `tests\test_voice_app_c.c` | `E925960121254D77789F7AADC0D3D642CE0606DBBC8D182ABD124316603EA082` |
| `tests\test_voice_app_titan_c.c` | `761E607B7852A44E1EF248AF3CCA1CC3DF38A1E0A3FBBFBD4B3B1329D81CE9D6` |
| `tests\test_voice_app.py` | `338EAE7B5C172117D60F47A696F8565222E518DEA72589065D611CFF310AA68B` |

## 3. 本轮改了什么（根因 → 修法）

**根因**：胶水层 `voice_app_titan.c` 的取窗映射到了**非消费**的 `voice_ring_peek_latest()`，
于是**没有任何代码推进消费者游标 `read_index`**。环 `VOICE_RING_CAPACITY = 32,768`、PDM 回调一块 800 个样本，
所以接受满 32,000 个之后 `voice_ring_push()` 走 fail-closed 分支**整块拒绝**，`total_samples` 冻结；
而 `voice_app.c` 的 R2 隔离要求"新**接受**的样本攒满一整窗" —— 这个差值永不增长，**隔离条件永不可满足**，
状态机永久停在 `CAPTURING`。与真机 SWD 快照（`accepted_samples` 冻结 32,000、`overrun_count` 持续增长）一致。

**修法**：新增消费式、**全有或全无**的 `voice_ring_take_window()`；io 表字段 `peek_window` → **`take_window`**。
核心不变式：`write_index` 只在函数开头 latch 一次、绝不复读；生产者只写 `[write_index, +count)` 且溢出时
fail-closed 什么都不写，所以**永远不会写进 `[read_index, write_index)`** 这个正在被复制的区间；
`read_index` 在复制完成后**单次 32 位 store** 发布。

**明确未动**：UART 帧 / CRC / ACK / 超时 / 门控语义、舵机路径、`board.h` 的 `RA_SRAM_SIZE`、`fsp.ld`、
训练启动门控、MaixCam2。**内存侧硬证据：`data` 与 `bss` 逐字节不变**（见 §5）。

## 4. 请重点审查这 10 点

1. **`voice_ring_take_window()` 的并发正确性**：`write_index` 是否真的只读一次、`read_index` 是否在复制后单次发布、
   生产者是否可能写进正在被复制的区间。**请独立复核，不要采信注释。**
2. **改名是否彻底**：全仓 `Grep` `peek_window`，确认生产代码零残留（应只剩文档与历史记录）。
3. **`voice_audio_titan_ring()` 去掉 `const` 是否过宽** —— 是否给了不该有的写权限，或削弱了原有的只读保证。
4. **R1 语义变化**：短返回现在**恒为 0**（旧实现会返回"已经攒到的那部分"）。请确认 `voice_app.c` 的 R1 判断在新语义下
   仍然正确，且**没有别的代码依赖旧的"部分复制"行为**。
5. **R2/隔离是否引入新的活锁**：消费发生在 R2 判断**之前**，所以隔离期间仍在释放空间 —— 请确认这条推理成立，
   以及 `accepted_samples` 在隔离期内是否**一定能**推进。
6. **用例 7 是否真的在旧实现上失败**：执行 agent 已用变异 G1（把调用还原成旧写法）验证过；
   **请你独立重跑一次**（命令见 §6）。不接受"它应该会失败"。
7. **用例 9 的声明是否诚实**：宿主是协作式的，无法复现抢占式中断交错，所以它**只断言"使并发安全成立的不变式"**，
   而不是假装复现交错。请判断这样做是否足够，还是必须补真机测试。
8. **采样率的两个结论**：请复核 (a) "回调**不重复计数**"（`r_pdm.c` 数据中断是累加后整除、每满 800 条目回调一次、
   一个 FIFO 条目 = 一个 PCM 样本、`channel = 2` 是硬件通道号不产生 ×2）；
   (b) 算术 `Fout = PDM_CLKn/((SINCDEC+1)×2)`、`CKDIV=0` 语义 ÷2 ⇒ `Fout = PDMIFCLK/500` ⇒ 要 16,000 Hz 则
   **PDMIFCLK 必须正好 8 MHz**。
9. **寄存器地址表**（runbook §6a）：`R_PDM_BASE = 0x40256000`、`BASE_NS_OFFSET = 0U`、`CH[3]` 在 +0x100 且步长 0x100、
   本工程 `channel = 2`（`ra_gen\hal_data.c:587-588`）⇒ CH[2] 块基址 `0x40256300`、`PDMDSR = 0x40256320`、
   `PDSFCR = 0x40256324`。请与 `R7KA8P1KF_core0.h` 逐条对照。
10. **两处执行 agent 主动改动的接受与否**：见 §7。

**注意**：`smart_hand/titan_rtthread/voice_*.{c,h}` 在整个 git 仓库里是**未跟踪文件**（`git status` 显示 `??`），
**没有基线提交可以 `git diff`**。所以"最小 diff"是报告 §2 的逐文件改动清单 + 关键 hunk，不是机器 diff。请据此审查。

## 5. 测试与构建结果（已由执行 agent 完成，可复跑）

### 5.1 相关主机测试：10 个模块全部通过，退出码全为 0

| 模块 | 解释器 | 结果 |
|---|---|---|
| `test_voice_app` | 托管 py 3.13 | Ran 15 tests → **OK** |
| `test_voice_features` | `D:\Anaconda\python.exe` | Ran 5 tests → **OK** |
| `test_voice_audio` | 托管 py | Ran 1 test → **OK** |
| `test_voice_audio_titan` | 托管 py | Ran 4 tests → **OK** |
| `test_voice_split` | Anaconda py | Ran 22 tests → **OK (skipped=1)** |
| `test_voice_memory_budget` | 托管 py | Ran 12 tests → **OK** |
| `test_servo_group_recovery` | 托管 py | Ran 2 tests → **OK** |
| `test_run_one_cycle_d2` | 托管 py | Ran 8 tests → **OK** |
| `test_drv_usart_v2` | 托管 py | Ran 7 tests → **OK** |
| `test_voice_kws`（TFLite 对照） | `D:\voice_kws_env\Scripts\python.exe` | Ran 5 tests → **OK** |

`test_voice_kws` 自报 **int8 logits 逐位一致 95.83%，max |diff| = 1，mean |diff| = 0.0417**，与交接文档 §7 记录一致。

> 托管 Python 3.13 **没有 numpy**，`test_voice_features` / `test_voice_split` 必须用 Anaconda；
> 用错解释器会得到 `ModuleNotFoundError: No module named 'numpy'` —— 那是环境问题，不是代码问题。

### 5.2 断言与变异

- 胶水层用例 6 个 / 103 断言 → **10 个 / 391 断言**
- 策略层断言仍 **277**（未动数量）
- 变异：策略层 4 个（M1–M4）+ **胶水层 1 个（G1，抓用例 7）**，全部实测抓到

### 5.3 真机构建

- `make all` **退出码 0**，无 error、无 warning、"Nothing to be done" 0 次；日志确认 `voice_*.c` 被重新编译
- `text 157,296`（基线 157,280，**+16**）/ `data 1,024`（**不变**）/ `bss 436,216`（**不变**）
- `Debug\rtthread.hex`：445,442 B，`B7780848…934B`（基线 445,397 B / `60AD1D89…392A`）
- `Debug\rtthread.elf`：2,768,048 B，`E14F3C9A…EF3B1`（基线 2,767,628 B / `10E3F605…3651F0`）
- `Debug\rtthread.map`：1,049,384 B，`CEF5FAF2…4A92078`（基线 1,049,223 B / `1D013DDD…649E3D0`）
- **集成未静默失效**：map 中 `voice_ring_take_window` **存在**（`.text`），`voice_app_titan_init` 存在
  且 `__rt_init_voice_app_titan_init` 在**初始化表**中
- **构建可复现**：推新源文件 mtime 后重跑 `make all`，hex/elf/map **三者逐字节不变**

> ⚠️ 别被 ELF 哈希误导：本轮只往 `voice_audio.h` 加过一段注释，`.text` 与 `hex` **完全不变**，
> 但 ELF 从 `82E3805F…` 变成 `E14F3C9A…` —— 编译带 `-g -gdwarf-2`，DWARF 行号表会随注释增删位移。
> **判断"代码是否变了"看 `hex` 与 `text`，不要看 ELF 哈希。**

### 5.4 任务书逐条对照

执行 agent 已按任务书 25 条要求自查，**23 条达标、2 条部分达标（原因均为"需要真机"）**：
报告 **§9 任务书逐条对照** 有完整表格与证据。请你复核这份自查本身是否成立 —— 尤其第 14、16 条的"部分"是否合理。

## 6. 复跑命令

```bash
cd "C:/Users/zzh/OneDrive/Desktop/PCBBOM/嵌赛物联网"

# 托管 Python（无 numpy）：以下 6 个模块
python -m unittest smart_hand.tests.test_voice_app smart_hand.tests.test_voice_audio \
    smart_hand.tests.test_voice_audio_titan smart_hand.tests.test_voice_memory_budget \
    smart_hand.tests.test_servo_group_recovery smart_hand.tests.test_run_one_cycle_d2 \
    smart_hand.tests.test_drv_usart_v2

# 必须用 Anaconda（这两个 import numpy）
D:/Anaconda/python.exe -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_split

# 必须用 TensorFlow venv
D:/voice_kws_env/Scripts/python.exe -m unittest smart_hand.tests.test_voice_kws

# 真机构建（注意 platform/env_released 是斜杠，写成下划线会 command not found）
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

**环境坑（会浪费时间）**：本机 **PowerShell 拿不到 stdout**（exit 0 但无回显）→ 命令输出必须重定向到文件再用 Read 读回；
**Bash 没有 PATH**（`ls`/`head`/`grep` 全 command not found）；
**CDT/make 经 MSYS `sh` 启动时不继承 PowerShell 的 PATH**；
**宿主 gcc 在 `D:\mingw64\bin`**。

## 7. 两处需要你/用户裁决的改动

1. **测试 harness 的编码缺陷（执行 agent 修的）**：`tests/test_voice_app.py` 的 `build()`/`run()` 用
   `subprocess.run(..., text=True)` 捕获输出，而 gcc 与测试二进制会把**含非 ASCII 字符的绝对路径**打进诊断
   （本工程路径含中文）。Python 以 UTF-8 解码失败 → 读线程抛 `UnicodeDecodeError` → `stdout` 变 `None` → `parse_cases()` 崩。
   **失败模式恰好是反的：越是变异被正确抓到、越是会崩**（那时输出里正好有 `FAIL <路径>`），
   导致变异套件**根本无法被检查**（首次运行时确实是 `ERROR: setUpClass`）。
   修法是两处 `capture_output` 加 `errors="replace"`。请判断是否接受。
2. **构建环境的副作用（未清理，等用户决定）**：真机工程的 make 通过 MSYS `sh` 拉起工具链，而 `sh` 不继承
   PowerShell 的 PATH，导致 `arm-none-eabi-*` 找不到。为完成构建，在 `C:\Users\zzh\.cargo\bin\` 下创建了
   **30 个转发脚本**（`arm-none-eabi-gcc` 等，每个约 155 字节）。**执行 agent 没有删除**，请让用户决定保留或清除
   （清除时**不要动**同目录的 rust 可执行文件）。

## 8. 红线（复验时同样适用）

| 禁止 | 原因 |
|---|---|
| 在缓冲问题验收通过前接通舵机 6 V 驱动板 | 语音只是提示，安全门仍权威 |
| 把语音结果接到机械动作 | 必须人工确认 |
| 改 UART 帧 / CRC / ACK / 超时 / 门控语义 | 已验收的通信契约 |
| 改 `board.h` 的 `RA_SRAM_SIZE`、`fsp.ld` | 内存算过账；本轮 `data`/`bss` 逐字节未变 |
| 用改模型常量的方式去"凑"采样率 | 掩盖偏差，明令禁止 |
| 宣称 16 kHz 或宣称真实识别率 | 见 §9 |
| 烧写工程根 `titan_uart_test\rtthread.hex` | 09-21 旧版（350,872 B） |
| 用 `rt_kprintf` 当可观察证据 | Titan 控制台是 `null`，输出被丢弃 |

## 9. 采样率：必须按"未验证"处理的事项

- 真机测到的 **约 16,720–16,800 样本/秒** 是"回调计数 ÷ 经过时间"，**不能当实际 PCM 采样率**。
  它只可能**偏低**（FIFO 仅 32 深，中断延误丢掉的条目不计入），**不可能虚高**。
- 因此那 ~4.5% 的偏差只能来自 (a) PDM 真实速率偏快 或 (b) 计时基准偏快
  （tick = `SysTick_Config(SystemCoreClock/1000)`，端点量化本身约 ±3%，与 4.5% 同阶）。**离线无法区分。**
- **配置本身是自洽的、16 kHz 可达**（前提是 PDMIFCLK = 8 MHz）。但 **PDM 实际吃哪个时钟未验证**：
  R_PDM 的**完整寄存器映射已逐条读完，块内没有任何时钟源选择或分频寄存器**，
  唯一相关的是模块停止位 `MSTPCRC` bit 24。**这不是根因结论，只是待测项。**
- **`field_accuracy_validated` / `hardware_inference_validated` 仍为 0**，不得引用任何识别率数字。

**请优先执行 runbook §6c（播已知频率纯音 + FFT 看峰值）** —— 它是唯一与回调计数、与计时基准**都无关**的判据。

## 10. 其余未验证项（请勿当成已验证）

修复后能否真机连续运行；采样率精确值；PDMIFCLK；真实识别率；推理耗时 / 堆运行期水位 / 栈水位；
并发正确性（所有主机测试都是单线程）；"驱动在缓冲区末尾回绕"的假设（源码可证，未真机确认）；
环的稳态占空比（窗口 16,000 样本、无 hop；若真实速率确为 16.7 kHz，长期会缓慢趋满并偶发 overrun 后经 R2 恢复 —— 未在真机观察）。

---

**一句话**：根因已定位并最小修复（消费者侧改消费式取窗，"预览"与"消费"彻底分成两个操作），
390+ 条新增断言 + 一个能稳定抓住旧实现的变异测试为证，固件已构建且哈希可查、内存布局逐字节未变、
仓库与真机工程源码一致；**板子未刷写，等你裁决。**
