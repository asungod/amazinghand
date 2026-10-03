# 两颗 SCS0009 校准前就绪度审计（2026-08-15）

> 作者：claudeA。本文件只做**只读**审计：读取仓库内已有舵机工具、校准模板、接线卡与安全门源码，
> 并运行**离线**单元测试。本批 `hardware_accessed=false`：未上电、未连接串口、未移动舵机、
> 未打开任何 COM 口、未修改生产代码、未触碰 D 盘 Studio 工程、未填写任何校准数值。
>
> 本文件**不下达**任何真机上电、改线、烧录或舵机运动指令。所有"阻断项"由 Codex 主模型裁决。
> 本文件**不猜测、不预填**舵机方向、中心值、软限位或抓握姿态。

## 0. 审计范围与证据等级

审计对象：进入"两颗 SCS0009 的 PC 总线标定"之前的**软件与安全准备情况**。

| 等级 | 含义 |
|---|---|
| `SOURCE` | 本审计直接读到的仓库源码/模板文件内容 |
| `OFFLINE_TEST` | 本审计本次实际运行的离线测试，结果见 §9 |
| `PROJECT_DOC` | 项目内接线卡/操作卡/规范文档，不是原厂手册 |
| `HARDWARE_SESSION` | 既往用户真机会话，主模型审核，非本审计作者上机 |
| `UNVERIFIED` | 本地资料不足以确认，**禁止补全** |
| `BLOCKED` | 存在冲突或缺口，上电前必须由 Codex 主模型裁决 |

不在本批范围：真机通电、机械装配状态、舵机极性实测、连杆/舵盘到位情况、
`E0002` 附件补齐、README 状态同步。

## 1. 结论摘要

**软件侧总体：可进入校准阶段的工具链已存在且离线自检全绿（229/229 通过）。**
**阻断项集中在电源与操作文档层，共 3 条，全部需 Codex 主模型裁决后才能上电。**

| 维度 | 就绪度 | 依据 |
|---|---|---|
| 只读识别工具 | 就绪 | §2.1，寄存器地址与厂商 SDK 逐条一致 |
| 单颗小幅动作工具 | 就绪 | §2.3 |
| 双颗同步动作工具 | 就绪 | §2.4 |
| 框架归中工具 | 就绪（但含 511 假设，见 §2.5） | §2.5 |
| 机构冒烟工具 | 就绪（默认值必须被实测值覆盖，见 §2.6） | §2.6 |
| 校准模板 | 就绪且**保持空白**（0 数据行） | §3.1 |
| 数据日志模板 | 就绪且保持空白 | §3.2 |
| PC 端失败关闭模型 | 就绪，但**不覆盖校准阶段工具**（见 §4.1） | §4.1 |
| Titan 端安全门 / 姿态库 | 就绪且默认全未配置；固件无舵机写包路径 | §4.2 |
| 厂商 SDK 依赖 | 就绪（导入成功，未开端口） | §9 |
| 校准证据落盘能力 | **缺口**：全部工具只打印到终端，无落盘选项 | §7.1 |
| 方向/软限位采集流程 | **缺口**：无专用工具，只能人工观察 | §7.2 |
| 电源限流数值 | **`BLOCKED`**：文档内 1.0A 与 2.0A 冲突 | §6.1 |
| 外部电源入口唯一性 | **`BLOCKED`**：三份操作文档均无该检查项 | §6.2 |
| 温度阈值一致性 | **`BLOCKED`（轻）**：五处阈值 50/55/60 不统一 | §6.3 |

## 2. 舵机工具逐个审计

全部位于 `smart_hand/host/`。以下"是否写寄存器/是否使能力矩"由源码逐行确认。

| 工具 | 写寄存器 | 使能力矩 | 产生运动 | 强制确认开关 | 电压门(raw) | 温度门(raw) | 结果落盘 |
|---|---|---|---|---|---|---|---|
| `probe_scs0009.py` | 否 | 否 | 否 | 无（只读，无需） | 无（只打印） | 无（只打印） | 无 |
| `set_scs0009_id.py` | 是（EPROM ID） | 否 | 否 | `--only-one-servo-connected` | 无 | 无 | 无 |
| `nudge_scs0009.py` | 是 | 是 | 是（±delta 后自动回位） | `--loose-servo-confirmed` | `50..70` | `>=60` 拒绝 | 无 |
| `sync_nudge_scs0009_pair.py` | 是 | 是 | 是（双颗同步 ±delta 回位） | `--loose-servos-confirmed` | `50..70` | `>=60` 拒绝 | 无 |
| `center_hold_scs0009_pair.py` | 是 | 是 | **是（大幅：到 raw 511）** | `--frame-mounted-confirmed` | `50..70` | 起始 `>=50`；保持中 `>=55` | 无 |
| `finger_smoke_scs0009.py` | 是 | 是 | 是（±delta 闭合/张开） | `--mechanism-free-confirmed` | `50..70` | `>=50` 拒绝 | 无 |

### 2.1 `probe_scs0009.py` — 只读识别（就绪）

- 文件头明确声明只发 PING，不使能力矩、不改 ID、不写任何寄存器；源码逐行核对属实。
- 读取寄存器地址：`PRESENT_POSITION=56`、`PRESENT_SPEED=58`、`PRESENT_LOAD=60`、
  `PRESENT_VOLTAGE=62`、`PRESENT_TEMPERATURE=63`、`MOVING=66`、`PRESENT_CURRENT=69`。
  **本审计已与厂商 SDK `scservo_sdk/scscl.py` 的 `SCSCL_*` 常量逐条比对，全部一致**（`SOURCE`）。
- 状态寄存器读取失败时打印 `STATUS WARNING` 但保留 PING 结论，不伪造读数——符合"读取失败不冒充新值"的规范。
- `--ids` 默认 `1,0-20`，`parse_ids` 限制 `0..253`，不会误发广播 ID `254`。
- 端口选择：未给 `--port` 且存在多个串口时直接报错退出，不猜端口。
- **缺口**：无 `--output`，结果只进终端。见 §7.1。

### 2.2 `set_scs0009_id.py` — 改 ID（就绪，本阶段预计不需要）

- 三重拒绝：未加 `--only-one-servo-connected` 拒绝；ID 越界拒绝；新旧 ID 相同拒绝。
- 改写前先 PING 旧 ID 必须响应、新 ID 必须**不**响应，否则拒绝——防止总线上撞 ID。
- 改写后用"新 ID 能 PING + 旧 ID 不再响应"双向验证，不依赖可能丢失的应答包；失败时回锁 EPROM。
- 全程不发位置/力矩命令。
- 现状：既有记录为第一颗 ID1、第二颗已改 ID2，**本阶段预计无需再次使用本工具**。

### 2.3 `nudge_scs0009.py` — 单颗小幅动作（就绪）

- `--delta` 硬限制 `1..30` raw；超出直接拒绝。
- 先读起始位置，**先用起始位置写一次保持目标再使能力矩**，减小上电跳变——设计正确。
- 目标越界保护：`5 <= target <= 1018`。
- 动作后自动回位，并校验 `|reached-target|<=8`、`|returned-start|<=8`，超差抛错。
- `finally` 分支无条件释放力矩，异常路径也释放——失败关闭正确。
- **注意（不是缺陷，但影响校准语义）**：方向由 `direction = 1 if start <= 511 else -1` 自动决定。
  按既有记录 ID1 起始约 20、ID2 起始约 1000，两颗会朝**相反的原始寄存器方向**移动。
  该工具因此**不能**用来直接判定统一的逻辑正方向；`direction_sign` 仍须人工观察机构实际运动后判定。

### 2.4 `sync_nudge_scs0009_pair.py` — 双颗同步小幅动作（就绪）

- 同样 `--delta` 限 `1..30`，先保持位置再使能力矩，`finally` 释放力矩。
- 使用 `groupSyncWrite`，每次 `txPacket` 前后都 `clearParam`，无残留参数。
- 确认开关语义是 **`--loose-servos-confirmed`（两颗均松散、未装入机构）**。
  **操作顺序含义**：一旦舵机固定进 `Finger Frame`，本工具的前置声明即不再成立，
  此后应改用 §2.5 / §2.6 的工具。这一点在现有文档中未被显式写成"工具选择表"，属文档层建议项（§7.3）。

### 2.5 `center_hold_scs0009_pair.py` — 框架归中并保持（就绪，含明确假设）

- 依次（非同时）对 ID1、ID2 使能力矩并移动到 `RAW_CENTER`，降低峰值电流——设计正确。
- 保持期间每 5 秒复读位置/电压/温度，超窗立即抛错并释放力矩；`Ctrl+C` 也走释放路径。
- `--hold-seconds` 限 `5..300`；到位超时 12 秒抛错。
- **必须记入边界的假设**：`RAW_CENTER = 511` 是**写死的模块常量，无命令行覆盖参数**。
  511 是 0..1023 量程的**电气中点**，**不是**实测机械中心。
  → 结论：**`config/servo_calibration_template.csv` 的 `center_raw` 不得直接抄 511**，
  必须来自装配后实测并由 Codex 主模型确认。本审计不填写任何数值。
- **运动幅度提示（仅陈述，非指令）**：既有文档记录当前位置约 ID1=20、ID2=1000，
  归中到 511 是**接近半量程的大幅转动**，与本工具其余"小幅"工具性质不同。

### 2.6 `finger_smoke_scs0009.py` — 装好连杆后的冒烟测试（就绪，默认值须被覆盖）

- `--delta` 限 `1..20`；四相位 `SMALL_CLOSE → CENTER → SMALL_OPEN → FINAL_CENTER`，每相位校验 `<=10` raw 容差。
- 两颗使用**相反符号**（`center1+delta` / `center2-delta`），即已假设对置安装；符合单指两关节对置结构。
- 越界预检：所有目标必须落在 `20..1003`。
- **失败关闭亮点**：启动时校验 `|当前位置 - 传入 center| <= 20`，否则拒绝运行。
  即：若操作者忘记传入实测中心而沿用默认 511，而真实中心不在 511 附近，**工具会拒绝而不是乱动**。
- **仍须注意**：`--center1` / `--center2` 默认值均为 `511`。
  这两个默认值**不构成校准结论**，正式运行时必须显式传入实测中心。本审计不给出任何建议数值。

## 3. 校准与数据模板审计

### 3.1 `config/servo_calibration_template.csv` — 空白（符合要求）

- 实测行数：**1 行（仅表头，0 条数据行）**（`SOURCE`）。当前**未被填写**，符合"未经机械实测禁止填写"。
- 表头字段完整：`calibration_version, servo_role, servo_id, bus_name, baud_rate, direction_sign,
  center_raw, soft_min_raw, soft_max_raw, max_step_raw, speed_limit_raw, position_unit_status,
  position_scale, position_unit, load_unit_status, load_scale, load_unit, driver_name,
  driver_version, verified_by, verified_at, notes`。
- 仓库内**不存在**任何已填写的 `servo_calibration_v*.csv`（全仓库 CSV 清点见 §9），
  即当前无任何被预填的方向/中心/限位数值。
- `SERVO_CALIBRATION_AND_LOGGING.md` §5 已规定：`direction_sign` 未验证留空、
  `max_step_raw` 实测前留空、`position_unit_status` 只能填 `raw_only` 或确认后的 `confirmed`、
  `load_unit_status` 初始固定 `raw_only`。规范齐备。

### 3.2 数据日志模板 — 空白（符合要求）

- `data/grasp_trial_manifest_template.csv`、`data/single_finger_log_template.csv` 均为 **1 行表头、0 数据行**。
- 逐样本表已包含两舵机各自的 `target/position/speed/load/voltage/temperature` 原始值
  以及 `read_ok`、`data_age_ms`，满足"读取失败保留行、原始字段留空、不冒充新值"的规范。
- `host/analyze_servo_log.py` 的离线测试已覆盖：时间倒退拒绝、单文件多 trial 拒绝、
  读取失败行不得携带新鲜反馈值（`OFFLINE_TEST`，见 §9）。

## 4. 安全门审计

### 4.1 PC 端 `host/servo_safety_model.py` — 模型正确，但**不覆盖本阶段工具**

模型本身审计通过：

- `load_calibrations` 强制**恰好 2 行**、`servo_id` 唯一、`servo_role` 唯一、
  两行 `calibration_version` 必须一致；任一必填字段为空即抛错——空模板天然无法加载，符合失败关闭。
- `ServoCalibration.__post_init__` 强制 `direction_sign ∈ {-1,1}`、
  `0 <= soft_min < soft_max <= 1023`、`center_raw` 必须落在软限位内、步长与速度上限为正。
- `ServoCommandGate` 覆盖：未 arm 拒绝、故障锁存后拒绝、ID 集合不匹配拒绝、
  读取失败/数据过期/位置越软限位/电压越窗/温度超限拒绝、目标越软限位拒绝、单步超 `max_step_raw` 拒绝；
  运行期反馈异常会**自动 disarm**；`note_bus_write(False)` 锁存故障且必须显式 `clear_fault` 才能恢复。
- `plan_logical_offsets` 把上层逻辑偏移经 `direction_sign` 映射为原始目标，
  使策略/视觉代码无需处理舵机正反——架构边界正确。

**关键审计发现（必须写入交接，避免被误述）**：

> 本审计对全仓库 `.py` 检索 `servo_safety_model` 的引用，结果只有两处：
> `host/run_offline_rehearsal.py`（离线彩排）与 `tests/test_servo_safety_model.py`（单元测试）。
> **§2 的 6 个 PC 舵机工具没有任何一个导入或使用 `ServoCommandGate`。**

含义：**校准阶段的真机动作不受该失败关闭门保护**，只受各工具自身内联的
电压/温度/步长/越界/容差检查保护（§2 表格）。这是可接受的引导期状态——
安全门需要校准数据，而校准数据正是本阶段要产生的（先有鸡还是先有蛋）——
但**任何对外材料不得写成"两颗舵机校准过程由安全门保护"**。

### 4.2 Titan 端安全门与姿态库 — 失败关闭，且固件当前无舵机写包路径

- `titan_rtthread/grip_pose_bank.c` 的 `grip_pose_bank_init` 用 `memset(bank,0,...)`
  把三个 profile 的 `configured` 全部清零，只赋 action 枚举。
  `grip_pose_bank_resolve` 在 `match->configured` 为 0 时返回 `GRIP_POSE_NOT_CONFIGURED`——
  这正是 39/41/65 真机测试中观察到 `pose=NOT_CONFIGURED actionable=0` 的来源（`SOURCE` 解释 `HARDWARE_SESSION`）。
- 全仓库检索确认：**没有任何生产 C 代码调用 `servo_safety_gate_init` 并传入硬编码校准值**；
  `center_raw` / `soft_min_raw` 只出现在 `servo_safety_gate.c` 的**校验逻辑**中，不是预填数据。
- `smart_hand_vision_state.c` 在拒绝路径上调用 `clear_actionable()`，不保留上一次可执行目标——正确。
- **`titan_rtthread/smart_hand_uart.c`（428 行）中检索 `scs0009` / `servo_` / `SERVO`，命中数为 0。**
  即当前通信固件**完全没有舵机写包能力**，与 `LAB_BRINGUP_CHECKLIST.md` 第 17 行的硬边界声明一致。

结论：Titan 侧对本次 PC 校准**无参与、无风险敞口**，本阶段无需改动 Titan 或 D 盘工程。

## 5. 接线卡与操作文档审计

### 5.1 现有文档覆盖情况

| 文档 | 覆盖本阶段的内容 | 状态 |
|---|---|---|
| `HARDWARE_WIRING_CARDS.md` 卡4 | 电源→转接板→控制器共地、只读优先、ID 唯一后才同总线、限流/发热立即断电 | 存在，但见 §6.1 冲突 |
| `TOMORROW_SINGLE_FINGER_RUNBOOK.md` | 停止点（先只固定舵机，不装舵盘/拉杆）、B 模式、D/V/G 线序、只读检查、归中、冒烟 | 存在，但见 §6.1 冲突 |
| `SERVO_CALIBRATION_AND_LOGGING.md` §4 | 阶段 A/B/C 完整安全顺序、异常立即断电、阶段未过不得进入下一阶段 | 完整 |
| `SERVO_CALIBRATION_AND_LOGGING.md` §5/§7 | 校准字段填写规则、最小验收标准（正常/失败/集成边界） | 完整 |
| `LAB_BRINGUP_CHECKLIST.md` | 明确"当前通信固件无舵机写包能力，不要连接舵机总线/不要打开 6V" | 与 §4.2 源码一致 |

### 5.2 文档间冲突与缺口（只列，不裁决）

| 编号 | 冲突/缺口 | 出处 |
|---|---|---|
| C1 | **初始限流 2.0A vs 1.0A** | 卡4 第 83 行"限流约2.0A"；`SERVO_CALIBRATION_AND_LOGGING.md` 第 60 行"从 1.0A 限流完成验证"；`TOMORROW_SINGLE_FINGER_RUNBOOK.md` 第 38 行"限流先保持1.0A" |
| C2 | **外部电源入口唯一性无检查项** | 全仓库检索"电源入口/单一电源/绿色端子/圆孔"，**只有** `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` 第 57 行提出疑虑；卡4、明日操作卡、校准规范**三份操作文档均无该检查项** |
| C3 | **温度阈值五处不统一** | `nudge`=60、`sync_nudge`=60、`center_hold`=50(起)/55(保持)、`finger_smoke`=50、`servo_safety_model` 默认=50 |
| C4 | 工具与装配阶段的对应关系未成表 | `sync_nudge` 声明"未装入机构"，`center_hold` 声明"已装入框架"，`finger_smoke` 声明"机构活动顺畅"；三者互斥但无一张选择表 |
| C5 | COM 端口号 | 三份文档均写 `COM4` 并已注明"可能变化"；不构成冲突，但每次需实测确认 |

## 6. 阻断项（上电前必须由 Codex 主模型裁决）

以下三项**本审计不裁决、不给出数值、不给出操作指令**，仅陈述现状。

### 6.1 `BLOCKED` — 初始限流取值未统一（C1）

项目文档同时存在 2.0A 与 1.0A 两种"初始限流"。两颗舵机同总线、其中一步是接近半量程的
归中大幅转动（§2.5），限流取值直接影响堵转与发热风险边界。需 Codex 主模型给出唯一取值，
并把被否决的那份文档同步更正（本批不改文档）。

### 6.2 `BLOCKED` — 外部电源入口唯一性未确认且无检查项（C2）

启动上下文第 56–57 行记录：照片疑似 DC 圆孔与绿色端子处**同时**接有导线，
必须确认只使用一个外部电源入口后才能上电。本审计确认：
**该要求尚未落入任何一张接线卡或操作卡的勾选项**，因此即使操作者逐条走卡4也不会被拦住。
需 Codex 主模型确认实物入口后再决定是否补写检查项（本批不改文档）。

### 6.3 `BLOCKED`（轻） — 温度阈值不统一（C3）

首次产生运动的两个工具（`nudge` / `sync_nudge`）使用**最宽松**的 `>=60` 拒绝阈值，
而后续工具与 PC 安全模型使用 `>=50`。即风险最高的"首次动作"环节反而门槛最低。
本审计**不修改任何生产代码**；是否统一、统一到哪个值，由 Codex 主模型裁决。

## 7. 非阻断缺口与建议（本批不实施）

### 7.1 校准证据无法自动落盘

`probe_scs0009.py` 及其余 5 个工具**均无 `--output` / 日志文件参数**，结果只写终端。
而竞赛证据索引 `E0002`（两颗 SCS0009 低幅 PC 总线动作）当前状态仍是 `needs_attachment`。
→ 建议（不实施）：为只读探针增加原始读数落盘选项，使校准过程天然产出可附证据。
本批**不改生产代码**，故仅记录。

### 7.2 `direction_sign` 与软限位无采集工具

`SERVO_CALIBRATION_AND_LOGGING.md` §4 阶段 B 第 7 步要求"逐步确认方向并探测保守软限位，
在接近硬限位前人工停止"，但仓库中**没有**对应工具：`nudge` 的方向由起始位置自动决定
（§2.3），且不报告逻辑方向；无任何工具做递进式限位探测。
→ 现状：`direction_sign`、`soft_min_raw`、`soft_max_raw` **只能靠人工观察 + 人工停止**产生。
本审计不提供任何推测值。

### 7.3 缺一张"阶段 ↔ 工具 ↔ 确认开关"对照表

C4 所述三个确认开关语义互斥，误用会让声明与实物状态不符（例如舵机已固定却用
`--loose-servos-confirmed`）。建议（不实施）在操作卡内补一张对照表。

### 7.4 `run_all_checks.ps1` 语法检查清单未覆盖两个较新测试

`[2/8]` 的 `py_compile` 列表未包含 `tests/test_supported_class_mock_probe.py` 与
`tests/test_titan_uart_polling_tx_contract.py`。影响极小（`unittest discover` 已覆盖执行），
与舵机校准无关，仅登记。

## 8. 本批未做与不得外推

未做：

- 未上电、未连接串口、未打开任何 COM 口、未枚举串口设备、未 PING、未读寄存器；
- 未移动舵机，未使能力矩，未运行 §2 中任何一个舵机工具（连 `--help` 也未运行）；
- 未填写 `servo_calibration_template.csv` 任何字段，未创建任何 `servo_calibration_v*.csv`；
- 未修改任何生产代码、协议、CRC、消息语义；未触碰 `D:\Micu\RTTWorkspace\titan_uart_test`；
- 未修改 `README.md`、接线卡、操作卡或既有 validation report；
- 未补齐 `E0002` 附件，未改动 `evidence_index.csv`。

不得外推：

- 本审计只证明**软件工具与模板处于可进入校准的状态**，
  **不证明**接线正确、极性一致、电源安全、机械装配到位或舵机可安全转动；
- §9 的 229 项离线测试全部通过，只覆盖**电脑端逻辑**，与真机、供电、机构无关；
- 厂商 SDK 导入成功只说明依赖链完整，**不代表**转接板已枚举、COM 口存在或舵机在线；
- `center_hold` 中的 `511` 是电气量程中点，**不是**机械中心；`finger_smoke` 的默认 `511`
  同样不是校准结论。二者均不得被引用为 `center_raw`；
- 既有 ID1/ID2 记录来自 2026-08-11 会话，按 `SERVO_CALIBRATION_AND_LOGGING.md` §5 规定，
  `servo_id` 须"断电重启后再次读取确认"，本审计**未**做此确认；
- Titan 39/41/65 与 10 分钟 UART 证据与本阶段**无关**，不得用于支持舵机结论；
- 历史发热事件（误把 40 针电源脚当 GND）保留在文档中，本审计未删除、未淡化。

## 9. 本批实际运行的命令与结果

全部为离线只读操作，未打开任何串口。

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python --version` | `Python 3.11.7` |
| 2 | 厂商 SDK 导入检查（仅 `import`，**未调用** `comports()`，**未** `openPort()`） | PASS：`scservo_sdk` OK；`pyserial 3.5`；常量 `SCSCL_TORQUE_ENABLE=40`、`PRESENT_VOLTAGE=62`、`PRESENT_TEMPERATURE=63`、`scs_id=5` |
| 3 | `grep "^SCSCL_" third_party/.../scscl.py` 与 `probe_scs0009.py` 常量比对 | PASS：56/58/60/62/63/66/69 全部一致 |
| 4 | `python -m unittest tests.test_servo_safety_model tests.test_analyze_servo_log -v` | PASS：`Ran 12 tests ... OK` |
| 5 | `python -m unittest discover -s tests` | PASS：`Ran 229 tests in 0.882s ... OK`，`exit=0` |
| 6 | 全仓库 CSV 清点（排除 `third_party`） | `config/servo_calibration_template.csv` = 1 行（仅表头）；`data/*_template.csv` 均 1 行；**无任何已填写校准文件** |
| 7 | `grep -rn "servo_safety_model" --include=*.py` | 仅 2 处引用：`run_offline_rehearsal.py`、`tests/test_servo_safety_model.py`；**6 个舵机工具均未引用** |
| 8 | `grep -n "scs0009\|servo_\|SERVO" titan_rtthread/smart_hand_uart.c` | 命中 0 条（文件 428 行）——固件无舵机写包路径 |
| 9 | `grep -rn` 电源入口 / 限流数值（`*.md`，排除 `third_party`） | 发现 C1 限流冲突、C2 入口唯一性缺口 |

## 10. 并发会话说明（审计快照边界）

本审计期间仓库存在**另一个并发会话**（grokB 的支持类别归档批次），需在此登记以免误判归属：

- `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` 在本审计首次读取后于 **10:41 被改动**。
  本审计已**重新完整读取**并逐行比对：改动仅为**新增** 3 条归档指针
  （第 45 行 `E0006` 归档报告、第 73 行 README 等四份文档已对齐、第 74 行 grokB 交接文件），
  **未改动** §3.3 PC 舵机既有证据、§4 硬件阶段与安全红线（含电源入口疑虑）、§5 舵机工具清单。
  → **本审计全部结论不受影响**。
- 同期被改动的 `README.md`(10:28)、`LAB_BRINGUP_CHECKLIST.md`(10:27)、`GRIP_POLICY_MVP.md`(10:27)、
  `competition_2026/README.md`(10:28)、`evidence_index.csv`(10:28)、
  `validation_reports/supported_class_mock_2026-08-15.md`(10:20)、
  `docs/GROKB_TO_CODEX_SUPPORTED_CLASS_ARCHIVE_2026-08-15.md`(10:41)
  **均非本审计所写**。本审计对 README / LAB_BRINGUP_CHECKLIST 的引用取自其 10:28 之后的版本。
- `tests/*.exe` 的 10:45 时间戳来自**他人执行 `run_all_checks.ps1` 的 gcc 重建**；
  本审计**未调用 gcc**，只运行了 `python -m unittest`。
- 本审计所依赖的关键文件在今日**全部未被改动**，故 §6 三条阻断项成立：
  `HARDWARE_WIRING_CARDS.md`(08-14 17:47)、`TOMORROW_SINGLE_FINGER_RUNBOOK.md`(08-12)、
  `SERVO_CALIBRATION_AND_LOGGING.md`(08-11)、`host/*scs0009*.py`、`host/servo_safety_model.py`、
  `titan_rtthread/*`、`config/servo_calibration_template.csv`。

## 11. 交接摘要

- 修改文件：**仅新增本文件** `smart_hand/docs/TWO_SERVO_CALIBRATION_READINESS_AUDIT_2026-08-15.md`。
  未修改任何其它文件。
- `hardware_accessed=false`。未上电、未连串口、未动舵机、未填校准表。
- 是否触碰生产代码 / 协议 / 校准数据 / D 盘工程：**否（四项全否）**。
- 需 Codex 主模型裁决的阻断项：**§6.1 限流取值**、**§6.2 电源入口唯一性**、**§6.3 温度阈值一致性**。
- 需在对外材料中保持的边界：校准阶段**不受** PC 失败关闭门保护（§4.1）；
  `511` 不是机械中心（§2.5、§2.6）。
