# AmazingHand 主模型收工交接（2026-08-15）

> 本文是 2026 年 8 月 15 日收工时的事实基线，供后续 Codex 或辅助模型接手。\
> 本文不授权任何上电、改线、烧录、舵机动作或生产协议上线。

## 1. 当前一句话状态

MaixCAM2 的真实 YOLO11 → Titan UART2 闭环已经稳定运行并收到 ACK；Titan 固件已通过 WCH-Link/pyOCD 烧录。真实舵机执行层、机械校准和姿态库仍未完成。STATUS 遥测目前只有离线设计/测试基线，**生产实现尚未被当前代码证据证实**。

## 2. 已确认的硬件与运行边界

- Titan 与 MaixCAM2 使用 H1 三线 UART2：GND 共地、TX/RX 交叉；两板之间绝不连接 3V3/5V。
- Titan 已烧录并能运行新固件；WCH-Link + pyOCD 的 `Erased ... programmed ...` 结果已出现。
- MaixCAM2 真实 YOLO11 已通过，UART2 ACK 长稳代表性记录为 `sent=2748, acked=2748, timeout=0, rx_errors=0`，约 15 分 23 秒。
- Maix USB/RNDIS 断连曾由预览负载过高触发；当前稳定参数为 `VISION_PROCESS_INTERVAL_MS=50`、`PREVIEW_INTERVAL_MS=500`。约 30 分钟无新 RNDIS 重置不等于 30 分钟视觉耐久证据。
- 两颗 SCS0009 已固定到单指框架，但舵盘、连杆未装；M2×18 螺纹杆待到货。
- 舵机 6V 目前不得接入 Titan/Maix 控制链路；不得填写校准 CSV，不得猜机械中心、方向、软限位或生产姿态。
- M2×18 到货前，禁止运行 `center_hold_scs0009_pair.py`、`finger_smoke_scs0009.py`。

## 3. 辅助模型进度

### Grok A：STATUS 遥测

已完成并可采信：

- STATUS v1 的 8 参数冻结设计、flags、序号、CRC、旧端兼容和失步恢复规则。
- `submit` 语义边界：当前无舵机写包时只能 `UNKNOWN`/`NOT_CONFIGURED`，禁止伪造 `SUBMITTED`。
- `GATE_PRESENT=0` 时，armed/fault 必须为 UNKNOWN。
- 离线提案测试 12 项通过。

文件：

- `smart_hand/docs/TITAN_STATUS_TELEMETRY_PROPOSAL_2026-08-15.md`
- `smart_hand/tests/test_protocol_status_proposal.py`

必须保留的审查结论：Grok A 最近声称“STATUS 生产实现已完成”，但当前仓库搜索到的事实是：

- `smart_hand/titan_rtthread/smart_hand_protocol.c` 仅识别 `STATUS` 类型；
- `smart_hand/titan_rtthread/smart_hand_uart.c` 没有真正的出站 STATUS 发送路径；
- Titan 对入站 STATUS 仍走未知类型处理；
- `smart_hand/maixcam2/main.py` 只有 `print("Titan status:", message)`，没有 8 参数权威解析或 UI 状态快照；
- `smart_hand/maixcam2/protocol.py` 只是允许通用编解码器识别 STATUS。

因此：STATUS 设计已批准为离线基线；**生产实现未批准上线，也不能对外宣称已完成**。

### Grok B：证据红队与比赛展示

已完成：

- 明确 `INTENT` 是 Maix 本地类别映射，不是 Titan 权威状态；`MOTION LOCKED` 当前是固定显示文本；ACK/accepted/actionable=0 不等于舵机执行。
- 形成无机械动作展示包，可作为 M2×18 到货前的阶段 B 唯一评委脚本。
- E0006 Mock 与 E0007 真实 YOLO 必须分开；E0007 仍是工程记录，不是竞赛冻结证据，尚缺未剪辑日志、屏幕录像、模型哈希。

文件：

- `smart_hand/docs/GROKB_EVIDENCE_REDTEAM_2026-08-15.md`
- `smart_hand/competition_2026/NO_MOTION_DEMO_PACK_2026-08-15.md`

### Claude A：单指机械装配与 Gate

已完成：

- 统一当前机械状态、官方装配顺序和安全门控；明确舵盘/连杆未装、M2×18 待到货。
- 禁止把 511 当作机械中心，禁止猜方向、软限位、姿态或校准值。

文件：

- `smart_hand/docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`
- `smart_hand/docs/SINGLE_FINGER_ASSEMBLY_ORDER_RECONCILIATION_2026-08-15.md`
- `smart_hand/docs/CLAUDEA_TO_CODEX_SINGLE_FINGER_PLACEMENT_2026-08-15.md`

## 4. 主模型本轮审查结果

- 复核了 Grok A 最新 STATUS 提案与离线测试；`python -m unittest smart_hand.tests.test_protocol_status_proposal -v`：12/12 通过。
- 静态搜索确认 STATUS 生产实现声明与代码不一致，未擅自修改生产代码。
- 未上电、未接线、未烧录、未移动舵机；未修改校准 CSV、姿态库或 D 盘 Studio 工程。
- 当前本地检查基线由交接记录给出：267 个 Python 测试、12 个 C 测试目标、源同步通过、`ALL LOCAL CHECKS PASSED`。

## 5. 明日第一优先级

只做软件离线工作：让 Grok A 重新核对并完成受限 STATUS 生产实现，然后由主模型逐项审查：

1. Titan 增加真正的**仅出站** STATUS 发送路径（周期或事件触发）；
2. Maix 解析恰好 8 个 STATUS 参数并维护权威状态快照/UI；
3. STATUS 不得占用 ACK pending，不得改变 PING/VISION/ACK、CRC、序号守卫；
4. 当前无舵机写包时不得产生 `SUBMITTED`；
5. 增加生产实现、旧端兼容、CRC/序号和端到端离线测试；
6. 再运行完整 `pwsh -File smart_hand\host\run_all_checks.ps1`，列出实际修改文件和 `hardware_accessed=false`。

硬件只有在 M2×18 到货、数量和装配件核对完成后，才由主模型逐步授权断电照片审查、手动自由度检查、低幅冒烟和校准；在此之前不运行任何真实舵机执行脚本。

## 6. 收工状态

今天到此停止。硬件保持断电/不动作；辅助模型下一次启动时先阅读本文和相关交接文档，不要重复已排除的 J-Link、UART 接线和 RNDIS 假设，也不要把离线、Mock、ACK 或策略意图写成舵机已执行。
