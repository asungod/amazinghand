# 支持类别 mock 安全拒绝测试计划（39 / 41 / 65）

- 日期：`2026-08-14`
- 对象：MaixCAM2 ↔ Titan Mini，`uart2` / `115200`，三线 `GND` + 交叉 `TX/RX`
- **计划状态：`ARCHIVED_AUTHORIZED_SUMMARY`**
- **归档：`validation_reports/supported_class_mock_2026-08-15.md`，证据索引 `E0006`。**
- 文件性质：**测试计划 + 2026-08-15 状态同步**。原 `not_run` 字段不得改写成未给出的计数器或未附原始日志。
- 本文件作者：计划编写者；2026-08-15 状态同步：grokB。两者均 **未执行任何硬件操作，未修改任何生产代码**，
  `hardware_accessed=false`。

## 0. 当前状态、执行前置门与命题

### 0.1 当前已验证 / 未验收状态

| 项 | 状态 | 依据 |
|---|---|---|
| MaixCAM2 ↔ Titan `uart2` **短时双向 ACK** | **已验证** | `validation_reports/uart2_bidirectional_acceptance_2026-08-14.md`：`sent=104` / `acked=104` / `timeout=0` / `malformed=0` / `rx_errors=0`；证据等级为用户提供的真机终端输出、经主模型审核 |
| `class=3` **策略层**拒绝路径 | **已验证** | 同上：`unsupported_class` / `NO_ACTION` / `actionable=0` |
| **长期热稳定 / 长期可靠性** | **未验收** | 10 分钟无舵机通信与热观察已通过，不得外推为长期可靠性或整机验收 |
| 10 分钟无舵机 UART2 通信与热观察（门 1） | **已通过** | `validation_reports/uart2_10min_no_servo_stress_2026-08-14.md`：第二次 `sent=2126` / `acked=2126` / 约 11 分 49 秒 PASS；第一次约 7 分 59 秒 FAIL |
| 断联恢复 | 未验收 | 同上 |
| 姿态层拒绝路径（本计划目标） | **短时窗口已观察** | `validation_reports/supported_class_mock_2026-08-15.md`：三类 `reason=accepted` / `pose=NOT_CONFIGURED` / `actionable=0`；不是姿态或舵机验收 |
| 舵机执行 | 未验收，全程禁止 | 真机 `PAUSED_FOR_THERMAL_SAFETY_REVIEW` |

**结论：短时 UART 双向 ACK 与 10 分钟无舵机通信/热观察已归档；39/41/65 三轮
10 秒策略链路已按授权摘要归档。** 长期热稳定、断联恢复、姿态数值和舵机仍未验收。
本文不再作为“尚未执行”的纸面计划；也不得把归档摘要改写成完整 15 条 PASS。

### 0.2 执行前置门（两道，缺一不可）

**门 1 — 必须先完成并通过 10 分钟无舵机 `class=3` 通信/热稳定测试。**

**唯一定义源：`docs/UART2_10MIN_NO_SERVO_STRESS_TEST_CARD_2026-08-14.md`。**

该卡的前置条件、分阶段观察时间点、通过条件与立即停止条件，**即为门 1 的全部定义**。
本计划**不重复维护**这些判据，以避免双源漂移。此处只声明门禁关系：

| 项 | 说明 |
|---|---|
| 门 1 的定义与通过条件 | 全部以上述卡为准；本文不复述、不补充、不修改 |
| 视觉源范围限定 | 仓库权威 mock（未修改，默认 `class=3`），对应该卡第 1 节的 mock 模式要求 |
| 门 1 当前状态 | **已通过**。真机由用户操作，归档证据见 validation_reports/uart2_10min_no_servo_stress_2026-08-14.md；第一次失败与第二次通过均已如实记录。该结论仅覆盖10分钟无舵机UART2通信与热观察，不代表长期可靠性、整机或舵机验收。 |
| 判定材料 | 门 1 的归档结果报告（按该卡第 2、3 节记录）须在 §5.0 出示 |

若该卡与本计划出现任何冲突，**以该卡为准**；发现冲突应先修订该卡，
不得在本文另立一套判据。

门 1 未完成、或其任一通过条件不满足 → 本计划继续 `BLOCKED`，
不得以「反正只跑 10 秒」为由跳过。

**门 2 — 类别注入的测试专用脚本已经创建并通过Codex独立审查。**

**门 1 + 门 2 全部通过，且用户与 Codex 主模型明确授权后，本计划方可执行。**

### 0.3 本计划证明什么 / 不证明什么

**要证明的单一命题：** 当 Maix 送出**受支持类别**（39/41/65）且置信度达标时，Titan
的 `grip_policy` 会正确判出对应抓握意图，但因为**生产姿态库未配置**而在姿态解析层
被安全拒绝，`actionable` 恒为 `0`，同时 ACK 链路继续正常工作。

| 要证明 | 不证明（禁止外推） |
|---|---|
| 39/41/65 各自映射到正确 action | 舵机执行、机械动作、抓握成功 |
| 三类均为 `pose=NOT_CONFIGURED`、`actionable=0` | 姿态数值正确性（本次不填任何姿态） |
| `pose_unavailable` 计数增长、`policy_rejected` 不增长 | 长期稳定性（由门 1 单独负责，本计划不重复认领） |
| 短时窗口内 ACK 持续、`timeout=0` | 断联恢复验收 |

与上一轮（`class=3`）的区别：上一轮走的是**策略层**拒绝（`unsupported_class`），
本轮 39/41/65 走的是**姿态层**拒绝（`NOT_CONFIGURED`）。两条不同的拒绝路径，
必须分别取证。

## 1. 前置事实与不变量（本次不改动）

源码依据（只读引用，不修改）：

| 事实 | 位置 |
|---|---|
| 39→`CYLINDRICAL`、41→`POWER`、65→`PRECISION`，其余 `UNSUPPORTED_CLASS` | `titan_rtthread/grip_policy.c:42-56` |
| 最低置信度 `70` | `titan_rtthread/grip_policy.h:6`，`smart_hand_uart.c:19` |
| 三条姿态 profile 的 `configured` 恒为 `0`（`memset` 后只赋 action） | `titan_rtthread/grip_pose_bank.c:5-14` |
| `configured=0` → 返回 `GRIP_POSE_NOT_CONFIGURED` | `titan_rtthread/grip_pose_bank.c:43-46` |
| 姿态非 `OK` → `clear_actionable()`，`actionable=0` | `titan_rtthread/smart_hand_vision_state.c:64-71` |
| 策略通过但姿态不可用 → `pose_unavailable++`（不计入 `policy_rejected`） | `titan_rtthread/smart_hand_uart.c:126-137` |
| VISION 帧无论是否可动作都回 `ACK status=0` | `titan_rtthread/smart_hand_uart.c:237` |
| 全仓库只有 `tests/` 里出现 `configured = 1u`，生产路径没有 | `tests/test_grip_pose_bank_c.c` 等 |

由此可推断的**预期**（待真机证实）：本测试**不需要重新编译或重新烧录 Titan**。
当前在跑的固件已包含 policy + pose bank，`class=3` 已被正确判定即为证据。

固件身份现场核对（二选一即可，**不要为此复位 Titan**）：

- 启动 banner 可见时：`smart_hand: listening on uart2 at 115200 (policy+seq guard; poses unconfigured; no servo write)`
- banner 已滚走时：`sh_status` 中存在 `decision policy_rejected=... pose_unavailable=... vision_expired=...` 这一行

两者都对不上 → **停止**，说明在跑的不是 policy 版固件，本计划不适用。

## 2. 类别注入方式：测试专用脚本（已通过Codex独立审查）

### 2.1 明确禁止的执行方式（后续所有 mock 注入测试的通则）

**不得通过编辑设备端 `vision_source.py`（或任何生产文件）来切换类别。**
具体禁止：改动 `MockVisionSource` 默认 payload、逐轮往返编辑设备副本、
以"改完再改回来"的方式在三个类别之间切换。

理由：逐轮编辑生产文件会在设备端制造与仓库不一致的中间态，
一旦测试中途因停止条件中断，设备将停留在被改过的状态；
且"改回去"这一步本身没有独立证据，无法自证未污染。

**本条为通则，效力不限于本计划：** 后续任何 mock 注入测试
（任意类别、任意置信度、任意几何量、任意帧率）一律不得以修改设备端生产文件的
方式实现，一律改用符合 §2.2 审查清单的测试专用脚本。
若某项测试确实无法用脚本实现，须先提请主模型裁决，不得自行破例。

### 2.2 改为使用测试专用脚本

类别注入应由一个**独立于生产运行路径的测试专用脚本**完成。

**门 2 测试专用脚本已经创建并通过Codex独立审查。** 脚本已通过独立审查
（Codex 主模型或指定评审）；参考：
- `maixcam2/supported_class_mock_probe.py`
- `tests/test_supported_class_mock_probe.py`
- `docs/SUPPORTED_CLASS_MOCK_PROBE_USAGE_2026-08-14.md`

审查清单（供评审逐条核对，本文只提出要求，不提供实现）：

| # | 约束 |
|---|---|
| 1 | 运行期间**不写入、不覆盖、不重命名**任何生产文件：`main.py`、`protocol.py`、`link_monitor.py`、`target_tracker.py`、`vision_source.py` |
| 2 | 类别由**参数**传入，不靠改源码切换 |
| 3 | **类别参数严格只允许 `39` / `41` / `65`**；收到任何其他值（含 `3`、`0`、负数、越界、非整数、缺省）必须**立即拒绝并退出**，不得回退到默认值、不得截断取模、不得发出任何帧 |
| 4 | 其余五个字段固定为 `(320, 240, 80, 120, 96)`；几何量固定以保证 `TargetTracker` 的 IoU 匹配稳定 |
| 5 | 置信度**固定为 `96`**，不得提供任何降低或绕过 `70` 阈值的开关 |
| 6 | **非 MaixCAM2 电脑环境下默认 `dry-run`**：不枚举串口、不打开任何串口、不写任何字节，只打印将要发送的帧内容供审查。真机发送须由显式确认参数开启，且该参数不得有默认值 |
| 7 | 帧编码与 ACK 统计**复用生产模块**（`protocol` / `link_monitor`），不得另写一套协议或另一套统计口径 |
| 8 | **不具备任何舵机写包能力**，不引用 `scs0009_*` 相关路径 |
| 9 | 脚本退出后，设备即回到「运行标准 `main.py` + 未修改 `vision_source.py` = `class=3`」状态，无需任何"改回去"动作 |
| 10 | 脚本自身不落在生产应用目录的五个文件名之列，可被单独删除 |

约束 3 的用意：本计划只授权 39/41/65 三个受支持类别。若脚本能传入任意类别，
就等于把"未授权类别扫描"混进本次测试，超出 §0.3 命题范围。
约束 6 的用意：电脑侧审查、干跑和真机发送必须物理隔离，
避免在无接线、无授权的电脑上误开串口或误触真机。

### 2.3 仓库权威基线（用于事后自证）

| 项 | 值 |
|---|---|
| `smart_hand/maixcam2/vision_source.py` SHA-256 | `4B27679D9B7812EF5039F74366BA6455E31CE96EFA48D1632A08B2D4C5CCA084` |
| 大小 | `7603` 字节 |
| `main.py` | 不改，`VISION_MODE` 保持 `"mock"`，`UART_DEVICE` 保持 `/dev/ttyS2` |
| Titan 侧 | 一行不改、不 Build、不烧录 |

## 3. 安全门（全程不得触碰）

| 硬边界 | 具体含义 |
|---|---|
| 舵机全程断开 | 舵机总线物理不连接、6V 电源关闭且不上电，全程无机械动作 |
| 不接 5V/VBUS | 两板各自 USB 供电，板间只有 `GND` + 交叉 `TX/RX` 三根线 |
| 不填写姿态 | 不得设置任何 `profiles[i].configured = 1u`，不得写入舵机目标值，不得动 `config/servo_calibration_template.csv` |
| 不解除安全门 | 不改 `SMART_HAND_MIN_CONFIDENCE`、`servo_safety_gate.*`、`grip_pose_bank.c`、`smart_hand_vision_state.c` |
| 不改协议 | 不动 `smart_hand_protocol.*`、CRC、序号守卫 |
| 不改设备端生产文件 | 见 §2.1，类别一律由测试脚本参数注入；**该条为后续所有 mock 注入测试的通则** |
| 不注入故障 | 不使用 `host/uart_fault_corpus.json`，不发 HELLO 草案 |
| 不动 D 盘工程 | `D:\Micu\RTTWorkspace\titan_uart_test` 全程只读 |

**如果本次出现 `actionable=1`，那是严重缺陷，不是成功。** 立即停止并保留全部日志。

## 4. 预期输出（逐字对照）

### 4.1 Titan UART1 控制台每帧日志

```text
VISION seq=<n> class=39 conf=96 action=CYLINDRICAL_GRASP reason=accepted pose=NOT_CONFIGURED actionable=0
VISION seq=<n> class=41 conf=96 action=POWER_GRASP       reason=accepted pose=NOT_CONFIGURED actionable=0
VISION seq=<n> class=65 conf=96 action=PRECISION_GRASP   reason=accepted pose=NOT_CONFIGURED actionable=0
```

（实际输出无对齐空格，以字段值为准。）

### 4.2 Titan `sh_status`：750 ms 实时状态窗口

**必须在 Maix 侧仍在发送 VISION 时执行**，才能看到 `reason=accepted`：

```text
decision policy_rejected=<不增长> pose_unavailable=<持续增长> vision_expired=<不增长>
vision present=1 age_ms=<0..750> action=<对应 GRASP> reason=accepted pose=NOT_CONFIGURED actionable=0
```

**已知陷阱：** 停止发送超过 `750 ms` 后再打 `sh_status`，视觉候选已被清除，会显示
`vision present=0 ... action=NO_ACTION reason=invalid_payload pose=NO_ACTION actionable=0`
（依据 `smart_hand_vision_state.c:12-21` 的 `clear_vision_candidate`）。
**这是正常的过期表现，不是失败。** 停机后的快照只用于读计数器。

### 4.3 Maix 控制台（每 5 秒）

```text
link stats: sent=... tx_fail=0 acked=... rejected=0 unexpected=0 malformed=0 timeout=0 consecutive_timeout=0 max_consecutive_timeout=0 pending=0..1 rtt_last_ms=... rtt_avg_ms=... rtt_max_ms=...
uart stats: rx_errors=0
```

若测试脚本复用生产统计口径（§2.2 约束 5），上述字段名与判据直接适用。

### 4.4 单轮 10 秒的量级估算（参考值，非判据）

| 量 | 估算 | 依据 |
|---|---|---|
| VISION 帧 | 约 `18–21` | 发送间隔 `500 ms`，首帧约在 t≈0.5 s |
| PING 帧 | 约 `10–11` | `PING_INTERVAL_MS=1000` |
| `sent` | 约 `28–32` | 两者之和 |
| `link stats` 打印次数 | `3`（t≈0/5/10 s） | `STATS_INTERVAL_MS=5000` |
| Δ`pose_unavailable` | ≈ 本轮 VISION 帧数 | 每帧 `+1` |
| Δ`policy_rejected` | `0` | 39/41/65 不走策略拒绝分支 |

`sent` 与 `acked` 相差 `0–1` 属正常（在途 ACK），与上一轮 `pending=1` 判定口径一致。

## 5. 执行步骤（两道门通过后方可执行）

### 5.0 电脑侧门禁（不通电，先做）

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\check_maix_deploy.py --expected-mode mock
Get-FileHash smart_hand\maixcam2\vision_source.py -Algorithm SHA256
```

要求：全部通过，哈希等于 §2.3 基线。并核对：

- 门 1：`docs/UART2_10MIN_NO_SERVO_STRESS_TEST_CARD_2026-08-14.md` 所定义的
  10 分钟测试已实际执行，其第 2 节记录完整、第 3 节通过条件全部满足，且结果已归档；
- 门 2：测试脚本审查意见为通过（§2.2 全部 10 条约束逐条核对）。

任一项缺失 → 停止，本计划维持 `BLOCKED`。

### 5.1 通电与接线核对

1. 两板断电状态下确认三线：`GND`、`Maix B0/U2T → Titan H1 RXD2`、`Maix B1/U2R ← Titan H1 TXD2`。
2. 确认**未接** 5V/VBUS，确认舵机总线**物理断开**、6V **关闭**。
3. 两板各自 USB 上电。打开 Titan UART1 控制台（上次为 `COM14`，`115200/8N1`，现场确认）。
4. 按 §1 核对固件身份。记录起始 `sh_status` 作为**全局基线 T0**。

### 5.2 三轮测试（A=39，B=41，C=65）

每轮相同流程：

1. 记录本轮开始前的 `sh_status`（记为 `S_before`），特别是 `policy_rejected` /
   `pose_unavailable` / `vision_expired` 三个数。
2. **以本轮类别为参数启动测试脚本**（不编辑任何文件）。同时录制两端未剪辑终端。
3. **运行约 10 秒**（以看到第 3 条 `link stats` 为准，10–12 秒可接受）。
4. 在脚本**仍在发送 VISION** 时，于 Titan 控制台执行一次 `sh_status`（记为 `S_live`）。
   这一步必须落在 §4.2 的 750 ms 实时窗口内。
5. 停止脚本。
6. 用手背触检两端接口、三根线材、两块板：**任何温热即进入 §7 停止流程**。
7. **等待 Titan 打印 `smart_hand: VISION_OFFLINE; cleared vision; sequence baseline reset`**
   （断流后约 1.5 秒）。记录停机后的 `sh_status`（记为 `S_after`，只读计数器）。
8. 间隔至少 30 秒散热，再进入下一轮。

**第 7 步是强制的，不能跳过。** 依据 `smart_hand_sequence_guard.c:34-44`：发送端每次
重启序号从 `0` 开始，若 Titan 未复位序号基线，
`delta = (0 - last_accepted) & 0xFFFF ≥ 0x8000` 会被判为 `OLD`，整轮 VISION 全部进入
`ignored_old` 而不进业务层。此时**发送端仍会看到 `acked` 正常增长**
（`smart_hand_uart.c:206-210` 对忽略帧照样回 ACK=0），表面一切正常，实际什么都没测到。
必须以 Titan 侧证据为准。

### 5.3 通电时间控制

10 分钟量级的热行为由门 1（§0.2，定义见该操作卡）单独负责，本计划不重复认领长期热结论。
本计划三轮合计互连通电约 `60–90` 秒，仍须执行每轮触检（第 6 步），
且本次结论**不得**写成长期热安全由本计划验收。

## 6. 验收判据

单轮 PASS 需全部满足：

| # | 判据 | 证据来源 | 结果 |
|---|---|---|---|
| 1 | 出现本轮类别的 VISION 日志，`class` 等于设定值 | Titan 控制台 | `summary_recorded` |
| 2 | `action` 等于 §4.1 表中对应值 | Titan 控制台 | `summary_recorded` |
| 3 | `reason=accepted` | Titan 控制台 | `summary_recorded` |
| 4 | `pose=NOT_CONFIGURED` | Titan 控制台 | `summary_recorded` |
| 5 | `actionable=0`，**全轮无一帧为 1** | Titan 控制台 | `summary_recorded`（无逐帧原文） |
| 6 | Δ`pose_unavailable` > 0 且 ≈ 本轮 VISION 帧数 | `S_live/S_after` − `S_before` | `not_provided` |
| 7 | Δ`policy_rejected` = 0 | 同上 | `not_provided` |
| 8 | Δ`ignored_old` / `duplicates` 不增长 | Titan 控制台 + `sh_status` | `not_provided` |
| 9 | `acked` 持续增长，`sent − acked ≤ 1` | Maix `link stats` | `summary_recorded`（`30/30`） |
| 10 | `timeout=0`、`consecutive_timeout=0`、`malformed=0`、`rejected=0`、`unexpected=0`、`tx_fail=0` | Maix `link stats` | `summary_recorded`（错误全 0） |
| 11 | `rx_errors=0` | Maix `uart stats` | `summary_recorded` |
| 12 | Titan `invalid`、`payload`、`tx_fail` 不增长 | `sh_status` | `not_provided` |
| 13 | 舵机全程断开、无任何机械动作 | 现场 + 照片 | `summary_recorded`（无照片） |
| 14 | 本轮触检无发热 | 现场 | `not_provided` |
| 15 | 设备端五个生产文件全程未被写入 | 起止哈希比对 | `not_provided` |

整体 PASS = A/B/C 三轮全部 PASS，且 §8 的 `class=3` 基线复验通过。
2026-08-15 归档：**不**宣称整体 PASS。授权摘要覆盖判据 1–5、9–11、13；6–8、12、14、15 与 §8 复验为 `not_provided`。详见 `validation_reports/supported_class_mock_2026-08-15.md`。

任一轮 FAIL：保留日志，**不进入下一轮**，不接舵机「继续验证」。

## 7. 停止条件

出现任一条即**立即停止本计划**：

| 停止条件 | 判定信号 | 立即动作 |
|---|---|---|
| 任意发热 | 线材、接口、任一板出现温热或异味 | 停脚本 → 两板断电 → 断开三线 → 记录时间与部位 → 不再上电，等复审 |
| `timeout` 连续增长 | 连续两次 `link stats` 中 `timeout` 增加，或 `consecutive_timeout ≥ 1` 且不回零 | 停脚本，保留两端日志，不重连、不重烧 |
| `malformed` | 发送端 `malformed ≥ 1`，或 Titan `dropped invalid frame` / `invalid`、`payload` 持续增长 | 同上 |
| Titan 复位 | 控制台重新出现启动 banner、`sh_status` 计数器归零、`link=OFFLINE` 且不恢复 | 停脚本，记录复位前最后 20 行，不立即重试 |
| 失去控制台 | UART1 无输出、串口掉线、msh 不响应 | 停脚本，两板断电，检查是否为供电或线材问题；**不猜针脚试插** |

补充停止条件（沿用 `LAB_BRINGUP_CHECKLIST.md` 第 7 节）：误接 5V/VBUS、`rx_errors`
持续增长、`tx_fail > 0`、序号跳变、pin1 方向存疑。

**任何停止条件触发后，不得为「补数据」而临时填姿态、改置信度阈值、改生产文件
或接舵机。**

## 8. 测试后回到 class=3 基线状态

由于本计划不编辑任何设备端生产文件（§2.1），恢复**不是**"把数字改回去"，
而是"退出测试脚本后确认设备回到未改动的 `class=3` 基线"。该确认是必需步骤。

**步骤：**

1. 确认测试脚本已完全退出，无残留进程。
2. 比对设备端五个生产文件与仓库哈希一致，确认脚本运行期间未写入任何生产文件。
3. **等待 Titan 打印 `sequence baseline reset`** 后，再运行标准 `main.py`
   （`VISION_MODE="mock"`，`vision_source.py` 未修改，默认 `class=3`）。
4. 观察 Titan 应恢复为**策略层**拒绝：

```text
VISION seq=<n> class=3 conf=96 action=NO_ACTION reason=unsupported_class pose=NO_ACTION actionable=0
```

5. `sh_status` 中此时应改为 `policy_rejected` 增长、`pose_unavailable` **不再增长**。
   这一反向变化本身即是「已回到基线 + 前面第 6/7 判据成立」的交叉验证。
6. 停止 Maix，两板断电，断开三线。
7. 回电脑复验仓库未被污染：

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
Get-FileHash smart_hand\maixcam2\vision_source.py -Algorithm SHA256
python smart_hand\host\check_maix_deploy.py --expected-mode mock
```

要求哈希仍为 `4B27679D9B7812EF5039F74366BA6455E31CE96EFA48D1632A08B2D4C5CCA084`，
且显示 `MAIX DEPLOY PREFLIGHT PASSED`。哈希若已变化 → 说明测试脚本越界写了生产文件，
按 §2.2 约束 1 判为脚本审查失效，用备份还原，并在结果报告中如实记录这次污染。

**基线复验未完成前，本次测试不算结束。**

## 9. 证据清单

| 证据 | 形式 | 去向 |
|---|---|---|
| 门 1 结果报告（按 `UART2_10MIN_NO_SERVO_STRESS_TEST_CARD_2026-08-14.md` 第 2、3 节） | 文档 | 本计划执行的前置附件 |
| 门 2 测试脚本审查意见（§2.2 十条逐条核对） | 文档 | 同上 |
| 三轮 Titan UART1 未剪辑日志 | 文本 | 结果报告附件 |
| 三轮发送端未剪辑日志 | 文本 | 同上 |
| 每轮 `S_before` / `S_live` / `S_after` | `sh_status` 原文 | 同上 |
| 回到 `class=3` 后的对照日志 | 文本 | 同上 |
| 接线与舵机断开照片 | 图片 | 同上 |
| 起止两次生产文件 SHA-256 | 文本 | 同上 |
| 时间、操作人、环境温度 | 文本 | 同上 |

结果报告建议落到
`smart_hand/validation_reports/supported_class_mock_2026-08-14.md`
（**本计划不创建该文件**），并在
`smart_hand/competition_2026/evidence/evidence_index.csv` 追加一行。

证据等级写法沿用既有口径：若由用户提供终端输出、模型只做审核转写，必须写
「用户提供的真机终端输出，经主模型审核」，不得写成记录者亲自上机。

## 10. 结论边界

**本计划三轮 10 秒策略链路已按主模型授权摘要归档**（`validation_reports/supported_class_mock_2026-08-15.md`，`E0006`）。
该归档**不是** §6 十五条整体 PASS，也**不是** §8 `class=3` 基线复验完成。

已归档摘要**只能**写出：

- 在该次短时窗口内，受支持类别 39/41/65 进入 `grip_policy` 后得到正确抓握意图；
- 因生产姿态库未配置，三类均在姿态层被拒绝，`actionable` 恒为 `0`；
- 该拒绝路径与 `class=3` 的策略层拒绝路径不同（字段为 `accepted` + `NOT_CONFIGURED`，不是 `unsupported_class`）；`sh_status` 计数器原文未附，不得写成已用计数器交叉验证；
- 期间 ACK 链路持续正常，舵机全程断开、无机械动作。

**不得**据此写出：姿态已验证、可以开始接舵机、热安全已验收、长期稳定、断联恢复
已验收、生产联调完成。长期热稳定结论只能来自
`docs/UART2_10MIN_NO_SERVO_STRESS_TEST_CARD_2026-08-14.md` 所定义的门 1 测试
及后续独立的长时测试，不能由本计划的三轮 10 秒窗口代替。
