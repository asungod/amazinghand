# AmazingHand 辅助模型新会话启动上下文（2026-08-15）

> 用途：Grok/Claude 等辅助模型丢失对话后，先完整阅读本文件，再执行主模型给出的单一任务。
> 本文件不授予任何真机操作权限。除非任务明确写明，辅助模型一律 `hardware_accessed=false`。

## 1. 项目目标与期限

- 目标：在 2026-08-26 前完成可演示的单指/机械手 MVP。
- 主架构：`MaixCAM2（视觉） -> UART2 -> Titan Mini（策略、安全、实时控制） -> TTL 总线舵机转接板 -> SCS0009`。
- 官方 Arduino 示例只作为 SCS0009 协议与控制逻辑参考；当前架构不要求另加 ESP32/Arduino。ESP32-S3 仅作进度失败时的备选控制器。
- 用户是硬件/软件初学者；任何真机步骤必须由 Codex 主模型逐步授权。

## 2. 仓库与权限边界

- 仓库根目录：`C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\smart_hand`
- Titan Studio 工程：`D:\Micu\RTTWorkspace\titan_uart_test`
- 除非任务明确授权，禁止修改 D 盘 Studio 工程。
- 禁止猜测或预填：舵机方向、中心值、软限位、生产抓握姿态。
- 禁止绕过 Titan 安全门，禁止把 Mock/离线测试写成真机或机械验证。
- 禁止单方面修改协议、CRC 或消息语义。

## 3. 已确认的真机证据

### 3.1 Titan 与 MaixCAM2

- Titan Mini 已通过 WCH-Link + pyOCD 烧录；UART1 控制台可用。
- Titan 生产通信口为 `uart2`，115200；Maix 端为 `/dev/ttyS2`（B0/B1）。
- 两板正确接法只有三线：交叉 TX/RX + GND；禁止互接 3V3/5V；两板各自 USB 供电。
- 历史上误把 40 针电源脚当 GND 曾造成明显发热。正确接口是 Titan 独立 H1 三针 UART2；历史发热事件不得从文档删除。
- 无舵机 UART2 压力测试第二轮通过约 11 分 49 秒：`sent=2126`、`acked=2126`、`pending=0`，所有错误计数为 0，无发热/重启。证据：`validation_reports/uart2_10min_no_servo_stress_2026-08-14.md`。

### 3.2 支持类别真机策略链路

2026-08-14 至 2026-08-15，舵机和 6V 电源断开的条件下，三类均完成 10 秒真机测试：

| class | Titan 决策 | Maix 结果 | Titan 安全结果 |
|---|---|---|---|
| 39 | `CYLINDRICAL_GRASP` | `sent=30 acked=30`，错误全 0 | `reason=accepted pose=NOT_CONFIGURED actionable=0` |
| 41 | `POWER_GRASP` | `sent=30 acked=30`，错误全 0 | `reason=accepted pose=NOT_CONFIGURED actionable=0` |
| 65 | `PRECISION_GRASP` | `sent=30 acked=30`，错误全 0 | `reason=accepted pose=NOT_CONFIGURED actionable=0` |

- 三轮结束均观察到 `VISION_STALE`、`VISION_OFFLINE`、`sequence baseline reset`。
- 这只证明 UART、ACK、类别映射和未配置姿态拒绝路径正确；不证明姿态、舵机、机械手或长期稳定性。
- 独立探针目录：`maixcam2_supported_probe_app/`。选择文件现已撤销 live 授权，只保留 `65`，误运行应为 dry-run。
- 归档报告：`validation_reports/supported_class_mock_2026-08-15.md`；竞赛索引 `E0006`（授权摘要，原始未剪辑日志/照片/`sh_status` 计数未附）。

### 3.3 PC 舵机总线既有证据

- 仓库 README 记录：SCS0009 ID1/ID2、PC 只读、空载单颗小幅动作、双舵机同步小幅动作已做过。
- 竞赛证据索引 `E0002` 仍标记 `needs_attachment`，因此不得写成已形成完整可提交证据。
- `center_hold_scs0009_pair.py` 与 `finger_smoke_scs0009.py` 是已准备工具，不代表完整机构已验证。

### 3.4 真实 YOLO11 长稳闭环与 USB/RNDIS

- MaixCAM2 真实 YOLO11 瓶子识别到 Titan UART2 ACK 闭环已连续运行至少约 15 分 23 秒。
- 代表性统计：`sent=2748`、`acked=2748`，`tx_fail/rejected/unexpected/malformed/timeout/rx_errors` 均为 0；RTT 平均约 28 ms，最大 138 ms。
- 真实策略日志已出现 `class=39 action=CYLINDRICAL_GRASP reason=accepted pose=NOT_CONFIGURED actionable=0`；低置信度与目标丢失/恢复门控也已观察通过。
- Windows 曾出现 `Remote NDIS Compatible Device hardware stopped responding`。限制视觉处理为 20 FPS、USB/RNDIS 预览为 2 FPS 后，长稳窗口内未再出现重置。
- 证据：`validation_reports/maixcam2_yolo11_titan_uart2_long_run_2026-08-15.md`。
- Maix 屏幕已加入目标、置信度、策略意图、链路状态、ACK/RTT 与 `MOTION LOCKED` 叠加。`INTENT` 只表示本地策略意图，不表示 Titan 已执行舵机动作。

## 4. 当前硬件阶段与安全红线（2026-08-15 更新）

- 两颗 SCS0009 **已经固定到单指框架**；舵盘和连杆均未安装。
- 一根 `M2x18` 螺纹杆仍在运输中，预计约两天后到货。机械动作与完整标定暂停，不要要求用户重复装框。
- 本阶段不安排舵机动作、上电、改线或填写校准 CSV；下一次真机操作由 Codex 主模型依据到货情况逐步授权。
- 后续门控顺序为：断电照片审查 -> 唯一外部电源入口确认 -> 只读探测 -> 电气中点参考 -> 舵盘/连杆装配 -> 手动自由度检查 -> 低幅冒烟测试。该顺序不是当前执行授权。
- 任一异常发热、焦味、异常复位、串口消失、堵转或电流突升都必须立即断电。

## 5. 当前软件与关键入口

- 全部离线检查：`pwsh -File smart_hand\host\run_all_checks.ps1`
- PC 舵机工具：
  - `host/probe_scs0009.py`
  - `host/set_scs0009_id.py`
  - `host/nudge_scs0009.py`
  - `host/sync_nudge_scs0009_pair.py`
  - `host/center_hold_scs0009_pair.py`
  - `host/finger_smoke_scs0009.py`
- 空白校准模板：`config/servo_calibration_template.csv`；未经过机械实测禁止填写。
- 单指操作参考：`TOMORROW_SINGLE_FINGER_RUNBOOK.md`、`SERVO_CALIBRATION_AND_LOGGING.md`。
- `README.md`、`LAB_BRINGUP_CHECKLIST.md`、`GRIP_POLICY_MVP.md`、`competition_2026/README.md` 已于 2026-08-15 与 10 分钟 UART / 39/41/65 归档对齐；仍以本文件与 validation report 为真机证据上限。
- 给 Codex 主模型的本批交接：`docs/GROKB_TO_CODEX_SUPPORTED_CLASS_ARCHIVE_2026-08-15.md`。
- 当前完整离线验收：267 个 Python 测试、12 个 C 测试目标、Titan 规范源/Studio 源同步检查全部通过。
- 当前辅助模型任务分工：`docs/AUX_MODEL_TASK_BOARD_2026-08-15.md`。

## 6. M2x18 到货前允许推进的工作

1. Titan -> Maix 权威 STATUS 遥测扩展的协议提案、字段定义、兼容性分析和测试向量；只做设计，不改生产协议或生产代码。
2. 对装配 Gate、Runbook 与官方装配顺序做文档一致性修正，明确当前因 `M2x18` 未到而暂停。
3. 红队审查真实 YOLO11 长稳报告、README 与比赛证据索引，消除 Mock/真机、ACK/动作、INTENT/执行之间的歧义。
4. 整理不依赖机械动作的比赛演示脚本、故障恢复讲稿、日志采集清单和证据附件清单。
5. 为上述工作补充离线测试；不得借此填写机械参数、修改 D 盘工程或授权真机动作。

当前辅助模型固定分工：Grok A 负责 STATUS 遥测与安全语义；Grok B 负责证据红队与比赛展示；Claude A 负责机械装配文档一致性。三者不得互相修改对方正在负责的文件，发现并发改动只记录归属并基于最新版本复核。

## 7. 辅助模型工作规范

每批必须一次性交付：

1. 修改文件的完整路径。
2. 关键改动摘要。
3. 实际运行的命令和通过/失败结果。
4. 明确 `hardware_accessed=false`（除非用户亲自操作，辅助模型只记录用户证据）。
5. 明确未验证项和不得外推项。
6. 是否触碰生产代码、协议、校准数据或 D 盘工程。

辅助模型不得向用户下达真机上电、改线、烧录或舵机运动指令；这部分由 Codex 主模型负责。
