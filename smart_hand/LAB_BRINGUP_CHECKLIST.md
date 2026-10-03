# MaixCAM2 - Titan Mini 实验室上板检查表

适用范围：验证 Titan 固件下载、UART1 控制台、MaixCAM2 摄像头/YOLO11，以及
MaixCAM2 **UART2**（`/dev/ttyS2`，B0/B1）与 Titan **H1/uart2** 的结构化消息链路。
历史文件 `uart4_open_probe.py` 只用于曾经的 UART4 打开探针，不是本检查表的生产链路。
本文不包含舵机、机械动作或 Titan NPU。

**2026-08-15 状态**：UART2 短时实物闭环已验证（H1 三线交叉、不接 VCC；
`sent=104/acked=104`，`timeout=malformed=rx_errors=0`；15 秒无发热）。
10 分钟无舵机通信/热观察第二次通过（`sent=2126/acked=2126`，约 11 分 49 秒）。
39/41/65 各 10 秒策略链路已观察：`sent=30/acked=30`，错误全 0，
`reason=accepted` / `pose=NOT_CONFIGURED` / `actionable=0`。
未验收：断联恢复、长期热安全、姿态数值、舵机。正确接口是独立 H1，**不是** 40 针 U18。
证据：`validation_reports/uart2_10min_no_servo_stress_2026-08-14.md`，
`validation_reports/supported_class_mock_2026-08-15.md`。

**硬边界（2026-08-14）**：当前通信固件**没有舵机写包能力**。
**不要连接舵机总线，不要打开 6 V 舵机电源**。禁止两板 3V3/5V 互连。
本检查表下列“无舵机联调”步骤仅准备、不默认执行烧录；烧录需 Codex/人工明确批准后进行。

## 0. 首次无舵机实物联调准备卡（只准备，不默认执行）

1. Titan 仅 USB 和/或 J-Link 供电；**舵机 6 V 保持关闭且物理不连接**。
2. Maix 与 Titan 仅交叉 TX/RX/GND；**禁止连接双方 5V/VBUS**。
3. Studio Refresh → Clean → Build 通过后，再考虑烧录；烧录后看 shell，运行
   `list_device`、`sh_status`。
4. Maix 先用 `VISION_MODE="mock"`，禁止一开始用不稳定 YOLO。
5. 验证 PING 在线；三类 VISION（39/41/65）action 映射正确；空 pose 时
   `actionable=0`。
6. 验证重复/旧 VISION 出现 `ignored_duplicate` / `ignored_old`，且不刷新视觉年龄。
7. 停止 Maix VISION 但保留 PING，约 750 ms 出现 `VISION_STALE`。
8. 完全断开 TX，约 1500 ms 出现 OFFLINE，并 reset 序号基线。
9. 恢复后确认序号可重新建立 FIRST，但不会自动产生动作（pose 仍未配置）。
10. 保存未剪辑终端、接线照片、固件/MAP 哈希、时间和操作人。

联调前在电脑运行：

```powershell
pwsh -File smart_hand\host\run_all_checks.ps1
pwsh -File smart_hand\host\check_titan_sync.ps1
pwsh -File smart_hand\host\check_titan_linkage.ps1   # 需 Studio Build 后的新 MAP
```

`check_titan_sync` 哈希一致 **不等于** 已链接进 ARM 固件。

## 1. 准备物品

- Titan Mini、MaixCAM2 和两根各自供电的 USB 线。
- J-Link 与匹配的 20pin 2.54mm 转 10pin 1.27mm Cortex 转接件。
- 3.3V 逻辑 USB-TTL 和三根串口线。
- MaixCAM2 到 Titan H1 的三根连接线。
- RT-Thread Studio 工作空间：`D:\Micu\RTTWorkspace`。
- Titan 工程：`D:\Micu\RTTWorkspace\titan_uart_test`。

开始前确认 `smart_hand/titan_rtthread` 与 Studio `src` 中 UART 运行时依赖文件
（协议、uart、vision_state、sequence_guard、grip_policy、grip_pose_bank、
servo_safety_gate.h）哈希一致：`pwsh -File host\check_titan_sync.ps1`。

出发前可在 `smart_hand` 目录运行 `python host\create_validation_report.py`，保存本次
60 项测试、Maix 文件和两份 Titan 源码的本地哈希报告。该报告不替代现场结果。
现有 Debug ELF/MAP 的静态资源基线见
`validation_reports/titan_resource_baseline_2026-08-11.md`；它不能替代上板后的堆和
线程栈水位。

## 2. 只验证 Titan

### 断电接线

先核对 J-Link 转接板和 Titan 调试接口的 pin 1。方向不确定时停止，不要试插试烧。

UART1 控制台使用 3.3V USB-TTL：

```text
Titan 40pin pin 8  TXD1 -> USB-TTL RX
Titan 40pin pin 10 RXD1 <- USB-TTL TX
Titan 40pin pin 6  GND  -> USB-TTL GND
```

不要连接 USB-TTL 的 VCC、5V 或 3.3V 供电脚。Titan 使用自己的 USB 供电。

### 构建与下载

1. 在 RT-Thread Studio 打开 `D:\Micu\RTTWorkspace`。
2. 选择 `titan_uart_test` 并执行完整构建，要求 `0 errors`。
3. 使用 Titan BSP 工程自带或明确匹配 RA8P1 的 J-Link 配置下载，不能猜相近芯片。
4. 打开 UART1 串口终端：115200 baud、8 数据位、无校验、1 停止位。
5. 复位 Titan。

正常启动应包含类似：

```text
smart_hand: listening on uart2 at 115200 (policy+seq guard; poses unconfigured; no servo write)
```

在 msh 中执行：

```text
list_device
free
ps
sh_status
```

`list_device` 应出现 `uart1` 和 `uart2`。尚未连接 Maix 时，`sh_status` 应显示
`link=OFFLINE`，帧计数为 0 或初始值。保存 `free` 的堆 total/used/max/available，
并在 `ps` 中确认存在 `sh_uart`、栈大小为 2048 B；此时的 `max used` 只是启动基线。

### Titan 启动失败分支

- 没有任何控制台输出：先检查 USB-TTL 是否为 3.3V、TX/RX 是否交叉、GND
  是否连接和串口参数，不要先改通信代码。
- 出现 `device uart2 not found`：运行 `list_device`，再检查工程中的
  `BSP_USING_UART2`；不要把链路改到占用控制台的 `uart1`。
- J-Link 无法识别目标：断电检查 VTref、GND、SWD/JTAG 信号和 pin 1 方向。
- 通信线程未启动但系统 shell 正常：保存完整启动日志和 `list_device` 输出。

## 3. 连接 MaixCAM2 与 Titan UART2

只使用 Titan **独立 H1 三针**。不要使用 40 针 U18 上的任何电源脚当 GND。

两板断电后连接：

```text
MaixCAM2 U2T / B0 / UART2_TX -> Titan H1 pin 2 / RXD2
MaixCAM2 U2R / B1 / UART2_RX <- Titan H1 pin 3 / TXD2
MaixCAM2 GND             -> Titan H1 pin 1 / GND
```

两板分别通过自己的 USB 供电。只连接 TX、RX、GND，不连接 5V/VBUS。先确认 H1
pin 1 的实物方向，不要按线色推断。2026-08-14 已在该接法下完成短时双向 ACK；
10 分钟与断联恢复仍按下面 §4–§5 执行，不得用短时统计勾掉。

上传 Maix 文件前，在电脑的 `smart_hand` 目录运行：

```powershell
python host\check_maix_deploy.py --expected-mode mock
```

要求最后显示 `MAIX DEPLOY PREFLIGHT PASSED`，再把它列出的五个文件放入
MaixVision 的同一应用目录：

```text
maixcam2/main.py
maixcam2/protocol.py
maixcam2/link_monitor.py
maixcam2/target_tracker.py
maixcam2/vision_source.py
```

先保持 `main.py` 中 `VISION_MODE = "mock"`，启动 Titan 并保持 UART1 控制台可见，
再运行 Maix 的 `main.py`。

## 4. 正常链路验收

Titan 预期输出（mock 默认 class 可能为演示值；策略日志不再使用旧 POWER_GRASP 笼统诊断）：

```text
smart_hand: vision link ONLINE
VISION seq=... class=... conf=... action=... reason=... pose=NOT_CONFIGURED actionable=0
```

生产姿态未配置时 **actionable 必须为 0**。bottle/cup/remote 的 action 应分别为
`CYLINDRICAL_GRASP` / `POWER_GRASP` / `PRECISION_GRASP`（若 Maix 发送对应 class）。

MaixVision 预期持续收到 `status=0` 的 ACK，并每 5 秒输出：

```text
link stats: sent=... tx_fail=0 acked=... rejected=0 unexpected=0 malformed=0 timeout=0 consecutive_timeout=0 max_consecutive_timeout=0 pending=... rtt_last_ms=... rtt_avg_ms=... rtt_max_ms=...
uart stats: rx_errors=0
```

首次统计可能暂时显示少量 `pending`，因为发送和 ACK 接收不是同一时刻。稳定后：

- `sent`、`acked` 持续增加；
- `uart stats` 中 `rx_errors` 保持为 0；
- `tx_fail`、`rejected`、`unexpected`、`malformed`、`timeout` 保持为 0；
- `pending` 通常为 0，发送后短暂为 1 或 2 可以接受；
- Titan 的 `invalid`、`payload`、`tx_fail` 不持续增加；
- `gaps` 和 `duplicates` 不持续增加。

连续运行至少 10 分钟，并保存开始与结束时的 Maix `link stats`、`uart stats`，以及
Titan 的 `free`、`ps`、`sh_status` 输出。重点比较 `sh_uart` 的 `max used` 和系统堆
最大使用量；若栈余量低于 25% 或峰值持续增长，先停止扩展功能并分析调用深度/动态
分配。

## 5. 断联、视觉过期、序号与恢复验收

保持两板供电。**全程不接舵机 6 V。** 不要带电移动 5V/VBUS 或供电线。

### 5.1 仅停 VISION、保留 PING

- 约 750 ms 后 Titan 应出现 `VISION_STALE; cleared candidate/actionable`。
- `sh_status` 中 vision present 应变为 0；link 可仍为 ONLINE（PING 维持）。
- PING **不得**刷新视觉年龄。

### 5.2 重复/旧序号

- 重放同一 VISION 序号：日志 `ignored_duplicate`，不更新 vision age / actionable。
- 旧序号：`ignored_old`，同样不刷新业务状态；ACK 仍可为 0（幂等忽略）。

### 5.3 完全断联

- 停止 Maix 或断开 Maix TX→Titan RX。
- Titan 约 1.5 秒后 OFFLINE，清视觉，并 **reset 序号基线**。
- Maix 若仍在运行但收不到 ACK，`timeout` 和 `consecutive_timeout` 增加。
- 恢复后可重新接受 FIRST 序号并 ONLINE，**不会**因空 pose 自动产生动作。
- 收到匹配 ACK 后，Maix 的 `consecutive_timeout` 回到 0；累计 `timeout` 保留。

恢复后再次执行 `free`、`ps`、`sh_status`，确认有效帧继续增长、没有持续解析错误，
堆和 `sh_uart` 栈峰值没有异常增长；记录 sequence have_last / last_accepted /
gaps / duplicates / old。

## 6. MaixCAM2 单板 YOLO11 验收

基础 UART 和断联恢复全部通过后，MaixCAM2 可断开 Titan 单独验证视觉：
电脑端测试已覆盖处理/发送调度、时钟回绕、短暂遮挡、超时失效和非法载荷拒绝，
但这些测试不包含真实摄像头阻塞时间和 MaixPy 调度开销，仍需执行以下步骤。

1. 确认 MaixPy 版本不低于 4.7.0，默认模型 `/root/models/yolo11n.mud` 可用。
2. 将 `vision_source.py` 与 `yolo_probe.py` 放在 MaixVision 同一应用目录。
3. 运行 `yolo_probe.py`，依次用有目标和无目标画面测试。
4. 有目标时屏幕应显示检测框/类别/置信度，控制台打印 `class/center/size/confidence`；无目标时应打印 `target: NONE`。
5. 完全在画面外或低于 0.5 置信度的目标不应生成 VISION 载荷。
6. 保持 `PRINT_REPLAY_ROWS=False`，记录控制台周期输出的单次推理耗时和估算 FPS；数值应持续更新，不能把电脑端假模块结果当作板上性能。
7. 需要离线调参时另开一次测试，把 `PRINT_REPLAY_ROWS=True` 并保存完整控制台日志；逐帧打印会影响 FPS，不能用这次运行作为性能数据。
8. 回到电脑后运行 `python host\replay_vision.py <日志文件> --probe-log`，确认能提取 acquired/switch/lost 和 VISION 时间线。

默认允许全部 COCO 类别。若只演示常见可抓物体，可把 `ALLOWED_CLASS_IDS` 设为
`(39, 41, 47, 49, 65)`，分别代表 bottle、cup、apple、orange、remote。

单板探针稳定后，把 `main.py`、`protocol.py`、`link_monitor.py`、
`target_tracker.py` 和 `vision_source.py` 放在同一目录，才将 `VISION_MODE` 改为
`"yolo11"` 并恢复两板连接。默认推理尽可能连续运行，稳定目标最多每 500ms 发送
一次，不应把 UART 发送周期误认为推理帧率。

若在电脑规范源中切换模式，上传前运行
`python host\check_maix_deploy.py --expected-mode yolo11`，确认实际文件与预期一致。

观察每 5 秒的 `vision stats` 和 `target stats`，并完成三条真机场景：

- 固定目标连续出现至少 3 帧后，`acquired` 增加并开始发送 VISION；
- 短暂遮挡少于 750ms 时目标仍可保留，持续遮挡超过 750ms 后 `lost` 增加且停止发送 VISION；
- 换成不同类别或明显不同位置的目标，连续稳定至少 3 帧后 `switches` 增加。

匹配条件默认为同类别且 IoU 不低于 0.2。实机记录推理最近/平均/最大耗时和估算
FPS，若 3 帧稳定时间过长或目标频繁丢失，先保留日志再调整参数。无目标时 Maix
只发送 PING，因此 Titan 链路保持 ONLINE，但不会收到新的 VISION。Titan 当前仍会
保存最后一次视觉诊断值；Maix 的 750ms 失效处理不能替代未来舵机动作层自己的
目标新鲜度判断。

## 7. 暂停条件

出现以下任一情况时停止继续接线或扩展功能，保留日志后排查：

- 接口或转接板 pin 1 方向无法确认；
- 任一连接线或接口异常发热；
- 两板之间误接了 5V/VBUS；
- UART 持续出现 CRC/格式错误、序号跳变或部分写入；
- Maix 的 `uart stats` 中 `rx_errors` 持续增加；
- Titan 断联后没有进入 OFFLINE；
- Maix 报告 `ticks_ms` 不存在；
- YOLO11 初始化失败、模型不存在，或摄像头连续读取失败。

在上述验收全部通过前，不接舵机，也不加入机械动作。

未来动作层的电脑参考边界见 `ACTION_SAFETY_DESIGN.md`。该模型没有接入 Titan，
不能替代单指空载、软件限位、独立电源和真实安全停止测试。

`host/uart_fault_corpus.json` 和 `protocol/PROTOCOL_SESSION_DESIGN.md` 只是后续测试
准备。首次基线上板期间不要向 Titan 注入故障流，也不要把 HELLO 草案加入任一端。
