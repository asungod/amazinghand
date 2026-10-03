# DeepSeek → Codex 交接报告：Titan 端侧语音 KWS 第二批（并发与划分修正）

上一批：`DEEPSEEK_TO_CODEX_TITAN_VOICE_KWS_BATCH_2026-09-22.md`
本批范围：Codex 审核提出的 6 条修正 + 一轮针对并发改动的对抗性审查

**约束遵守**：未修改任何既有固件文件、未集成、未烧写。`board.h` / `fsp.ld` 的 mtime 仍为 `2026-08-10 20:29`，`RA_SRAM_SIZE 512` 原样；真机工程 `src/` 内无任何 `voice_*` 文件。

---

## 0. 结论摘要

| Codex 条目 | 状态 | 关键证据 |
|---|---|---|
| 1. 环形缓冲并发所有权 + fail-closed + 压力测试 | ✅ 完成 | 生产者不再写 `read_index`；新增 4 项测试 |
| 2. ISR 与线程统计量快照/reset 竞态 | ✅ 完成 | 最小临界区；含 `start()`/`stop()` |
| 3. `INT16_MIN` 峰值统计 | ✅ 完成 | 字段改 `int32_t`；已实证旧码丢失峰值 |
| 4. 按 speaker ID 严格分组 | ✅ 完成 | 见 §3 |
| 5. 静态内存预算脚本 | ✅ 完成 | 见 §4，未动 `RA_SRAM_SIZE` |
| 6. 合成指标不得冒充真实准确率 | ✅ 完成 | `accuracy_interpretable_as_keyword_spotting` 三档判定 |
| **附加：对抗性审查** | ⚠️ **发现 6 个缺陷，其中 1 个致命** | 见 §2，已全部修复 |

**最重要的一条**：对抗审查发现了一个**会导致采集完全起不来**的致命缺陷（F1），是我自己写的。详见 §2。

---

## 1. 真实 diff

完整 unified diff 在 `tmp/batch2/diffs/`（批 1 → 当前）：

```
tmp/batch2/diffs/voice_audio.c.diff            64 行
tmp/batch2/diffs/voice_audio_titan.c.diff     232 行
tmp/batch2/diffs/voice_audio_titan.h.diff      46 行
```

生成方式：把批 1 版本反向重放得到 `before/`，与当前文件对比。复现：

```bash
cd <项目根>
git diff --no-index --no-color tmp/batch2/before/voice_audio.c tmp/batch2/after/voice_audio.c
```

`voice_audio.c` 的核心变更（第 1 条）：

```diff
-    /* A single push larger than the buffer can never be satisfied. */
+    /* A block larger than the whole buffer can never be accepted. */
     if (count > VOICE_RING_CAPACITY)
     {
-        samples += (count - VOICE_RING_CAPACITY);
-        count = VOICE_RING_CAPACITY;
+        ring->overrun_count += count;
+        return count;
     }
 
     write = ring->write_index;
-    read = ring->read_index;
-    pending = write - read; /* wrap-safe unsigned distance */
+    read = ring->read_index; /* read-only here; the consumer owns it */
+    pending = write - read;  /* wrap-safe unsigned distance */
 
     if ((pending + count) > VOICE_RING_CAPACITY)
     {
-        dropped = (pending + count) - VOICE_RING_CAPACITY;
-        ring->read_index = read + dropped;    /* <-- SPSC 违规 */
-        ring->overrun_count += dropped;
+        ring->overrun_count += count;
+        return count;
     }
```

**未加 diff 的文件**（新建、无前版）：`tools/voice_memory_budget.py`、`smart_hand/tests/test_voice_split.py`、`smart_hand/tests/test_voice_memory_budget.py`；以及 `train_voice_kws.py` 的划分与度量改动（该文件是新建的未跟踪文件，无入库前版可比对；改动内容见 §3）。

---

## 2. 对抗性审查结果（本批最重要的部分）

派了一个独立审查者，任务是**证伪**这批并发改动，而非复述。它读了真实固件工程（`rtconfig.py` / `ra_gen` / `ra/fsp/src/r_pdm`）逐条核对代码里的外部事实。

### F1（确定 / 致命，已修）：`VOICE_CALLBACK_GRANULARITY = 1000` 被 FSP 判为非法，采集永远起不来

`R_PDM_Start` 在配置硬件前有一道**无条件**检查：

```c
ra/fsp/src/r_pdm/r_pdm.c:259  stages_per_interrupt = 1U << p_extend->interrupt_threshold;
ra/fsp/src/r_pdm/r_pdm.c:266  FSP_ERROR_RETURN((0 == (number_of_data_to_callback % stages_per_interrupt)),
                                                FSP_ERR_INVALID_SIZE);
```

本工程 `interrupt_threshold = PDM_INTERRUPT_THRESHOLD_16`（= 4 → 16 stages），而 `1000 % 16 = 8 ≠ 0` → `R_PDM_Start` 立即返回 `FSP_ERR_INVALID_SIZE`，`start()` 返回 −23，**一个 PCM 样本都采不到**，ring 永远为空，`probe()`（自称 stage A 唯一证据来源）只会返回负值。

> 措辞更正（Codex 指出）：**这不是"16 个值里失败 8 个"，而是每一次调用都无条件失败**。`1000 % 16 == 8` 是确定性的，不存在偶尔启动成功的可能。

该检查**不受 `BSP_CFG_PARAM_CHECKING_ENABLE` 影响**（此项目里它是 0），因为它不在任何 `#if` 内。

**讽刺之处**：`voice_audio_titan.c` 自己的注释里就写了"必须是 `1<<interrupt_threshold` 的倍数"，取值却违反了它——很可能被 `16000/1000 = 16` 这个巧合误导。

**修法**：粒度改为 **800**（50 ms，同时是 16 的倍数且整除 16000），并加两道 `_Static_assert` 把它变成**编译期**错误：

```c
#define VOICE_PDM_STAGES_PER_INTERRUPT (1U << PDM_INTERRUPT_THRESHOLD_16)
_Static_assert((VOICE_CALLBACK_GRANULARITY % VOICE_PDM_STAGES_PER_INTERRUPT) == 0U, ...);
_Static_assert((VOICE_CAPTURE_SAMPLES % VOICE_CALLBACK_GRANULARITY) == 0U, ...);
```

**反证**（已实测）：把粒度改回 1000 → 编译失败 `static assertion failed: "R_PDM_Start rejects a callback granularity that is not a multiple of 1<<interrupt_threshold"`；800 → 零警告通过。

**为什么之前所有测试都没抓到**：这批文件**根本不在固件构建里**（`titan_uart_test/src/` 无 `voice_*`，`rtthread.map` 里 voice 符号数 = 0），而主机测试只覆盖 `voice_audio.c`，**`voice_audio_titan.c` 主机覆盖率为 0**。

### F2（确定 / 已修）：`reset_stats()` 会让 ISR 的缓冲游标永久错相

`pdm_callback` 原本用 `g_stats.callbacks` 反推样本落在缓冲哪一块，而 `reset_stats()` 会清零 `callbacks`。**同一个字段既当统计量又当 ISR 的寻址索引** → 采集中途任何一次 reset，ISR 之后就一直读错块，恒定延迟 `r × 62.5 ms`（r ∈ [0,15]），本会话内不自愈。

**真实可达**：`probe()` 第二次调用时——第一次 probe 按设计"留着采集"，第二次 `start()` 因 `g_running != 0` 提前返回，紧接着的 `reset_stats()` 就打在正在跑的采集上，`callbacks` 是任意非整秒相位，r ≠ 0 的概率 15/16。

审查者把它证伪到只剩**延迟**（不丢样本、不重复、不撕裂，因为回调要读的 region 与 ISR 正在写的 region 永不重合），没有夸大。

**修法**：ISR 的缓冲游标改为**独立计数器** `g_isr_block`，只由 `start()` 重置，`reset_stats()` 不碰它。统计与寻址彻底分离。

### F3（确定 / 已修）：临界区"远小于 1 微秒"的说法没有依据

`voice_rms_locked()` 在关中断状态下做 `(double)uint64 / (double)uint32`。本工程 `-mfpu=fpv5-sp-d16`，**无双精度硬件**，`__aeabi_ddiv` 确实被链入（`rtthread.map:10371`）。**修法**：改用单精度除法，并把注释改成诚实的量级估计（"几百个周期，远低于约 50 ms 的 PDM 中断周期，但不是免费"）。

### F4（确定 / 已修）：同一丢失量被记进两套计数器且永不复位

- `voice_audio.c` 在拒绝分支加 `ring->overrun_count`，同时 `pdm_callback` 把 `voice_ring_push` 的返回值加到 `g_stats.overrun_count` → 同一丢失量两套账。
- `voice_ring_reset_counters()` **全仓零调用者** → 一次 reset 后两套账永久分叉。

**修法**：`reset_stats()` 现在一并调用 `voice_ring_reset_counters()`；`samples_captured` 的注释改为如实的"麦克风交付的样本数（**包含**被 ring 拒收的）"，因为它正是采样率探测的被除数。

### F5（确定 / 已修）：测试鉴别力矩阵——容量守卫在裸奔

审查者把 `voice_audio.c` 逐条改坏，得到鉴别力矩阵：

| 变异 | 现测能抓到？ |
|---|---|
| 生产者推 `read_index`（批 1 原 bug） | ✅ |
| 拒绝却仍覆写未读数据 | ✅ |
| 截断代替拒绝 | ✅ |
| **只在 `count>CAPACITY` 分支写 `read_index`** | ❌（仅溢出测试抓到） |
| **删掉 `count > VOICE_RING_CAPACITY` 守卫** | ❌ **9 个测试全绿** |
| **把 `write_index` 发布提前到拷贝之前** | ❌ 全绿 |
| **`read_index` 在拷贝前发布** | ❌ 全绿 |

**守卫是承重的**：没有它，`pending + count` 在 uint32 里回绕——`pending=100, count=0xFFFFFFF0 → 和 = 84 ≤ 32768`，检查被绕过，拷贝循环跑约 43 亿次。

**修法**：新增 `test_absurd_push_cannot_wrap_the_capacity_check()`，直接以 `0xFFFFFFF0` 为输入。反证：删掉守卫后该测试**段错误**（退出码 139）。

**但必须说清它没证明什么**：后三个变异全绿是**结构性的**，不是遗漏——单线程顺序交错测试**构造不出**"消费者在 push 中途观察"这种时序。它证明的是"索引算术在同一条时间轴上对任意 pop/push 交错都正确（含回绕、含 fail-closed 后的守恒）"，**没有**证明原子性、可见性或发布顺序。

> 审查者还纠正了我原来注释里的一个错误论证：我写"32 位存储原子所以安全"，但**原子性 ≠ 可见性顺序**。这段代码当前安全的**真实原因**是"生产者是 ISR、消费者是同核线程，二者永不并发（ISR 不会被线程抢占），整个 push 对消费者是整体原子的"。**一旦消费者移到另一个核、或改成 DMA/双核读取，这段代码会静默损坏而无任何提示。** 注释已按此改写。

### F6（确定 / 已修）：`voice_ring_peek_latest` 头文件首句与实现矛盾

头文件写 "Copies the most recent count samples"，但可用样本不足时实现返回的是**最旧的** available 个。已改写文档，明确要求调用方**必须检查返回值**——短返回意味着缓冲未填满，拿到的是全部可读范围而非最新段。

### 审查者尝试过但**没能**证伪的（同样重要）

1. SPSC 所有权逐行核对无违规；
2. `pending + count` 回绕在当前实现下不可能发生（被守卫挡住），并用 `0xFFFFFFF0` 构造输入验证过；
3. fail-closed 无部分写入：按生产者写窗口与消费者读窗口逐一验证四种回绕关系，**包括消费者读循环中被 ISR 抢占的情形**；
4. 临界区充分：枚举 ISR 会写的每个变量的**全部读取点**，均在关中断段内；无嵌套/重入；
5. 32 位对齐原子性前提成立（从汇编量出 `write_index` 偏移 65536、`read_index` 65540，均 4 字节对齐）；
6. 代码里引用的 FSP 事实**全部为真**（`PDM_PRV_FIFO_SAMPLE_SIZE`、granularity 检查、`pdm_dat_isr` 回调时机、`R_PDM_Read` 不可用等）；
7. 代码里标为 "UNVERIFIED" 的缓冲回绕假设，被它**从驱动源码证成了**（`r_pdm_fifo_read` 线性填充、在 16000 处精确回绕，`16000 % 800 == 0` ⇒ 块不跨接缝）。

---

## 3. 第 4 条：按说话人严格分组

- `wav_corpus()` 现在返回 `(pcm, y, speakers)`，说话人由**文件名**解析（`<speaker>_<distance>_<index>.wav`，与 `tools/voice_dataset/record_keyword.py` 写出的名字严格一致）。
- **解析失败即报错退出，不静默兜底**——静默兜底要么把两个人并成一个身份，要么把一个人拆散到多个集合。
- 新增纯函数 `speaker_split()`：先按**身份**分组打乱，再展开为样本索引，因此同一说话人**必然同集合**；函数内还有集合交集自检。
- 说话人 < 2 → `SystemExit` 拒绝训练（中文可操作提示）；= 2 → 1 人训练 1 人验证，**无独立测试集且明确声明"不以验证集冒充测试集"**；≥ 3 → 另有独立测试说话人。
- 合成自检走 `synthetic_split()`，**显式不是按说话人划分**，metrics 里 `speaker_disjoint: false`。

`smart_hand/tests/test_voice_split.py` 22 项（1 项 skip），核心断言：对每个说话人，其全部样本索引与三个集合求交必须**恰好命中一个**，且被该集合**完整包含**；测试数据用**轮流交错**构造，使"按顺序切片"的实现错误立刻暴露。

---

## 4. 第 5 条：静态内存预算

`tools/voice_memory_budget.py`（+ 12 项测试）。纯正则解析宏，无硬编码数字；结构体尺寸与**真 ARM 编译器**做了 37 项交叉验证；缺文件时降级为"未确认"而非估算。

| 项 | 字节 |
|---|---|
| 语音已存在的 static（全 `.bss`） | 131,613 |
| 集成后完整预算（`.bss`） | 243,208 |
| 其中线程栈局部 | 3,944 |
| 模型数据（`.rodata`/Flash） | 15,950 |
| 链接脚本 RAM 区剩余 | 1,385,484 |
| RT-Thread 堆（**未动**） | 386,060 |
| Flash 余量 | 921,876 |

**本批新发现的优化点（两个子 agent 都没提）**：`voice_frontend_t` 占 48,868 B，其中 `mel_weight[40][257]` 一项 **41,120 B**，而它 **95.4% 是零**（10,280 个位置只有 468 个非零，每 band 中位数仅 9 个）。改稀疏表示约需 **2,032 B，可省 39,088 B（95%）**，同时减少内层乘法。尚未实施。

---

## 5. 测试命令与完整结果

```powershell
cd <项目根>

# 前端 + 环缓冲 + 划分 + 内存预算（不需要 TensorFlow）
python -m unittest smart_hand.tests.test_voice_features smart_hand.tests.test_voice_audio `
    smart_hand.tests.test_voice_split smart_hand.tests.test_voice_memory_budget

# 推理引擎 vs TFLite（需要 TensorFlow）
D:\voice_kws_env\Scripts\python.exe -m unittest smart_hand.tests.test_voice_kws

# C 主机自检
.\smart_hand\tests\test_voice_features_c.exe
.\smart_hand\tests\test_voice_audio_c.exe
.\smart_hand\tests\test_voice_kws_c.exe
```

**实测结果**

```
═══ base python ═══
Ran 40 tests in 6.594s
OK (skipped=1)

═══ venv（含 TF）═══
Ran 33 tests in 1.057s
OK (skipped=1)
  int8 logit agreement: exact 95.83%, max |diff| 1, mean |diff| 0.0417

═══ C 自检 ═══
C voice feature tests passed
C voice audio tests passed
  stress: accepted=3193698 consumed=3165234 rejected=1777537
C voice kws tests passed

═══ 设备工具链（工程真实旗标 -fsyntax-only）═══
  OK  voice_features.c
  OK  voice_audio.c
  OK  voice_audio_titan.c      <- 含 _Static_assert
  OK  voice_kws.c
  OK  voice_model_data.c
```

**变异测试**（证明测试有牙齿，不是摆设）：

| 注入的缺陷 | 结果 |
|---|---|
| 生产者重新推进 `read_index`（批 1 原 bug） | ✅ 失败（`test_producer_never_touches_read_index` 的 `before == after`） |
| 溢出时部分接受而非整块拒绝 | ✅ 失败（压力测试 `dropped == count`） |
| 删掉 `count > CAPACITY` 守卫 | ✅ 失败（新测试段错误，退出码 139） |
| 粒度改回 1000 | ✅ 编译期失败（`_Static_assert`） |

---

## 6. 未完成 / 未验证（**请勿据此宣称完成**）

1. **`voice_audio_titan.c` 主机覆盖率为 0。** F1/F2 恰好都落在这个文件里，是审查者读固件源码找出来的，不是测试抓到的。要在主机上覆盖它需要给 RT-Thread/FSP 打桩，本次未做。
2. **仍然没有任何真实识别率。** 仓库零音频资产，所有数字出自合成自检，`field_accuracy_validated` / `hardware_inference_validated` 恒为 `false`。
3. **真机采样率仍未实测。** 且该值决定 ring/缓冲/窗口的尺寸。
4. **未链接、未烧写、未上电。** 只做了 `-fsyntax-only`。
5. **集成后链接出来的真实 `.bss` 总量未确认**——131,613 / 111,595 是逐符号 sizeof+对齐求和，链接器还可能插填充。
6. **发布顺序（F5 的后三个变异）无法用单线程测试覆盖**，只能靠代码复核；审查者已复核，但这条防线是"人看过的"，不是"测试守着的"。
7. `mel_weight` 稀疏化**未实施**（§4）。
8. `g_voice_model_labels` 指向的字符串字面量字节数未计入内存预算。

---

## 7. 三个待你裁决的老问题仍然有效

1. **语音只读状态如何上报？** 固件 `RT_CONSOLE_DEVICE_NAME="null"` 且 FINSH 未开，**没有任何调试终端**，`rt_kprintf` 输出会被丢弃。任务书 §4-D 的"调试终端验证"此路不通。
2. **是否改 `board.h` 的 `RA_SRAM_SIZE`？** 本次仍**未动**，语音走静态分配绕过。
3. **首轮真机验证前是否先统一固件版本？** V_SIGN 文档记录的 `F12600ADE0…` 与现存两个 hex 都不匹配，且源码 mtime 晚于文档。

---

## 8. 审查者留下的临时目录（我删不掉）

`C:\Users\zzh\AppData\Local\Temp\va_audit\`（变异的 `voice_audio.c` 副本、驱动器、模型程序）。`rm` / `PowerShell Remove-Item` 都被权限规则拦下，**我没有绕过**。请自行删除。项目仓内它没有创建或修改任何文件。

另有两个更早的临时目录待清理：`/tmp/voice_generated_backup`、`C:/Users/zzh/AppData/Local/Temp/fake_voice_ds`。
