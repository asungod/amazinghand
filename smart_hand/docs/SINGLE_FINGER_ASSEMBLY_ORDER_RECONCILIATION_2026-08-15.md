# 单指装配顺序裁决：官方顺序 vs 旧 Runbook（2026-08-15）

状态：`OFFLINE_DOCUMENT_RECONCILIATION_NOT_AN_EXECUTION_AUTHORIZATION`

> 作者：claudeA（机械装配文档一致性）。本文件**只裁决文档顺序**，`hardware_accessed=false`。
> 不授权任何上电、动作、装配步骤；不改脚本、不填校准值。
> 全部官方依据引自 `C:\Users\zzh\Downloads\AmazingHand-1.0\AmazingHand-1.0\docs\AmazingHand_Assembly.pdf`
> （SHA-256 `328E46FF…DE567`，37 页，**PDF 页码 = 幻灯片编号**）。逐条页码/几何依据见
> `SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md`。

---

## 1. 当前机械状态（本文件统一口径，其他文档以此为准）

| 项 | 状态 |
|---|---|
| 两颗 SCS0009（ID1 / ID2） | **已固定进单指 Finger Frame part1 + part2** |
| 舵盘（servo horn） | **未安装** |
| 球头拉杆（ball joint rod） | **未安装** |
| `M2x18` 螺纹杆 | **运输中，预计约两天后到货** |
| 外部 6V | 关闭；上一轮测试结束时两颗 `torque=0` |
| 手指机构本体（Proximal / Distal / Gimbal / Link + 轴 + 指壳） | **`UNVERIFIED`** — 仓库内无任何装配完成记录，见 §5 |

**因此：本阶段不做任何机械动作，也不要求用户重复装框。**

---

## 2. 冲突陈述

| 来源 | 装框之后的顺序 |
|---|---|
| **官方**（`Assembly.pdf`） | p19 手指机构插入衬套 → **p20 球头拉杆先接到 link** → p22/p26 电气中点下**把舵盘压上输出轴** → p23/p27 精调 |
| **项目旧 Runbook**（`TOMORROW_SINGLE_FINGER_RUNBOOK.md` 原文、`SERVO_CALIBRATION_AND_LOGGING.md` §4 阶段 B 原文、`SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md` §5–§6 原文） | 装框 → 上电置中 → **保持期间装舵盘** → 断电装连杆 |

两者把「舵盘」和「连杆」的先后**完全颠倒**。

---

## 3. 裁决：以官方顺序为准

### 3.1 官方逐页依据

| 官方页 | 原文 / 内容 | 本裁决用到的点 |
|---|---|---|
| **p11**「★ Ball joint rod」 | 所需件 `2x M2 Ball joint` / **`1x M2 threaded rod L18mm`** / `1x Spacer` / `1x Length tooling assembled`；页内标 `X2`；页尾 `You will need two of them for a whole finger assembly.` | 球头拉杆**每根**要 1 根 `M2 L18mm`，**每指要 2 根** |
| **p12**「★ Servo horn」 | 所需件 `1x Ball joint rod assembly` / `1x Custom servo horn` / `1x M2x10 screw` / `1x M2 nut`；`Start screw the M2 screw into the remaining hole of the custom servo horn…` | **舵盘在此步就被螺栓固定到球头拉杆上**，之后不是独立零件 |
| **p19**「★ Finger final assembly」 | `Insert finger assembly into the bushings…` `Insert the washer and the screw together into the gimbal hole.` | 手指机构先插进指框衬套 |
| **p20**「★ Finger final assembly」 | `Insert the free side of a ball joint rod on the M2 threaded present on link part, **by ensuring servo horn is in the good way to be later assembled on servo axis**.` 配图：两组「舵盘＋拉杆」已接在 link 上、**舵盘悬空未上轴**，两颗舵机输出轴裸露 | **拉杆先接 link；舵盘此时仍未上输出轴** |
| **p22**（Python）/ **p26**（Arduino） | `Place servo horns as following picture (= middle position), as closed as you can` / `Screw both servo horns with M2x4 screw`；p26 另有 `Set position 511 for each Servo with Feetech software` | **舵盘在电气中点被压上输出轴**，用 M2×4 固定 |
| **p23** / **p27** | `check if servo horns are correctly align with middle plan of the servo… when finger is closed`；p27 示例 `MiddlePos_1 = 520`、`MiddlePos_2 = 511` | 精调在装舵盘**之后** |

### 3.2 为什么旧顺序不只是"另一种做法"

官方 **p12** 已把舵盘螺栓固定到球头拉杆上（`M2x10 screw` + `M2 nut`），
**p20** 再把该组件的另一端接到 link，并明确要求此时就摆正舵盘朝向
（`by ensuring servo horn is in the good way to be later assembled on servo axis`）。

→ 在官方设计里，**舵盘不是一个可以单独先装到输出轴上的零件**，
它是「舵盘＋球头拉杆」组件的一端，上轴时另一端已经连着 link。

→ 旧 Runbook 的「保持期间装舵盘，之后再断电装连杆」把舵盘当成独立件先行安装，
与官方装配对象定义不一致；即便强行执行，之后再把拉杆接到已在轴上的舵盘，
也会扰动刚刚在中点对好的相位。

### 3.3 裁决后的标准顺序（文档口径，**不是执行授权**）

```
[已完成] 装框：2× SCS0009 + Finger frame part1(含2个衬套) + part2，4× 2x7 螺钉        (官方 p17 → p18)
   ↓
[待办·前置] 手指机构本体装配：Proximal/Distal/Gimbal/Link + D2x10/D2x16 轴 + L25 螺纹杆 + 指壳   (官方 p13–p16)
   ↓
[待办·被 M2x18 阻断] 球头拉杆 ×2：每根 1× M2 L18 + 2× 球头 + 1× Spacer，用 Length tooling 定长   (官方 p10–p11)
   ↓
[待办·被 M2x18 阻断] 舵盘组件 ×2：改制十字舵盘 + M2x10 + M2 螺母，固定到球头拉杆一端            (官方 p12)
   ↓
[待办] 手指机构插入指框衬套，M2.5 大垫圈 + 2.5x8 热塑螺钉锁进 gimbal                        (官方 p19)
   ↓
[待办] 球头拉杆自由端接到 link 的 M2 螺纹杆，两侧 M2 螺母锁紧；舵盘此时仍悬空                 (官方 p20)
   ↓
[待办·需上电] 电气中点参考（raw 511 / 0°）下把舵盘压上输出轴，M2x4 中心螺钉固定             (官方 p22 / p26)
   ↓
[待办·需上电] 精调中点：手指闭合时舵盘与舵机中平面对齐                                    (官方 p23 / p27)
   ↓
[待办] 实测方向、机械中心、保守软限位 → 才允许写入校准 CSV
```

**安全门控保留**：以上每一个「需上电」步骤仍受
`SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md` 的 Gate 约束，
并且必须由 Codex 主模型在现场逐步授权。本文件**不解除**任何门控。

---

## 4. M2×18 依赖链：它阻断的不只是连杆

官方 **p11** 明确球头拉杆需要 `1x M2 threaded rod L18mm`，每指 2 根；
官方 **p12** 把舵盘固定到球头拉杆上；官方 **p20** 要求拉杆先接 link，舵盘随后上轴。

→ **依赖链：`M2x18` 缺 ⇒ 做不出球头拉杆(p11) ⇒ 做不出舵盘组件(p12) ⇒ 到不了 p20 ⇒ 官方顺序下装不了舵盘(p22)。**

→ **结论：在官方顺序下，`M2x18` 未到货同时阻断「连杆」和「舵盘」两步。**
这也解释了为什么当前阶段除装框外无法推进，并且**不存在**"先把舵盘装上等零件"这一中间选项。

> 旧 Runbook 的顺序会造成一种错觉：舵盘似乎可以先装、只等 `M2x18` 装连杆。
> 按官方定义并非如此。这是本次必须改文档的实际风险，不只是措辞问题。

### 4.1 数量口径（需 Codex 与用户核对）

官方每指需要：**2 根 `M2 L18mm`**（两根球头拉杆各 1 根）＋ **1 根 `M2 L25mm`**（插进 link，官方 p13 / p15）。

`AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` §4 记为「**一根** `M2x18` 螺纹杆仍在运输中」。

→ **`UNVERIFIED`**：这一根到货后是否足以完成 2 根球头拉杆、以及 `L25` 是否已在手，
本地资料无法确认。**本文件不推断、不代购、不建议替代**，交 Codex 与用户核对。

### 4.2 官方文档自身的一处尺寸冲突（只列，不裁决）

| 官方页 | 关于球头拉杆用杆 | 关于 link 用杆 |
|---|---|---|
| **p6**「★ Reworking standard parts」 | `8x M2 Threaded rod **L16mm maximum (L14 minimum)**` | `4x M2 Threaded rod **L26mm minimum (L28 maximum)**` |
| **p9 / p11 / p13 / p15** | `2x M2 threaded rod **L18mm**` | `1x M2 threaded rod **L25mm**` |

两处数值互不相容（`L18` 超出 p6 的 14–16 上限；`L25` 低于 p6 的 26–28 下限）。
官方 p10–p11 另给了 `Length tooling`（页面标注 `33mm`）来最终定长，
拉杆成品长度由球头旋入深度调节，切割长度只是毛坯 —— 这可能是范围与标称并存的原因，
但**数值冲突本身客观存在**。

→ 项目现按 `M2x18` 采购，与 **p9/p11** 一致。**本文件不裁决孰对**，只登记以免日后被当成项目笔误。

---

## 5. 本裁决暴露的前置缺口（`UNVERIFIED`）

| # | 缺口 | 影响 |
|---|---|---|
| P1 | **手指机构本体（Proximal/Distal/Gimbal/Link + 轴 + L25 杆）是否已装配**，仓库内无任何记录 | 官方 p19 要求机构先插入衬套，是 p20 的前置 |
| P2 | **柔性指壳（Proximal_Shell / Distal_Shell）是否已打印** | `AmazingHand_项目交接文档.md` 第 78 行记「因无法打印 TPU，默认尚未打印」；官方 p16 在 p19 之前 |
| P3 | 十字舵盘是否已按官方 p6 改制（钻 ⌀1.5、攻 M2、切除多余臂并打磨） | 官方 p12 用的是「Custom servo horn」，不是原厂十字盘 |
| P4 | `M2x10 screw` + `M2 nut`（舵盘↔球头，官方 p12）、`M2.5 large washer` + `2.5x8` 热塑螺钉（官方 p19）是否在手 | 均为 p12 / p19 的必需件 |
| P5 | 单根 `M2x18` 是否够用、`L25` 是否在手（§4.1） | 直接决定何时能解除暂停 |

以上均**未**在本次改动中被写成"已完成"或"已具备"。

---

## 6. 本裁决对其他文档的约束

被本文件统一口径的文档：

- `TOMORROW_SINGLE_FINGER_RUNBOOK.md`
- `SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`
- `SERVO_CALIBRATION_AND_LOGGING.md` §4

三者与本文件不一致时，**以本文件为准**；再有分歧以官方 `Assembly.pdf` 原页为准。

**不在本文件裁决范围**：`README.md`、`competition_2026/*`、`validation_reports/*` 的证据口径
（属 Grok B 的证据红队条线）；Titan STATUS 遥测语义（属 Grok A 条线）。
发现的越界问题只在交接报告中登记，不由本条线修改。

---

## 7. 不得外推

- 本文件只统一**文档顺序与状态口径**，**不证明**任何机械步骤已完成、可执行或安全。
- 「装框已完成」仅指两颗舵机已用螺钉固定进 part1+part2，**不含**照片审查、只读复核、方向确认。
- 官方顺序被采纳**不等于**官方顺序被授权执行；每一步仍需 Codex 现场逐步授权。
- `511` 始终是**电气中点参考**，不是机械中心（官方 p27 示例把 ID1 改到 `520`）。
- 官方 p2「同向＝屈伸、反向＝内收外展」**未给出**与 SCS0009 原始寄存器方向的映射，
  且官方 p23/p27 自述 `rotation way is not obvious` → `direction_sign` 必须实测。
