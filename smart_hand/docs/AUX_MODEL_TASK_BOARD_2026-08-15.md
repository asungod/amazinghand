# AmazingHand 辅助模型任务分工（2026-08-15）

状态：`OFFLINE_ONLY_WHILE_M2X18_PENDING`

> 两颗舵机已装入单指框架；舵盘、连杆未安装；一根 M2x18 螺纹杆预计约两天后到货。到货前不做机械动作。所有辅助模型必须先完整阅读 `AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md`。

## 全局红线

- `hardware_accessed=false`；不得下达上电、改线、烧录、串口占用或舵机动作指令。
- 不修改 D 盘 Studio 工程，不填写校准 CSV，不猜方向、中心、软限位或生产姿态。
- 不把 ACK、策略 `INTENT`、`accepted` 或 `pose=NOT_CONFIGURED` 写成舵机已经执行。
- 生产协议、Titan C 与 Maix 生产代码默认只读；只有 Codex 主模型书面批准后才可修改。
- 每个任务一次性交付，不要中途反复询问用户；证据不足处标 `UNVERIFIED`。

## Grok A：Titan STATUS 遥测与安全语义设计

目标：设计 Titan -> Maix 的权威状态遥测，使 Maix 界面将“本地推断意图”与“Titan 实际安全状态”分开显示。

必须交付：

1. 审计现有协议、ACK 字段、序号/CRC、在线/陈旧判定和 Titan 状态来源。
2. 提出最小向后兼容方案，至少覆盖：链路在线、最后接收序号、策略动作、拒绝原因、姿态配置状态、安全门 armed/disarmed、动作是否真正提交、故障/陈旧标志。
3. 明确哪些字段能由现有代码权威产生，哪些必须保持 `UNKNOWN/NOT_CONFIGURED`。
4. 给出二进制布局、长度、字节序、CRC 覆盖范围、版本协商、旧端兼容行为和失步恢复。
5. 提供正常、低置信、姿态未配置、disarm、VISION_STALE、序号重放、CRC 错误等测试向量。
6. 只新增设计文档和离线测试草案；不得修改生产协议或生产代码。

建议输出：`docs/TITAN_STATUS_TELEMETRY_PROPOSAL_2026-08-15.md`。

## Claude A：机械装配文档一致性

目标：让所有操作文档忠实反映当前机械状态和官方装配顺序，不形成提前动作授权。

必须交付：

1. 对照 `SINGLE_FINGER_SERVO_PLACEMENT_AUDIT_2026-08-15.md`、官方装配证据、`SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md` 和 `TOMORROW_SINGLE_FINGER_RUNBOOK.md`。
2. 修正“装框尚未完成”等过期表述；统一为舵机已装框、舵盘/连杆未装、M2x18 待到货。
3. 解决项目旧顺序与官方“拉杆先接 link、舵盘在电气中点压上输出轴”顺序冲突；以官方证据为主，并保留安全断电门控。
4. 删除或改写任何暗示当前可运行 `center_hold` 或 `finger_smoke` 的文字。
5. 只改 docs；不得发真机指令、改脚本、填校准值。

## Grok B：证据红队与比赛展示包

目标：把现有真机成果整理成评委能看懂、又不夸大成熟度的证据包。

必须交付：

1. 审查 `README.md` 和 `validation_reports/maixcam2_yolo11_titan_uart2_long_run_2026-08-15.md`。
2. 列出所有可能混淆 Mock/真实 YOLO、ACK/舵机执行、INTENT/Titan 权威状态、散置台架/装框机构的句子并提出最小修正。
3. 编写 3 分钟无机械动作演示流程：实时识别、置信度门、目标移出/恢复、UART ACK/RTT、`MOTION LOCKED` 安全解释。
4. 编写异常恢复流程：RNDIS 断连、UART timeout、Titan offline、摄像头无目标；不得要求增加帧率或绕过安全门。
5. 建立证据附件清单：未剪辑日志、屏幕录像、接线照片、版本/哈希、测试统计和仍未验证项。
6. 默认只改 docs/competition_2026 与 validation report 的证据索引，不修改生产代码。

## Codex 主模型保留工作

- 审查并裁决辅助模型输出；决定是否批准 STATUS 协议实现。
- Maix 新状态叠加的短时真机视觉核验。
- M2x18 到货后的全部上电、舵机动作、舵盘/连杆装配和机械标定步骤。
- 最终校准值、生产姿态、Titan 舵机执行层与整机验收。

## 可直接发送的任务指令

### 发给 Grok A

```text
先完整阅读 smart_hand/docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md 和
smart_hand/docs/AUX_MODEL_TASK_BOARD_2026-08-15.md。
执行“Grok A：Titan STATUS 遥测与安全语义设计”整批任务。
只做协议提案、兼容性分析、测试向量和离线测试草案，不修改生产协议、Titan C、
Maix 生产代码或 D 盘工程。hardware_accessed=false。连续完成后一次性交付给 Codex 审查。
```

### 发给 Grok B

```text
先完整阅读 smart_hand/docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md 和
smart_hand/docs/AUX_MODEL_TASK_BOARD_2026-08-15.md。
执行“Grok B：证据红队与比赛展示包”整批任务。
重点审查 Mock/真机、ACK/执行、INTENT/Titan 权威状态、散置台架/装框机构的证据边界，
并整理三分钟无机械动作演示与附件清单。默认只改 docs、competition_2026 和证据索引；
不改生产代码。hardware_accessed=false。连续完成后一次性交付给 Codex 审查。
```

### 发给 Claude A

```text
先完整阅读 smart_hand/docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md 和
smart_hand/docs/AUX_MODEL_TASK_BOARD_2026-08-15.md。
执行“Claude A：机械装配文档一致性”整批任务。
以官方装配证据为准，统一当前状态为舵机已装框、舵盘/连杆未装、M2x18 待到货，
解决旧 Runbook 与官方装配顺序冲突。只改 docs，不下达真机指令，不改脚本或校准值。
hardware_accessed=false。连续完成后一次性交付给 Codex 审查。
```

## 每批统一交付格式

1. 修改文件完整路径。
2. 关键改动和证据来源。
3. 实际运行命令与完整通过/失败摘要。
4. `hardware_accessed=false` 声明。
5. 生产代码、协议、校准数据、D 盘工程是否被触碰。
6. 仍未验证项与禁止外推项。
7. 给 Codex 的 10 行以内最小审查提示。
