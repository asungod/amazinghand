# Smart Hand 双边缘 AI 通信 MVP

当前完整项目交接：
[`../AmazingHand_MaixCAM2_Titan_完整上下文交接_2026-08-11.md`](../AmazingHand_MaixCAM2_Titan_完整上下文交接_2026-08-11.md)。

**今晚宿舍续作交接与防跑偏任务书（2026-08-12）**：
[`../AmazingHand_宿舍续作_Grok_Claude_交接与防跑偏_2026-08-12.md`](../AmazingHand_宿舍续作_Grok_Claude_交接与防跑偏_2026-08-12.md)。

2026 秋季竞赛的评分映射、合规边界、排期和证据模板见
[`competition_2026/README.md`](competition_2026/README.md)。当前建议以 AIC
“AI+硬件创新”为主线；全国 3D 具身智能赛须先取得组委会对开源机械本体二次创新
资格的书面确认。

第一阶段目标是：在不依赖机械手的前提下，让 MaixCAM2 与 Titan Mini 通过 UART
交换结构化消息，并对分包、粘包、乱码、CRC 错误和通信超时保留处理边界。
电脑离线协议与解析已通过。2026-08-14 在 Titan **独立 H1 三针**（不是 40 针 U18）上完成
MaixCAM2 ↔ Titan UART2 **短时双向实物闭环**：ACK 跟随发送，`timeout=0`，
`malformed=0`，`rx_errors=0`。同日第二次 10 分钟无舵机通信/热观察通过
（`sent=2126` / `acked=2126`，约 11 分 49 秒）。2026-08-14 至 2026-08-15，
39/41/65 各 10 秒策略链路观察到正确类别映射，且 `pose=NOT_CONFIGURED` /
`actionable=0`。2026-08-15 又完成真实 YOLO11 瓶子识别、目标移出/恢复、Titan
策略映射和无舵机长稳闭环：序号至少连续到 2770，代表不少于约 15 分 23 秒；
代表性完整统计为 `sent=2748/acked=2748`，所有链路错误计数为 0。电脑端曾出现
USB-RNDIS 重置，限制视觉处理为 20 FPS、预览为 2 FPS 后，检查窗口内未再出现重置。
这仍不是姿态数值、舵机执行或完整单指验收。
两板之间仍禁止连接 VCC；舵机必须保持断开。

**2026-08-14 发热事件（历史，不得删除）**：曾把 40 针电源脚误当 GND 后明显发热。
正确改到 H1 三线交叉后有过 15 秒无发热观察。发热史仍有效；不得写成“必须永久断线”，
也不得写成整机生产联调已通过。

## 当前完成内容

- **电脑离线验证通过**（电脑端所有测试）：
  - 326 个 Python 单元/压力/集成测试全部通过（2026-08-16 当前计数，含四指配置、八舵机规划与整组停机离线模型）。
  - 12 个独立 C 测试程序/目标全部通过（+ **序号防重放 sequence_guard**；含视觉决策状态）。
  - Maix 五个部署文件预检通过，并输出 SHA-256。
  - PC 端 PING/VISION/ACK 正常路径及 CRC 坏帧恢复通过。
  - `smart_hand_protocol.c/.h` 与 `smart_hand_uart.c` 在规范目录和 D 盘 Studio 工程中哈希一致。

- **MaixCAM2 单板真机通过**：
  - 板卡识别为 `maixcam2`。历史探针 `uart4_open_probe.py` 曾打开 **UART4**
    （`A21/A22`、`/dev/ttyS4`）；该文件只作历史打开探针，**不是**当前生产入口。
  - 生产入口已切到前面板 **UART2**：`B0/B1`、`/dev/ttyS2`、115200（见 `main.py`）。
  - `yolo_probe_single_file.py` 已在 MaixVision 运行并显示实时画面和检测输出。
  - 生产 `main.py` 已运行真实 YOLO11 + UART2 + 画面叠加；正式目标限制为
    bottle(39)、cup(41)、remote(65)。当前视觉处理上限 20 FPS、USB/RNDIS 预览 2 FPS，
    用于避免 Windows `Remote NDIS Compatible Device` 在持续预览时重置。
  - 多文件应用必须使用 **Run Project**。

- **PC 端舵机总线通过（空载/总线层）**：
  - 已验证：两颗 SCS0009-C001 的 ID1/ID2、PC 只读通信、散置状态单颗小幅动作、双舵机同步小幅动作和返回；ID1 在已配置下限附近的单向恢复也已通过。两颗最终均 `torque=0`，并已关闭外部 6V。证据见 [`validation_reports/two_servo_loose_bench_acceptance_2026-08-15.md`](validation_reports/two_servo_loose_bench_acceptance_2026-08-15.md)。
  - 已准备但待完整机械机构实测：`center_hold_scs0009_pair.py`（框架归中工具）、`finger_smoke_scs0009.py`（装好连杆后的单指冒烟测试工具）。不得将二者写成已在完整机构上验证。
  - 当前实物状态（用户 2026-08-15 确认）：两颗舵机已经装入指框；舵盘和连杆未安装；
    一根 M2x18 螺纹杆仍在运输中，预计约两天后到货。机械流程在此暂停，不要重复要求装框，
    也不得把此前散置台架测试写成装框后标定通过。
  - 下一阶段必须按 [`docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md`](docs/SINGLE_FINGER_MOUNTED_CALIBRATION_GATE_2026-08-15.md) 分门执行；511 只是电气中点参考，不是机械中心。

- **Titan 烧录与 UART2 短时闭环已验证；整机执行层未验证**：
  - Titan 已通过 pyOCD + WCH-Link 烧录；UART1 控制台可见，固件监听 `uart2`。
  - 2026-08-14：H1 三线交叉、独立供电、不接 VCC；15 秒无发热；短时双向 ACK 成立。
    证据：`validation_reports/uart2_bidirectional_acceptance_2026-08-14.md`。
  - 2026-08-14：10 分钟无舵机 UART2 通信/热观察第二次通过。
    证据：`validation_reports/uart2_10min_no_servo_stress_2026-08-14.md`。
  - 2026-08-14 至 2026-08-15：39/41/65 各 10 秒策略链路，`sent=30/acked=30`，
    错误全 0，`reason=accepted` / `pose=NOT_CONFIGURED` / `actionable=0`。
    证据：`validation_reports/supported_class_mock_2026-08-15.md`。
  - 2026-08-15：真实 YOLO11 瓶子识别、目标丢失/恢复及无舵机长稳闭环通过；
    序号至少到 2770，代表性 `sent=2748/acked=2748`，错误全 0，平均 RTT 28 ms。
    证据：`validation_reports/maixcam2_yolo11_titan_uart2_long_run_2026-08-15.md`。
  - 未验收：真实物理拔线后的完整 OFFLINE 恢复、长期热安全、舵机执行、软限位、生产姿态数值。
  - 软件默认拒绝物理动作的实际原因是：`config/servo_calibration_template.csv` 不完整，且生产 `grip_pose_bank` 姿态未配置。`hardware_accessed=false` 只是离线演练输出的证据标签，不是拒绝动作的根因。

## 目录（2026-08-12 更新）

```text
smart_hand/
├── ACTION_SAFETY_DESIGN.md
├── COMPETITION_PITCH_AND_STORYBOARD.md
├── DEMO_MVP_RUNBOOK.md
├── EXECUTION_STATE_DESIGN.md
├── GRIP_POLICY_MVP.md
├── HARDWARE_WIRING_CARDS.md
├── LAB_BRINGUP_CHECKLIST.md
├── SERVO_CALIBRATION_AND_LOGGING.md
├── TITAN_AI_DATA_PLAN.md
├── TOMORROW_SINGLE_FINGER_RUNBOOK.md
├── docs/
│   ├── TITAN_RUNTIME_INTEGRATION_GAP_AUDIT_2026-08-12.md
│   ├── TITAN_VISION_RUNTIME_INTEGRATION_RESULT_2026-08-12.md
│   ├── TITAN_SEQUENCE_AND_BUILD_RESULT_2026-08-13.md
│   ├── UART2_PIN_EVIDENCE_AUDIT_2026-08-14.md
│   ├── THERMAL_EVENT_RECOVERY_RUNBOOK_2026-08-14.md
│   ├── GROK_AUTHORIZED_OFFLINE_IMPLEMENTATION_BATCH_2026-08-12.md
│   └── GROK_SEQUENCE_FAILSAFE_AND_ARM_BUILD_BATCH_2026-08-13.md
├── config/
│   └── servo_calibration_template.csv          # 空白模板，禁止预填
├── data/
│   ├── grasp_trial_manifest_template.csv
│   └── single_finger_log_template.csv
├── protocol/
│   ├── PROTOCOL.md
│   ├── PROTOCOL_SESSION_DESIGN.md
│   └── SESSION_TEST_VECTORS.json
├── maixcam2/
│   ├── main.py
│   ├── link_monitor.py
│   ├── protocol.py
│   ├── target_tracker.py
│   ├── time_api_probe.py
│   ├── uart4_open_probe.py                    # 历史 UART4 打开探针，非生产入口
│   ├── uart2_loopback_probe_single_file.py    # UART2 回环探针（单文件）
│   ├── vision_source.py
│   ├── yolo_probe.py
│   └── yolo_probe_single_file.py
├── titan_rtthread/                             # 规范源（与 D 盘 Studio 哈希同步）
│   ├── smart_hand_protocol.c/.h
│   ├── smart_hand_uart.c                       # VISION→policy+pose+seq guard；无舵机写包
│   ├── smart_hand_vision_state.c/.h            # 可主机测试的纯状态模块
│   ├── smart_hand_sequence_guard.c/.h          # 16 位序号防重放
│   ├── grip_policy.c/.h
│   ├── grip_pose_bank.c/.h                     # 生产默认未配置
│   ├── scs0009_packet.c/.h
│   ├── scs0009_stream.c/.h
│   ├── scs0009_transaction.c/.h
│   ├── servo_safety_gate.c/.h
│   ├── servo_motion_monitor.c/.h
│   └── servo_feedback_poll.c/.h
├── host/
│   ├── run_all_checks.ps1                      # 统一验收入口
│   ├── run_offline_rehearsal.py
│   ├── run_demo.py
│   ├── no_servo_uart_acceptance.py             # 无舵机 UART 离线场景引擎
│   ├── titan_uart_acceptance.py                # 默认 dry-run 验收器（live 本批禁用）
│   ├── uart_segment_probe.py                   # 分段回环；默认 dry-run，三重门控才开串口
│   ├── titan_uart_acceptance_vectors.json
│   ├── accept_uart_frame.py                    # 兼容入口
│   ├── check_maix_deploy.py
│   ├── check_titan_sync.ps1 / check_titan_resources.ps1 / check_titan_linkage.ps1  # 函数级符号
│   ├── probe_scs0009.py / set_scs0009_id.py / nudge_scs0009.py
│   ├── sync_nudge_scs0009_pair.py / center_hold_scs0009_pair.py / finger_smoke_scs0009.py
│   ├── grip_policy_model.py / action_safety_model.py / execution_state_model.py / servo_safety_model.py
│   ├── replay_vision.py / sweep_vision_params.py / generate_uart_fault_corpus.py
│   └── smart_hand_dashboard.html
├── tests/                                      # 326 个 Python 测试 + 12 个独立 C 测试程序/目标（2026-08-16）
│   ├── test_*.py
│   ├── test_*_c.c + .exe
│   ├── test_single_finger_pipeline_c.c
│   └── test_smart_hand_vision_state_c.c
├── competition_2026/
├── validation_reports/
└── third_party/
```

## 先在电脑验证

在本目录运行：

```powershell
pwsh -File host\run_all_checks.ps1
```

该命令依次运行 Python 单元/压力测试、语法检查、Maix 上板文件预检、无硬件演示、
C 解析器测试和 Titan 双目录源码哈希检查；任一步失败都会返回非零退出码。需要
单独定位时可运行：

```powershell
python -m unittest discover -s tests -v
python host\check_maix_deploy.py --expected-mode mock
python host\run_demo.py
pwsh -File host\check_titan_sync.ps1
```

### 证据时间线（禁止把后一层写成前一层）

| 时间 | 层 | 状态 |
|------|----|------|
| 持续 | 电脑离线协议/测试 | 通过 |
| 2026-08-11 起 | Maix 单板 YOLO / 历史 UART4 打开探针 | 通过；UART4 不是生产入口 |
| 2026-08-11 至 2026-08-15 | PC 舵机总线散置台架 | ID1/ID2 只读、单颗与同步小幅往返通过；装框/连杆未测；与 Titan UART2 无关 |
| 2026-08-14 前 | 误用 40 针电源脚当 GND | 发热；已断开 |
| 2026-08-14 | Titan 烧录 + UART1 控制台 | 已验证 |
| 2026-08-14 | H1 UART2 短时双向闭环 | 已验证（见 validation_reports） |
| 2026-08-14 | 10 分钟无舵机 UART2 通信/热观察 | 第二次通过；第一次约 7m59s FAIL |
| 2026-08-14 至 2026-08-15 | 39/41/65 短时策略链路 | 已观察映射与未配置姿态拒绝；非姿态/舵机验收 |
| 2026-08-15 | 真实 YOLO11 → Titan 长稳闭环 | ≥15m23s；目标丢失/恢复通过；代表性 sent=2748/acked=2748，错误全 0 |
| 未做 | 真实物理拔线后的完整 OFFLINE 恢复 / 长期热安全 | 未验收 |
| 未做 | 机械校准、生产姿态数值、舵机执行 | 未授权 |

### 成熟度区分表（当前状态）
| 成熟度       | 验证方式       | 状态     | 证据/缺口                          |
|--------------|----------------|----------|------------------------------------|
| 电脑离线     | 本地检查.ps1   | 通过     | 267 Python + 12 C；序号防重放与非法 VISION 清目标已测 |
| Maix 单板    | MaixVision     | 通过     | 真实 YOLO11、显示、目标过滤运行；20 FPS 推理调度、2 FPS 预览消除已观察到的 RNDIS 重置 |
| PC 舵机总线  | 电脑工具       | 部分通过 | 已验证 ID/只读/空载小幅与同步；归中与装连杆冒烟待完整机构实测 |
| Titan/整机   | 真机联调       | 部分通过 | 已烧录；H1、真实 YOLO11、目标丢失/恢复及 ≥15m23s 无舵机闭环已验证；物理拔线恢复/姿态数值/舵机未验收 |

### 真正的未完成项短表（禁止把“已有模块”写成“已接入 Titan 真机”）
| 未完成项 | 当前状态 | 证据缺口 |
|----------|----------|----------|
| Titan VISION 决策 + 序号防重放（规范源） | **2026-08-13 离线完成** | 非法 VISION invalidate；dup/old 不刷新；见 `TITAN_SEQUENCE_AND_BUILD_RESULT_2026-08-13.md` |
| Studio ARM 链接新 .c | 源已复制到 `src/` | headless 构建超时；**需人工 Refresh/Clean/Build** + `check_titan_linkage.ps1` |
| 舵机软限位与方向 | 模板空白 | 真实机械实测后才能填写，软件默认拒绝物理动作 |
| Maix ↔ Titan 实物 UART | H1 短时、10 分钟无舵机及 2026-08-15 真实 YOLO11 ≥15m23s 闭环已验证 | 真实物理拔线后的完整 OFFLINE 恢复、长期热安全未做 |
| 支持类别策略映射 | 2026-08-15 归档 39/41/65 短时窗口 | 只证明映射与 `NOT_CONFIGURED` 拒绝；非姿态验收 |
| 真实抓握姿态 / 舵机执行层 | 姿态库默认全未配置；无 SCS0009 写包路径 | 不得猜测角度；本批明确不实现执行层 |
| Titan NPU / 双 AI | 仅路线图 | 不得写成已部署 |

当前 Python 测试还覆盖视觉处理/发送独立调度、3 帧稳定后限频发送、短暂
遮挡与超时失效、单调时钟回绕、非法视觉载荷，以及实际 `main()` 在 mock、无目标、
视觉初始化失败和 UART 瞬时读错后的帧输出。加速耐久测试模拟 10 分钟、60001 次
主循环，核对 601 个 PING、1200 个 VISION 和 1801 个连续序号；这不是实物耐久结论。

`run_demo.py` 会模拟 MaixCAM2 发送 `PING` 和 `VISION`，Titan 端解析后返回
`ACK`，同时故意插入一个损坏帧，验证 CRC 拒收和下一帧自动恢复。
`check_maix_deploy.py` 只读检查五个必传 Maix 文件、局部导入、UART2（`/dev/ttyS2`）配置和参数
范围，并输出文件 SHA-256；使用 `--expected-mode mock` 或 `yolo11` 可防止上传错
运行模式。
`check_titan_sync.ps1` 只读计算规范源与 D 盘 RT-Thread Studio 工程中三份 Titan 源码的
SHA-256；任一文件缺失或内容不同都会返回失败，不会自动覆盖文件。

## 离线视觉回放

无需摄像头即可把带时间戳的检测结果送入实际目标跟踪和发送调度逻辑：

```powershell
python host\replay_vision.py host\vision_replay_example.csv
python host\replay_vision.py host\vision_replay_example.csv `
  --stable-frames 2 --stale-timeout-ms 500 --match-iou 0.3 --send-interval-ms 250
```

CSV 列为 `time_ms,class_id,center_x,center_y,width,height,confidence`；无目标行的
`class_id` 写 `NONE`。工具输出目标 acquired/switch/lost、会发送的 VISION 和最终
统计，可在拿到真机检测日志后比较不同参数，不会连接 Maix 或 Titan。

真机采集时把 `yolo_probe.py` 的 `PRINT_REPLAY_ROWS` 临时设为 `True`，保存完整
MaixVision 控制台文本，例如 `maix_probe.log`，然后运行：

```powershell
python host\replay_vision.py maix_probe.log --probe-log
```

回放工具会忽略普通探针输出，只提取 `REPLAY,` 行。逐帧打印会占用控制台时间，
所以测量真实推理 FPS 时必须保持 `PRINT_REPLAY_ROWS=False`；性能记录和回放采集应
分成两次运行。

同一份 CSV 或探针日志可批量比较参数组合并输出 CSV 指标：

```powershell
python host\sweep_vision_params.py host\vision_replay_example.csv `
  --stable-frames 2,3,4 --stale-timeout-ms 500,750,1000 `
  --match-iou 0.1,0.2,0.3 --send-interval-ms 250,500
```

输出包括首次获取/发送时间、acquired/switches/lost、发送数和最终 active 状态。工具
不自动推荐参数，避免用单一指标掩盖获取速度与误切换之间的权衡。

## 故障语料与本地归档

`host/uart_fault_corpus.json` 包含 10 组已由生产解析器自校验的分片、粘包、CRC、
噪声、截断、超长输入、未知类型和边界值语料。重新生成并验证：

```powershell
python host\generate_uart_fault_corpus.py --output host\uart_fault_corpus.json
```

当前语料仅用于电脑解析器；有 USB-TTL 后仍需受控的串口发送工具和实物验收，不能
把生成成功视为电气链路测试。

生成带时间戳的本地验证报告：

```powershell
python host\create_validation_report.py
```

脚本重新执行全部检查，并在 `validation_reports` 下保存输出、Maix/Titan/Studio
SHA-256 和环境信息。它不调用 Git 或网络；检查失败时仍保存报告并返回非零状态。

现有 Titan Debug ELF/MAP 的只读资源审计见
[`validation_reports/titan_resource_baseline_2026-08-11.md`](validation_reports/titan_resource_baseline_2026-08-11.md)。
当前基线约占 119.84 KiB FLASH；GNU 静态 RAM 口径约 134.04 KiB，其中 128 KiB
是 FSP 主栈。BSP 分区文件确认 CPU0 有 1,488 KiB RAM，但 RT-Thread 通用
`board.h` 仍只把前 512 KiB 纳入系统堆，导致 976 KiB CPU0 RAM 未利用。首次上板
保持已构建基线，取得 `free`、`ps` 和线程栈水位后再单独修正并验证堆边界。

Studio 每次重建后可重复执行同一套只读检查：

```powershell
pwsh -File host\check_titan_resources.ps1
pwsh -File host\check_titan_resources.ps1 `
  -MaxFlashBytes 131072 -MaxStaticRamBytes 147456
```

第一条打印 ELF/MAP 哈希、FLASH/静态 RAM、系统堆区间、CPU0/共享内存分区和 Smart
Hand 关键符号。当前 `board.h` 少用 976 KiB CPU0 RAM，因此默认显示 warning 但仍
成功；指定 `-FailOnWarnings` 可让 warning 返回非零。阈值只用于发现意外增长，不是
真机内存安全证明。

## Session 协议草案

[`protocol/PROTOCOL_SESSION_DESIGN.md`](protocol/PROTOCOL_SESSION_DESIGN.md) 提出
未来 `HELLO(BOOT_ID,VERSION,CAPABILITIES)` 会话重置，并配有 JSON 测试向量和主机
参考模型。当前协议仍是 v1，Python/C 解析器都没有加入 HELLO，必须等首次真机基线
通过后再决定是否两端同时升级。

## 动作安全参考模型

[`ACTION_SAFETY_DESIGN.md`](ACTION_SAFETY_DESIGN.md) 和
`host/action_safety_model.py` 定义了未来 Titan 动作层的主机参考安全门，覆盖默认
禁止、显式 arm、目标新鲜度、断联停止请求、故障锁存和序号回绕。它没有接入 Titan
C 固件，也没有决定真实舵机的安全停止方式；在完成当前通信基线上板前不要移植。

## 三类物体抓握策略

[`GRIP_POLICY_MVP.md`](GRIP_POLICY_MVP.md) 固定首版演示只识别 bottle(39)、
cup(41) 和 remote(65)，分别产生圆柱、包络和精细抓握意图；其余类别、置信度低于
70 或非法输入均为 `NO_ACTION`。Titan 运行时已含该策略；2026-08-15 归档的
无舵机短时窗口观察到三类正确映射，并因姿态未配置保持 `actionable=0`。
`host/grip_policy_model.py` 仍是电脑端参考实现，不含任何舵机位置。

## 演示和 Titan 第二级 AI 路线

[`DEMO_MVP_RUNBOOK.md`](DEMO_MVP_RUNBOOK.md) 把固定底座、人工放入抓取区域、明确
动作授权和 90 秒评委演示流程写成分阶段门槛；未通过通信、真实视觉和单指安全验证
时不得跳到整手动作。

电脑端可直接打开 `host/smart_hand_dashboard.html`。页面可模拟瓶子/杯子/遥控器、
低置信度、目标消失、UART断联和受阻故障，并要求显式 ARM 才能进入模拟闭合；页面
醒目标注“模拟/回放、不驱动舵机”和“Titan NPU尚未部署”。它目前没有串口后端，
不能作为真机闭环证据。

[`EXECUTION_STATE_DESIGN.md`](EXECUTION_STATE_DESIGN.md) 与
`host/execution_state_model.py` 固定了未来 Titan 执行层的
`DISARMED/READY/CLOSING/HOLDING/RELEASING/FAULT` 参考转换。它仍是电脑模型，没有
加入 D 盘 RT-Thread 工程。

[`COMPETITION_PITCH_AND_STORYBOARD.md`](COMPETITION_PITCH_AND_STORYBOARD.md) 包含
90秒讲解词、三个演示场景、拍摄分镜和能力表述边界；
[`HARDWARE_WIRING_CARDS.md`](HARDWARE_WIRING_CARDS.md) 汇总J-Link、UART1、两板
UART2和单指舵机供电四张到货接线核对卡。

[`TITAN_AI_DATA_PLAN.md`](TITAN_AI_DATA_PLAN.md) 定义未来使用视觉语义与 SCS0009
位置/负载等反馈进行执行状态识别的数据边界。当前没有真机数据或 Titan NPU 模型，
因此只保留采集、标签、训练和回退方案，不生成合成精度或伪造模型结果。

[`SERVO_CALIBRATION_AND_LOGGING.md`](SERVO_CALIBRATION_AND_LOGGING.md) 把单指两舵机
到货后的逐只识别、机械软限位校准、低风险联动和数据记录写成可执行流程；`config`
和 `data` 下的三个 CSV 只是空白模板，不包含任何假定的 ID、角度、负载或阈值。
首次通信上板基线通过前不要把该流程误当成已经实现的 Titan 舵机驱动。
采集真实 CSV 后可运行 `host/analyze_servo_log.py` 生成原始寄存器摘要和 HTML 曲线；
工具会拒绝时间倒退、样本序号重复和读取失败却填入反馈值的数据。

若电脑已安装 GCC，还可以验证 Titan 使用的 C 解析器与 Python 端完全一致：

```powershell
gcc -std=c99 -Wall -Wextra -Werror `
  -Ititan_rtthread `
  tests\test_protocol_c.c titan_rtthread\smart_hand_protocol.c `
  -o tests\test_protocol_c.exe
tests\test_protocol_c.exe
```

部分 Windows 环境会对 OneDrive 目录中的新 EXE 进行长时间扫描；遇到编译链接
卡住时，至少先使用 `gcc ... -fsyntax-only` 做语法检查，或把输出 EXE 放到本地
非同步目录。

## MaixCAM2 上板

当前生产入口是前面板 **UART2**（以 `main.py` 为准）：

- B0：UART2_TX（项目文档亦写 U2T；官方丝印对应见 `docs/UART2_PIN_EVIDENCE_AUDIT_2026-08-14.md`）
- B1：UART2_RX（项目文档亦写 U2R）
- 设备：`/dev/ttyS2`
- 波特率：115200

历史探针 `uart4_open_probe.py` 使用 A21/A22、`/dev/ttyS4`。保留该文件，但不要把它
重新写成生产链路。

首次运行新版 `main.py` 前，先单独运行 `time_api_probe.py`。预期最后输出
`TIME API PROBE OK`；该步骤用于真机确认单调时钟 API，不应以电脑端语法检查
代替。2026-08-11真机已确认MaixPy `ticks_diff`的参数顺序为“先旧值、后新值”，
该行为与常见MicroPython写法不同；探针、主程序、YOLO探针和推理耗时统计已统一修正。

把 `maixcam2/main.py`、`maixcam2/link_monitor.py`、`maixcam2/protocol.py`、
`maixcam2/target_tracker.py` 和 `maixcam2/vision_source.py` 放到同一应用目录后运行。

`main.py` 默认 `VISION_MODE = "mock"`，用于先隔离验证 UART。Maix 单板可以运行
`yolo_probe.py` 验证摄像头、默认 `/root/models/yolo11n.mud` 模型和目标转换；该
路径按官方 `nn.YOLO11` API 编写，要求 MaixPy 4.7.0 或更高。探针成功后再把
`VISION_MODE` 改为 `"yolo11"`。`YOLO_ALLOWED_CLASS_IDS=None` 表示允许全部 COCO
类别，也可配置为元组，例如 `(39, 41, 47, 49, 65)` 对应 bottle、cup、apple、
orange、remote。探针默认在板载屏幕画检测框、类别和置信度；显示初始化失败时仍
保留控制台结果，也可将 `SHOW_PREVIEW=False` 关闭预览。

MaixVision 的 `Run File` 只上传当前文件，不会带上 `vision_source.py`。采用这个
按钮时直接运行无本地依赖的 `yolo_probe_single_file.py`；模块化 `yolo_probe.py`
留给完整应用部署。单文件版只是实验室探针，正式检测策略仍以 `vision_source.py`
为规范源，后续不要只修改探针副本。

YOLO 模式选择置信度最高的合法检测；同置信度时先选择更靠近画面中心的框，再按
面积选择。部分越界框会裁剪，完全越界或非法框会丢弃。视觉推理与 UART 发送已经
解耦：默认尽可能连续推理，但稳定目标最多每 500ms 发送一次。新目标或目标切换需
连续 3 帧满足同类别且 IoU 不低于 0.2；短暂漏检期间保留当前目标，超过 750ms 未
再次观察到才失效。没有稳定目标时不发送伪造的 `VISION`，但 PING 仍保持视觉链路
在线。

上述跟踪逻辑已通过电脑端测试，但摄像头吞吐、实际 IoU 抖动和 750ms 参数是否适合
真实场景仍需 MaixCAM2 验证。Maix 端过期控制也不能替代 Titan 未来动作层自己的
目标时间戳/新鲜度门槛，不能重复执行 Titan 中保存的旧目标。

PING、视觉处理和 VISION 发送使用单调毫秒时钟调度，不依赖主循环次数；程序每
5 秒输出 UART 接收错误、发送失败、ACK 成功/拒绝/异常、格式错误、超时、连续
超时、待确认数量和 ACK 往返时间。连续接收或视觉读取异常只在首次及每 100 次
打印错误，避免日志反过来阻塞主循环。YOLO 模式还输出推理最近/平均/最大耗时、估算 FPS，以及
目标 acquired/updated/switches/lost、候选连续帧数和当前 active 状态。

首次上板和两板联调按 [`LAB_BRINGUP_CHECKLIST.md`](LAB_BRINGUP_CHECKLIST.md)
逐项执行。该检查表明确区分已由电脑测试验证的逻辑和仍需真机确认的接口行为。

## Titan Mini 上板

1. 在 RT-Thread Studio 打开现有工作空间 `D:\Micu\RTTWorkspace`。
2. 运行 `host\check_titan_sync.ps1`，确认规范源与工程 `src` 中三份源码一致。
3. 选择现有工程 `titan_uart_test`，确认控制台使用 `uart1`、通信使用 `uart2`。
4. 完整构建并下载，终端应看到 `smart_hand: listening on uart2 at 115200`。

可在 msh 中执行 `list_device` 确认 `uart2`，执行 `sh_status` 查看有效帧、
CRC/格式错误、序号跳变、重复帧、发送失败和离线次数。

## 硬件连接

Titan 侧只用 **H1 独立三针**，不要用 40 针 U18：

```text
MaixCAM2 B0 / UART2_TX -> Titan H1 pin 2 / RXD2 / P802
MaixCAM2 B1 / UART2_RX <- Titan H1 pin 3 / TXD2 / P801
MaixCAM2 GND           -> Titan H1 pin 1 / GND
```

两块板分别通过各自 USB 供电。不要连接两块板的 5V/VBUS/3V3。接线前确认
H1 实物 pin1 标记。2026-08-14 该接法已完成短时双向闭环；长期互连仍未验收。

## 验收标准

- 连续 10 分钟收发，无解析错误和序号异常。
- 任意拆分 UART 字节流仍能还原完整帧。
- CRC 错误帧被丢弃，下一帧能自动恢复。
- MaixCAM2 断联后，Titan 约 1.5 秒进入 `VISION_OFFLINE`。
- 恢复通信后链路自动回到 `ONLINE`，不要求重启。

## 参考

- MaixPy 当前文档入口：<https://wiki.sipeed.com/maixpy/doc/zh/index.html>
- MaixPy YOLO 物体检测：<https://wiki.sipeed.com/maixpy/doc/zh/vision/yolov5.html>
- Titan Mini BSP：<https://github.com/RT-Thread-Studio/sdk-bsp-ra8p1-titan-mini>
- RT-Thread UART：<https://www.rt-thread.io/document/site/programming-manual/device/uart/uart/>

## SCS0009 电脑端真机工具

2026-08-11 已使用 Waveshare Bus Servo Adapter (A) V1.1 在 `COM4`、1Mbps、6.0V
条件下完成两颗 SCS0009-C001 的真机验证。第一颗为ID1，第二颗已从默认ID1改为
ID2；并联Ping、状态读取、单颗小幅动作以及双舵机同步小幅动作/回位均通过。

- `host/probe_scs0009.py`：只读发现和状态读取，不写寄存器；
- `host/set_scs0009_id.py`：仅在单独连接一颗舵机时改ID并读回验证；
- `host/nudge_scs0009.py`：单颗空载小幅动作、自动回位和释放力矩；
- `host/sync_nudge_scs0009_pair.py`：ID1/ID2同步小幅动作和回位。
- `host/center_hold_scs0009_pair.py`：舵机固定进框架、尚未装舵盘时，依次低速移动到
  原始位置511（仅为电气中点参考，不是机械中心）并保持，供安装舵盘；必须显式确认框架已经固定；
- `host/finger_smoke_scs0009.py`：完整机构手动确认无卡滞后，必须显式传入两颗舵机各自
  的实测安全机械参考值，再执行±12原始计数的小幅闭合/张开测试。

总线舵机使用1,000,000 baud；不要与 MaixCAM2-Titan 链路的115200混淆。SCS0009
使用6.0V，转接板上的9-12.6V丝印不是该舵机的供电要求。单颗与双颗只读可从1.0A限流
开始；任何双舵机移动/保持/机构测试前先关闭输出，再设为2.0A。绿色端子与DC圆孔只能
选择一个外部舵机电源入口，Type-C只负责电脑数据/控制。运动、保持、校准期间任一舵机
达到50°C立即关闭6V。PC校准脚本不经过Titan生产`ServoCommandGate`。

官方装配顺序是：断电固定两颗舵机（不装舵盘）→ 检查ID2左/ID1右及输出轴方向 →
通电依次置中并保持 → 安装舵盘 → 断电安装连杆 → 手动检查无卡滞 → 小幅冒烟测试。
不要在舵机仍松散放置时运行置中保持，也不要在软限位未知时直接尝试全行程。

`host/servo_safety_model.py` 是后续移植到 Titan 动作层前的电脑参考边界：只有两行完整
校准、两颗舵机的新鲜有效反馈、供电/温度正常、目标位于软限位内且单步不超过
`max_step_raw` 时才返回可下发目标。它还使用 `direction_sign` 将统一的逻辑偏移转换为
各舵机原始方向。总线写失败会撤销使能并锁存故障；该文件本身不访问串口或转动舵机。

`titan_rtthread/scs0009_packet.c/.h` 是与RT-Thread UART无关的SCS0009 C协议核心，当前
只构造Ping、读取、力矩、单颗位置和双颗同步位置包，并校验/解析状态包。其归中和力矩
指令字节已与微雪官方Python SDK逐字节交叉核对，电脑端C测试通过。它尚未加入D盘Titan
Studio工程，也没有选择舵机UART、半双工收发方向或超时参数；UART2仍保留给MaixCAM2，
不得直接把这个协议核心误认为已完成Titan舵机驱动。

`titan_rtthread/scs0009_stream.c/.h` 在协议核心之上提供逐字节状态包接收器，可处理UART
分段、前导噪声、连续`FF`、坏长度、错误ID、错误校验和，以及坏包后紧接正确包的恢复；
外部事务超时时调用reset即可丢弃半包。它不负责UART中断、收发方向切换和超时计时，
这些仍须在Titan选定舵机UART并完成实板电气验证后接入。

`titan_rtthread/scs0009_transaction.c/.h` 限制同一总线只有一个等待响应的单播事务，
使用32位毫秒计时并正确处理回绕；坏包在截止时间前可以恢复，超时、舵机错误和人工
中止分别进入明确状态。写位置超时不会自动重发，避免无法判断首次写入是否已经执行时
产生重复动作。同步广播写本身无响应，因此必须通过后续单播读取验证。

`titan_rtthread/servo_motion_monitor.c/.h` 专门处理同步广播后的到位验证：ID1和ID2都必须
在本次动作开始后读回，且两者均进入目标容差才算完成；缺一颗、读失败、舵机错误或
超时均不能宣布成功。容差和动作超时当前只是调用参数，须由单指实测后填写。

`titan_rtthread/grip_policy.c/.h` 将电脑参考策略等价翻译为C：COCO 39瓶子对应圆柱抓握、
41杯子对应包络抓握、65遥控器对应精细抓握；默认置信度门槛70。非法视觉载荷、低置信度
和其他类别只能返回`NO_ACTION`。该模块只产生意图，不包含任何舵机位置；机械校准完成
前不得给三种意图填入臆测角度。现有Studio工程中的`grip=`输出仍只是旧诊断文本，尚未
替换或接入这个新模块。

`titan_rtthread/grip_pose_bank.c/.h` 是意图与舵机安全门之间的显式配置闸门。初始化后
三种姿态均为“未配置”，即使识别结果已接受也不能生成逻辑舵机目标；只有机械校准后
明确写入某一姿态的两颗舵机逻辑偏移，且ID合法唯一，才交给`servo_safety_gate`继续
检查。测试中的偏移仅为隔离验证数据，生产姿态库仍保持空白。

`titan_rtthread/servo_feedback_poll.c/.h` 提供不阻塞调用者的两舵机轮询状态机：每颗只用
一次连续寄存器读取取得位置、速度、负载、电压和温度原始值，ID1事务结束后再处理ID2。
读取失败或超时会把该颗`read_ok`清零并将数据年龄设为无效，不用旧值冒充新反馈；完整
原始遥测供日志使用，位置/电压/温度子集供安全门使用。轮询周期和响应超时仍需实板测量。

`tests/test_single_finger_pipeline_c.c` 把视觉策略、空姿态闸门、舵机安全门、同步包编码和
双舵机到位监测串成端到端仿真。正常启动因姿态未校准而不产生指令；测试专用参数只用
于证明完整路径；过期反馈和单颗反馈缺失均失败。明天的实物顺序见
[`TOMORROW_SINGLE_FINGER_RUNBOOK.md`](TOMORROW_SINGLE_FINGER_RUNBOOK.md)。

停电或无实物时可运行 `python host/run_offline_rehearsal.py`。该入口复用正式视觉回放、
抓取策略、执行状态机和UART故障语料，验证支持/不支持目标、保持阶段断链安全停止以及
10种串口异常恢复；它还要求空白校准表继续拒绝物理动作。输出中的
`hardware_accessed=false` 是边界声明，不得把离线通过描述成舵机或Titan真机通过。
