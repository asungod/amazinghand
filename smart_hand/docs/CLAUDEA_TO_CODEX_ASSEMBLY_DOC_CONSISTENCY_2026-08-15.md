# claudeA → Codex 主模型交接：机械装配文档一致性（2026-08-15）

- 发件：claudeA（机械装配文档一致性条线）
- 收件：Codex 主模型
- 任务来源：`docs/AUX_MODEL_TASK_BOARD_2026-08-15.md` §「Claude A：机械装配文档一致性」
- `hardware_accessed=false`：未上电、未接线、未开串口、未移动舵机、未安装任何零件
- 未改脚本、未填校准值、未下达任何真机指令
- 生产代码 / 协议 / CRC / 校准 CSV / 姿态库 / D 盘 `titan_uart_test`：**六项全未触碰**

---

## 1. 修改文件完整路径

| # | 路径 | 动作 |
|---|---|---|
| 1 | `smart_hand\docs\SINGLE_FINGER_ASSEMBLY_ORDER_RECONCILIATION_2026-08-15.md` | **新建**·顺序裁决主文档 |
| 2 | `smart_hand\TOMORROW_SINGLE_FINGER_RUNBOOK.md` | **重写**·状态同步 + 去执行授权化 |
| 3 | `smart_hand\docs\SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md` | **重写**·Gate 2/3 内容按官方对调 |
| 4 | `smart_hand\SERVO_CALIBRATION_AND_LOGGING.md` | **修改**·§1 状态、§2 已确认/未确认、§4 阶段 B/C/D |
| 5 | `smart_hand\docs\CLAUDEA_TO_CODEX_ASSEMBLY_DOC_CONSISTENCY_2026-08-15.md` | **新建**·本报告 |

**未改**：`README.md`、`competition_2026\*`、`validation_reports\*`、`host\*`、`titan_rtthread\*`、
`maixcam2\*`、`protocol\*`、`config\servo_calibration_template.csv`（仍 1 行表头、0 数据行）、D 盘工程。

---

## 2. 关键改动与证据来源

### 2.1 状态口径统一（任务项 2）

四份文档现在一致陈述：**两颗舵机已固定进 Finger Frame；舵盘与球头拉杆均未安装；`M2x18` 运输中；机械动作暂停。**

清理掉的过期表述：

| 文件 | 原文 | 现状 |
|---|---|---|
| `TOMORROW_SINGLE_FINGER_RUNBOOK.md` | 「先只完成两颗舵机与 `Finger Frame Part1/Part2` 的固定」 | 已删；改为 §2「已完成：装框」+ 官方核对判据 |
| `SINGLE_FINGER_MOUNTED_CALIBRATION_GATE` §2 | 「下一阶段唯一目标：只把两颗舵机固定到 Finger Frame」 | 已改为「装框已完成，下一阶段是断电照片审查与只读复核」 |
| `SINGLE_FINGER_MOUNTED_CALIBRATION_GATE` §1 | 只列散置台架证据 | 增列「装框已完成」为入口条件 (b)，并注明仅指螺钉已固定 |
| `SERVO_CALIBRATION_AND_LOGGING` §4 阶段 B-1 | 「再将 ID1/ID2 固定进 `Finger Frame Part1/Part2`」 | 已删；阶段 B 改为断电机械装配 |

保留：Runbook 中「原名『明天…』因 2026-08-12 停电顺延」的历史说明**未删除**，只标注其中一句已过期。

### 2.2 顺序冲突裁决（任务项 3）——以官方证据为主

**冲突**：项目旧顺序「装框 → 上电置中 → 保持期间装舵盘 → 断电装连杆」
vs 官方「p19 机构插入衬套 → **p20 拉杆先接 link** → p22/p26 电气中点下**舵盘才上输出轴**」。

**裁决：采官方顺序。** 依据（`AmazingHand_Assembly.pdf`，SHA-256 `328E46FF…DE567`，页码=幻灯片编号）：

| 页 | 原文/内容 | 作用 |
|---|---|---|
| p11 | 球头拉杆所需 `1x M2 threaded rod L18mm`，标 `X2`，页尾 `You will need two of them for a whole finger assembly.` | 每指 2 根拉杆，各需 1 根 L18 |
| p12 | `1x Ball joint rod assembly` + `1x Custom servo horn` + `1x M2x10 screw` + `1x M2 nut` | **舵盘在此步就被螺栓固定到拉杆上**，之后不是独立零件 |
| p20 | `Insert the free side of a ball joint rod on the M2 threaded present on link part, by ensuring servo horn is in the good way to be later assembled on servo axis.` 配图舵盘悬空、输出轴裸露 | 拉杆先接 link；舵盘尚未上轴 |
| p22 / p26 | `Place servo horns as following picture (= middle position)` / `Screw both servo horns with M2x4 screw` / `Set position 511` | 舵盘在电气中点压上输出轴 |

**为什么不是"两种做法都行"**：官方把舵盘定义为「舵盘＋球头拉杆」组件的一端（p12），
上轴时另一端已连着 link（p20）。旧顺序把舵盘当独立件先装，与官方装配对象定义不一致；
即便强行执行，事后再接拉杆也会扰动刚在中点对好的相位。

**安全门控全部保留**：Gate 结构、限流 1.0A→2.0A、50 °C 阈值、立即断电条件、
「每一步需 Codex 现场授权」均未放松。Gate 编号仍为 0–4，只对调了 2 与 3 的**内容**。

### 2.3 本条线最重要的发现：`M2x18` 阻断的不只是连杆

```
M2x18 缺 → 做不出球头拉杆(p11) → 做不出「舵盘＋拉杆」组件(p12)
        → 到不了「拉杆接 link」(p20) → 官方顺序下装不了舵盘(p22)
```

→ **不存在"先把舵盘装上、只等零件装连杆"这一中间选项。**

旧 Runbook 与旧 Gate 2 恰好隐含了该选项。若沿用旧文档，很可能在等件期间
被误读成"舵盘这步现在就能做"，从而产生一次未授权的上电与大幅归中动作。
这是本次必须改文档的**实际安全风险**，不只是措辞问题。

### 2.4 去执行授权化（任务项 4）

- `TOMORROW_SINGLE_FINGER_RUNBOOK.md`：**移除**了 `center_hold` 与 `finger_smoke` 的
  可直接复制执行的 PowerShell 命令块，改为指向 Gate 文档的说明性引用，
  并明写「当前两者均不具备执行条件」。仅保留纯离线的 `run_offline_rehearsal.py`。
- `SERVO_CALIBRATION_AND_LOGGING.md` §4 顶部加入暂停横幅：
  「阶段 B 起全部暂停…阶段 C、D 中的两条命令当前均不具备执行条件，且每次运行需 Codex 单独授权」。
- Gate 文档顶部状态改为 `PAUSED_WAITING_M2X18` + `NOT_AN_EXECUTION_AUTHORIZATION`。

---

## 3. 实际运行命令与结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `python -m unittest discover -s tests` | **PASS**：`Ran 267 tests in 0.988s ... OK`，`exit=0`（与启动上下文记载的 267 基线一致） |
| 2 | 全仓库 grep「先只完成 / 只把两颗舵机固定 / 再将 ID1/ID2 固定进 / 断电安装拉杆」 | 仅剩 Runbook §注 中"该表述已过期"的自述，无实质残留 |
| 3 | grep 三份受管文档中的 `center_hold` / `finger_smoke` | Runbook 内无命令块；规范与 Gate 内的命令均处于显式前置条件之下 |
| 4 | 受管四份文档乱码扫描 | 无 |
| 5 | `wc -l config/servo_calibration_template.csv` | `1`（仅表头，未填写） |

**未运行**：`run_all_checks.ps1`、gcc、任何舵机脚本（连 `--help` 也未运行）。

---

## 4. 需 Codex 处理的跟进项

### 4.1 越界未改：Gate 模板存在两行过期引用（**请指派**）

`validation_reports\single_finger_gate0_gate1_template_2026-08-15.md` 作者为 **grokB**，
按启动上下文 §6「三者不得互相修改对方正在负责的文件」，**我未改动**。
但其中两行在本次 Gate 内容对调后已过期：

| 行 | 现文 | 建议改为 |
|---|---|---|
| 5 | `不覆盖：Gate 2 电气中点 / 装舵盘、Gate 3 装连杆、Gate 4 单指冒烟` | `不覆盖：Gate 2 断电机械装配（机构＋球头拉杆）、Gate 3 电气中点与装舵盘、Gate 4 实测范围与单指冒烟` |
| 249 | `可以安装舵盘或连杆（那是 Gate 2 / Gate 3，须另行授权）` | `可以安装机构、连杆或舵盘（那是 Gate 2 / Gate 3，须另行授权）` |

另：该模板第 4 行「Gate 0（断电装框与照片审查）」的措辞在装框已完成后偏窄，
是否同步为「断电照片审查」由你决定。

### 4.2 需向用户核对的实物问题（我不能问，也不猜）

| # | 问题 | 影响 |
|---|---|---|
| Q1 | 到货的 `M2x18` 数量是否满足官方**每指 2 根**（p11 `X2`） | 直接决定何时解除暂停 |
| Q2 | link 用的 `M2 L25mm`（p13/p15）是否已在手 | Gate 2 第 1 步的必需件 |
| Q3 | 手指机构本体（Proximal/Distal/Gimbal/Link + 轴）是否已装配 | 官方 p19 的前置，仓库内**无任何记录** |
| Q4 | 柔性指壳是否已打印 | 早期交接记「因无法打印 TPU，默认尚未打印」；官方 p16 在 p19 之前 |
| Q5 | 十字舵盘是否已按官方 p6 改制（钻 ⌀1.5、攻 M2、切臂打磨） | 官方 p12 用的是 Custom servo horn |
| Q6 | `M2x10`+`M2` 螺母（p12）、`M2.5` 大垫圈+`2.5x8` 热塑螺钉（p19）是否齐备 | Gate 2 必需件 |
| Q7 | 装框所用 M2×6 是否与官方 `2x7` 同为**自攻型** | 承接前一批 M1；「顶到底/顶穿/顶壳」已由 STL 几何证伪，只剩此项与啮合 1 mm |

### 4.3 登记但不裁决：官方文档自身尺寸冲突

| 官方页 | 球头拉杆用杆 | link 用杆 |
|---|---|---|
| p6 | `8x M2 Threaded rod L16mm maximum (L14 minimum)` | `4x M2 Threaded rod L26mm minimum (L28 maximum)` |
| p9 / p11 / p13 / p15 | `2x M2 threaded rod L18mm` | `1x M2 threaded rod L25mm` |

两处数值互不相容（L18 超出 p6 上限；L25 低于 p6 下限）。官方 p10–p11 另有 `Length tooling`（标注 33 mm）最终定长，
拉杆成品长度由球头旋入深度调节，切割长度只是毛坯——可能是范围与标称并存的原因，但**冲突客观存在**。
项目现按 `M2x18` 采购，与 p9/p11 一致。已在裁决文档 §4.2 登记，**不裁决孰对**，以免日后被当成项目笔误。

---

## 5. 仍未验证项与禁止外推项

**未验证**：Q1–Q7 全部；以及两个关节的方向、机械中心、软限位（`direction_sign` / `center_raw` /
`soft_min_raw` / `soft_max_raw` 仍全空）。

**禁止外推**：

- 「装框已完成」**仅指**螺钉已固定，**不含** Gate 0 的断电照片审查与安装方向现场核对；
- 采纳官方顺序**不等于**官方顺序已被授权执行；
- `511` 始终是**电气中点参考**，官方 p27 示例本身把 ID1 调到 `520`，**不得写入 `center_raw`**；
- 官方 `Overview.pdf` p2「同向＝屈伸、反向＝内收外展」**未给出**与 SCS0009 原始寄存器方向的映射，
  且官方 p23/p27 自述 `rotation way is not obvious` → `direction_sign` **必须实测**；
- 本批只统一文档，**不证明**任何机械步骤已完成、可执行或安全。

---

## 6. 给 Codex 的最小审查提示（10 行内）

1. 核心改动只有一处实质性：**Gate 2 与 Gate 3 内容对调**，理由是官方 p12/p20 把舵盘定义为「舵盘＋拉杆」组件的一端。
2. 请优先确认 §2.3 的依赖链结论——它意味着等件期间**舵盘也不能装**，旧文档隐含了相反暗示。
3. 四份文档状态口径已统一为「已装框 / 舵盘连杆未装 / M2x18 待到货 / 暂停」。
4. Runbook 已移除两条动作命令的可执行块；规范与 Gate 内的命令均加了显式前置与暂停横幅。
5. 安全门控无任何放松：限流、50 °C、立即断电条件、逐步授权要求原样保留。
6. §4.1 有两行过期引用在 grokB 的模板里，我按不跨条线规则未改，请指派。
7. §4.2 的 Q1–Q7 需你向用户核对实物，我不能问也不猜。
8. `config/servo_calibration_template.csv` 仍 1 行表头、0 数据行。
9. 离线测试 267/267 通过，`exit=0`。
10. `hardware_accessed=false`；生产代码/协议/校准/姿态库/D 盘工程未触碰。
