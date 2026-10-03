# 支持类别 39 / 41 / 65 真机策略链路证据（2026-08-15）

- 日期：`2026-08-14` 至 `2026-08-15`
- 对象：MaixCAM2 ↔ Titan Mini，`uart2` / `115200`，无舵机
- 对应计划：`docs/NEXT_SUPPORTED_CLASS_MOCK_TEST_PLAN_2026-08-14.md`
- 对应探针：独立目录 `maixcam2_supported_probe_app/`（非生产五文件）
- 结果口径：**短时无舵机 UART / ACK / 类别映射 / 未配置姿态拒绝路径**
- 证据等级：用户操作真机；主模型写入启动上下文的授权摘要；本文件只做归档转写
- 真机操作者：用户
- 本文件作者：grokB（文档与证据索引），`hardware_accessed=false`
- 本文件作者未亲自编译、烧录、接线、开串口、上电或驱动舵机
- 权威摘要来源：`docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` §3.2

本报告只转写启动上下文已确认的三轮事实。不得把本文理解为本记录员亲自上机。通过项仅覆盖「10 秒窗口内的 UART、ACK、39/41/65 类别映射、未配置姿态拒绝」，不是姿态验收、不是舵机验收、不是机械手验收、不是长期稳定性验收，也不是计划 §6 全部 15 条判据的完整竞赛附件包。

## 0. 三轮总览

舵机和 6V 电源断开。每类各完成约 10 秒真机测试。

| class | Titan 决策 | Maix 结果 | Titan 安全结果 |
|---|---|---|---|
| 39 | `CYLINDRICAL_GRASP` | `sent=30` `acked=30`，错误全 0 | `reason=accepted` `pose=NOT_CONFIGURED` `actionable=0` |
| 41 | `POWER_GRASP` | `sent=30` `acked=30`，错误全 0 | `reason=accepted` `pose=NOT_CONFIGURED` `actionable=0` |
| 65 | `PRECISION_GRASP` | `sent=30` `acked=30`，错误全 0 | `reason=accepted` `pose=NOT_CONFIGURED` `actionable=0` |

三轮结束均观察到：

- `VISION_STALE`
- `VISION_OFFLINE`
- `sequence baseline reset`

该结束序列与计划 §5.2 第 7 步一致：断流后 Titan 清除视觉候选并复位序号基线。它证明本轮发送已停止且基线已复位，**不**单独证明断联恢复验收。

## 1. 现场约束（授权摘要已写明）

- 舵机总线断开，6V 电源断开，无机械动作。
- 本记录员 `hardware_accessed=false`，未操作硬件。
- 未修改生产代码、协议、CRC、校准参数；未碰 `D:\Micu\RTTWorkspace\titan_uart_test`。
- 类别注入走独立探针目录，不编辑设备端生产五文件。
- 两板独立 USB、三线 `GND` + 交叉 `TX/RX`、不接 `3V3/5V`、H1 `uart2` 沿用既有接线口径；本次摘要未另行否定这些约束。

## 2. 与上一轮 `class=3` 的路径区别

| 轮次 | 类别 | 拒绝层 | 可见字段 |
|---|---|---|---|
| 已归档短时双向 / 10 分钟压力 | `3` | 策略层 | `reason=unsupported_class`，`actionable=0` |
| 本归档三轮 | `39` / `41` / `65` | 姿态层 | `reason=accepted`，`pose=NOT_CONFIGURED`，`actionable=0` |

`reason=accepted` 只表示 `grip_policy` 接受了该类别并给出对应抓握意图；随后因生产姿态库未配置而在姿态解析层拒绝执行。`actionable=0` 是预期安全结果。若出现 `actionable=1`，按计划应判为严重缺陷。本次授权摘要中三类均为 `actionable=0`。

## 3. 计划 §6 判据对照（只填已给出的事实）

| # | 判据 | 本归档状态 | 依据 |
|---|---|---|---|
| 1 | 本轮类别 VISION 日志，`class` 等于设定值 | **摘要已记录** | 三类分别对应 39/41/65 决策行 |
| 2 | `action` 等于计划 §4.1 | **摘要已记录** | `CYLINDRICAL_GRASP` / `POWER_GRASP` / `PRECISION_GRASP` |
| 3 | `reason=accepted` | **摘要已记录** | 三类安全结果列 |
| 4 | `pose=NOT_CONFIGURED` | **摘要已记录** | 三类安全结果列 |
| 5 | `actionable=0`，无一帧为 1 | **摘要已记录** | 三类均为 `actionable=0`；原始逐帧日志未附 |
| 6 | Δ`pose_unavailable` > 0 且 ≈ VISION 帧数 | **未提供** | 无 `S_before` / `S_live` / `S_after` 原文 |
| 7 | Δ`policy_rejected` = 0 | **未提供** | 同上 |
| 8 | Δ`ignored_old` / `duplicates` 不增长 | **未提供** | 仅有结束时 `sequence baseline reset` |
| 9 | `acked` 持续增长，`sent − acked ≤ 1` | **摘要已记录** | 三类均为 `sent=30` `acked=30` |
| 10 | `timeout` / `malformed` / `rejected` / `unexpected` / `tx_fail` / 连续超时均为 0 | **摘要已记录** | 「错误全 0」 |
| 11 | `rx_errors=0` | **摘要已记录** | 含于「错误全 0」 |
| 12 | Titan `invalid` / `payload` / `tx_fail` 不增长 | **未提供** | 无 `sh_status` 计数原文 |
| 13 | 舵机全程断开、无机械动作 | **摘要已记录** | 舵机和 6V 断开 |
| 14 | 本轮触检无发热 | **未逐轮写明** | 10 秒轮次未单独给出触检记录 |
| 15 | 设备端五个生产文件未被写入 | **未提供哈希对** | 使用独立探针目录；起止 SHA-256 未附 |

整体计划 PASS 还要求 §8 的 `class=3` 基线复验。**本次授权摘要未给出该复验日志**，因此本报告**不**把计划整体标为 PASS。

`sent=30` 与计划 §4.4 量级（约 10 个 PING + 约 20 个 VISION）一致，可作交叉核对，不是独立计时证明。

## 4. 未随本报告归档的原始附件

计划 §9 清单中，下列材料**未**进入本仓库附件：

- 三轮 Titan UART1 未剪辑日志全文
- 三轮发送端未剪辑日志全文
- 每轮 `S_before` / `S_live` / `S_after` 的 `sh_status` 原文
- 回到 `class=3` 后的对照日志
- 接线与舵机断开照片
- 起止两次生产文件 SHA-256
- 逐轮时间戳、环境温度

因此 `competition_2026/evidence/evidence_index.csv` 的 `E0006` 记为已记录的授权摘要，**不得**写成已形成完整可提交竞赛附件。缺附件不等于否定已给出的字段值，只限制外推与参赛引用等级。

## 5. 探针与选择文件现状（归档时只读核对）

- 独立探针目录：`maixcam2_supported_probe_app/`
- 该目录选择文件现为单行 `65`，无 `live=ENABLE` / `live_ack` / `live_class` 三令牌
- 按使用说明，误运行应为 `dry-run`，不得据此再发真机帧
- 仓库 `maixcam2/supported_class_mock_probe_selection.txt` 现为单行 `39`，同样无 live 令牌
- 本批**不**改选择文件、不改探针源码、不恢复 live 授权

## 6. 本次可以写、不可以写的结论

可以写：

- 2026-08-14 至 2026-08-15，在舵机和 6V 断开条件下，39 / 41 / 65 各完成约 10 秒真机策略链路观察。
- 三类 Maix 统计均为 `sent=30` / `acked=30`，错误计数全 0。
- Titan 分别给出 `CYLINDRICAL_GRASP` / `POWER_GRASP` / `PRECISION_GRASP`，且均为 `reason=accepted`、`pose=NOT_CONFIGURED`、`actionable=0`。
- 三轮结束均出现 `VISION_STALE`、`VISION_OFFLINE`、`sequence baseline reset`。
- 这证明该短时窗口内 UART、ACK、类别映射和未配置姿态拒绝路径按预期工作。

不可以写：

- 计划 §6 十五条全部 PASS，或计划整体验收通过。
- `class=3` 基线复验已完成。
- Δ`pose_unavailable` / Δ`policy_rejected` / Titan `invalid` 计数已用 `sh_status` 原文核过。
- 姿态数值、舵机方向/中心/软限位、机械手或抓握成功已验证。
- 可以开始让 Titan/Maix 控制舵机，或可以填写 `config/servo_calibration_template.csv`。
- 长期热安全、断联恢复、整机联调、生产验收已完成。
- 本记录员亲自操作硬件。
- 已具备完整可提交竞赛原始附件。

## 7. 证据索引

`competition_2026/evidence/evidence_index.csv` 追加 `E0006`。该行 `source_sha256` 为本文 SHA-256。
