# 单指机械装配 · 两颗 SCS0009 装框位置审计（2026-08-15）

> 作者：claudeA（单指机械装配证据审计员）。本批**只读资料 + 写文档**。
> `hardware_accessed=false`：未上电、未接线、未开串口、未移动舵机、未安装任何零件。
> 未修改生产代码、协议、校准 CSV、姿态库、D 盘 Studio 工程。
> 本文件**不是操作指令**，不授权任何真机步骤；所有装配动作须由 Codex 主模型逐步授权。
>
> 当前阶段红线（用户已声明）：**禁止上电、禁止动作、禁止安装舵盘和连杆、禁止填写校准 CSV。**
> 本文件第 6 节的舵盘相位内容**仅为后续备查**，本阶段不得据此安装。

---

## 0. 审计范围、资料清单与证据等级

审计目标：在「两颗 SCS0009 装入单指 Finger Frame」之前，把官方可考的机械事实固定下来，
并把不可考的部分显式标记，杜绝凭经验或外观推断。

### 0.1 本批实际使用的资料（全部本地，含 SHA-256）

| 代号 | 完整路径 | SHA-256 | 说明 |
|---|---|---|---|
| `ASM` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\docs\AmazingHand_Assembly.pdf` | `328E46FF80CF4F7B88F3AB205166F1BD1E51D0C423D87BD12494568C36CDE567` | 官方装配指南，**37 页**；实测 **PDF 页码 = 页面右下角幻灯片编号**，本文件引用即为该页码 |
| `TIPS` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\docs\AmazingHand_3DprintingTips.pdf` | `492E3441B61702420AF77B159879EEE8D1A17C38AA94556E47DE49BA3C623BF5` | 官方 3D 打印指引，5 页 |
| `TIPS-ATT` | `C:\Users\zzh\.codex\attachments\3a16bae7-f376-496b-a983-eed5a3414317\AmazingHand_3DprintingTips.pdf` | `492E3441…3BF5`（**与 `TIPS` 逐字节相同**） | 用户提供的附件，经哈希比对确认是 `TIPS` 的副本，无额外信息 |
| `OVW` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\docs\AmazingHand_Overview.pdf` | `1826CF25AF0F193A97382E8FF817AC5DFA44259EF3E44F56D9B552BEFCCAABC6` | 官方总览，6 页 |
| `RDM` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\README.md` | — | 官方仓库 README |
| `STL1` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\cad\stl\Amazing Hand Parts - Finger_Frame-1.stl` | `53FC7C75BD2FAA760F155B05C0E14A1A3EE7A20793B6A42CEBC4D80833AC68CE` | 官方 STL，本批做了几何量测 |
| `STL2` | `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\cad\stl\Amazing Hand Parts - Finger_Frame-2.stl` | `5D0877160DB49EB333CD60D2BC31D58A234ACA3FFB9AC32FA1D77AAE2A8CBAA6` | 同上 |
| `PRE-TXT` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\tmp\pdfs\amazinghand_assembly.txt` | — | 前期会话提取的 `ASM` 全文（602 行），本批已与 `ASM` 原文逐页复核一致 |
| `PRE-IMG` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\tmp\pdfs\amazinghand_assembly\` | — | 前期提取页图：`page-18.png`、`calibration-21.png`、`calibration-22.png` 等 |
| `HO-0811` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\AmazingHand_MaixCAM2_Titan_完整上下文交接_2026-08-11.md` | — | 项目历史交接，第 860–867 行含既有装框结论 |
| `HO-0813` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\AmazingHand_主模型临时交接_完整上下文与审查规范_2026-08-13.md` | — | 第 195 行含 M2×6 替代结论 |

`ASM` 用本机 Read 工具直接打开时报「password-protected」；本批改用 PyMuPDF 读取，
`needs_pass=0 / is_encrypted=False / permissions=-4 / pages=37`，即该 PDF 仅设了权限位，
内容可完整读取。**未做任何解密或破解。**

### 0.2 证据等级

| 等级 | 含义 |
|---|---|
| `OFFICIAL-TEXT` | 官方 PDF 正文可直接读到的原文 |
| `OFFICIAL-FIG` | 官方 PDF 页面图片可直接看到的内容 |
| `OFFICIAL-CAD` | 由官方 STL 几何量测得出，可复算 |
| `PROJECT-DOC` | 项目自身历史文档，不是原厂资料 |
| `UNVERIFIED` | 本地官方资料不足以确认，**禁止补全** |

---

## 1. 结论摘要

| # | 审计项 | 结论 | 等级 |
|---|---|---|---|
| 1 | ID1/ID2 框内位置 | **正视输出轴、指根枢轴在上、线缆向下时：ID1 = 右，ID2 = 左**；官方三处独立互证 | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |
| 2 | 输出轴朝向 | 官方硬性要求：**输出轴远离外展/内收枢轴（bushing 大孔）那一端** | `OFFICIAL-TEXT` |
| 3 | 线缆出口 | 官方图示：**线缆从远离枢轴的一端引出**（与输出轴同侧、朝枢轴反方向） | `OFFICIAL-FIG` |
| 4 | 框架正反面 | **贴舵机的一面 = 带 ⌀2.2×0.6 引导沉孔的那一面**；该面与「装手掌板」的沉孔面**互为反面** | `OFFICIAL-CAD` + `OFFICIAL-FIG` |
| 5 | 官方螺钉 | **4× "Servo 2x7 screw"**，随 SCS0009 附带；孔为 ⌀1.5 自攻底孔 | `OFFICIAL-TEXT` + `OFFICIAL-CAD` |
| 6 | M2×6 能否替代 | **几何上"顶穿/顶到底"风险可排除**（塑料通孔 8.00 mm > 7 mm ≥ 6 mm）；但**啮合长度少约 1 mm**，且**螺纹类型是否同为自攻未确认** | 部分 `OFFICIAL-CAD`，部分 `UNVERIFIED` |
| 7 | 顶壳风险 | **装框阶段不存在顶指壳风险**（指壳装在手指机构上，不在框架上）；唯一潜在干涉面是 Step 4 与手掌板的贴合面，而该面在几何上不会被 6/7 mm 螺钉穿出 | `OFFICIAL-CAD` + `OFFICIAL-TEXT` |
| 8 | 装框阶段零件 | 只需 `Finger_Frame-1.stl` + `Finger_Frame-2.stl`（+2 个外购衬套）；其余手指零件本阶段全部不需要 | `OFFICIAL-TEXT` |
| 9 | 舵盘官方相位 | 官方在**电气中点**（Python 0° / Arduino raw **511**）下装舵盘，两舵盘固定螺钉共线且垂直于手指轴线；精调判据是**手指闭合时舵盘与舵机中平面对齐** | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |
| 10 | 官方明确警告 | 「由于舵机对称安装，**旋转方向并不显然**」——官方自己要求反复试配 | `OFFICIAL-TEXT` |
| 11 | 发现的资料冲突 | `TIPS` 截图中的 Frame-2 比当前 `STL2` **在 Y 向长 2.00 mm**（体积差 320.02 mm³ 完全吻合）→ 版本差异 | `OFFICIAL-CAD` |
| 12 | 发现的规格冲突 | 官方整手供电写 **5V / 最大 3A**；项目文档一贯写 **6.0V** | `OFFICIAL-TEXT` vs `PROJECT-DOC` |

---

## 2. ID1 / ID2 在单指框架内的准确位置

### 2.1 官方三处互证

| 出处 | 证据原文 / 图片含义 | 等级 |
|---|---|---|
| `ASM` **第 21 页**（`PRE-IMG\calibration-21.png`）「Step 3 : Finger calibration with Python ★ Setting IDs」 | 整指实物照片，两条引线标注：**"ID 2" 指向图中左侧舵机，"ID 1" 指向图中右侧舵机**。照片姿态：手指朝上、两舵机在下、线缆向下、可见输出轴/舵盘面朝镜头 | `OFFICIAL-FIG` |
| `ASM` **第 23 页**「★ Fine tuning」 | 正文原文：`- right servo horn (ID1) is a bit not far enough => New Middle pos should be increased of +3°` / `- left servo horn (ID2) is OK`。配图中**右侧舵机画红色虚线（需修正）、左侧画绿色虚线（合格）**，与文字一一对应 | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |
| `ASM` **第 27 页**「Step 3 : Finger calibration with Arduino ★ Fine tuning」 | 正文原文：`- right servo horn (ID1) is a bit not far enough => New Middle pos should be increased to 520` / `- left servo horn (ID2) is OK with 511 value`。配图同第 23 页，红/绿虚线左右一致 | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |

三处**互相独立**（一处是照片标注，两处是不同控制路线下的文字＋图），结论完全一致。

### 2.2 位置表

**视角定义（必须先满足，否则左右无意义）：**
正视**舵机输出轴/舵盘所在的那一面**；**指根外展/内收枢轴（Finger frame part1 的大圆孔＋衬套）朝上**；
**两根舵机线缆朝下**。此视角即 `ASM` 第 21/22/23/26/27 页照片的拍摄姿态。

| 舵机 ID | 该视角下的位置 | 官方直接依据 | 等级 |
|---|---|---|---|
| **ID 1** | **右侧** | `ASM` p23 / p27 正文 `right servo horn (ID1)`；`ASM` p21 照片 "ID 1" 箭头指右 | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |
| **ID 2** | **左侧** | `ASM` p23 / p27 正文 `left servo horn (ID2)`；`ASM` p21 照片 "ID 2" 箭头指左 | `OFFICIAL-TEXT` + `OFFICIAL-FIG` |

### 2.3 与整手编号的关系

`ASM` **第 24 页**与**第 28 页**（Python / Arduino 两版，文字相同）原文：

```
ID are defined as follow :
   -Index finger : 1 & 2
   -Middle finger : 3 & 4
   -Ring finger : 5 & 6
   -Thumb finger : 7 & 8
```

→ 本项目的 ID1/ID2 对应**食指（Index）**位。`RDM` 第 115–117 行原文：
`Note that this assembly guide is for a standalone right hand.` /
`If you need to build a standalone left hand, you can keep the same IDs for servo locations`
→ 左右手不改变「ID 绑定到舵机位置」这一规则。

### 2.4 一处曾被误读、本批已排除的假冲突

`PRE-TXT` 第 479 行把 `ASM` 第 25 页抽出为 `ID 1    ID 2`，顺序与第 21 页相反，**曾疑似左右矛盾**。
本批调阅 `ASM` 第 25 页原图确认：该页是「Arduino 路线逐颗设 ID」，
**"ID 1" 与 "ID 2" 是上下两张独立照片各自的标题**，每张只接一颗舵机，
**不表示左右位置**。→ **不构成冲突**，第 21/23/27 页结论不受影响。

### 2.5 明确不能由本批断言的一点

`ASM` **第 29 页**「★ Fingers mounting /!\ reminder about IDs related to finger location」的整手 CAD 渲染图上标有红色 `1 2 3 4 5 6 7 8`。
该渲染的**观察方向与第 21/23/27 页的单指照片不是同一视角**，本批**无法**由该渲染反推单指内部左右。
→ 整手渲染**不作为**本审计 ID 左右的依据；单指左右**只以第 21/23/27 页为准**。

---

## 3. 输出轴朝向、线缆出口方向与框架正反面

### 3.1 输出轴朝向（官方硬性要求）

`ASM` **第 18 页**「Step 2 : Finger assembly ★ Actuators」正文原文（`PRE-TXT` 第 348 行同）：

```
Be aware to orient them as well as the servo axis is far from the abduction / adduction pivot of the finger
```

「abduction / adduction pivot」的定义见 `ASM` **第 17 页**「★ Bushings」正文原文：

```
Start pushing both bushings at each side of the finger frame part1.
You will have to push against a flat surface to insert them until the end.
This will create abduction / adduction of finger
```

→ **外展/内收枢轴 = Finger frame part1 上压入两个衬套的那个大圆孔**。
→ **两颗舵机的输出轴必须位于远离该大圆孔的一端。**

`OFFICIAL-CAD` 佐证（可复算）：`STL1` 与 `STL2` 在**同一装配坐标系**中导出。
`STL1` 衬套孔轴心在 `(x,y) = (0.00, 0.00)`；`STL1` 的舵机螺钉孔在 `y = -12.40`，
`STL2` 的舵机螺钉孔在 `y = -40.95`。两排螺钉孔中点约 `y = -26.7`，
即舵机本体（含输出轴）整体位于距枢轴约 **26.7 mm** 的另一端，与上述正文完全一致。

### 3.2 线缆出口方向

| 出处 | 图片含义 | 等级 |
|---|---|---|
| `ASM` **第 18 页**右侧「装配完成」与「侧视」两张照片（`PRE-IMG\page-18.png`） | 衬套大孔在**上**，两颗舵机输出轴在**中下部**，**两根线缆自最下端引出**，方向背离衬套大孔 | `OFFICIAL-FIG` |
| `ASM` **第 20 页**四张照片 | 同姿态：枢轴在上、输出轴裸露（此时尚未装舵盘）、**两根线缆自下方引出** | `OFFICIAL-FIG` |
| `ASM` **第 21 / 22 / 23 / 26 / 27 页**照片 | 全部保持同一姿态：手指朝上、线缆朝下 | `OFFICIAL-FIG` |

→ **线缆出口在远离指根枢轴的一端**，与输出轴同处该端。

**注意范围**：`ASM` 第 18 页正文**没有**用文字规定线缆方向，上述结论来自图片一致性。
线缆在**整手**装配中的走向另有规定（`ASM` 第 30 页 `passing wires through the rectangular hole before`；
第 31 页 `Let the wires going on the inside (finger side)`），但那是 Step 4，不属本阶段。

### 3.3 框架正反面 —— 由官方 STL 几何唯一确定

`ASM` **第 18 页**正文原文：

```
Have a detailed look on finger frame part1 & 2 : holes for screwing servos are counterbored,
that will ease the screwing into plastic part.
```

即**官方要求靠「沉孔」识别方向**。`ASM` 第 18 页两张零件平铺照片用**红色虚线圈**标出了这些沉孔。
但平铺照与装配照之间无法单凭肉眼确定沉孔朝向，本批因此改用 `STL1`/`STL2` 几何量测。

**量测结果（可复算，脚本见 §10）：**

`STL1`（Finger_Frame-1），包围盒 `20.00 × 21.00 × 8.00 mm`，板厚方向为 Z（`z = 4.50 … 12.50`）：

| 孔位 (x, y) | 与枢轴距离 | 芯孔 | 沉孔 | 沉孔开在哪一面 |
|---|---|---|---|---|
| `(0.00, 0.00)` | — | ⌀8.14，z 4.80–12.20 | — | 衬套孔（压入 2 个 Dint 6 衬套） |
| `(±6.00, -7.00)` | 7.00 mm（**近**枢轴） | ⌀1.90 通孔，z 4.50–11.90 | ⌀2.80 × 0.60 | **+Z 面（z = 12.50）** |
| `(±6.00, -12.40)` | 12.40 mm（**远**枢轴） | ⌀1.50 通孔，z 5.10–12.50 | ⌀2.20 × 0.60 | **−Z 面（z = 4.50）** |

`STL2`（Finger_Frame-2），包围盒 `20.00 × 8.95 × 8.00 mm`，同一坐标系：

| 孔位 (x, y) | 芯孔 | 沉孔 | 沉孔开在哪一面 |
|---|---|---|---|
| `(±6.00, -40.95)` | ⌀1.50 通孔，z 5.10–12.50 | ⌀2.20 × 0.60 | **−Z 面** |
| `(0.00, -44.55)` | ⌀1.90 通孔，z 4.50–11.90 | ⌀2.70–2.90 × 0.60 | **+Z 面** |

**决定性交叉验证（数量完全对上）：**

- **⌀1.50 芯孔 + ⌀2.20 沉孔（开在 −Z 面）** 共 **4 个**
  （`STL1` 远枢轴一对 2 个 + `STL2` 两侧一对 2 个）
  ←→ `ASM` 第 18 页 `4x Servo 2x7 screws`，**数量 4 = 4** ✔
- **⌀1.90 芯孔 + ⌀2.80 沉孔（开在 +Z 面）** 共 **3 个**
  （`STL1` 近枢轴一对 2 个 + `STL2` 中心 1 个）
  ←→ `ASM` 第 30 页 `Fix the finger with 3x thermoplastic screws 2.5x8`，**数量 3 = 3** ✔

**与官方照片的一致性检查（本批据此排除肉眼歧义）：**
按 STL，在 −Z 面上「远枢轴一对」有可见沉孔、「近枢轴一对」是平口 ⌀1.90；
`ASM` 第 18 页 part1 平铺照恰好呈现「远枢轴一对有沉孔并被红圈标注、近枢轴一对为平口」，
part2 平铺照呈现「两侧一对有沉孔并被红圈标注、中心孔为平口」。
→ **两张平铺照拍的都是 −Z 面**，即**贴合舵机的那一面**。三方证据自洽。

**因此，框架正反面的可操作判据（无需命名"正/反"）：**

> **舵机螺钉从「有 ⌀2.2 浅沉孔」的那一面拧入；那一面就是贴合舵机的一面。**
> 同一零件上「装手掌板」的 3 个孔，其沉孔开在**相反的那一面**，装框阶段**不使用**。
> Finger frame part1 上，舵机孔是**距大圆枢轴孔较远**的那一对。

---

## 4. 固定螺钉规格：官方 2×7 与 M2×6 替代

### 4.1 官方规格

| 出处 | 原文 | 含义 |
|---|---|---|
| `ASM` 第 5 页（Step 1 元件清单） | `- ⒞ 4x Servo 2x7 screw` / `- ⒟ 2x Servo M2x4 screw` / `All comes with SCS0009 package` | 4 颗 2×7 用于固定舵机；2 颗 M2×4 是**舵盘中心螺钉**；两者均随 SCS0009 附带 |
| `ASM` 第 9 页（Step 2 元件清单） | `- ⒞ 4x Servo 2x7 screw` | 同上，复述 |
| `ASM` 第 18 页（★ Actuators 所需件） | `- 4x Servo 2x7 screws` | 装框阶段用量 |
| `ASM` 第 18 页正文 | `Put both SCS0009 side by side and fix them together with finger frame part1 and part2 by using servo 2x7 screws.` | 用法：两颗舵机并排，由 part1 与 part2 夹持固定 |

→ **官方件 = 4× "Servo 2x7 screw"（⌀2 × 长 7 mm，随舵机附带）**。

### 4.2 螺纹类型（重要，且与"M2×6"不是同一件事）

`OFFICIAL-CAD`：舵机螺钉孔芯径为 **⌀1.50**，而螺钉公称外径为 **⌀2.0**。
孔径显著小于螺钉外径，且 `ASM` 第 18 页原文写明沉孔的作用是
`that will ease the screwing **into plastic part**`（拧**进塑料**）。

→ 该孔是**自攻/成形螺纹底孔**，官方 2×7 是**自攻型**螺钉，靠拧入塑料自行成形螺纹。

→ **`UNVERIFIED`**：项目文档 `HO-0813` 第 195 行与 `HO-0812`（`AmazingHand_宿舍续作…_2026-08-12.md` 第 110 行）
所称的「M2×6」**是否同为自攻型**，本地资料无法确认。
若为**普通机制螺纹 M2 螺钉**（螺纹已成形、大径 2.0），拧入 ⌀1.5 未攻塑料孔的受力方式与自攻螺钉不同，
存在**胀裂孔壁或滑牙**的风险差异。**本批不下结论，交 Codex 裁决。**

### 4.3 「顶到底 / 顶穿」风险 —— 几何上可排除

`OFFICIAL-CAD` 事实：

- 舵机螺钉孔是**通孔**：⌀1.50 段 `z = 5.10 → 12.50`，其上游是 ⌀2.20 沉孔 `z = 4.50 → 5.10`，
  合计贯穿整块板；
- 板厚（Z 向）= `12.50 − 4.50` = **8.00 mm**（`STL1` 与 `STL2` 均为 8.00 mm）。

推论（对 6 mm 与 7 mm 均成立，且**不依赖任何未知量**）：

1. 因为是**通孔**，不存在"拧到孔底顶死"的情形 → **「顶到底」风险为零**。
2. 螺钉需先穿过舵机自身安装耳（厚度 ≥ 0），再进入塑料。
   即使把舵机耳厚度取最极端的 0，进入塑料的最大长度也只有螺钉全长
   （7 mm 或 6 mm），**均小于 8.00 mm 的塑料厚度** → **螺钉不可能从另一面穿出**。
3. 螺钉穿出的唯一潜在受害面是 **+Z 面**，而 +Z 面是 Step 4 与**手掌板**的贴合面
   （该面正是那 3 个 ⌀1.9/⌀2.8 手掌板孔的沉孔面），**不是任何指壳**。

→ **结论：M2×6 与官方 2×7 在"顶到底 / 顶穿 / 顶壳"这一维度上均安全，且 6 mm 比 7 mm 更保守。**

### 4.4 「顶壳」风险的正面澄清

`ASM` 第 16 页「★ Finger shells」所需件为
`1x Finger mechanism / 1x Distal shell / 1x Proximal shell / 4x Thermoplastic screw 2.5x6`，
即**指壳安装在"手指机构"（Proximal / Distal）上，不安装在 Finger Frame 上**。

→ **装框阶段（本阶段）在结构上与指壳没有接触面，不存在顶指壳的问题。**
→ 掌壳/顶壳（`ASM` 第 34–36 页 Step 5）装在 Hand plate / Wrist interface 上，
与单指框架的舵机螺钉之间是否存在间接干涉：**`UNVERIFIED`**（本地资料未给出该处间隙尺寸），
但该问题属 Step 5，与本阶段无关。

### 4.5 M2×6 替代的真实代价（须由 Codex 裁决）

| 维度 | 判定 | 等级 |
|---|---|---|
| 顶到底 / 顶穿 / 顶壳 | **无风险**（§4.3） | `OFFICIAL-CAD` |
| 螺纹啮合长度 | 比官方**少约 1 mm** | `OFFICIAL-CAD` 推算 |
| 少 1 mm 是否仍满足夹持强度 | **`UNVERIFIED`** —— 官方无任何关于替代长度的说明 | `UNVERIFIED` |
| 螺纹类型是否同为自攻 | **`UNVERIFIED`**（§4.2） | `UNVERIFIED` |
| 项目既有立场 | `HO-0813` 第 195 行：`M2x7 缺两颗时，四颗一致的 M2x6 可作为临时固定验证，只要不顶到底、不松动` | `PROJECT-DOC` |

→ 项目既有立场中的「**不顶到底**」这一前提，本批已由 `OFFICIAL-CAD` **证明成立**；
「**不松动**」仍为**运行期人工判据**，无官方数据支撑 → 保持 `UNVERIFIED`。

---

## 5. 装框阶段应打印 / 使用的具体零件

### 5.1 本阶段所需件（官方逐字）

`ASM` **第 17 页**「★ Bushings」所需件：

```
- 1x Finger frame part1
- 2x Bushing Dint 6mm
```

`ASM` **第 18 页**「★ Actuators」所需件：

```
- 1x Finger frame part1 with bushings
- 1x Finger frame part2
- 2x Feetech SCS0009
- 4x Servo 2x7 screws
```

→ 官方把「压衬套」排在「装舵机」**之前**（第 17 页在第 18 页之前，且第 18 页所需件写明
`Finger frame part1 **with bushings**`）。

### 5.2 对应的具体文件名

| 官方零件名 | 3D 打印文件（STL） | 对应 STEP | 本阶段是否需要 |
|---|---|---|---|
| Finger frame part1 | `cad\stl\Amazing Hand Parts - Finger_Frame-1.stl` | `cad\step\Amazing Hand Parts - Finger_Frame-1.step` | **需要 ×1** |
| Finger frame part2 | `cad\stl\Amazing Hand Parts - Finger_Frame-2.stl` | `cad\step\Amazing Hand Parts - Finger_Frame-2.step` | **需要 ×1** |
| Bushing Dint 6mm | —（**外购标准件，非打印件**） | — | 需要 ×2 |

（路径均相对 `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\`）

**本阶段明确不需要**的打印件（官方归在其他步骤）：
`Amazing Hand Parts - Proximal.stl`、`- Distal.stl`、`- Gimbal.stl`、`- Link.stl`、
`- Proximal_Shell.stl`、`- Distal_Shell.stl`、`BallJoint_Rod - Spacer.stl`、
`BallJoint_Rod - Length_Toolings.stl`，以及全部 Hand / Palm / Top / Wrist 类零件。

### 5.3 打印参数依据

`TIPS` **第 1 页**「Finger parts (rigid)」正文：

```
Support needed for :
- Gimbal
- Link
- Proximal
- Distal
High robustness required
PLA
0.2 layers
at least 80% infill
```

→ **Finger frame 两件属"Finger parts (rigid)"分组，但不在"support needed"名单内。**

`TIPS` 第 1 页右侧的 PrusaSlicer 截图（`OFFICIAL-FIG`）物件列表中可读到
`Feetech_Hand - …ger_Frame-2.stl`（被选中）与 `Feetech_Hand - …ger_Frame-1.stl`，
与 `Dist / Prox / Gimbal / Link / Ball joint - Spacer` 同盘；
该盘参数显示 `Supports: Partout`（＝全部）、`Remplissage: 100%`、`0.20mm QUALITY`、`ColorFabb PLA High speed`。

→ **正文名单与截图参数并不一致**（正文只对 4 个件要求支撑，截图对整盘开了支撑）。
本批**如实并列，不裁决**。项目文档 `AmazingHand_项目交接文档.md` 第 277 行
`Finger Frame 和 Spacer 通常无需支撑` 与**正文名单一致**。

### 5.4 打印指引截图与当前 STL 的版本差异（本批新发现）

`TIPS` 第 1 页截图中被选中的 Finger_Frame-2 显示：

```
Taille : 20,00 x 10,95 x 8,00 mm
Volume : 1641,64
Faces  : 3768 (1 coque)
échelle 100%   rotation 0,0,0
```

本批对当前 `STL2` 的量测：

```
faces  = 3768          ← 与截图完全相同
bbox   = 20.00 x 8.95 x 8.00 mm     ← Y 比截图少 2.00 mm
volume = 1321.62 mm^3               ← 比截图少 320.02 mm^3
```

**校验**：`20.00 × 8.00 × 2.00 = 320.00 mm³`，与体积差 `320.02 mm³` 吻合到 0.02 mm³。
→ 截图中的 Frame-2 相当于在当前件基础上**沿 Y 多出一段 2.00 mm 的等截面**。
面数相同、比例 100%、无旋转 → 判定为**同拓扑的版本修订差异**，不是缩放或摆放差异。

**影响与边界**：
- 以哪个版本为准：`RDM` 第 91 行把 `cad` 目录指为 STL 来源，`cad\README.md` 也只指向打印指引，
  → **应以 `cad\stl\` 当前文件为准**；`TIPS` 截图是较早版本的示意。
- **`UNVERIFIED`**：该 2.00 mm 差异**是否改变了 4 个舵机螺钉孔的孔位**，本地资料无法比对
  （截图未给孔位坐标）。**若用户手上的实物是按 `TIPS` 截图版本打印的，孔位一致性须实物核对，本批不推断。**

---

## 6. 后续安装舵盘的官方相位与参考姿态（**仅备查，本阶段禁止安装**）

> ⚠ 本节内容属 `ASM` **Step 3**，官方顺序在装框之后**还隔着两页装配**（见 §7）。
> 当前阶段已明确**禁止安装舵盘**。本节只把官方依据固定下来，**不构成任何执行建议**。

### 6.1 官方装舵盘时的舵机位置（电气中点）

| 路线 | 出处 | 原文 |
|---|---|---|
| Python | `ASM` 第 22 页 | `Run Python script "Hand_FingerMiddlePos.py"` / `By default, middle position is set to 0` / `This program will servos in their middle position` |
| Arduino | `ASM` 第 26 页 | `Set position 511 for each Servo with Feetech software` |

`ASM` 第 26 页配图为 FD 软件截图（`OFFICIAL-FIG`），可读到 `Goal = 511`、`Set` 按钮，
反馈区 `Position 508 / Goal 508 / Tmp 20 / Torque 0 / State Normal / Voltage 4.8V`。

→ **官方装舵盘的参考位置是"电气中点"：Python 记为 0°，Arduino/FD 记为 raw 511。**

### 6.2 官方舵盘摆放相位

`ASM` 第 22 页 / 第 26 页共同正文：

```
Place servo horns as following picture (= middle position), as closed as you can
Screw both servo horns with M2x4 screw
```

`ASM` 第 22 页与第 26 页配图（`PRE-IMG\calibration-22.png`）：
照片中一条**红色虚线水平贯穿两只舵盘的中心固定螺钉并向两侧延伸**，
即两只舵盘在中点位置时**共线，且该线垂直于手指轴线（横向）**。

→ 官方相位判据是**图示比对**，正文自己写明只能 `as closed as you can`（尽量接近），
因为花键齿距无法给出任意角度。**官方不提供角度数值。**

### 6.3 官方精调判据（装完舵盘之后）

`ASM` 第 23 页（Python）/ 第 27 页（Arduino）共同正文：

```
Stop the program as soon as the finger is in closed position, and check if servo horns are correctly
align with middle plan of the servo. If not, change the middle position a little bit to fit with this
requirement (servo horns aligned with middle servo middle plan when finger is closed).
```

- Python 版补充：`Value is an angle value in °.`（第 23 页）
- Arduino 版补充：`Value is a raw value, so 1 step=0.293°.`（第 27 页）
- 官方示例（第 27 页）：`MiddlePos_1 = 520`、`MiddlePos_2 = 511`；
  第 23 页对应 `MiddlePos_1 = 3`、`MiddlePos_2 = 0`（度）

→ **注意：官方示例本身就把 ID1 从 511 改成了 520。**
即 **511 是"装舵盘时的电气中点参考"，不是最终机械中心**；最终中点须逐颗精调后各自不同。

### 6.4 官方对旋转方向的明确警告（必须保留）

`ASM` 第 23 页 / 第 27 页共同正文：

```
(Due to symmetrical location of servos, rotation way is not obvious, perform several settings
to be sure of the good fine tuned middle pos)
```

配套的机构学陈述见 `OVW` **第 2 页**：

```
=> Flexion / Extension occurs when motors acting in the same way
=> Abduction / Adduction occurs when motors acting in opposite way
```

→ **`UNVERIFIED`（重要）**：`OVW` 说的是**电机"作用方向"**，
本地官方资料**没有**给出「作用方向」与「SCS0009 原始寄存器增减方向」之间的映射，
且官方自己声明对称安装使旋转方向"不显然"。
→ 因此**不得**由官方资料推断任一舵机的 `direction_sign`，
也**不得**据此判定项目脚本 `smart_hand/host/finger_smoke_scs0009.py` 中
「ID1 `center+delta` / ID2 `center−delta`」这一反号方案对应的是屈伸还是内收/外展。
**该项必须实测，本批不填、不猜。**

---

## 7. 五个阶段的严格区分（防止跨阶段外推）

官方顺序（页码均取自 `ASM`）与当前授权状态：

| # | 阶段 | 官方页 | 官方内容 | 当前状态 |
|---|---|---|---|---|
| **A** | **断电装框** | p17 → p18 | p17 压入 2 个 Dint6 衬套到 part1；p18 两颗 SCS0009 并排，由 part1+part2 用 **4× 2×7** 夹持固定；要求输出轴远离枢轴 | **下一步准备做的就是本阶段**；全程**断电**，官方本页无任何通电内容 |
| — | （装框与舵盘之间，官方还有两页） | p19 → p20 | p19 手指机构插入衬套，M2.5 大垫圈 + 2.5×8 热塑螺钉锁进 gimbal；p20 球头拉杆装到 link 上，**舵盘此时随拉杆悬空、尚未装上输出轴** | **禁止**（本阶段禁装连杆） |
| **B** | **电气中点** | p22 / p26 | 把舵机驱动到中点：Python `0°` / Arduino·FD `raw 511` | **禁止**（本阶段禁止上电、禁止动作） |
| **C** | **安装舵盘** | p22 / p26 | 在中点保持下按图摆放舵盘，用 **M2×4** 中心螺钉固定 | **禁止** |
| **D** | **安装连杆** | p20（拉杆装 link）+ p22/p26（舵盘上轴合拢机构） | 球头拉杆两端分别与 link 和舵盘连接 | **禁止** |
| **E** | **机械范围标定** | p23 / p27（精调中点）；p24 / p28（四指各自不同中点） | 判据＝手指闭合时舵盘与舵机中平面对齐；1 step = 0.293°；示例 ID1 511→520 | **禁止**（且禁止填写校准 CSV） |

**三条不得跨阶段外推的界线：**

1. **A 完成 ≠ B 可做。** p18 只证明机械固定；官方在 A 与 B 之间还插入 p19/p20 两页装配。
2. **B 的 511 ≠ E 的机械中心。** §6.3 已证官方示例自己把 ID1 改到 520。
   → `config/servo_calibration_template.csv` 的 `center_raw` **不得填 511**。
3. **官方"同向/反向"≠ 原始寄存器方向。** §6.4 已说明映射缺失，`direction_sign` 只能实测。

**本阶段（A）与官方顺序的一处项目侧差异（只列，不裁决）：**
`HO-0811` 第 866–876 行记载的项目计划是「先固定舵机 → 上电置中 → **保持期间装舵盘** → 断电装连杆」，
即**舵盘先于连杆**；而 `ASM` p20 → p22 的官方顺序是**球头拉杆先装到 link 上（舵盘随拉杆悬空）
→ 再在中点把舵盘压上输出轴**。两者顺序不同。
→ 本批**不裁决**孰优；仅指出这是与官方装配顺序的**实质差异**，且**不影响本阶段 A**。

---

## 8. 本批发现的资料冲突与规格差异（只列，不裁决）

| # | 冲突 | 双方出处 | 处置建议 |
|---|---|---|---|
| X1 | **Frame-2 尺寸差 2.00 mm** | `TIPS` p1 截图 `20,00 × 10,95 × 8,00 / Volume 1641,64 / Faces 3768` vs 本批量测 `STL2` `20.00 × 8.95 × 8.00 / 1321.62 / 3768` | 以 `cad\stl\` 为准（`RDM` p91）；实物孔位一致性 `UNVERIFIED`，须实物核对 |
| X2 | **打印支撑** | `TIPS` p1 正文只对 Gimbal/Link/Proximal/Distal 要求支撑 vs 同页截图整盘 `Supports: Partout` | 项目文档与正文一致；本批不裁决 |
| X3 | **供电电压口径** | `OVW` p6 `DC Supply 5V / Max current 3A`（整手 8 舵机）、`RDM` p126 建议 `5V / 2A` 适配器、`ASM` p26 FD 反馈 `Voltage 4.8V` vs 项目 **6.0V** | **已部分裁决**：`docs\TWO_SERVO_POWER_AND_THERMAL_DECISION_2026-08-15.md` 第 12–18 行已定 6.0V，依据写明是 **SCS0009 器件规格**（6V 堵栈电流约 1A/颗），**不是** AmazingHand 整手文档。二者不必然矛盾（器件工作电压 vs 整手推荐供电），但本地**无 SCS0009 规格书**可核 → 保留为**知悉项**，见 U10 |
| X4 | **螺钉型别** | `ASM` 全篇写 `Servo 2x7 screw`（自攻，随舵机附带） vs 项目文档写 `M2x6` | 见 §4.2、§4.5，型别是否同为自攻 `UNVERIFIED` |
| X5 | （已排除）`ASM` p25 的 "ID 1 / ID 2" 顺序 | 见 §2.4 | **不构成冲突**，已查证为两张独立照片的标题 |

---

## 9. 仍未确认项（`UNVERIFIED` 清单）

以下各项**本地官方资料不足以确认**，本批**拒绝**凭经验或外观补全：

| # | 未确认项 | 为什么无法确认 |
|---|---|---|
| U1 | 项目手上的「M2×6」是否为**自攻型**螺钉 | 官方只写 `Servo 2x7 screw`（随 SCS0009 附带），未给螺纹型别规格；项目文档也未写明所购螺钉类型 |
| U2 | 少 1 mm 啮合长度是否仍满足夹持强度 | 官方无任何替代长度说明，也无扭矩/拔出力数据 |
| U3 | SCS0009 安装耳厚度 | 本地无 SCS0009 机械图纸；§4.3 的结论已设计为**不依赖**该值 |
| U4 | 各舵机的 `direction_sign` | §6.4：官方只给"同向/反向"的机构学描述，未给与原始寄存器方向的映射，且官方自称"不显然" |
| U5 | 机械中心 `center_raw`、软限位 `soft_min_raw`/`soft_max_raw` | 官方只给"电气中点 511/0°"这一装配参考，并示例把 ID1 改到 520；真值须实测 |
| U6 | `TIPS` 截图版本与当前 STL 之间**孔位**是否一致 | 截图未给孔位坐标，只给外形尺寸与体积 |
| U7 | Step 5 掌壳/顶壳与单指框架舵机螺钉的间接干涉 | 本地资料未给该处间隙尺寸；且属 Step 5，非本阶段 |
| U8 | 用户实物两颗舵机在框架中的**实际**朝向与左右 | 属真机核对，本批 `hardware_accessed=false`，不看实物、不据照片判定 |
| U9 | 整手渲染（`ASM` p29）红色 1–8 标号与单指内部左右的对应 | 该渲染视角与单指照片不同，见 §2.5 |
| U10 | AmazingHand 官方 `5V` 与已裁决 `6.0V` 是否真正冲突 | 本地**无 SCS0009 器件规格书**；`OVW` p6 给的是整手推荐供电，裁决依据是器件规格，两个口径无法在本地资料内对齐（X3） |

---

## 10. 与项目既有文档的一致性核对

| 项目既有表述 | 出处 | 本批核对结论 |
|---|---|---|
| `正视舵机输出轴、指根大转轴在上、线缆向下时，单指编号为左侧ID2、右侧ID1` | `HO-0811` 第 861–862 行 | ✅ **与官方一致**，且本批补上了官方页码依据（`ASM` p21/p23/p27），此前项目文档未附出处 |
| `两颗舵机输出轴应远离指根的外展/内收转轴` | `HO-0811` 第 862 行 | ✅ **与官方原文一致**（`ASM` p18） |
| `M2x7 缺两颗时，四颗一致的 M2x6 可作为临时固定验证，只要不顶到底、不松动` | `HO-0813` 第 195 行 | ⚠ **前提"不顶到底"已被本批证明成立**（§4.3）；但"是否自攻"与"是否夹紧"仍 `UNVERIFIED`（U1/U2） |
| `Finger Frame 和 Spacer 通常无需支撑` | `AmazingHand_项目交接文档.md` 第 277 行 | ✅ 与 `TIPS` 第 1 页**正文**名单一致；与同页**截图**参数不一致（X2） |
| `舵机上电归中后再安装舵盘` | `HO-0810/0811` 第 694/741 行 | ✅ 方向与官方一致（B→C），但与官方**连杆先后顺序**存在差异，见 §7 |
| `center_hold_scs0009_pair.py` 置中到 raw **511** | 项目脚本（本批复核版本：**2026-08-15 11:23**） | ✅ 与官方"装舵盘用电气中点 511"一致。该脚本的常量现已命名为 `RAW_ELECTRICAL_MIDPOINT = 511`，**命名本身即与本节 §6.3 结论一致**；⚠ 仍须保持：**511 不得写入 `center_raw`** |
| `finger_smoke_scs0009.py` 的 `--center1/--center2` | 项目脚本（本批复核版本：**2026-08-15 11:23**） | ✅ 两参数现为 `required=True`，帮助文本写明 `measured safe mechanical reference`，**511 默认值已移除** → 与 §6.3「511 不是机械中心」一致 |
| `finger_smoke_scs0009.py` 的 ID1 `+delta` / ID2 `−delta` | 同上，第 95–96 行 | ⚠ **该反号方案对应屈伸还是内收/外展，本批无法由官方资料判定**，见 §6.4 / U4，必须实测 |

---

## 11. 本批实际执行的命令与产物

全部为只读读取与离线计算，**未触碰硬件**。

| # | 操作 | 结果 |
|---|---|---|
| 1 | 列举 `AmazingHand-1.0` 与 `.codex\attachments\3a16bae7-…` 目录 | 附件仅含 `AmazingHand_3DprintingTips.pdf` |
| 2 | `sha256sum` 比对附件与官方仓库副本 | **逐字节相同**（`492E3441…3BF5`） |
| 3 | Read 工具打开 `ASM` | 报 `PDF is password-protected` |
| 4 | PyMuPDF 打开 `ASM` | `needs_pass=0, is_encrypted=False, permissions=-4, pages=37`；确认**页码=幻灯片编号** |
| 5 | 逐页提取 `ASM` / `TIPS` / `OVW` 文本 | 与前期 `PRE-TXT` 复核一致 |
| 6 | 渲染 `ASM` p19/p20/p23/p25/p26/p27/p29、`TIPS` p1/p2 | 输出至任务临时目录，**未写入项目仓库** |
| 7 | 解析 `STL1`/`STL2`（自写二进制 STL 解析 + Hough 式孔轴检测） | 得 §3.3 全部孔位/孔径/沉孔朝向 |
| 8 | 计算 `STL1`/`STL2` 面数、包围盒、体积 | `6228 / 20×21×8 / 2337.27`；`3768 / 20×8.95×8 / 1321.62` |
| 9 | 与 `TIPS` p1 截图数值比对 | 面数相同、体积差 `320.02` ≈ `20×8×2.00` → 判定版本差异（X1） |
| 10 | grep 项目历史交接文档 | 定位 `HO-0811` 第 860–867 行、`HO-0813` 第 195 行等既有表述 |

**本批产物**：
- 入库：**仅本文件**
  `smart_hand\docs\SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md`
- 未入库（任务临时目录 `C:\Users\zzh\.claude\jobs\261df232\tmp\`，可随时丢弃）：
  渲染页图 `asm_p*.png` / `tips_p*.png` / `p18_*.png`，
  分析脚本 `stl_probe.py` / `stl_holes.py` / `stl_holes2.py` / `stl_vol.py` / `crop_p18.py` / `zoom_p18.py` / `tips_zoom.py` / `tips.py`

**未触碰**：`smart_hand/host/*`、`titan_rtthread/*`、`maixcam2/*`、`protocol/*`、
`config/servo_calibration_template.csv`、姿态库、`D:\Micu\RTTWorkspace\titan_uart_test`、
以及 `C:\Users\zzh\Downloads\AmazingHand-1.0`（**全程只读，未改动官方资料**）。

---

## 11.1 并发会话说明（审计快照边界）

本批执行期间（本文件写入时间 **15:35**），仓库内有**其他会话**在 11:23–13:01 之间改动了多个文件。
以下均**非本审计所写**，仅登记归属并说明对本文件结论的影响：

| 时间 | 文件 | 对本文件的影响 |
|---|---|---|
| 11:23 | `host\center_hold_scs0009_pair.py` | 常量由 `RAW_CENTER` 改名为 `RAW_ELECTRICAL_MIDPOINT`；**本批已按改名后版本复核**（§10） |
| 11:23 | `host\finger_smoke_scs0009.py` | `--center1/--center2` 改为 `required=True`、移除 511 默认值；**本批已按新版复核**（§10） |
| 11:31 | `HARDWARE_WIRING_CARDS.md`、`SERVO_CALIBRATION_AND_LOGGING.md`、`TOMORROW_SINGLE_FINGER_RUNBOOK.md` | 本文件**未引用**这三份的行号，只引用了仓库外的历史交接（`HO-0811`/`HO-0813`/`项目交接文档.md`，今日均未改动）→ **不受影响** |
| 11:56 / 11:59 / 12:05 | `sync_nudge_scs0009_pair.py` / `probe_scs0009.py` / `nudge_scs0009.py` | 本文件未引用其行号 → 不受影响 |
| 12:16 | `docs\TWO_SERVO_POWER_AND_THERMAL_DECISION_2026-08-15.md` | **D1 已裁决**（6.0V；1.0A→2.0A；50°C）；本批据此把 X3 由"待裁决"改写为"知悉项 + U10" |
| 12:16 | `validation_reports\two_servo_loose_bench_acceptance_2026-08-15.md` | 已归档"散置台架只读/单颗小幅/双颗同步"验收，与用户声明的当前状态一致；该报告自述"不证明机械中心、安装方向、机械软限位" → **与本文件 §7、§9 相互印证，无冲突** |
| 12:16 / 12:17 / 12:18 / 12:55 / 13:01 | `README.md`、`evidence_index.csv`、`tests\*.exe`（gcc 重建）、`tests\test_center_hold_scs0009_pair_safety.py`、`docs\SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`、`docs\CENTER_HOLD_PAIR_SAFETY_AUDIT_2026-08-15.md`、`validation_reports\single_finger_gate0_gate1_template_2026-08-15.md` | 本批**未读取、未引用、未改动**；`.exe` 的 gcc 重建**非本批所为**（本批未调用 gcc） |

本文件所依赖的**官方资料**（`C:\Users\zzh\Downloads\AmazingHand-1.0`）在今日**无任何改动**，
已用 `find -newermt` 复核为空 → §2–§6 全部官方结论**不受并发影响**。

## 12. 交接摘要（供 Codex 审查）

- **修改文件**：仅新增 `smart_hand\docs\SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md`。
- **主要结论**：ID1=右 / ID2=左（官方三处互证）；输出轴远离枢轴（官方原文）；线缆朝远离枢轴一端（官方图）；
  **贴舵机面 = 有 ⌀2.2 沉孔的面**（STL 几何 + 4/3 孔数与官方 BOM 完全对上）；
  官方螺钉为 4× 自攻 `2x7`；**M2×6 的顶到底/顶穿/顶壳风险几何上可排除**，代价是啮合少约 1 mm 且螺纹型别未确认；
  装框只需 `Finger_Frame-1.stl` + `Finger_Frame-2.stl` + 2 个外购衬套；
  舵盘官方相位＝电气中点（0° / raw 511）下按图共线摆放、M2×4 固定，**511 不是机械中心**。
- **仍未确认项**：U1–U9（§9），其中 U1（M2×6 是否自攻）、U2（夹持强度）、U6（旧版孔位）与本阶段直接相关。
- **需 Codex 注意的冲突**：X1 STL 版本差 2 mm、X3 官方 5V vs 项目 6.0V、X4 螺钉型别。
- **`hardware_accessed=false`**：未上电、未动作、未安装舵盘/连杆、未填写校准 CSV、未改生产代码/协议/姿态库/D 盘工程。

**本批到此停止，等待 Codex 审查。**
