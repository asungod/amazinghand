# Titan STATUS 遥测提案（2026-08-15，第二轮冻结）

状态：`PRODUCTION_PATH_IMPLEMENTED_STUDIO_BUILT`  
作者：grokA。2026-08-16 已在仓库规范源和 D 盘 Studio 工程实现仅出站 STATUS，并在 Maix 解析 8 参数；Maix 侧另有 1500 ms 权威快照失效保护。  
`hardware_accessed=false`（本文件描述的实现批次）。未改 ACK/PING/VISION/CRC、校准 CSV、姿态库行为；D 盘同步与编译已完成，尚未在本文档对应批次中宣称真机回归。

第一轮草稿曾写 `arg_count = 7 或 8`。本轮废除该表述。STATUS 载荷冻结为**恰好 8 个十进制参数**。

---

## 0. 本提案解决什么

Maix 屏幕上的 `INTENT` 只是本地类别映射，不是 Titan 权威状态。现有 UART 回程只有 `ACK,seq,status`，`status∈{0,1,2}`，无法区分：

- 策略已接受 vs 低置信拒绝 vs 姿态未配置；
- 链路在线 vs 视觉陈旧 vs 序号被反重放丢弃；
- 安全门 armed/disarmed；
- **动作是否真正提交到舵机总线**。

Titan 已有这些状态的内存来源（见 §1）。STATUS 类型名已在生产编解码器中预留；当前生产实现已加入 UART2 出站 STATUS，但尚未完成不接舵机条件下的真机回归证据。

本提案规定：Titan→Maix 周期或事件驱动发送一条 STATUS，让 Maix 把「本地 INTENT」和「Titan 权威快照」分开显示。实现须等 Codex 批准。

---

## 1. 现有协议与状态来源审计（只读）

### 1.1 线格式（生产，不改）

| 项 | 现有事实 | 出处 |
|---|---|---|
| 帧 | `$` + ASCII body + `*` + 4 位大写十六进制 CRC + `\r\n` | `maixcam2/protocol.py`、`titan_rtthread/smart_hand_protocol.c` |
| body | `TYPE,seq[,arg…]`，逗号分隔十进制无符号整数 | 同上 |
| TYPE | `PING` `ACK` `VISION` `STATUS` | `MESSAGE_TYPES` / `parse_type` |
| seq | uint16，`0..65535` | 编解码强制 |
| arg | 最多 8 个 uint32 | `MAX_ARGS` / `SHP_MAX_ARGS` |
| 最大帧 | 128 字节 | `MAX_FRAME_SIZE` |
| CRC | CRC-16/CCITT-FALSE：初值 `0xFFFF`，多项式 `0x1021`，**覆盖 `$` 之后、`*` 之前的 body 全部字节**，不含 `$` `*` CRC 与 `\r\n` | `crc16_ccitt` / `shp_crc16_ccitt` |

本提案不改 CRC 算法、不改帧头尾、不改 TYPE 集合、不改 PING/VISION/ACK 载荷。

### 1.2 ACK 语义（生产，不改）

Titan `send_ack(seq, status)`：`ACK` 的帧序号回显入站序号，**恰好 1 个参数**：

| status | 含义 | 是否刷新链路/视觉/序号基线 |
|---|---|---|
| 0 | 协议层收下（含合法 PING/VISION；也用于 DUPLICATE/OLD 的幂等忽略） | 仅 FIRST/IN_ORDER/FORWARD_GAP 刷新 |
| 1 | 载荷非法（PING 带参、VISION 非 6 参或越界） | 否；非法 VISION 会 `invalidate` 视觉候选 |
| 2 | 未知 TYPE（含入站 STATUS/ACK） | 否 |

Maix `AckMonitor.acknowledge`：`status==0` 记 `acked`，否则记 `rejected`。Maix **不得**把 STATUS 帧序号当作某次 PING/VISION 的 ACK。

### 1.3 入站序号 / 在线 / 陈旧

| 规则 | 值 | 出处 |
|---|---|---|
| 半程反重放 | `delta=(seq-last)&0xFFFF`；0=DUPLICATE；`1..0x7FFF`=更新；`≥0x8000`=OLD | `smart_hand_sequence_guard.c` |
| DUPLICATE/OLD | ACK 0，不刷新 link / vision / freshness | `smart_hand_uart.c` |
| 链路在线 | 仅业务接受的 PING/VISION 刷新 `g_last_valid_tick` | 同上 |
| 链路超时 | 1500 ms → `OFFLINE`，清视觉，**复位序号基线** | `SMART_HAND_LINK_TIMEOUT_MS` |
| 视觉陈旧 | 750 ms → `VISION_STALE`，`clear_vision_candidate` | `SMART_HAND_VISION_STALE_MS` |

陈旧后当前 Titan **擦掉** `last_decision`（action=NONE，reason=INVALID_PAYLOAD，pose=NO_ACTION）。STATUS 必须用粘滞 `VISION_STALE` 位表达「刚过期」，不能假装决策仍在。

### 1.4 Titan 权威源 vs 当前能否填

| 字段需求 | 权威源 | 当前能否权威产生 | 不能时的值 |
|---|---|---|---|
| 链路在线 | `g_link_online` | 能 | — |
| 最后接收序号 | `g_sequence_guard.last_accepted` + `have_last` | `have_last=0` 时无值 | `last_rx_seq=0` 且 flags 无 `HAVE_LAST_RX` |
| 策略动作 | `last_decision.action` | 能（有视觉或陈旧擦除后的 NONE） | — |
| 拒绝原因 | `last_decision.reason` | 能 | — |
| 姿态配置 | `last_pose_result` / `pose_bank.configured` | 能；生产 bank 全未配置 | 接受策略后恒为 `NOT_CONFIGURED` |
| 安全门 armed | `servo_safety_gate.armed` | **不能**：`smart_hand_uart.c` 未实例化 gate | `GATE_PRESENT=0`，armed/fault 必须读成未知，不得填 0 冒充 disarmed |
| 动作是否提交 | `note_bus_write` / 舵机写包 | **不能**：固件无舵机写包路径 | 见 §3，只允许 `UNKNOWN` 或 `NOT_CONFIGURED` |
| 故障/陈旧 | `vision_expired`、`fault_latched`、`invalid_frames` | 陈旧能；gate 故障不能 | gate 故障码=`FAULT_UNKNOWN` |

真机已观察：`reason=accepted pose=NOT_CONFIGURED actionable=0`。这只证明策略+未配置姿态拒绝，**不证明**提交或机械执行。

---

## 2. 冻结的唯一 STATUS 帧

### 2.1 文本帧（唯一合法形状）

```text
$STATUS,<tx_seq>,<ver>,<flags>,<last_rx_seq>,<action>,<reason>,<pose>,<submit>,<fault>*<CRC16>\r\n
```

- TYPE 固定 `STATUS`（已存在，无需新 TYPE）。
- **参数个数固定 8**。7 个或 9 个都是非法 STATUS，新解码器必须拒绝，不得部分解释。
- 每个参数都是无前导符号的十进制 ASCII，范围见 §2.3。禁止十六进制、浮点、空字段。
- 字节序：文本协议，无多字节整数端序问题。CRC 按 body 的 ASCII 字节序计算。
- 本冻结帧最坏长度约 50 字节，低于 128。

示例（数值见 §6 正常向量）：

```text
$STATUS,10,1,11,7,1,0,2,1,255*<CRC16>\r\n
```

### 2.2 两个序号，禁止混用

| 名称 | 位置 | 谁递增 | 语义 |
|---|---|---|---|
| `tx_seq` | 帧序号（TYPE 后第一字段） | Titan 出站 STATUS 计数器，uint16 回绕 | 只标识这条遥测；**不**进入入站反重放；**不**关闭 Maix 的 PING/VISION pending |
| `last_rx_seq` | 第 3 个载荷参数（下标 2） | 仅当入站 PING/VISION 被业务接受时更新 | Titan 最后一次接受的入站序号 |

重复入站序号：Titan 仍 ACK 0，但 `last_rx_seq` **不变**。下一条 STATUS 必须仍报旧的 `last_rx_seq`。  
链路 OFFLINE 后序号基线复位：`HAVE_LAST_RX` 清零，`last_rx_seq` 报 0。

### 2.3 八个载荷参数（下标 0..7）

| 下标 | 名字 | 文本范围 | 含义 |
|---|---|---|---|
| 0 | `ver` | 必须为 `1` | 本冻结模式版本。其它值：整帧不可解释，权威字段视为 UNKNOWN |
| 1 | `flags` | `0..65535` | 位域，见 §2.4 |
| 2 | `last_rx_seq` | `0..65535` | 见 §2.2 |
| 3 | `action` | `0..3` | 与 `grip_action_t` 相同：0 NONE，1 CYLINDRICAL，2 POWER，3 PRECISION |
| 4 | `reason` | `0..4` | 与 `grip_reason_t` 相同：0 ACCEPTED，1 INVALID_PAYLOAD，2 INVALID_CONFIGURATION，3 LOW_CONFIDENCE，4 UNSUPPORTED_CLASS |
| 5 | `pose` | `0..3` | 与 `grip_pose_result_t` 相同：0 OK，1 NO_ACTION，2 NOT_CONFIGURED，3 INVALID_PROFILE |
| 6 | `submit` | `0..3` | 动作是否真正提交，见 §3 |
| 7 | `fault` | `0..12` 或 `255` | 0 无门故障；1..12 对齐 `servo_gate_block_reason_t`；**255=FAULT_UNKNOWN**（当前无 gate 实例时必须用 255，禁止填 0 冒充无故障） |

### 2.4 flags 位

| bit | 名字 | 1 的含义 |
|---|---|---|
| 0 | `LINK_ONLINE` | `g_link_online` |
| 1 | `HAVE_VISION` | 当前仍持有未过期视觉候选 |
| 2 | `VISION_STALE` | 自上次有效 VISION 以来发生过 750 ms 过期；下一次业务接受的 VISION 清零 |
| 3 | `HAVE_LAST_RX` | 序号守卫已有 `last_accepted` |
| 4 | `GATE_PRESENT` | 运行时确实存在已 init 的 `servo_safety_gate`。当前固件必须为 0 |
| 5 | `GATE_ARMED` | 仅当 `GATE_PRESENT=1` 时有意义 |
| 6 | `GATE_FAULT` | 仅当 `GATE_PRESENT=1` 时有意义 |
| 7 | `HAVE_ACTIONABLE` | `have_actionable_target`。当前因姿态未配置必须为 0 |
| 8..15 | 保留 | 发送必须为 0；接收忽略 |

`GATE_PRESENT=0` 时，接收端必须把 armed/fault 显示为 UNKNOWN，即使 bit5/bit6 为 0。

---

## 3. `submit`：动作是否真正提交

这是本提案的安全语义核心。`submit` **不是** `reason=accepted` 的别名，也不是 `INTENT`。

| 值 | 名字 | 何时允许发出 | 对 Maix 的显示含义 |
|---|---|---|---|
| 0 | `SUBMIT_UNKNOWN` | 无舵机写路径、未观察 `note_bus_write`、或视觉已擦除无法断言 | 未知，不得写成已执行或未执行 |
| 1 | `SUBMIT_NOT_CONFIGURED` | `pose` 为 `NOT_CONFIGURED` 或 `INVALID_PROFILE`，或校准未加载 | 不可能已提交；姿态/校准缺失 |
| 2 | `SUBMIT_BLOCKED` | 仅当 `GATE_PRESENT=1` 且 gate 拒绝/锁存 | 有门且明确拦住 |
| 3 | `SUBMIT_SUBMITTED` | **仅当** 已向总线发出写包且 `note_bus_write(success)` | 真正提交。当前固件**禁止**发出此值 |

派生规则（实现时必须按序）：

1. `pose ∈ {NOT_CONFIGURED, INVALID_PROFILE}` → `submit=NOT_CONFIGURED`。
2. 否则若无写路径或 `GATE_PRESENT=0` → `submit=UNKNOWN`。
3. 否则若 gate 拒绝或 `GATE_FAULT` → `submit=BLOCKED`。
4. 否则若 `note_bus_write(1)` → `submit=SUBMITTED`。
5. 否则 → `submit=UNKNOWN`。

当前 Titan 合法输出只有 `0` 或 `1`。任何实现若在无写路径时发出 `3`，视为协议违规。

`reason=accepted` 且 `pose=NOT_CONFIGURED` 且 `submit=NOT_CONFIGURED` 且 `HAVE_ACTIONABLE=0`：这是 39/41/65 真机已观察到的组合，STATUS 必须原样编码，不得升级成 SUBMITTED。

---

## 4. 版本、旧端、失步恢复

### 4.1 版本协商

无独立握手。`ver` 就是协商。

- 发送端本阶段只许发 `ver=1`。
- 接收端：`ver≠1` → 不解释其余 7 个数，权威快照保持上一帧或全 UNKNOWN。
- 将来 `ver=2` 必须换新文档；不得在 v1 上再加第 9 参数。

### 4.2 旧端行为（必须保持）

| 对端 | 行为 |
|---|---|
| 旧 Titan（不发 STATUS） | 新 Maix：无 STATUS 超时后权威栏全 UNKNOWN；`INTENT` 仍只标本地；`MOTION LOCKED` 仍只表示本机未授权动作 |
| 旧 Maix（`handle_message` 只 `print` STATUS） | 收到 8 参 STATUS：TYPE 合法、CRC 合法则打印，不解析字段，不计入 ACK。链路统计不变 |
| 任一侧 | PING / VISION / ACK 字节级不变 |
| 新解码器 | STATUS 不是 8 参、`ver` 非法、枚举越界 → 丢弃，不更新快照，不当作 ACK |

### 4.3 失步恢复

| 事件 | STATUS / 序号 |
|---|---|
| CRC 错 / 截断 | 现有解析器丢帧；不 ACK；快照不变 |
| 入站 DUPLICATE/OLD | ACK 0；`last_rx_seq` 不变 |
| 链路 1500 ms OFFLINE | Titan 复位入站基线；下一条 STATUS：`LINK_ONLINE=0`，`HAVE_LAST_RX=0` |
| VISION_STALE | `HAVE_VISION=0`，`VISION_STALE=1`，决策按现网擦除规则，`submit=UNKNOWN` |
| Maix 重启 | 入站序号在 Titan 仍有效，直到 OFFLINE 复位；Maix 不得用新的 pending 去匹配旧 STATUS.tx_seq |

---

## 5. 发送节奏（设计约束，非本批实现）

建议：每次业务接受的 VISION/PING 之后发 1 条 STATUS；另在 200–500 ms 心跳补发，使陈旧/掉线可被 Maix 看见。  
禁止用 STATUS 替代 ACK。ACK 仍必须先回。

---

## 6. 测试向量

下列 body 可用生产 `encode_frame("STATUS", tx_seq, *args)` 生成完整帧。CRC 随 body 计算，测试里用 `decode_frame` 断言往返，不硬编码 CRC 字符串（除非做 CRC 破坏用例）。

### 6.1 正常（策略接受、姿态未配置、未提交）

对应已观察真机：class 39、accepted、pose NOT_CONFIGURED。

```
tx_seq=10
args = [1, 11, 7, 1, 0, 2, 1, 255]
# flags=11 = LINK_ONLINE|HAVE_VISION|HAVE_LAST_RX
# action=CYLINDRICAL=1, reason=ACCEPTED=0, pose=NOT_CONFIGURED=2
# submit=NOT_CONFIGURED=1, fault=255
```

冻结用例采用 `flags=11`（LINK_ONLINE + HAVE_VISION + HAVE_LAST_RX）。

### 6.2 姿态未配置（显式）

与 6.1 相同语义；测试名单独覆盖 `pose=2` 且 `submit=1` 且禁止 `submit=3`。

### 6.3 低置信拒绝

```
args = [1, 11, 8, 0, 3, 1, 0, 255]
# action=NONE, reason=LOW_CONFIDENCE, pose=NO_ACTION
# submit=UNKNOWN（规则 2：未到姿态层且无写路径）
```

### 6.4 VISION_STALE

```
args = [1, 0b00001101, 8, 0, 1, 1, 0, 255]
# flags: LINK_ONLINE|VISION_STALE|HAVE_LAST_RX = 1+4+8 = 13
# HAVE_VISION=0, 决策已擦除: action=NONE, reason=INVALID_PAYLOAD, pose=NO_ACTION
# submit=UNKNOWN
```

### 6.5 CRC 错误

对合法 STATUS 翻转 body 一字节。`StreamParser` 必须丢弃，下一条完好帧仍可解析。权威快照不得被破坏帧更新。

### 6.6 重复入站序号

先接受 `last_rx_seq=4` 的 VISION 快照；再模拟 DUPLICATE。下一条 STATUS 的 `last_rx_seq` 仍为 4，`HAVE_LAST_RX` 仍为 1。

### 6.7 旧端兼容

- `encode_frame("ACK", 5, 0)` 仍是 1 参 ACK，解码后不得被 STATUS 解码器认领。
- 7 参 STATUS、0 参 STATUS 必须被新解码器拒绝。
- 无 STATUS 到达时，权威快照构造为全 UNKNOWN，且不得从本地 INTENT 填 `submit`。

---

## 7. 离线测试位置

`smart_hand/tests/test_protocol_status_proposal.py`

- 草案编解码与派生规则只存在于该测试模块，**不**写入 `maixcam2/protocol.py` 或 Titan C。
- 线格式复用现有 `encode_frame` / `decode_frame` / `StreamParser`，以证明 v1 STATUS 可走现有帧，无需改生产编解码。
- 本批不要求 `unittest discover` 全绿去掩盖其它批次失败测试；本文件自身必须全绿。

---

## 8. 给 Codex 的最小审查提示

1. 唯一形状：`STATUS` + 8 参，废除 7/8 双长度。
2. `tx_seq` ≠ `last_rx_seq`；STATUS 不得当 ACK。
3. CRC 覆盖范围与现网完全相同。
4. `submit` 三态核心：当前只许 UNKNOWN / NOT_CONFIGURED；无写路径禁止 SUBMITTED。
5. `GATE_PRESENT=0` 时 armed/fault/fault_code 不得冒充“已 disarm / 无故障”（fault=255）。
6. 旧 Titan 不发 STATUS → Maix 权威栏 UNKNOWN；旧 Maix 只打印不崩溃。
7. 实现前必须再批；本文件不是改 `smart_hand_uart.c` 的授权。

---

## 9. 本批未做与禁止外推

未做：上电、开串口、改 Titan/Maix 生产源、改 D 盘、填校准、发 STATUS 真机。  
不得外推：本提案通过离线测试 ≠ 遥测已上线；`reason=accepted` ≠ 舵机动作；`511` 仍只是电气中点，与 STATUS 无关。
