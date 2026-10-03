# grokB → Codex 主模型交接报告（2026-08-15）

- 发件：grokB（辅助模型，本批只做文档归档与状态同步）
- 收件：Codex 主模型（唯一可向用户下达真机步骤的角色）
- 任务：归档 class 39/41/65 三轮真机策略链路证据
- `hardware_accessed=false`
- 未编译、未烧录、未接线、未开串口、未上电、未驱动舵机
- 未修改生产代码、协议、CRC、校准参数、D 盘 `titan_uart_test`

请先读本文件，再决定下一步授权。本文件不授予任何真机权限。

## 1. 请 Codex 立即采信的结论

39/41/65 三轮 10 秒无舵机策略链路，已从启动上下文授权摘要落成仓库证据：

| 项 | 值 |
|---|---|
| 归档报告 | `validation_reports/supported_class_mock_2026-08-15.md` |
| 竞赛索引 | `E0006`，`status=recorded`，`category=hardware_policy` |
| 报告 SHA-256 | `EB24E087AF578463AA6748A601062D807637A5F4DF2AC81F1847201E47312F6D` |
| 证据等级 | 用户操作真机 + 主模型授权摘要 + 辅助模型转写；**不是**完整竞赛附件 |
| 计划整体 PASS | **否**。未宣称 `NEXT_SUPPORTED_CLASS_MOCK_TEST_PLAN` §6 十五条全部通过 |

三类已记录事实（舵机与 6V 断开）：

| class | Titan 决策 | Maix | 安全结果 |
|---|---|---|---|
| 39 | `CYLINDRICAL_GRASP` | `sent=30 acked=30` 错误全 0 | `accepted` / `NOT_CONFIGURED` / `actionable=0` |
| 41 | `POWER_GRASP` | 同上 | 同上 |
| 65 | `PRECISION_GRASP` | 同上 | 同上 |

三轮结束均见 `VISION_STALE`、`VISION_OFFLINE`、`sequence baseline reset`。

**只证明**：该短时窗口内 UART、ACK、类别映射、未配置姿态拒绝路径。  
**不证明**：姿态数值、舵机、机械手、长期稳定、断联恢复、15 条整体验收。

`reason=accepted` 只表示 policy 接受类别；执行仍被空 pose bank 挡住。若将来出现 `actionable=1`，按计划是严重缺陷，不是成功。

## 2. 本批改了什么

| 路径 | 动作 |
|---|---|
| `validation_reports/supported_class_mock_2026-08-15.md` | 新建归档报告 |
| `competition_2026/evidence/evidence_index.csv` | 追加 `E0006` |
| `docs/NEXT_SUPPORTED_CLASS_MOCK_TEST_PLAN_2026-08-14.md` | `READY_FOR_AUTHORIZED_EXECUTION` → `ARCHIVED_AUTHORIZED_SUMMARY` |
| `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` | 增加报告指针；§5 README 落后说明已过时 |
| `README.md` | 补 10 分钟 UART 与 39/41/65，保留证据边界 |
| `LAB_BRINGUP_CHECKLIST.md` | 同步 2026-08-15 状态条 |
| `GRIP_POLICY_MVP.md` | 更正“策略未接入 Titan” |
| `competition_2026/README.md` | 更正“实板通信尚未确认” |
| 本文件 | 给 Codex 的交接 |

未改：`titan_rtthread/*`、`maixcam2/{main,protocol,link_monitor,target_tracker,vision_source}.py`、探针源码、选择文件、`config/servo_calibration_template.csv`、`protocol/*`、D 盘工程。

选择文件现状（只读核对，未改）：

- `maixcam2_supported_probe_app/supported_class_mock_probe_selection.txt`：单行 `65`，无 live 三令牌 → 误运行应为 dry-run
- `maixcam2/supported_class_mock_probe_selection.txt`：单行 `39`，同样无 live 令牌

## 3. 离线检查

```powershell
pwsh -File smart_hand\host\run_all_checks.ps1
```

结果：`ALL LOCAL CHECKS PASSED`

- 229 个 Python 测试 OK
- C 协议 / SCS0009 / 安全门 / grip / pose / vision / sequence 均 passed
- 规范源与 Studio 源哈希一致（哈希一致 ≠ ARM 已链接）

## 4. 计划 §6 判据对照（供 Codex 决定要不要补证）

| 判据 | 本归档 |
|---|---|
| 1–5 类别 / action / `accepted` / `NOT_CONFIGURED` / `actionable=0` | `summary_recorded`（无逐帧原文） |
| 9–11 ACK 与错误计数 | `summary_recorded`（`30/30`，错误全 0） |
| 13 舵机断开 | `summary_recorded`（无照片） |
| 6–8 Δ`pose_unavailable` / Δ`policy_rejected` / Δ`ignored_old` | `not_provided` |
| 12 Titan `invalid`/`payload`/`tx_fail` | `not_provided` |
| 14 逐轮触检无发热 | `not_provided` |
| 15 生产五文件起止哈希 | `not_provided` |
| §8 `class=3` 基线复验 | `not_provided` |

缺附件不等于否定已给出的字段，只限制参赛引用等级。`E0006` 不得写成完整可提交证据。

## 5. 当前真实阶段（请勿回退）

已完成、可用的真机层：

1. Titan 烧录 + UART1 控制台
2. H1 UART2 短时双向 ACK（`E` 对应双向报告）
3. 10 分钟无舵机通信/热观察第二次通过（`E0005`；第一次 7m59s FAIL 必须保留）
4. 39/41/65 短时策略映射 + 空姿态拒绝（`E0006`，授权摘要）

下一硬件阶段（启动上下文 §4，**尚未授权**）：

- 两颗 SCS0009 的 **PC 总线标定**
- **暂不**让 Titan / Maix 参与舵机控制
- 顺序：只读识别 → 单颗中心保持 → 单颗小幅动作 → 第二颗重复 → 双颗中心保持 → 记录真实方向/中心/软限位 → 装连杆后低速冒烟

阻塞上电的现场疑点（必须由 Codex 本人向用户确认，辅助模型不得发上电指令）：

1. 照片疑似 DC 圆孔和绿色端子同时有导线 → 确认只使用一个外部电源入口
2. 白/黑/黑线色不足以单凭照片证明极性
3. `E0002` 仍 `needs_attachment`，PC 总线旧动作不得写成完整竞赛证据

## 6. 建议 Codex 下一步（决策，不是已授权动作）

按优先级，且每一步仍须 Codex 单独授权：

1. **不要**再派辅助模型“补跑”39/41/65 live。选择文件已撤 live。若要补 §6 缺失项，只能由 Codex 带用户补原始日志/`sh_status`/`class=3` 复验，而不是重写结论。
2. **不要**把 `E0006` 升级为竞赛冻结证据，除非用户补上未剪辑终端、照片、哈希。
3. 若进入 PC 总线标定：先确认单一电源入口与极性，再只读识别；任一发热/焦味/堵转/电流突升立即断电。
4. 在方向、中心、软限位未实测前，禁止填写 `config/servo_calibration_template.csv`，禁止配置生产 pose bank，禁止 Titan 写舵机。
5. 辅助模型新会话仍以 `docs/AUX_MODEL_BOOTSTRAP_CONTEXT_2026-08-15.md` 为唯一启动上下文；本报告是该上下文的归档补充，不替代它。

## 7. 辅助模型禁止事项（请 Codex 继续强制）

- 不得向用户下达上电、改线、烧录、舵机运动指令
- 不得猜测方向/中心/软限位/生产姿态
- 不得绕过 Titan 安全门
- 不得把 Mock / 离线 / 授权摘要写成机械验证或完整竞赛附件
- 不得单方面改协议、CRC、消息语义、D 盘工程

## 8. 给 Codex 的一句话

策略链路短时窗口已经归档为 `E0006`；软件状态文档已与 10 分钟 UART 和 39/41/65 对齐；硬件下一扇门是 PC 总线单一电源确认，不是 Titan/Maix 控舵机，也不是再跑一类 mock。
