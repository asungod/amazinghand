# Grok B 真机证据红队（2026-08-15）

- 作者：grokB
- `hardware_accessed=false`
- 审查对象：`README.md`，`validation_reports/maixcam2_yolo11_titan_uart2_long_run_2026-08-15.md`，竞赛索引与讲解稿
- 配套评委包：`competition_2026/NO_MOTION_DEMO_PACK_2026-08-15.md`
- 本文件只做证据边界审查与最小修正提案。不改生产代码、协议、校准 CSV、D 盘工程。
- 机械装配顺序与 Gate 正文归 Claude A；STATUS 协议归 Grok A。README 机械段落若并发修改，以最新版复核，本表只钉证据语义。

## 0. 四条不得混淆的边界

| 易混对 | 已证明 | 未证明 |
|---|---|---|
| Mock / 真实 YOLO | 2026-08-15 长稳跑 `VISION_MODE=yolo11`，真实摄像头检出 bottle/39 | Mock 的 39/41/65 十秒探针（`E0006`）不是真实视觉 |
| ACK / 舵机执行 | `sent=acked`、错误计数 0 | ACK 只证明 Titan 收帧并回了 status=0；无舵机写包 |
| `INTENT` / Titan 权威状态 | 屏幕 `INTENT` 由 Maix 按 class_id **本地**映射 | 不是 Titan `sh_status`，不是 armed，不是已提交动作 |
| 散置台架 / 装框机构 | 散置小幅往返已归档（`E0002`，仍缺附件） | 舵机已装框，但无舵盘/连杆；不得写成装框后标定或可动作 |

屏幕硬编码（`maixcam2/main.py`，只读引用）：

- `INTENT {CYLINDRICAL|POWER|PRECISION}` ← `TARGET_INTENTS[class_id]`，不读 Titan
- `MOTION LOCKED` ← 固定字符串，不读安全门、不读 pose bank

评委口播必须说：**INTENT 是端侧策略意图；MOTION LOCKED 表示当前没有授权机械动作。**

## 1. 高危句子与最小修正

### 1.1 `README.md`

| # | 原文位置 / 摘录 | 风险 | 最小修正（请 Codex 或文档主人落地） |
|---|---|---|---|
| R1 | 「无舵机长稳闭环」「短时双向实物闭环」 | “闭环”可被听成舵机控制闭环 | 改为「无舵机 UART/ACK 长稳」「短时双向 ACK」 |
| R2 | 「两板之间仍禁止连接 VCC；舵机必须保持断开。」 | 与后文「两颗舵机已经装入指框」矛盾；评委以为总线悬空 | 改为「两板之间仍禁止连接 VCC。舵机已装框，但本阶段不接 Titan/Maix 控制、不上舵机 6V、不装舵盘/连杆。」 |
| R3 | 时间线「PC 舵机总线散置台架……装框/连杆未测」 | 装框已发生；“未测”应限标定/动作 | 改为「散置台架已测；装框后只读/动作未测；连杆未装」 |
| R4 | 成熟度「Titan/整机 / 部分通过」 | “整机”暗示手指或整手 | 行名改为「Titan / 无舵机视觉链路」 |
| R5 | 「center_hold……finger_smoke……已准备但待完整机械机构实测」 | 在 M2x18 暂停期可被读成“可以跑脚本” | 加一句：「M2x18 到货并由 Codex 按 Gate 授权前，禁止运行这两个脚本。」机械门控正文仍归 Claude A。 |
| R6 | 「检查窗口内未再出现重置」与长稳「≥15m23s」并列 | 两个窗口会被合成一个 30 分钟视觉验收 | 分开写：长稳通信 ≥15m23s；RNDIS 复查另计约 30 分钟，且只覆盖预览节流后的调试口 |

### 1.2 YOLO 长稳报告

| # | 摘录 | 风险 | 最小修正 |
|---|---|---|---|
| Y1 | `Status: REAL_HARDWARE_NO_SERVO_ACCEPTED` | “ACCEPTED”易被竞赛材料直接引用为整项通过 | 副标题补「通信/策略映射验收；非机械、非竞赛冻结」 |
| Y2 | `infer_fps=100.0` | 与生产 20 FPS 处理上限冲突，评委以为跑满 100 | 禁止引用该字段当相机/NPU 帧率。它是瞬时推理耗时换算，且与 `VISION_PROCESS_INTERVAL_MS=50` 不是同一口径 |
| Y3 | 「stable USB/RNDIS debugging after preview throttling」+「checked 30-minute window」 | 可写成“视觉 30 分钟耐久已过” | 只能写：预览降到 2 FPS 后，被检查的约 30 分钟窗口无新的 NDIS 10400。不是整机热耐久 |
| Y4 | 「This proves the real-camera class reached Titan policy handling」 | 正确，但下一句若被截断会丢安全边界 | 引用必须连写 `pose=NOT_CONFIGURED actionable=0` |
| Y5 | 报告未附未剪辑终端、屏幕录像、模型哈希 | 与 `E0003` 一样不能当竞赛冻结件 | 索引记 `recorded` 工程归档 + 附件仍缺 |

本红队**不改写**该历史报告正文，以免制造第二证据源。修正通过本文件与 `E0007` 注释约束引用。

### 1.3 竞赛讲解稿（过期，评委向）

`COMPETITION_PITCH_AND_STORYBOARD.md` 仍写「Maix UART4 已真机打开」「Titan 固件已编译但未烧录」「YOLO 真机、两板联调尚未完成」，并设计「授权并抓握」「手指动作近景」。

当前可演示层是 **DEMO_MVP 阶段 B：真实视觉但不动作**。90 秒抓握分镜整段标 `FUTURE`，赛场不得使用。本批不改该文件（避免与演示包双源）；以 `competition_2026/NO_MOTION_DEMO_PACK_2026-08-15.md` 为当前唯一评委脚本。

`DEMO_MVP_RUNBOOK.md` 阶段 A 仍把 mock 写成“首次实验室验收”。实验室已越过 A/B 的无动作部分。请 Codex 后续把阶段 A 标为历史，阶段 B 标为当前可演，阶段 C/D 标为未授权。

### 1.4 竞赛入口

`competition_2026/README.md` 在本批同步：补真实 YOLO 长稳、装框但未动作、`INTENT`/`MOTION LOCKED` 边界，并改掉“实验室恢复后先做单指校准再做 Titan 链路”的过期顺序。

## 2. 证据索引处置

| ID | 处置 |
|---|---|
| E0003 | 保持 `needs_attachment`。补注释指向长稳报告，但仍缺模型哈希与未剪辑录像 |
| E0006 | 保持：Mock 十秒策略映射，不得与 E0007 合并 |
| E0007 | **本批新增**：真实 YOLO11 → UART2 ACK 长稳（授权摘要级 `recorded`） |

`E0002` 仍 `needs_attachment`。散置动作不得写入赛场讲稿。

## 3. 仍未验证 / 禁止外推

`UNVERIFIED`：

- 未剪辑 Maix/Titan 终端全文、屏幕录像、接线照片、YOLO 模型哈希与输入尺寸
- 真实物理拔 UART 后的 OFFLINE + 序号基线恢复
- 断联恢复卡所定义的拔线/再插试验
- 长期热安全、装框后只读、电气中点、舵盘/连杆、软限位、生产姿态
- Titan → Maix 权威 STATUS（Grok A 设计中）；屏幕 INTENT 不能当权威状态
- cup(41) / remote(65) 的**真实摄像头**长稳（长稳报告只写了 bottle/39）
- `infer_fps`、检测数、选中数的竞赛级口径

禁止外推：AI 已驱动机械手、生产联调完成、整手抓握、Titan NPU 已部署、30 分钟视觉耐久、Mock 等于真机、ACK 等于动作、511 等于机械中心。

## 4. 给 Codex 的落地补丁（可选，本批未改 README）

R2 建议替换：

```text
两板之间仍禁止连接 VCC。舵机已装入指框，但本阶段不接 Titan/Maix 舵机总线、
不打开外部 6V、不安装舵盘和连杆；M2x18 到货前不做机械动作。
```

R1 建议把「无舵机长稳闭环」一律写成「无舵机 UART/ACK 长稳」。
