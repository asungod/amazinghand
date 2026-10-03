# 单指装配操作卡（2026-08-15 状态同步版）

状态：`PAUSED_WAITING_M2X18` · `NOT_AN_EXECUTION_AUTHORIZATION`

> 本卡只反映当前真实状态与官方顺序，**不构成任何执行授权**。
> 真机上电、舵机动作、舵盘/连杆装配一律由 Codex 主模型在现场逐步授权。
> 本次修订：claudeA，`hardware_accessed=false`，未改脚本、未填校准值。
>
> 顺序依据与冲突裁决见 `docs/SINGLE_FINGER_ASSEMBLY_ORDER_RECONCILIATION_2026-08-15.md`；
> 门控条件见 `docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`。
>
> 历史说明（保留，不删）：本卡原名「明天单指首次装配测试操作卡」，
> 因 2026-08-12 实验室停电顺延；其中"先只完成装框"的表述已于 2026-08-15 过期，见 §2。

---

## 1. 当前真实状态

| 项 | 状态 |
|---|---|
| 两颗 SCS0009（ID1 / ID2） | **已固定进单指 Finger Frame part1 + part2** |
| 舵盘（servo horn） | **未安装** |
| 球头拉杆（ball joint rod） | **未安装** |
| `M2x18` 螺纹杆 | **运输中，预计约两天后到货** |
| 外部 6V | **关闭**；上一轮测试结束时两颗舵机 `torque=0` |
| 舵机 ID | 已分别为 ID1 / ID2，**本阶段不需要改 ID** |
| 手指机构本体、柔性指壳 | **`UNVERIFIED`**，仓库内无装配/打印完成记录 |

**本阶段不做机械动作，也不需要用户重复装框。**

---

## 2. 已完成：装框（官方 p17 → p18）

装框本身已完成。官方对该步的要求如下，供**事后核对**用（不是重做指令）：

- 两颗 SCS0009 并排，由 Finger frame part1（已压入 2 个 Dint6 衬套）与 part2 夹持，
  官方件为 **4× `Servo 2x7 screw`**（随 SCS0009 附带的自攻螺钉）；
- 官方 p18 原文：`Be aware to orient them as well as the servo axis is far from the abduction / adduction pivot of the finger`
  → **两颗输出轴必须远离指根外展/内收枢轴（衬套大孔）那一端**；
- 正视输出轴、指根枢轴朝上、线缆朝下时：**ID2 在左、ID1 在右**
  （官方 p21 照片标注 + p23 / p27 正文 `right servo horn (ID1)` / `left servo horn (ID2)`）；
- 螺钉从**有 ⌀2.2 浅沉孔的那一面**拧入，该面即贴合舵机的一面；
  Finger frame part1 上，舵机孔是**距大圆枢轴孔较远**的那一对
  （官方 p18 原文 `holes for screwing servos are counterbored` + 官方 STL 几何，
  详见 `docs/SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md` §3.3）。

关于临时使用 M2×6 代替官方 2×7：
「顶到底 / 顶穿 / 顶壳」已由官方 STL 几何证伪（塑料为 8.00 mm 通孔，6 mm 与 7 mm 均不可能穿出）；
**仍未确认**的是螺纹型别是否同为自攻、以及少约 1 mm 啮合是否足够夹紧。
该项待 Codex 裁决，详见同一审计文档 §4。

---

## 3. 当前暂停原因与解除条件

**暂停原因：`M2x18` 螺纹杆未到货。**

按官方装配定义，这一根杆同时阻断两步（依赖链见裁决文档 §4）：

```
M2x18 缺 → 做不出球头拉杆(p11) → 做不出「舵盘＋拉杆」组件(p12)
        → 到不了「拉杆接 link」(p20) → 官方顺序下装不了舵盘(p22)
```

> ⚠ 因此**不存在**"先把舵盘装上、只等零件装连杆"这一中间选项。
> 旧版本操作卡曾隐含该选项，已在本次修订中移除。

**解除暂停需要 Codex 确认的事项（本卡不代为判断）：**

1. 到货的 `M2x18` 数量是否满足官方每指 **2 根**（官方 p11 `X2`）；
2. link 用的 `M2 L25mm`（官方 p13 / p15）是否已在手；
3. 手指机构本体与柔性指壳的实际状态（官方 p13–p16，本卡列为 `UNVERIFIED`）；
4. 十字舵盘是否已按官方 p6 改制为 Custom servo horn；
5. `M2x10` + `M2` 螺母（官方 p12）、`M2.5` 大垫圈 + `2.5x8` 热塑螺钉（官方 p19）是否齐备。

---

## 4. 官方顺序下的后续步骤（**仅为路线图，均未授权**）

```
[已完成] 装框                                                         官方 p17 → p18
[待办]   手指机构本体装配（Proximal/Distal/Gimbal/Link + 轴 + L25 + 指壳）  官方 p13–p16
[阻断]   球头拉杆 ×2（每根需 1× M2 L18）                                 官方 p10–p11
[阻断]   舵盘组件 ×2（Custom horn + M2x10 + M2 螺母，固定到拉杆一端）        官方 p12
[待办]   手指机构插入指框衬套，M2.5 垫圈 + 2.5x8 螺钉锁 gimbal              官方 p19
[待办]   球头拉杆自由端接 link，M2 螺母锁紧；舵盘此时仍悬空                  官方 p20
[需授权] 电气中点参考下把舵盘压上输出轴，M2x4 中心螺钉固定                   官方 p22 / p26
[需授权] 精调中点：手指闭合时舵盘与舵机中平面对齐                           官方 p23 / p27
[需授权] 实测方向 / 机械中心 / 保守软限位 → 才允许写入校准 CSV
```

**关于 `center_hold_scs0009_pair.py` 与 `finger_smoke_scs0009.py`：**

- 本卡**不再提供**这两个脚本的可直接执行命令块。
- 它们分别对应上表的 `[需授权]` 电气中点步与最终低幅冒烟步，
  其前置条件、限流设置与停止条件**统一由**
  `docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md` 的 Gate 2 / Gate 4 规定。
- **当前两者均不具备执行条件**：`M2x18` 未到货，舵盘与连杆均未安装。
- `finger_smoke_scs0009.py` 的 `--center1` / `--center2` 已是必填参数，
  **必须**传入实测安全参考值；脚本不会把 `511` 默认成机械中心。

**关于 `511`**：它是**电气中点参考**，不是机械中心。
官方 p27 的示例本身就把 ID1 从 `511` 调到 `520`。
在实测并经 Codex 确认前，`config/servo_calibration_template.csv` 的 `center_raw` **不得填 511**。

---

## 5. 暂停期间可以做的事（纯离线，不接硬件）

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
python smart_hand\host\run_offline_rehearsal.py `
  --output validation_reports\offline_rehearsal_latest.json
```

看到 `OFFLINE SINGLE-FINGER REHEARSAL PASSED` **只表示软件路径通过**；
不表示供电、接线、舵机方向、机械限位、Titan UART 或真实抓握已经验证。

其余可推进项见 `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` §6。

---

## 6. 不得外推

- 「装框已完成」**仅指**两颗舵机已用螺钉固定进 part1+part2；
  **不含**断电照片审查、装框后只读复核、安装方向的现场确认。
- 本卡采纳官方顺序，**不等于**官方顺序已被授权执行。
- 软件仍保持「姿态未配置即禁止自动动作」；不得填写机械软限位、抓握姿态或假定角度。
- 官方 p2 的「同向＝屈伸、反向＝内收外展」**未给出**与 SCS0009 原始寄存器方向的映射，
  且官方 p23/p27 自述 `rotation way is not obvious`
  → 舵机 `direction_sign` **必须实测**，不得由官方资料推断。
- 任一异常发热、焦味、异常复位、串口消失、堵转、电流突升，或任一舵机温度达到 **50 °C**，
  立即关闭外部 6V，不依赖软件命令停止。
