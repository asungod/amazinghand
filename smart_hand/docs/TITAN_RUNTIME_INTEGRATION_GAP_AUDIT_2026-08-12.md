# Titan 运行时接线缺口审计（2026-08-12）

**范围**：仅审计与离线验证。  
**规范源**：`smart_hand/`  
**审计对象**：`titan_rtthread/` 全部项目自有源、`tests/test_single_finger_pipeline_c.c`、`host/run_all_checks.ps1`、`ACTION_SAFETY_DESIGN.md`、`EXECUTION_STATE_DESIGN.md`、`GRIP_POLICY_MVP.md`。

> **2026-08-12 后续更新（不删除历史结论）**  
> 授权实施包已完成规范源接线：`smart_hand_uart.c` → `smart_hand_vision_state` → `grip_policy` + 空 `grip_pose_bank`；  
> 独立 750ms 视觉过期与断联 invalidate；**无** SCS0009 写包。详见  
> `TITAN_VISION_RUNTIME_INTEGRATION_RESULT_2026-08-12.md`。  
> 历史 §1「零调用 policy」描述的是**实施前**状态。仍待：Studio ARM 刷新构建、真机 UART、姿态校准、舵机执行层。

---

## 1. 当前 `smart_hand_uart.c` 收到 PING/VISION 后的真实调用路径

```text
INIT_APP_EXPORT(smart_hand_comm_init)
  -> rt_device_find("uart2") / open INT_RX / create "sh_uart" thread

rx_thread_entry
  -> rt_device_read 1 byte
  -> shp_parser_feed(&parser, byte, &message)
       |-- result == 1 --> handle_message(&message)
       |-- result < 0  --> g_stats.invalid_frames++, print dropped
  -> if link online and age > 1500ms:
       g_link_online = FALSE; offline_events++; print "VISION_OFFLINE; block new motion"
       （注意：不清除 g_have_vision / g_last_vision，不调用任何安全/舵机模块）

handle_message:
  PING (arg_count==0):
    mark_link_alive(seq)  // record_sequence + valid_frames + ONLINE 日志
    send_ack(seq, 0)
  PING (arg_count!=0):
    invalid_payloads++; send_ack(seq, 1)

  VISION + vision_payload_valid (6 args, 范围检查):
    class_id = args[0]; confidence = args[5]
    grip = (confidence >= 70) ? "POWER_GRASP" : "NO_ACTION"   // ← 旧诊断，非 grip_policy
    mark_link_alive(seq)
    g_last_vision = *message; g_have_vision = TRUE
    rt_kprintf(... grip=%s ...)
    send_ack(seq, 0)
  VISION 非法:
    invalid_payloads++; send_ack(seq, 1)

  其他类型:
    send_ack(seq, 2)
```

**结论**：运行时只做协议解析、链路统计、ACK 与控制台诊断。  
**零调用**：`grip_policy_*`、`grip_pose_bank_*`、`servo_safety_gate_*`、`scs0009_*`、`servo_feedback_poll_*`、`servo_motion_monitor_*`。  
`#include` 仅 `smart_hand_protocol.h` + RT-Thread。

旧诊断与正式策略的差异（已由强化后的单指流水线测试证明）：

| 输入 | 旧 uart 打印 | `grip_policy_decide` |
|------|--------------|----------------------|
| class=39 conf≥70 | POWER_GRASP | CYLINDRICAL |
| class=41 conf≥70 | POWER_GRASP | POWER |
| class=65 conf≥70 | POWER_GRASP | PRECISION |
| 任意 class conf&lt;70 | NO_ACTION | NO_ACTION |
| 不支持 class conf≥70 | POWER_GRASP（错误） | NO_ACTION |

---

## 2. 各模块：已完成什么、尚未接到哪里

| 模块 | 已完成（可离线证明） | 接到哪里 | 缺口 |
|------|----------------------|----------|------|
| `grip_policy` | 纯函数决策；三类 COCO→意图；非法/低置信/不支持→NONE | 仅 tests / 单指流水线；**未**被 uart 调用 | uart VISION 分支应用其结果替换 conf-only 字符串 |
| `grip_pose_bank` | init 后三种姿态 `configured=0`；未配置→`NOT_CONFIGURED`；无舵机写包 | 仅 tests | 生产 bank 保持空白；uart 路径应在 resolve 失败时拒绝动作 |
| `servo_safety_gate` | init/arm/disarm/plan_logical/fault latch/bus write note | 仅 tests | 无校准则 init 失败；uart/执行线程未持有 gate 实例 |
| `scs0009_packet` | ping/read/torque/write/sync_write 组包与 status 解析 | 仅 tests + PC 工具路径参考 | 无 Titan 舵机 UART 发送端 |
| `scs0009_stream` | 逐字节收包、噪声/坏包恢复 | 仅 tests | 无 ISR/半双工 RX 喂入 |
| `scs0009_transaction` | 单播事务状态机、超时、忙拒绝、写超时不自动重发 | 仅 tests | 无真实 tick/TX/RX 绑定 |
| `servo_feedback_poll` | 双 ID 轮询、失败清 read_ok、snapshot 给安全门 | 仅 tests | 未进单指流水线组合；无 UART/周期 |
| `servo_motion_monitor` | 同步写后双 ID 到位/超时/单缺失败 | 单指流水线 + 单测 | 无写后真实读回路径 |
| `smart_hand_protocol` | 帧编解码 CRC | uart 已用；C/Python 测试 | 会话 HELLO 草案未落地（今晚不启用） |
| `smart_hand_uart` | PING/VISION/ACK、统计、1.5s 离线 | 已在 RT-Thread 工程 | VISION 未接策略链；离线未清目标 |

**相对设计文档的缺口**

- `ACTION_SAFETY_DESIGN.md`：Python 参考有 link/arm/fresh/fault；C 侧仅有 `servo_safety_gate` 的 arm/fault 子集，**无**与 uart 链路事件的统一动作安全门实例，uart 离线也不清目标。
- `EXECUTION_STATE_DESIGN.md`：DISARMED/READY/CLOSING… 仅 Python；C 无执行状态机。
- `GRIP_POLICY_MVP.md`：C `grip_policy` 已等价；uart 仍打印旧 POWER_GRASP。

---

## 3. 函数级调用关系表

### 3.1 当前运行时（真实）

| 入口 | 输入 | 输出 | 状态 | 副作用 | 等待的硬件条件 |
|------|------|------|------|--------|----------------|
| `smart_hand_comm_init` | 无 | RT_EOK/错误 | 打开 uart2 | 创线程、RX 指示 | 设备名 `uart2` 存在 |
| `rx_thread_entry` | UART 字节 | 无 | parser + link | 读设备、take sem | UART2 RX 中断/轮询 |
| `shp_parser_feed` | byte | 0/1/&lt;0 + message | parser buffer | 无 I/O | 无 |
| `handle_message` | `shp_message_t` | ACK 帧 | stats, last_vision, link | `rt_device_write` ACK；kprintf | UART2 TX |
| `mark_link_alive` | seq | 无 | sequence, online, tick | 可能打印 ONLINE | 无 |
| `vision_payload_valid` | message | bool | 无 | 无 | 无 |
| 离线检查（线程内） | tick | 无 | link offline | 打印 OFFLINE；**不清 vision** | 单调 tick |

### 3.2 意图模块（已实现、未接线）

| 入口 | 输入 | 输出 | 状态 | 副作用 | 等待的硬件条件 |
|------|------|------|------|--------|----------------|
| `grip_policy_decide` | vision payload, min_conf | decision(action, reason, class) | 无 | 无 | 无（纯函数） |
| `grip_pose_bank_init` | bank* | 无 | 三 profile 未配置 | memset | 无 |
| `grip_pose_bank_resolve` | bank, decision, targets[] | OK/NO_ACTION/NOT_CONFIGURED/INVALID | 无 | 写 targets 仅当 OK | **生产需实测姿态**；当前应保持未配置 |
| `servo_safety_gate_init` | cal[2], age/v/t 限 | 0/1 | initialized | 拷贝 cal | **完整两行校准** |
| `servo_safety_gate_arm` | observations[2] | 0/1 | armed / block reason | 可能保持 disarm | 新鲜有效反馈 |
| `servo_safety_gate_plan_logical` | logical targets, obs | 0/1 + raw goals | last_block | 无总线写 | armed + 安全观测 |
| `servo_safety_gate_note_bus_write` | success | 无 | fault_latched | 失败锁存 | 总线写结果 |
| `scs0009_build_*` | id/pos/... | 字节长度 | 无 | 填 buffer | 无 |
| `scs0009_stream_feed` | byte | NONE/FRAME/REJECTED | parser 统计 | 无 | 舵机 RX 字节流 |
| `scs0009_transaction_begin/feed/tick` | id, now, timeout, bytes | 状态枚举 | txn 状态 | 超时不自动重发写 | 半双工时序 + 时钟 |
| `servo_feedback_poll_prepare/feed/tick` | now, bytes | 读包 / obs | 轮询索引与年龄 | 失败清 read_ok | 舵机 UART、period、timeout |
| `servo_motion_monitor_start/observe/tick` | goals, pos, ok, err, now | 运动状态 | seen[] | 双 ID 都到位才 COMPLETE | 写后真实读回；tolerance/timeout 待测 |

**意图中的目标串联（离线已组合，运行时未接）**

```text
VISION args
  -> grip_vision_payload_t
  -> grip_policy_decide
  -> grip_pose_bank_resolve   // 未配置 => 停
  -> servo_safety_gate_plan_logical  // 未 arm/无 cal/陈旧反馈 => 停
  -> scs0009_build_sync_write_positions
  -> （未来）半双工 TX
  -> servo_motion_monitor_* + feedback_poll 读回
```

---

## 4. `test_single_finger_pipeline_c.c` 已覆盖路径

| # | 路径 | 断言要点 |
|---|------|----------|
| 1 | 策略映射 | 39→CYLINDRICAL，41→POWER，65→PRECISION |
| 2 | 拒绝类 | conf=69、不支持 class → NONE |
| 3 | 生产默认 | bank init 后 resolve → NOT_CONFIGURED，无包 |
| 4 | FIXTURE 姿态 | 仅测试内 `configured=1` + 逻辑偏移；标注禁止进生产 |
| 5 | 非法意图 | 即使 FIXTURE 已配置，unsupported/low_conf → NO_ACTION |
| 6 | 安全规划 | FIXTURE cal + 新鲜观测 → arm + plan → 22 字节 sync 广播包 |
| 7 | 陈旧反馈 | age&gt;max → 无法 arm → 无包 |
| 8 | 显式 disarm | armed=0 → 不 plan → 无包（模拟断联/撤权后禁止新动作） |
| 9 | 到位监测 | 双 ID 观测 COMPLETE；单 ID + tick → TIMEOUT |

**未覆盖（且本批不改生产 C 故无法从 uart 直接测）**

- `handle_message` 真实分支与模块接线（uart 未 include 模块）
- 离线后清除 `g_last_vision` / 禁止复用旧目标
- `servo_feedback_poll` 与 uart 字节流联调
- 半双工方向脚、真实 timeout/period
- 执行状态机 CLOSING/HOLDING/FAULT
- 重复/旧序号是否刷新动作目标（ACTION_SAFETY 的 note_target 语义）

---

## 5. 真正缺失但可以离线验证的路径

| 缺口 | 离线手段 | 本批状态 |
|------|----------|----------|
| 旧 uart 诊断 ≠ grip_policy | 流水线中 class 映射断言 | **已强化** |
| 合法识别 + 未校准姿态 → 拒绝 | NOT_CONFIGURED + packet_length==0 | 已有并保留 |
| 不支持/低置信 + 即使姿态配置 → 无包 | NO_ACTION 断言 | **已强化** |
| disarm / 非 armed → 无包 | disarm 后 plan 不执行 | **已强化** |
| 陈旧/缺失反馈 → 无包 | age 与单缺 TIMEOUT | 已有 |
| 策略→姿态→门→组包→监测 组合 | 单指流水线 | 已有 |
| feedback_poll 状态机 | `test_servo_feedback_poll_c.c` | 已有独立测；未进流水线（可下一批组合，仍不必改生产） |
| uart 离线清目标 | 需改 `smart_hand_uart.c` 或抽纯函数再测 | **待 Codex 批准的最小补丁** |
| 序号/目标新鲜度动作门 | Python `action_safety_model` 已测；C 未实现统一门 | 第二轮后可加 C 参考，仍先审计 |

**本批刻意不做的“假接线”**：不在测试里 `#include` 并调用未导出的 uart static 函数；不把 FIXTURE 写入 CSV/生产 bank。

---

## 6. 必须等待实物的接口

| 接口/参数 | 为什么不能今晚填 |
|-----------|------------------|
| Titan 舵机 UART 设备名（非 uart2） | uart2 保留给 Maix；舵机口需板级确认 |
| 半双工 DE/RE 方向控制 GPIO 与时序 | 无转接/示波器与实板 |
| 事务 `timeout_ms`、轮询 `period_ms` | 依赖总线负载与读回延迟实测 |
| 运动 `tolerance_raw`、动作超时 | 依赖机构背隙与速度 |
| `direction_sign`、center、soft_min/max、max_step | 机械安装与空载/装连杆后实测 |
| 三种 grip 逻辑偏移 | 姿态库生产配置；禁止猜测 |
| 电压/温度原始阈值 | 6.0V 供电与温升实测 |
| Maix↔Titan 115200 真机误码/粘包 | J-Link 未到货，未烧录本固件 |
| 安全停止是 hold / 缓释 / torque-off | 卡滞与负载真机观察 |
| 装连杆后 finger_smoke 行程 | 机构未完整验证 |

---

## 7. 下一批最小生产补丁计划（仅提案，本批不实施）

**单一目标**（对齐交接文档第二轮）：  
把 Titan VISION 处理从旧字符串诊断改为调用现有 `grip_policy` + `grip_pose_bank`（未配置即拒绝），**仍不**接真实舵机 UART、**不**产生物理指令。

### 7.1 建议最小 diff 范围（待 Codex 批准）

1. `smart_hand_uart.c`（及必要时对应 `.h` 若抽公共结构）  
   - `#include "grip_policy.h"`、`#include "grip_pose_bank.h"`  
   - 静态 `grip_pose_bank_t`；init 时 `grip_pose_bank_init`（保持未配置）  
   - VISION 合法后：填 `grip_vision_payload_t` → `grip_policy_decide(..., 70)` → `grip_pose_bank_resolve`  
   - 打印使用 `grip_policy_action_name` / reason；resolve≠OK 时明确 `pose_not_configured` / `no_action`  
   - **禁止**在补丁中写 `configured=1` 或任何逻辑偏移  
2. 离线时：`g_have_vision=0` 并可选清除 last vision（对齐 ACTION_SAFETY“断联清目标”）  
3. **不** include scs0009 / safety_gate 写包路径（避免无校准下发出总线帧）  
4. 同步规范源与 Studio 三份（若只改 uart，则 check_titan_sync 需同步 `smart_hand_uart.c`）  
5. 新增/扩展主机可编译测试：构造 payload 调用与 uart 相同的决策辅助函数（若抽 `smart_hand_vision_decide()` 纯函数则更易测）；至少保证“高置信 bottle + 空 bank → 无写包意图”

### 7.2 验收标准（第二轮）

- 不支持类别、低置信、非法载荷 → NO_ACTION  
- 生产姿态库默认全未配置  
- 未配置姿态时不得生成 SCS0009 写包  
- 断联后目标失效并阻止新动作意图  
- PING/VISION/ACK 与统计不回归  
- Python/C 协议格式不变  
- 新测试证明“合法识别也会因未校准而拒绝动作”  
- `run_all_checks.ps1` + `run_offline_rehearsal.py` 全绿；`hardware_accessed=false`；校准表仍空白  

### 7.3 明确不做

- 真实半双工舵机 UART  
- J-Link 烧录与 Maix 联调  
- 自动抓握 / 全行程 / 填校准  
- 执行状态机完整移植  
- 协议 HELLO 升级  

---

## 8. 本批交付与声明

| 项 | 内容 |
|----|------|
| README 修正 | 四处证据表述 + 测试数量精确化 |
| 本审计文档 | `docs/TITAN_RUNTIME_INTEGRATION_GAP_AUDIT_2026-08-12.md` |
| 测试强化 | `tests/test_single_finger_pipeline_c.c`（仅 tests；FIXTURE 标注） |
| 生产 C | **未修改** `titan_rtthread/*` |
| D 盘工程 | **未修改** |
| 校准/姿态 | **未填写** |

**仍待实物**：J-Link 烧录、Maix–Titan UART、舵机口与半双工、软限位/方向/姿态、装连杆冒烟、安全停止策略。

**下一步**：将本审计与检查输出交 Codex；通过后再做 §7 最小补丁。
