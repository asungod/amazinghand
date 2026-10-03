# Titan 8 舵机安全扩展静态审计

**日期**：2026-08-16  
**状态**：`STATIC_AUDIT_ONLY / NOT_IMPLEMENTED / HARDWARE_UNVERIFIED`  
**硬件访问**：`false`

## 1. 结论

当前 Titan 舵机安全链是一个明确的 **2 舵机单指 fixture**，不能通过只把
`SERVO_GATE_COUNT` 从 `2u` 改成 `8u` 就宣称支持四指。固定下标、双 ID API、双舵机
sync-write、反馈轮询周期、motion monitor 完成条件、整组停机和 STATUS 提交语义都必须
一起扩展并通过失败路径测试。

在下述代码门槛、离线测试和真机验证全部满足前：

- 不得填写真实 8 舵机校准 CSV 或生产姿态；
- 不得授权四指上电、动作或负载抓握；
- 不得把 ACK、`accepted`、`actionable`、`INTENT` 或当前 STATUS 当作 8 舵机执行证据；
- 不得把现有单指两舵机 C 测试外推为四指安全证据。

本文件是静态设计门槛，不是生产实现授权，也不是硬件接线、烧录或动作指令。

## 2. 当前 2 舵机假设的源代码证据

| 模块 | 当前证据 | 扩到 8 前的风险 |
|---|---|---|
| 安全门数量与存储 | `titan_rtthread/servo_safety_gate.h:7` 定义 `SERVO_GATE_COUNT 2u`；`:62` 的校准数组以及 `:73-86` 的 init/arm/plan API 均绑定该数量 | 仅改宏会放大数组，但不会自动消除双项特判或证明集合完整性 |
| 安全门固定下标 | `titan_rtthread/servo_safety_gate.c:48-54` 直接访问 `observations[0]`、`observations[1]`；`:108-110` 只显式验证两份 calibration 和两 ID；`:175-179` 只比较两个 target ID | 第 3～8 项可能未被初始化、未做唯一性检查或未参与 fail-closed 判断 |
| 反馈轮询 API | `titan_rtthread/servo_feedback_poll.h:24-36` 的状态数组随 count，但 `:39-44` init API 只接受 `id1`、`id2` | 不能表达 8-ID 集合，也没有完整周期完成标志 |
| 反馈轮询实现 | `titan_rtthread/servo_feedback_poll.c:36-63` 只验证并写入两个 ID；`:66-89` 每次只发一项 read；`:141-148` 单项超时后推进 | 8 项串行轮询可能超过 freshness 门槛；部分新鲜反馈可能被误当完整快照 |
| motion monitor | `titan_rtthread/servo_motion_monitor.h:22-24` 保存 count 个 goal/position/seen；`servo_motion_monitor.c:32-54` 却直接验证和初始化 `[0]`、`[1]` | 只观察前两项即可启动或错误初始化剩余项的风险 |
| motion 完成规则 | `servo_motion_monitor.c:84-114` 对未知 ID/read failure/servo error 失败，并要求遍历项全部 seen 且到位 | 这是可复用基础，但必须证明 8/8 完成和 1/8 故障的整组行为 |
| sync write | `titan_rtthread/scs0009_packet.h:46-53` API 只有两对 ID/position；`scs0009_packet.c:116-145` 固定 `total = 22` 并只编码两项 | 无法表示 8 项、无法验证容量，broadcast 本身也不提供逐舵机成功 ACK |
| 单事务反馈 | `titan_rtthread/scs0009_transaction.c:15-36` 提供单事务 begin/busy/timeout；`:39-69` 处理反馈和 servo error；`:72-92` 处理 timeout | 单舵机 transaction 正确不等于 8 舵机整组周期正确，需要聚合状态 |
| STATUS 当前边界 | `titan_rtthread/smart_hand_uart.c:108-125` 固定 `gate_present=0`、`write_path_present=0`；`:435-436` 启动日志声明 pose 未配置且无 servo write | 当前 STATUS 只能证明通信/决策状态，不能证明提交到舵机 |
| STATUS 提交派生 | `titan_rtthread/smart_hand_status_telemetry.c:7-30`：无 pose、无 write path/gate、blocked/fault 均不能得到 `SUBMITTED`；只有 `write_observed_ok` 才返回 `SUBMITTED` | 8 舵机实现必须把 `write_observed_ok` 定义成整组成功证据，不能是“调用过发送函数” |

## 3. 最小生产代码门槛

### 3.1 通用 8 舵机数据模型与 API

最低要求不是散布 `8` 常量，而是一个有上限、显式携带数量的统一集合模型：

1. 定义单一最大值，例如 `SERVO_GROUP_MAX_COUNT = 8u`；运行时有效数量必须是显式字段，四指生产配置必须严格等于 8。
2. gate、feedback poll、motion monitor、packet builder 使用同一 ID/目标集合来源，禁止各模块自行维护不同顺序的平行数组。
3. 所有 API 同时接收 buffer、count、capacity；拒绝 `NULL`、`count != 8`、容量不足和非法 ID。
4. 去除 `observations[0/1]`、`calibration[0/1]`、`targets[0/1]`、`goals[0/1]` 的业务特判，全部通过受界循环验证。
5. 对外返回值必须区分配置错误、反馈不完整、范围错误、总线发送失败、确认失败和监视超时，但所有错误都要进入同一 fail-closed 总路径。

### 3.2 ID、角色和集合完整性

初始化和每次计划前都必须满足：

- 8 个 servo ID 均在协议合法范围内，且两两唯一；
- 8 个逻辑角色均存在且唯一，每个角色只映射一个 servo ID；
- calibration、pose target、feedback observation、raw goal 四个集合的 ID 集完全相等；
- 不允许通过数组顺序暗示角色；查找后仍需检测重复、缺失和未知 ID；
- 任一重复 ID、重复角色、缺项、未知项或未校准项都必须阻止整组 arm 和 plan。

已有 `tests/test_four_finger_config_rules.py` 的 8-role fixture 只能作为 schema 拒绝规则基础；其中 ID、姿态值和 `calibrated` 标志仍是 fixture，不是机械参数证据。

### 3.3 all-or-none 计划与提交

8 个目标必须先在内存中完成整组验证，再生成一个不可变的 group plan。推荐顺序：

1. 获取同一完整轮次的 8 项新鲜反馈；
2. 对 8 项分别检查 read_ok、ID、软限位、当前位置、电压、温度、最大步长；
3. 对 8 项目标分别检查 calibration、方向、目标范围和速度限制；
4. 只有 8/8 全部通过才构造写包；
5. 任一项失败时不得保留或发送前一轮的部分目标；
6. bus write 失败后 latch fault、disarm，并使该计划不可重试，必须重新采集完整反馈和重新计划。

禁止逐项“边校验边写”。否则第 1～N 项已经运动、第 N+1 项失败时无法保持整组原子安全语义。

## 4. 完整反馈周期与 freshness 预算

当前轮询器一次只读取一个舵机。扩展后必须为每个 ID 保存至少：`read_ok`、servo error、position、speed、load、voltage、temperature、observation timestamp/age 和本轮 generation/cycle 标识。

只有同一完整 generation 的 8 项都成功更新后，才发布给安全门一个 `complete snapshot`。7 项新鲜加 1 项旧值、1 项超时或 1 项坏帧，都不是完整快照。

时间预算必须在代码注释和测试中具体化。保守上界为：

```text
full_cycle_worst_ms =
    8 × (tx_time_ms + turnaround_margin_ms + response_timeout_ms + scheduler_margin_ms)
```

必须满足：

```text
full_cycle_worst_ms < max_feedback_age_ms
```

并留出 gate 计划、sync write 和 monitor 观察所需的余量。UART 波特率、读包字节数、半双工方向切换延迟、RT-Thread 调度抖动目前均未在真机确认，因此本审计不能给出可采信的数值。

最低失败语义：任一 ID 超时、坏 CRC/坏帧、servo error、重复回复、未知 ID 或超龄，立即将整组 snapshot 标记无效并 disarm；不得继续使用其他 7 项。

## 5. sync write 长度、发送结果与“部分写”

两舵机 builder 当前固定 22 字节。8 舵机版本必须：

1. 由协议字段长度计算帧长，禁止新的魔法总长度；
2. 在写 buffer 前校验 `capacity >= required_length`，并防止长度字段和索引溢出；
3. 重新校验 8 个 ID 唯一以及 position/speed/time 等字段范围；
4. 为 8 项确定稳定编码顺序，但安全语义不得依赖返回反馈的顺序；
5. 计算最大帧在目标 UART 波特率下的发送时长并纳入 timeout/freshness 预算；
6. 将 UART 返回的短写、0 字节、方向切换失败、driver error 全部视作整组写失败。

SCS broadcast sync write 没有逐舵机 ACK，因此“完整字节已交给 UART 驱动”仍不等于 8 个舵机均执行。`SUBMITTED` 至多表示整组计划通过 gate 且完整写包成功交给总线；若项目要表达 `EXECUTED/REACHED`，必须由发送后的 8 项独立反馈和 motion monitor 另行证明。

必须显式测试所谓“部分写”：虽然 broadcast 帧在电线上不是 8 次独立 API 调用，驱动短写、发送中止或帧损坏仍可能导致未知的部分执行。处理方式只能是 latch fault、disarm、禁止盲重发，然后执行经项目裁决的整组停止策略并重新取完整反馈。

## 6. 整组 torque-off 与停止策略

当前静态证据不足以证明已有“8 舵机全体 torque-off”生产路径。扩展前必须新增并验证：

- 一个显式 group stop API，输入冻结后的 8-ID 集合，拒绝缺项和重复 ID；
- 对每个 ID 尝试 torque-off，即使前一项发送失败也继续尝试剩余项；
- 聚合 8 项结果，任何一项失败都保持 fault latched，不得报告安全恢复；
- stop 过程中禁止新 plan、arm 或动作提交；
- torque-off 广播或逐项发送的选择必须基于 SCS0009 实际能力和机械风险，不在静态审计中猜测；
- 掉线时最终策略是 hold、缓释还是 torque-off，必须经实物机械风险评估后冻结，不能由辅助模型代替裁决。

“调用了 stop”不能作为安全证据；至少需要总线发送结果和后续 8 项状态/人工机械状态确认。

## 7. 故障传播、锁存和恢复

下列任意一项发生在任一舵机时，都必须传播为整组故障：

- 掉线、反馈超时、CRC/帧错误、servo error；
- 温度超限、电压越限、当前位置越过软限位；
- 目标越过软限位、单步过大、ID/角色/集合不一致；
- sync write 编码失败、容量不足、短写或总线发送失败；
- motion monitor 未见齐 8 项、任一项不再运动/未到位、未知 ID 或总超时。

整组故障后必须：

1. `fault_latched=1`；
2. `armed=0`，拒绝所有新动作；
3. 使当前 plan 和旧 feedback generation 失效；
4. 执行冻结的 group stop 策略；
5. STATUS 不得报告 `SUBMITTED`；
6. 只允许在故障原因消失、重新取得 8/8 新鲜安全反馈、显式 clear fault 后重新 arm。

`servo_safety_gate.c:221-239` 已有 bus-write failure latch/disarm 与 clear-fault 基础，但扩展测试必须证明它对“任意 1/8 失败”均成立，并且 clear fault 不会自动 arm 或复用旧计划。

## 8. motion monitor 的 8/8 完成定义

启动前必须验证完整 8 goals、唯一 ID 和合法位置。启动后：

- 只有 8 个目标 ID 全部在本轮 `seen` 且全部进入允许误差范围，才可 `COMPLETE`；
- 1/8、7/8 均必须保持未完成；
- 任一 read failure、servo error、未知 ID、越限、过温、掉线或 monitor timeout 都进入整组失败；
- timeout 必须覆盖 8 舵机完整反馈周期及调度余量，不能沿用只为 2 项 fixture 合理的数值；
- abort/reset 必须清除全部 8 项 seen、last position、goal 和 generation，防止下一动作继承旧状态。

还应独立定义“已提交”和“已到位”：sync write 完成不能直接令 motion monitor `COMPLETE`。

## 9. STATUS 不得误报 `SUBMITTED`

8 舵机 write path 接入后，`write_observed_ok` 必须是一次性、与当前 sequence/group plan 绑定的整组写入证据，至少要求：

- 当前 pose 已配置且 8-role/8-ID 完整；
- gate 存在、已 armed、未 blocked、未 fault；
- 8/8 目标已通过同一轮安全检查；
- 完整 sync-write 帧已成功交给 UART，未发生短写/driver error；
- 没有任何已知的 1/8 失败。

以下情况一律不得 `SUBMITTED`：

- `gate_present=0` 或 `write_path_present=0`；
- pose 未配置、低置信/不支持类、VISION stale；
- 8 项中任一缺失、重复、超时、过温、掉线、越限；
- builder/容量/发送失败或发送结果不完整；
- 仅收到 ACK、仅得出 actionable/INTENT、仅启动 motion monitor；
- 前一次动作曾成功，但当前动作没有新的 group-write evidence。

建议 STATUS 的提交证据在发送后立即消费或绑定动作 generation，防止旧的 `write_observed_ok=1` 泄漏到后续状态帧。motion monitor 的“到位/失败”若以后需要上报，应使用独立字段/版本，不得重解释现有 `SUBMITTED`。

## 10. 最小离线测试矩阵

| 领域 | 必须通过的正常路径 | 必须通过的失败路径 |
|---|---|---|
| 配置/init | 8 个合法、唯一 ID 与 8 个唯一角色初始化成功 | 0/7/9 项、重复 ID、重复角色、ID 0/254、任一未校准均 fail-closed |
| gate arm | 同一 generation 的 8/8 新鲜安全反馈才 arm | 1 项 read fail、stale、过温、欠/过压、位置越限、未知/重复 ID 均不 arm |
| plan | 8/8 目标合法生成 8 goals | 任一 pose 缺项、目标越限、step 过大、顺序打乱/重复 ID 均无包 |
| feedback poll | 每轮确实请求 8 个唯一 ID，8 项均更新并发布完整 snapshot | 第 1/4/8 项 timeout、坏帧、servo error；7 新鲜+1 旧；未知/重复回复均使整轮无效 |
| 时间预算 | 仿真 worst-case 仍小于 freshness 门槛 | 参数组合导致完整周期不满足门槛时 init/config 必须拒绝 |
| packet builder | 8 项 builder 长度、字段、checksum 与容量边界正确 | 重复 ID、非法值、capacity 少 1 字节、长度溢出均拒绝且 buffer 不被部分当有效包 |
| bus write | 完整写长度才记录 group write success | 0 字节、短写、driver error、方向切换失败均 latch fault/disarm |
| group stop | 对 8 ID 全部尝试并汇总成功 | 第 1/4/8 项 torque-off 失败时仍尝试其余项，fault 保持锁存 |
| monitor | 8/8 seen 且全到位才 COMPLETE | 1/8、7/8 不完成；任一 error/掉线/未知 ID/timeout 整组失败 |
| recovery | 原因消失 + 8/8 新反馈 + 显式 clear + re-arm 后才可新计划 | clear 后不自动 arm、不复用旧 feedback/plan/write evidence |
| STATUS | 整组 gate 通过且完整写入，当前 generation 可为 SUBMITTED | 无 gate/无 path、部分写、任一故障、旧 evidence、仅 ACK/actionable 均不得 SUBMITTED |
| 集成 | policy→pose→gate→builder→write→monitor 的纯 fixture 端到端，8 项均被覆盖 | 任一阶段注入 1/8 故障，后续不得继续并产生可审计 block reason |

现有 `tests/test_servo_safety_gate_c.c`、`test_servo_feedback_poll_c.c`、`test_servo_motion_monitor_c.c` 和 `test_single_finger_pipeline_c.c` 主要是两舵机 fixture；扩展时应保留这些回归测试，同时新增独立的 8 舵机测试目标，避免通过改宏掩盖 fixture 语义。

## 11. 真机仍必须验证的项目

下列项目全部为 `UNVERIFIED`，不能由离线测试替代：

- 真实 8 个舵机 ID、方向、中心、软限位、速度和安全步长；
- Titan 实际舵机 UART、半双工方向控制、波特率、8 项轮询周期和 RT-Thread 调度抖动；
- 8 舵机同时发送时的供电峰值、电压跌落、线束压降、地回路和热状态；
- broadcast sync write 的真实总线行为以及发送后逐舵机反馈；
- 任一舵机掉线、卡滞、过温、越限时的整组停止效果；
- hold、缓释、torque-off 对机械结构和被抓物的风险；
- 四指装配后的碰撞、连杆干涉、负载和真实三种姿态。

这些验证必须从无负载、小步长、单项故障注入逐级推进；本审计不授权任何具体动作参数。

## 12. 放行条件

只有同时满足以下条件，主模型才应考虑批准进入 8 舵机生产接线：

1. 本文第 3～9 节的代码门槛已实现且经过独立审查；
2. 第 10 节离线矩阵全部通过，且没有把 fixture 值写入生产校准/姿态；
3. D 盘 Studio 工程与仓库规范源的同步方式、diff 和构建产物可审计；
4. 8 舵机供电、接线、ID 和总线时序已有现场证据；
5. 整组停止策略经过主模型和用户明确裁决；
6. STATUS 在所有失败注入下均不误报 `SUBMITTED`；
7. 完成一次“8/8 反馈—计划—写入—反馈确认—停止”的无负载分阶段真机记录。

在此之前，项目的准确表述仍是：**四指 8-role 离线配置规则已有 fixture 覆盖；Titan 生产安全门、反馈轮询、写入与 motion monitor 仍是 2 舵机基础，8 舵机运行时和硬件均未验证。**
