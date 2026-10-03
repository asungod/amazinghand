# claudeA → Codex 主模型交接报告（2026-08-15）

- 发件：claudeA（辅助模型，本批只做只读审计与文档产出）
- 收件：Codex 主模型（唯一可向用户下达真机步骤的角色）
- 任务：审计「两颗 SCS0009 进入校准前」的软件与安全准备情况
- `hardware_accessed=false`
- 未上电、未接线、未开串口、未枚举串口、未 PING、未使能力矩、未移动舵机
- 未修改生产代码、协议、CRC、校准数据、D 盘 `titan_uart_test`
- 未填写 `config/servo_calibration_template.csv` 任何字段，未猜测方向/中心/软限位/姿态

请先读本文件，再决定下一步授权。本文件不授予任何真机权限，也不含任何上电指令。

完整审计正文：`docs/TWO_SERVO_CALIBRATION_READINESS_AUDIT_2026-08-15.md`（11 章）。
本报告是其决策摘要，不替代正文。

## 1. 请 Codex 立即采信的结论

**软件侧已就绪，可支撑 PC 总线标定；阻断项全部落在电源与操作文档层，不在代码层。**

| 维度 | 结论 |
|---|---|
| 6 个 PC 舵机工具 | 就绪，安全开关/越界/容差/释放力矩路径逐行核对通过 |
| 校准模板 | 就绪且**保持空白**（1 行仅表头，0 数据行） |
| 数据日志模板 | 就绪且保持空白，含 `read_ok` / `data_age_ms` |
| PC 端失败关闭模型 | 模型本身正确，但**不覆盖校准阶段工具**（见 §3.1） |
| Titan 安全门 / 姿态库 | 默认全未配置，失败关闭；**固件无舵机写包路径** |
| 厂商 SDK 依赖 | 完整（导入成功，未开端口） |
| 离线自检 | `Ran 229 tests ... OK`，`exit=0` |
| 代码层是否阻断上电 | **否**。阻断项为 §2 的三条，全在文档/电源层 |

可直接采信的三条硬事实（本审计源码级确认）：

1. `probe_scs0009.py` 的 7 个寄存器地址（56/58/60/62/63/66/69）与厂商 SDK
   `scservo_sdk/scscl.py` 的 `SCSCL_*` 常量**逐条一致**，只读探针可信。
2. `titan_rtthread/smart_hand_uart.c`（428 行）检索 `scs0009` / `servo_` / `SERVO`
   **命中 0 条** → 当前通信固件确无舵机写包能力，Titan 侧对本次 PC 标定**无风险敞口**，
   本阶段无需改动 Titan 或 D 盘工程。
3. 全仓库**不存在**任何已填写的 `servo_calibration_v*.csv`，
   `titan_rtthread` 内也**没有**任何硬编码校准值（`center_raw` / `soft_min_raw`
   只出现在校验逻辑中）。当前无任何被预填的方向/中心/限位。

## 2. 需要 Codex 裁决的事项（一次性清单，共 3 条）

以下三条**本审计不裁决、不给数值、不发指令**，只陈述现状与冲突出处。

| # | 需裁决 | 现状与冲突出处 | 阻断什么 |
|---|---|---|---|
| **D1** | **初始限流取唯一值** | `HARDWARE_WIRING_CARDS.md:83` 写「限流约 **2.0A**」；`SERVO_CALIBRATION_AND_LOGGING.md:60` 写「从 **1.0A** 限流完成验证」；`TOMORROW_SINGLE_FINGER_RUNBOOK.md:38` 写「限流先保持 **1.0A**」 | 阻断上电。标定含一次接近半量程的归中大幅转动，限流直接决定堵转/发热边界 |
| **D2** | **确认外部电源入口唯一性，并决定是否补写检查项** | 启动上下文 §4 记录「照片疑似 DC 圆孔与绿色端子同时接有导线」。本审计全仓库检索确认：**该要求尚未落入任何一张接线卡或操作卡的勾选项** —— 即操作者逐条走卡4 也不会被拦住 | 阻断上电。且属流程漏洞，不只是本次问题 |
| **D3** | **是否统一温度拒绝阈值** | 五处不一致：`nudge`=60、`sync_nudge`=60、`center_hold`=50(起)/55(保持)、`finger_smoke`=50、`servo_safety_model` 默认=50。**首次产生运动的两个工具用最宽松的 60**，风险最高的环节门槛最低 | 轻阻断。是否改、改到哪个值由 Codex 定；本审计**未改任何生产代码** |

补充：D1 裁决后需同步更正被否决的那份文档；D2 若决定补检查项，需指定落到哪张卡。
两项文档改动本批**均未执行**，等 Codex 指令。

## 3. 必须写进对外材料并长期保持的两条边界

### 3.1 校准阶段**不受** PC 失败关闭门保护

本审计对全仓库 `.py` 检索 `servo_safety_model`，引用只有两处：
`host/run_offline_rehearsal.py`（离线彩排）与 `tests/test_servo_safety_model.py`（单元测试）。

> **§1 表格中的 6 个 PC 舵机工具，没有任何一个导入或使用 `ServoCommandGate`。**

校准阶段的真机动作只受各工具**自身内联**的电压(`50..70`)/温度/步长/越界/容差检查保护。
这是可接受的引导期状态——安全门需要校准数据，而校准数据正是本阶段要产生的——
但**任何对外材料、答辩稿、竞赛附件都不得写成「两颗舵机校准过程由安全门保护」**。

### 3.2 `511` 不是机械中心

- `center_hold_scs0009_pair.py` 的 `RAW_CENTER = 511` 是**写死的模块常量，无命令行覆盖参数**。
- `finger_smoke_scs0009.py` 的 `--center1` / `--center2` **默认值同为 511**。
- 511 是 0..1023 量程的**电气中点**，不是实测机械中心。

→ `config/servo_calibration_template.csv` 的 `center_raw` **不得直接抄 511**，
必须来自装配后实测并由 Codex 确认。本审计不提供任何建议数值。

一处**正面**发现：`finger_smoke` 启动时校验 `|当前位置 - 传入 center| <= 20`，
若操作者忘记传实测中心而沿用默认 511、而真实中心不在附近，工具会**拒绝运行而不是乱动**。

## 4. 非阻断缺口（供 Codex 决定是否补，本批未实施）

| # | 缺口 | 影响 |
|---|---|---|
| G1 | **校准证据无法自动落盘**：6 个工具**全部无 `--output`**，结果只写终端 | `E0002` 仍 `needs_attachment`；标定过程不会天然产出可附证据 |
| G2 | **方向 / 软限位无采集工具**：`SERVO_CALIBRATION_AND_LOGGING.md` §4-B-7 要求「逐步确认方向并探测保守软限位」，但仓库中无对应工具 | `direction_sign`、`soft_min_raw`、`soft_max_raw` 只能靠人工观察 + 人工停止产生 |
| G3 | 缺「阶段 ↔ 工具 ↔ 确认开关」对照表 | 三个确认开关语义互斥（`--loose-servos-confirmed` 未装机构 / `--frame-mounted-confirmed` 已装框架 / `--mechanism-free-confirmed` 机构顺畅），误用会让声明与实物状态不符 |
| G4 | `run_all_checks.ps1` 的 `py_compile` 清单未含 `tests/test_supported_class_mock_probe.py`、`tests/test_titan_uart_polling_tx_contract.py` | 影响极小（`unittest discover` 已覆盖执行），与舵机无关，仅登记 |

与 G2 相关的一条语义提示（**不是缺陷**，但影响校准判读）：
`nudge_scs0009.py` 的方向由 `direction = 1 if start <= 511 else -1` 自动决定。
按既有记录 ID1 起始约 20、ID2 起始约 1000，两颗会朝**相反的原始寄存器方向**移动。
该工具因此**不能**用来直接判定统一的逻辑正方向。

## 5. 本批改了什么

| 路径 | 动作 |
|---|---|
| `docs/TWO_SERVO_CALIBRATION_READINESS_AUDIT_2026-08-15.md` | **新建**审计正文（11 章，22 KB） |
| 本文件 `docs/CLAUDEA_TO_CODEX_TWO_SERVO_READINESS_2026-08-15.md` | **新建**给 Codex 的交接 |

未改：`host/*`（含全部 6 个舵机工具与 `servo_safety_model.py`）、`titan_rtthread/*`、
`maixcam2/*`、`protocol/*`、`config/servo_calibration_template.csv`、`data/*`、
`README.md`、`HARDWARE_WIRING_CARDS.md`、`TOMORROW_SINGLE_FINGER_RUNBOOK.md`、
`SERVO_CALIBRATION_AND_LOGGING.md`、`evidence_index.csv`、D 盘工程。

生产代码 / 协议 / 校准数据 / D 盘工程：**四项全未触碰**。
唯一副作用：运行 `python -m unittest` 更新了 `__pycache__` 的 `.pyc`。

## 6. 本批实际运行的命令与结果（全部离线，未开串口）

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python --version` | `Python 3.11.7` |
| 2 | 厂商 SDK 导入检查（仅 `import`，**未调用** `comports()`，**未** `openPort()`） | PASS：`scservo_sdk` OK；`pyserial 3.5` |
| 3 | `probe_scs0009.py` 常量 vs SDK `SCSCL_*` 比对 | PASS：7/7 一致 |
| 4 | `python -m unittest tests.test_servo_safety_model tests.test_analyze_servo_log -v` | PASS：`Ran 12 tests ... OK` |
| 5 | `python -m unittest discover -s tests` | PASS：`Ran 229 tests in 0.882s ... OK`，`exit=0` |
| 6 | 全仓库 CSV 清点（排除 `third_party`） | 模板均 1 行表头；**无任何已填写校准文件** |
| 7 | `grep -rn "servo_safety_model" --include=*.py` | 仅 2 处；6 个舵机工具均未引用 |
| 8 | `grep -n "scs0009\|servo_\|SERVO" titan_rtthread/smart_hand_uart.c` | 命中 0 条 |
| 9 | `grep -rn` 电源入口 / 限流数值（`*.md`） | 得出 D1、D2 |

**未**运行 `run_all_checks.ps1`（含 gcc 与 D 盘同步检查）；本审计**未调用 gcc**。

## 7. 并发会话说明（请 Codex 注意归属）

审计期间仓库存在另一个并发会话（grokB 的支持类别归档批次）：

- `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` 在本审计首读后于 **10:41 被改动**。
  本审计已**重新完整读取并逐行比对**：改动仅为**新增** 3 条归档指针
  （`E0006` 报告、四份文档已对齐说明、grokB 交接指针），
  **未改动** §3.3 PC 舵机既有证据、§4 硬件阶段与安全红线、§5 舵机工具清单
  → **本审计全部结论不受影响**。
- `README.md`(10:28)、`LAB_BRINGUP_CHECKLIST.md`(10:27)、`GRIP_POLICY_MVP.md`(10:27)、
  `competition_2026/README.md`(10:28)、`evidence_index.csv`(10:28)、
  `supported_class_mock_2026-08-15.md`(10:20)、`GROKB_TO_CODEX_...md`(10:41)
  **均非 claudeA 所写**。
- `tests/*.exe` 的 10:45 时间戳来自**他人执行 `run_all_checks.ps1` 的 gcc 重建**，非本审计。
- 本审计所依赖的关键文件今日**全部未被改动**（`HARDWARE_WIRING_CARDS.md` 08-14 17:47、
  `TOMORROW_SINGLE_FINGER_RUNBOOK.md` 08-12、`SERVO_CALIBRATION_AND_LOGGING.md` 08-11、
  `host/*scs0009*.py`、`servo_safety_model.py`、`titan_rtthread/*`、校准模板），
  故 §2 三条裁决项成立。

## 8. 建议 Codex 下一步（决策，不是已授权动作）

每一步仍须 Codex 单独授权，且真机指令只能由 Codex 本人发出：

1. **先一次性裁决 §2 的 D1 / D2 / D3**，不要逐条往返。D1 与 D2 未定之前不宜开 6V。
2. D2 建议由 Codex 本人向用户核对实物电源入口（辅助模型不得发上电指令）；
   若确认需补检查项，请指定落到 `HARDWARE_WIRING_CARDS.md` 卡4 还是操作卡，再派辅助模型改。
3. **进入标定前先确定 §3.1 的表述口径**，避免后续答辩稿写出「校准受安全门保护」。
4. 若关心竞赛证据，可先决定是否补 G1（工具落盘能力）——
   否则标定过程仍不会自动产出 `E0002` 所缺的附件，事后补拍成本更高。
5. 在方向、中心、软限位**实测并经 Codex 确认前**：
   禁止填写 `config/servo_calibration_template.csv`，禁止配置生产 pose bank，禁止 Titan 写舵机。
6. 辅助模型新会话仍以 `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` 为唯一启动上下文；
   本报告与审计正文是补充，不替代它。

## 9. 不得外推（请 Codex 继续强制）

- 本审计只证明**软件工具与模板处于可进入校准的状态**；
  **不证明**接线正确、极性一致、电源安全、机械装配到位或舵机可安全转动。
- 229 项离线测试全绿只覆盖**电脑端逻辑**，与真机、供电、机构无关。
- 厂商 SDK 导入成功**不代表**转接板已枚举、COM 口存在或舵机在线。
- 既有 ID1/ID2 记录来自 2026-08-11 会话；按 `SERVO_CALIBRATION_AND_LOGGING.md` §5，
  `servo_id` 须「断电重启后再次读取确认」，本审计**未**做此确认。
- Titan 39/41/65 与 10 分钟 UART 证据与本阶段**无关**，不得用于支持舵机结论。
- `E0002` 仍 `needs_attachment`，PC 总线旧动作不得写成完整竞赛证据。
- 历史发热事件（误把 40 针电源脚当 GND）本审计未删除、未淡化。

## 10. 给 Codex 的一句话

代码层没有拦路石——6 个工具、模板、双侧安全门都就绪且离线全绿；
真正卡住上电的是三条**文档层**裁决（限流 1.0A/2.0A 二选一、单一电源入口无检查项、
温度阈值 50/60 倒挂），以及两条必须提前定死的表述边界
（校准阶段不受安全门保护、511 不是机械中心）。
