# Grok 连续实施包：序号防重放、非法目标失效、ARM 构建证据与无舵机联调准备

日期：2026-08-13  
前一批结论：`VISION -> grip_policy -> 空 pose_bank -> 拒绝动作` 主路径合理，89 个
Python 测试、11 个 C 测试和扩展源同步均通过；但 **尚未批准烧录或实物联调**。

请连续完成本任务的阶段 A～F 后再返回 Codex。第 9 节范围内的问题自行修复，不必逐项
询问；触发第 10 节才停止。

## 1. 本批必须修复的两个安全缺口

### 缺口一：协议合法但 VISION payload 非法时旧目标未立即清除

当前 `smart_hand_uart.c` 对 CRC/格式正确、但宽高为 0、置信度超过 100 等非法 VISION
只回 ACK=1，不调用 `smart_hand_vision_state_invalidate()`。如果未来姿态已经配置，前一个
actionable 目标会残留到 750 ms 超时。

要求：收到“帧类型为 VISION、但业务 payload 非法”的消息时立即 invalidate 视觉候选、
actionable 和 targets；仍 ACK=1，仍计入 invalid_payloads，不刷新链路或视觉时间。

CRC/帧解析错误暂不要求立即清目标，继续依赖 750 ms freshness 超时，避免单个噪声字节
造成无界状态抖动。

### 缺口二：重复或旧序号目前仍会重新处理并刷新视觉时间

当前 `record_sequence()` 只统计 duplicate/gap，不返回接受结果；重复或旧 VISION 仍会
进入 `note_vision()`，从而刷新目标时间。未来可能导致重放旧目标。

要求增加独立、可主机测试的 16 位序号防重放模块，并在 UART 中区分：

- 第一帧：接受；
- 正常递增：接受；
- 跨 `65535 -> 0` 回绕：接受；
- 前向跳号：接受并记 gap；
- duplicate：ACK 但不更新 link/vision/业务状态；
- old/backward：ACK 但不更新 link/vision/业务状态；
- 链路真正进入 OFFLINE 后 reset 序号基线，使 Maix 重启后的新会话可重新接受第一帧。

v1 协议没有 `BOOT_ID`，所以“断联后重置序号”是当前最小恢复策略。不要在本批启用 HELLO。

## 2. 允许修改和新增的范围

```text
smart_hand/titan_rtthread/smart_hand_sequence_guard.c       # 新建
smart_hand/titan_rtthread/smart_hand_sequence_guard.h       # 新建
smart_hand/titan_rtthread/smart_hand_uart.c
smart_hand/titan_rtthread/smart_hand_vision_state.c/.h      # 仅必要的小修
smart_hand/tests/test_smart_hand_sequence_guard_c.c          # 新建
smart_hand/tests/test_smart_hand_vision_state_c.c
smart_hand/host/run_all_checks.ps1
smart_hand/host/check_titan_sync.ps1
smart_hand/host/check_titan_linkage.ps1                      # 新建，只读 MAP/ELF 证据检查
smart_hand/tests/test_titan_linkage_check.py                 # 新建
smart_hand/README.md
smart_hand/LAB_BRINGUP_CHECKLIST.md
smart_hand/docs/TITAN_VISION_RUNTIME_INTEGRATION_RESULT_2026-08-12.md
smart_hand/docs/TITAN_SEQUENCE_AND_BUILD_RESULT_2026-08-13.md # 新建
smart_hand/competition_2026/evidence/ 下新的空白 UART 证据模板（如确有必要）
```

允许把规范运行时源文件的完全相同副本同步到：

```text
D:\Micu\RTTWorkspace\titan_uart_test\src\
```

不要修改 `Debug/*.mk`、ELF、MAP 或对象文件来伪造构建。构建产物只能由正常 Studio
Refresh/Clean/Build 或已确认等价的 IDE headless build 生成。

## 3. 阶段 A：实现纯 C 序号防重放模块

模块不得依赖 RT-Thread、UART、堆或文件系统。建议 API：

```c
void smart_hand_sequence_guard_init(...);
smart_hand_sequence_result_t smart_hand_sequence_guard_note(..., uint16_t sequence);
void smart_hand_sequence_guard_reset(...);
```

返回结果至少能区分 FIRST、IN_ORDER、FORWARD_GAP、DUPLICATE、OLD。判断规则与现有
Python `MotionSafetyGate._sequence_is_newer()` 一致：

```text
delta = (sequence - last_accepted) & 0xFFFF
delta == 0               -> duplicate
0 < delta < 0x8000       -> newer（delta==1 顺序；>1 gap）
delta >= 0x8000          -> old/ambiguous，拒绝
```

只有 FIRST/IN_ORDER/FORWARD_GAP 更新 `last_accepted`。DUPLICATE/OLD 不得改变基线。

测试至少覆盖：首次、连续、duplicate、old、forward gap、65535→0、0→65535 被视为 old、
半范围 `0x8000` fail closed、reset 后低序号重新作为 FIRST。

## 4. 阶段 B：UART fail-closed 接入

处理顺序建议：

1. parser 成功得到协议帧；
2. 检查该消息类型的 payload；
3. 若 VISION payload 非法：立即 invalidate，ACK=1，不记录/刷新序号和 link；
4. 若 PING payload 非法：ACK=1，不刷新任何状态；
5. payload 合法后交 sequence guard；
6. FIRST/IN_ORDER/GAP 才执行 `mark_link_alive` 和对应 PING/VISION 业务；
7. DUPLICATE/OLD 只回 ACK=0，并增加各自统计，不更新 link、vision 或 freshness；
8. link OFFLINE 时 invalidate vision 并 reset sequence guard。

注意：ACK=0 表示该重复/旧帧格式可理解且已被幂等忽略，不代表产生了新动作目标。日志
应能看到 ignored_duplicate / ignored_old。不要新增协议状态码。

移除或重构原 `record_sequence()`，避免同时维护两套互相冲突的序号状态。原 gaps、
duplicates 统计必须继续准确；建议新增 old_frames。

`sh_status` 至少显示：last accepted sequence 是否存在、值、gaps、duplicates、old。

## 5. 阶段 C：离线测试与持续安全边界

完成后应为：

- Python 测试不少于 90 个（新增 linkage checker 的单测时）；
- C 独立测试程序由 11 个增加到 12 个；
- 新序号测试全部通过；
- vision state 测试继续通过；
- 用静态或可主机编译的测试证明非法 VISION 会使已有 candidate/actionable 失效；
- 不支持/低置信/重复/旧序号都不能刷新 `last_vision_ms`；
- PING 仍不能刷新 vision freshness；
- 断联后 reset 序号并清视觉；
- `smart_hand_uart.c` 仍不存在 `scs0009`、运动规划或舵机 UART 写路径；
- 校准 CSV 仍只有表头，生产姿态仍全部未配置。

如果直接测试 RT-Thread 静态函数代价过大，应把“消息是否允许刷新业务状态”的规则放在
纯 C 模块中测试，不要通过 `#include smart_hand_uart.c` 和伪造大量 RT API 形成脆弱测试。

## 6. 阶段 D：同步检查扩展

把 `smart_hand_sequence_guard.c/.h` 纳入 `check_titan_sync.ps1`。同步检查必须覆盖 UART
实际链接所需的所有项目自有源和头文件，至少包括：协议、UART、vision_state、sequence
guard、grip_policy、grip_pose_bank、servo_safety_gate.h。

运行检查并保存 Match=True 结果。不要把“文件哈希一致”写成“已链接进 ARM 固件”。

## 7. 阶段 E：ARM 构建与链接证据

### 7.1 新增只读链接检查器

新建 `check_titan_linkage.ps1`，默认读取：

```text
D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.map
```

检查 MAP 的时间戳不得早于本批同步进 Studio 的最新 `.c` 时间；否则明确失败为 stale
build。MAP 中至少必须出现以下目标文件或关键符号：

```text
smart_hand_uart
smart_hand_protocol
smart_hand_vision_state
smart_hand_sequence_guard
grip_policy
grip_pose_bank
```

同时确认没有本批未授权的 SCS0009/servo execution 对象被 UART 路径新增引用。注意工程
中存在旧的其他对象不等于 UART 调用了它们；检查器应避免仅凭全局字符串做错误结论。

为检查器增加 Python 单测，使用临时假 MAP 覆盖：正常、缺符号、过期 MAP 三条路径。

### 7.2 尝试真实构建

优先使用 RT-Thread Studio：Refresh 工程 → Project Clean → Build。若 Grok 无法操作 GUI，
可以只读查找 IDE 可执行文件和已安装的 headless 参数；只有能确认等价于 Studio 工程构建
时才执行。不得直接运行旧 `Debug/makefile`，因为它可能未包含新增 `.c`。

构建成功后：

- 保存 `0 errors` 和 warnings 数；
- 运行 `check_titan_linkage.ps1`；
- 运行 `check_titan_resources.ps1`，记录新 Flash/RAM；
- 记录 MAP/ELF SHA-256 和时间；
- 不烧录、不连接 J-Link。

若无法真实构建：如实写“ARM Build 未执行”，但把下一次人工操作压缩成 5 步，并停止在
这个环境边界；不得把主机 GCC 当 ARM Build。

## 8. 阶段 F：准备首次无舵机实物联调

更新 `LAB_BRINGUP_CHECKLIST.md`，只准备、不执行以下路径：

1. Titan 仅 USB/J-Link 供电，舵机 6 V 电源保持关闭且不连接；
2. Maix 与 Titan 仅交叉 TX/RX/GND，禁止连接双方 5V/VBUS；
3. 先烧录并查看 Titan shell，运行 `list_device`、`sh_status`；
4. Maix 先用 mock 模式，禁止一开始用不稳定 YOLO；
5. 验证 PING 在线、三类 VISION 的 action 映射、空 pose 导致 actionable=0；
6. 验证重复/旧 VISION 被忽略且不刷新视觉年龄；
7. 停止 Maix VISION 但保留 PING，约 750 ms 出现 VISION_STALE；
8. 完全断开 TX，约 1500 ms 出现 OFFLINE；
9. 恢复后确认序号基线可重新建立，但不会自动产生动作；
10. 保存未剪辑终端输出、接线照片、固件哈希、时间和操作人。

操作卡必须反复标注：本批固件没有舵机写包能力，联调时不要连接舵机总线和 6 V。

## 9. 可以自行修复并继续的事项

- 序号回绕或半范围判断测试失败；
- duplicate/old 意外刷新 vision/link；
- 非法 VISION 没有清旧目标；
- 断联没有 reset 序号；
- 新 C 测试未纳入统一检查；
- 同步检查遗漏新增运行时文件；
- MAP 检查器对正常/缺符号/过期证据判断错误；
- README 测试数量、当前成熟度或操作卡表述过时；
- Studio 新增 `.c` 未自动纳入但可通过正常 Refresh/Clean/Build 解决。

## 10. 必须停止的条件

- 需要修改协议或启用 HELLO/BOOT_ID；
- 需要接入 SCS0009、servo_safety_gate 运行时或产生运动；
- 需要填写机械参数、姿态或安全停止策略；
- 需要手改 Debug makefile/对象/MAP 才能声称构建；
- 需要烧录或控制实体设备；
- 需要大规模重构现有模块 API；
- 完整本地检查无法恢复通过。

## 11. 统一验收

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\run_offline_rehearsal.py
pwsh -File smart_hand\host\check_titan_sync.ps1
```

如果 ARM Build 成功，再执行：

```powershell
pwsh -File smart_hand\host\check_titan_linkage.ps1
pwsh -File smart_hand\host\check_titan_resources.ps1
```

期望：全部适用检查通过，且离线演练仍为 `hardware_accessed=false`、
`physical_motion.authorized=false`。

## 12. 完成后一次性交付

1. 修改文件完整清单；
2. 两个安全缺口的修改前后行为；
3. sequence guard API 和所有边界测试；
4. invalid/duplicate/old/gap/rollover/断联恢复的处理表；
5. Python 与 C 测试数量和完整摘要；
6. 同步检查文件清单与结果；
7. ARM Build 是否真实执行，及 0 errors/warnings/资源/哈希；
8. linkage checker 正常、缺符号、过期 MAP 的测试证据；
9. 无舵机写包、空校准、空生产姿态的证明；
10. 首次无舵机联调操作卡更新摘要；
11. 剩余实物缺口；
12. 任何偏离及理由。

完成后停止，不烧录，不开始真实舵机执行层，交 Codex 最终判断是否达到纯通信固件上板边界。
