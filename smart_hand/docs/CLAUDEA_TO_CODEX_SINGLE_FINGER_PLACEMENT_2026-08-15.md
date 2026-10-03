# claudeA → Codex 主模型审查报告：单指装框机械证据（2026-08-15）

- 发件：claudeA（单指机械装配证据审计员，本批只读资料 + 写文档）
- 收件：Codex 主模型（唯一可向用户下达真机步骤的角色）
- 任务：在两颗 SCS0009 装入单指 Finger Frame 之前，把官方可考的机械事实固定下来
- `hardware_accessed=false`：未上电、未接线、未开串口、未移动舵机、未安装任何零件
- 未修改生产代码、协议、CRC、校准 CSV、姿态库、D 盘 `titan_uart_test`
- 官方资料 `C:\Users\zzh\Downloads\AmazingHand-1.0` **全程只读**，今日无任何改动（已复核）

审计正文：`docs\SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md`（12 节，39.9 KB，含逐条页码/STL 依据）。
本报告是其决策摘要，**不替代正文**，也**不授予任何真机权限**。

---

## 1. 请 Codex 立即采信的结论（均有官方出处）

| # | 结论 | 官方依据 |
|---|---|---|
| A1 | **ID1 = 右侧，ID2 = 左侧**（正视输出轴、指根枢轴朝上、线缆朝下） | `AmazingHand_Assembly.pdf` **p21** 照片箭头 + **p23** 与 **p27** 正文 `right servo horn (ID1)` / `left servo horn (ID2)`，配红/绿虚线图。三处互证 |
| A2 | **两颗输出轴必须远离外展/内收枢轴** | **p18** 原文 `Be aware to orient them as well as the servo axis is far from the abduction / adduction pivot of the finger`；枢轴定义见 **p17**（衬套压入 part1 大圆孔） |
| A3 | **线缆自远离枢轴的一端引出** | **p18 / p20 / p21 / p22 / p23 / p26 / p27** 照片姿态一致（p18 正文未用文字规定，故为图证） |
| A4 | **贴舵机的面 = 有 ⌀2.2 浅沉孔的那一面**；part1 上是**距大圆枢轴孔较远**的那一对孔 | **p18** 原文 `holes for screwing servos are counterbored, that will ease the screwing into plastic part` + 官方 STL 几何（见 §2） |
| A5 | **官方螺钉 = 4× "Servo 2x7 screw"**（随 SCS0009 附带），孔为 ⌀1.5 自攻底孔 | **p5 / p9 / p18** 元件表与正文 |
| A6 | **装框只需两个打印件**：`Finger_Frame-1.stl` + `Finger_Frame-2.stl`（+2 个外购衬套，非打印件） | **p17 / p18** 所需件清单 |
| A7 | **511 是"装舵盘用的电气中点"，不是机械中心** | **p22**（Python `middle position = 0`）/ **p26**（Arduino `Set position 511`）；**p27** 官方示例把 ID1 改到 **520**、ID2 保持 511 |

### 关键新证据：A4 的 STL 几何交叉验证（可复算）

本批解析官方 `cad\stl\Amazing Hand Parts - Finger_Frame-1.stl` / `-2.stl`：

| 孔类型 | 芯孔 | 沉孔 | 沉孔开在 | 全指数量 | 对上的官方 BOM |
|---|---|---|---|---|---|
| 舵机螺钉孔 | ⌀1.50 通孔 | ⌀2.20 × 0.60 | **−Z 面** | **4** | p18 `4x Servo 2x7 screws` ✔ |
| 手掌板孔 | ⌀1.90 通孔 | ⌀2.80 × 0.60 | **+Z 面**（相反面） | **3** | p30 `Fix the finger with 3x thermoplastic screws 2.5x8` ✔ |

两类孔的沉孔**开在相反两面**，且数量 **4 / 3** 与官方 BOM 完全对上，
并与 p18 两张零件平铺照的红圈标注位置自洽（平铺照拍的都是 −Z 面）。
→ 这条把「正反面」从**肉眼歧义**变成了**可自证的物理判据**：操作者摸到 ⌀2.2 沉孔即确定贴舵机面，无需任何推断。

---

## 2. 需要 Codex 裁决的事项（一次性清单，共 3 条）

本批**不裁决、不给建议值、不发操作指令**。

| # | 需裁决 | 现状 | 阻断什么 |
|---|---|---|---|
| **M1** | **M2×6 是否正式放行** | 项目立场（`AmazingHand_主模型临时交接…2026-08-13.md` 第 195 行）是「M2×7 缺两颗时，四颗一致的 M2×6 可作临时固定，只要**不顶到底、不松动**」。本批已**证明「不顶到底」成立**（见 §3）。剩余风险只有两条：① 啮合长度比官方少约 1 mm（`UNVERIFIED`，官方无替代长度数据）；② **螺纹型别是否同为自攻**（`UNVERIFIED`，见下） | 阻断装框动作 |
| **M2** | **实物 Frame-2 是按哪个版本打印的** | 本批发现官方 `3DprintingTips.pdf` **p1** 截图中的 Frame-2 为 `20,00 × 10,95 × 8,00 / Volume 1641,64 / Faces 3768`，而当前 `cad\stl` 中为 `20 × 8.95 × 8 / 1321.62 / 3768`。面数相同、体积差 `320.02 mm³ ≈ 20×8×2.00` → **同拓扑的版本修订，Y 向差 2.00 mm**。截图未给孔位坐标，**孔位是否一致无法比对** | 若实物是旧版打印，4 个舵机孔位一致性存疑；须实物核对 |
| **M3** | **装框之后的装配顺序采官方还是项目现行** | 官方顺序是 **p19**（机构插入衬套）→ **p20**（球头拉杆装到 link，**舵盘随拉杆悬空、尚未上轴**）→ **p22/p26**（中点下把舵盘压上输出轴）。项目现行计划（`…完整上下文交接_2026-08-11.md` 第 866–876 行）是「固定舵机 → 上电置中 → **保持期间装舵盘** → 断电装连杆」，即**舵盘先于连杆**。两者实质不同 | 不阻断本次装框（A 阶段两者一致），但影响其后每一步 |

**M1 的关键补充（请 Codex 特别看）：** 官方件写的是 `Servo 2x7 screw`，而 STL 孔芯径为 **⌀1.50**，
远小于螺钉公称外径 ⌀2.0，且 p18 原文写明沉孔作用是 `ease the screwing **into plastic part**`
→ **官方件是自攻/成形螺纹螺钉**。若项目手上的「M2×6」是**普通机制螺纹**（螺纹已成形、大径 2.0），
拧入 ⌀1.5 未攻塑料孔的受力方式与自攻件不同，**胀裂孔壁或滑牙的风险不同**。
本地无该螺钉规格资料 → `UNVERIFIED`，请 Codex 向用户确认实物螺钉型别后裁决。

---

## 3. 可以从风险清单中划掉的一项（本批已证明）

**「M2×6 顶到底 / 顶穿 / 顶壳」——几何上排除，对 6 mm 与 7 mm 均成立。**

证明（不依赖任何未知量）：

1. 舵机螺钉孔是**通孔**：⌀1.50 段 `z = 5.10 → 12.50`，上游 ⌀2.20 沉孔 `z = 4.50 → 5.10`，贯穿整板
   → **不存在"拧到孔底顶死"的情形**。
2. 板厚 `12.50 − 4.50` = **8.00 mm**（Frame-1 与 Frame-2 相同）。螺钉需先穿过舵机自身安装耳（厚度 ≥ 0），
   即使把耳厚取极端的 0，进入塑料的最大长度也只有螺钉全长（7 或 6 mm）**< 8.00 mm**
   → **不可能从另一面穿出**。
3. 唯一潜在受害面是 +Z 面，而 +Z 面是 Step 4 与**手掌板**的贴合面，**不是任何指壳**。
   指壳按 **p16** 装在「手指机构（Proximal / Distal）」上，**不装在 Finger Frame 上**
   → **装框阶段在结构上与指壳没有接触面**。

→ 请 Codex 把「顶到底/顶壳」从 M2×6 的待评估风险中移除，只保留啮合长度与螺纹型别两项。

---

## 4. 必须写进后续材料并长期保持的三条边界

1. **511 ≠ 机械中心。** 官方在 p22/p26 用它装舵盘，在 p27 示例里把 ID1 改到 **520**。
   → `config\servo_calibration_template.csv` 的 `center_raw` **不得填 511**。
   （项目脚本已同向修正：`center_hold_scs0009_pair.py` 常量现名 `RAW_ELECTRICAL_MIDPOINT`，
   `finger_smoke_scs0009.py` 的 `--center1/--center2` 已改为 `required=True` 并移除 511 默认值。）
2. **官方"同向/反向"≠ 原始寄存器方向。** `AmazingHand_Overview.pdf` **p2** 写
   `Flexion / Extension occurs when motors acting in the same way` /
   `Abduction / Adduction occurs when motors acting in opposite way`，
   但本地官方资料**未给出**「作用方向」与「SCS0009 原始寄存器增减」之间的映射；
   且 p23/p27 官方自述 `Due to symmetrical location of servos, rotation way is not obvious`。
   → **不得**据官方资料推断 `direction_sign`，也**不得**判定 `finger_smoke_scs0009.py` 中
   「ID1 `+delta` / ID2 `−delta`」对应屈伸还是内收/外展。**必须实测。**
3. **官方装框页不含任何通电内容。** p17/p18 全程断电作业；官方把上电中点放在 p22/p26（Step 3）。
   → 装框完成**不等于**可以进入置中。

---

## 5. `UNVERIFIED` 清单（本批拒绝补全）

| # | 未确认项 |
|---|---|
| U1 | 项目手上的「M2×6」是否为自攻型（→ M1） |
| U2 | 少 1 mm 啮合长度是否仍满足夹持强度（官方无数据） |
| U3 | SCS0009 安装耳厚度（本地无器件机械图；§3 的证明已设计为不依赖该值） |
| U4 | 各舵机 `direction_sign`（→ 边界 2） |
| U5 | 机械中心 `center_raw`、软限位 `soft_min_raw` / `soft_max_raw` |
| U6 | 打印指引截图版本与当前 STL 之间**孔位**是否一致（→ M2） |
| U7 | Step 5 掌壳/顶壳与单指框架舵机螺钉的间接干涉（属 Step 5，非本阶段） |
| U8 | 用户实物两颗舵机在框架中的**实际**朝向与左右（本批不看实物、不据照片判定） |
| U9 | 整手渲染（p29）红色 1–8 标号与单指内部左右的对应（视角不同，不作依据） |
| U10 | AmazingHand 官方 `5V` 与已裁决 `6.0V` 是否真正冲突（见 §6） |

---

## 6. 一条知悉项（已裁决，无需重开）

`AmazingHand_Overview.pdf` **p6** 写整手供电 `DC Supply 5V / Max current 3A`，
`README.md` p126 建议 `5V / 2A` 适配器，`Assembly.pdf` **p26** FD 反馈显示 `Voltage 4.8V`。
项目一贯用 **6.0V**，且已由 `docs\TWO_SERVO_POWER_AND_THERMAL_DECISION_2026-08-15.md`
第 12–18 行裁决为 6.0V（1.0A → 2.0A，50 °C），依据写明是 **SCS0009 器件规格**（6V 堵转约 1A/颗）。

→ 二者**不必然矛盾**（器件工作电压 vs 整手推荐供电），但本地**无 SCS0009 规格书**可对齐两个口径。
**本批不重开该裁决**，仅登记为 U10 供知悉。

---

## 7. 本批改了什么

| 路径 | 动作 |
|---|---|
| `docs\SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md` | **新建**审计正文（12 节） |
| 本文件 `docs\CLAUDEA_TO_CODEX_SINGLE_FINGER_PLACEMENT_2026-08-15.md` | **新建**给 Codex 的审查报告 |

未改：`host\*`（含全部舵机工具）、`titan_rtthread\*`、`maixcam2\*`、`protocol\*`、
`config\servo_calibration_template.csv`（仍 1 行表头、0 数据行）、`data\*`、
`README.md`、接线卡、操作卡、`evidence_index.csv`、D 盘工程，
以及 `C:\Users\zzh\Downloads\AmazingHand-1.0`（官方资料全程只读）。

生产代码 / 协议 / 校准数据 / 姿态库 / D 盘工程：**五项全未触碰**。

---

## 8. 本批实际执行的操作与结果（全部只读 + 离线计算）

| # | 操作 | 结果 |
|---|---|---|
| 1 | 比对用户附件与官方仓库副本 | `.codex\attachments\3a16bae7-…\AmazingHand_3DprintingTips.pdf` 与官方 `docs\` 内同名文件 **SHA-256 逐字节相同**（`492E3441…3BF5`），附件无额外信息 |
| 2 | Read 工具打开装配 PDF | 报 `PDF is password-protected` |
| 3 | 改用 PyMuPDF 打开 | `needs_pass=0, is_encrypted=False, permissions=-4, pages=37`；仅设权限位，**未做任何解密或破解** |
| 4 | 逐页提取三份官方 PDF 文本 | 确认 **PDF 页码 = 幻灯片编号**；与前期提取的 `tmp\pdfs\amazinghand_assembly.txt` 复核一致 |
| 5 | 渲染 p19/p20/p23/p25/p26/p27/p29 与打印指引 p1/p2 | 输出至任务临时目录，**未写入仓库** |
| 6 | 解析两个 Frame STL（自写二进制解析 + Hough 式孔轴检测） | 得全部孔位、孔径、沉孔朝向（§1 表） |
| 7 | 计算面数/包围盒/体积 | Frame-1 `6228 / 20×21×8 / 2337.27`；Frame-2 `3768 / 20×8.95×8 / 1321.62` |
| 8 | 与打印指引截图数值比对 | 面数相同、体积差 `320.02 ≈ 20×8×2.00` → 判定版本差异（M2） |
| 9 | 复核项目历史文档 | 定位既有装框结论与 M2×6 立场的确切行号 |

**未运行**：`run_all_checks.ps1`、gcc、任何舵机脚本（连 `--help` 也未运行）。

---

## 9. 并发会话说明（请 Codex 注意归属）

本批写入时间 15:35–15:50。仓库内另有会话在 **11:23–13:01** 改动了多个文件，**均非 claudeA 所写**：

- `host\center_hold_scs0009_pair.py`(11:23)、`finger_smoke_scs0009.py`(11:23)、
  `sync_nudge_scs0009_pair.py`(11:56)、`probe_scs0009.py`(11:59)、`nudge_scs0009.py`(12:05)
  → 本批已按**改动后**版本复核前两个脚本（常量改名、511 默认值移除）。
- `HARDWARE_WIRING_CARDS.md` / `SERVO_CALIBRATION_AND_LOGGING.md` /
  `TOMORROW_SINGLE_FINGER_RUNBOOK.md`(11:31)
  → 本文件**未引用**这三份的行号，只引用仓库外的历史交接（今日未改动）→ 不受影响。
- `docs\TWO_SERVO_POWER_AND_THERMAL_DECISION_2026-08-15.md`(12:16)
  → D1 已裁决，本批据此把电压问题降级为知悉项 U10。
- `validation_reports\two_servo_loose_bench_acceptance_2026-08-15.md`(12:16)
  → 已归档散置台架验收，其自述「不证明机械中心、安装方向、机械软限位」
  **与本审计 §7/§9 相互印证，无冲突**。
- `tests\*.exe`(12:18) 的 gcc 重建**非本批所为**（本批未调用 gcc）。

**官方资料今日无任何改动**（`find -newermt` 复核为空）→ §1 全部官方结论不受并发影响。

---

## 10. 建议 Codex 下一步（决策，不是已授权动作）

1. **一次性裁决 M1 / M2 / M3**，不要逐条往返。M1 与 M2 未定之前不宜开始装框。
2. M1 与 M2 都需要**向用户核对实物**（螺钉是否自攻、Frame-2 是按哪版打印）——
   这两条只能由 Codex 本人问，辅助模型不得发真机指令。
3. 若采纳 §1 的 A1–A7，建议把 **A4 的沉孔判据**写进操作卡：它是自证的，
   比"左/右/正/反"这类依赖视角的描述更不容易出错。
4. **在装框之前先定 §4 三条边界的表述口径**，避免后续答辩稿写出「511 是机械中心」
   或「已确定舵机正方向」。
5. `direction_sign`、`center_raw`、软限位在实测并经 Codex 确认前，
   禁止填写 `config\servo_calibration_template.csv`，禁止配置生产 pose bank。

---

## 11. 给 Codex 的一句话

装框所需的官方机械事实已全部落到页码和 STL 几何上：ID1 右 / ID2 左（三处互证）、
输出轴远离枢轴、沉孔面即贴舵机面（4/3 孔数与官方 BOM 对上）；
**M2×6 的"顶到底/顶穿/顶壳"已被几何证伪，可以划掉**，剩下的只有螺纹型别、啮合 1 mm 和旧版孔位这三件
——都需要你向用户核对实物，我不能问也不能猜。
