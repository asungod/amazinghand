# Grok 已授权离线实施包：Titan 视觉决策安全接线

日期：2026-08-12  
授权依据：`TITAN_RUNTIME_INTEGRATION_GAP_AUDIT_2026-08-12.md` 已由 Codex 核对，方向正确。  
执行方式：以下阶段连续完成后再交 Codex，不需要每个小步骤停下来询问。

## 1. 本批唯一总体目标

把 Titan 当前 `smart_hand_uart.c` 的 VISION 分支从“置信度大于等于 70 就打印
POWER_GRASP”的旧诊断，接入现有 `grip_policy` 与默认空白的 `grip_pose_bank`，并增加
独立于链路心跳的视觉目标过期机制。

本批结束时应做到：

- bottle(39)、cup(41)、remote(65) 映射到各自正确意图；
- 低置信、不支持类别和非法数据均不形成动作目标；
- 即使识别合法，生产姿态未配置时仍明确拒绝动作；
- PING 只能维持通信链路，不能让旧 VISION 永久保持新鲜；
- VISION 超时或通信断联时清除候选/可执行目标；
- 不接舵机 UART，不构造或发送 SCS0009 写包，不产生物理运动。

## 2. 允许修改范围

规范源：

```text
smart_hand/titan_rtthread/smart_hand_uart.c
smart_hand/titan_rtthread/smart_hand_vision_state.c       # 新建
smart_hand/titan_rtthread/smart_hand_vision_state.h       # 新建
smart_hand/tests/test_smart_hand_vision_state_c.c          # 新建
smart_hand/host/run_all_checks.ps1
smart_hand/host/check_titan_sync.ps1
smart_hand/README.md
smart_hand/docs/TITAN_RUNTIME_INTEGRATION_GAP_AUDIT_2026-08-12.md
smart_hand/docs/TITAN_VISION_RUNTIME_INTEGRATION_RESULT_2026-08-12.md # 新建
```

为保持 Studio 工程可最终构建，允许把以下规范文件的完全相同副本放入：

```text
D:\Micu\RTTWorkspace\titan_uart_test\src\
```

需要同步的文件至少包括：

```text
smart_hand_uart.c
smart_hand_vision_state.c
smart_hand_vision_state.h
grip_policy.c
grip_policy.h
grip_pose_bank.c
grip_pose_bank.h
servo_safety_gate.h       # grip_pose_bank.h 的类型依赖；本批不调用 safety gate
```

不要修改 Studio 的自动生成 `Debug/*.mk`、对象文件、ELF 或 MAP。新 `.c` 是否被 IDE
纳入工程，应由 RT-Thread Studio 刷新/清理构建生成，不得手改生成文件伪造成功。

## 3. 禁止事项

- 不修改校准 CSV，不给 `grip_pose_bank` 写入任何生产姿态。
- 不增加生产默认 FIXTURE、测试角度、软限位、方向、速度、负载、电压或温度阈值。
- 不 include 或调用 `scs0009_*`、`servo_safety_gate`、`servo_feedback_poll`、
  `servo_motion_monitor` 的运行时写包/运动路径。
- 不打开串口，不运行舵机脚本，不使用 J-Link，不声称 Titan 真机已验证。
- 不修改协议帧格式，不加入 HELLO，不修改 Maix Python 端。
- 不增加执行状态机完整移植、NPU 模型、机械臂、FPGA 或云端功能。
- 不把测试数据称为真实参数。

## 4. 阶段 A：新增可主机测试的纯 C 状态模块

新建 `smart_hand_vision_state.c/.h`。该模块不得 include RT-Thread，也不得访问 UART、
GPIO、文件或堆内存。

推荐职责：

```text
init
  -> grip_pose_bank_init，生产姿态默认全部未配置

note_vision(payload, now_ms)
  -> grip_policy_decide
  -> grip_pose_bank_resolve
  -> 保存最后决策、原因和姿态解析结果
  -> 只有 pose resolve == OK 才标记 actionable
  -> 任何拒绝/错误都清除旧 actionable 和旧 targets

expire(now_ms, timeout_ms)
  -> 使用 uint32_t 无符号差值处理时钟回绕
  -> 过期时清除视觉候选、actionable 和旧 targets

invalidate
  -> 断联时清除视觉候选、actionable 和旧 targets
  -> 不把生产 pose bank 悄悄配置为可用
```

允许状态结构持有：默认空 pose bank、最后决策、pose result、最后 VISION 时间、
`have_vision`、`have_actionable_target` 和仅在 resolve 成功时有效的逻辑 targets。

不要提供会在生产中绕过校准的“自动配置姿态”函数。测试若需要验证 pose=OK，只能在
测试文件中直接设置明确标注的 FIXTURE，且不得写入生产源或 CSV。

## 5. 阶段 B：纯模块测试

新增 `test_smart_hand_vision_state_c.c`，至少覆盖：

1. init 后三种姿态全未配置，actionable=false；
2. 39/41/65 的 policy 映射正确，但空 pose bank 全部因 NOT_CONFIGURED 而不可执行；
3. 高置信不支持类别为 NO_ACTION，不能沿用上一次目标；
4. 低置信目标为 NO_ACTION，不能沿用上一次目标；
5. 非法 payload fail closed；
6. 测试专用 FIXTURE pose 可证明 resolve=OK，但只能存在测试文件；
7. 在曾经 actionable 后收到拒绝目标，会立即清除旧 targets/actionable；
8. 只有 PING 的等价时间推进不能刷新 vision 时间；视觉约 750 ms 后失效；
9. `uint32_t` 毫秒回绕附近的过期判断正确；
10. invalidate 后候选、actionable、targets 全部失效；
11. null 指针、0 timeout 等边界 fail closed，不产生目标。

把该测试加入 `run_all_checks.ps1`，失败必须返回非零。完成后 C 测试程序数量应由 10
变为 11，README 必须同步更新。

## 6. 阶段 C：接入 `smart_hand_uart.c`

接入原则：协议有效性、策略接受、姿态可用性是三个不同层次。

### 合法 VISION 帧

- 现有 `vision_payload_valid` 继续做协议载荷范围检查；
- 协议合法后仍 `mark_link_alive`，并 ACK status=0；
- 把六个参数转换为 `grip_vision_payload_t` 并交给纯状态模块；
- 日志必须分别显示 action、policy reason、pose result、actionable；
- 不支持类别或低置信是“协议帧有效但业务拒绝”，不得错误 ACK 为 CRC/格式失败；
- 删除“任意 confidence>=70 都打印 POWER_GRASP”的旧逻辑。

### PING 与时间

- PING 只刷新通信链路时间，不刷新视觉目标时间；
- 通信链路超时继续沿用约 1500 ms；
- 视觉目标过期时间使用已有设计基线 750 ms，并以命名宏表达；这是通信新鲜度参数，
  不是机械参数；
- 每次接收循环都应检查视觉过期，即使 PING 持续到达。

### 失效与状态输出

- 链路从 ONLINE 进入 OFFLINE 时调用 vision state invalidate；
- 视觉过期时清除旧目标，不能因 PING 在线继续显示 actionable；
- `sh_status` 分开显示 link online/age 与 vision present/age/action/reason/pose/actionable；
- 原有效帧、无效帧、payload、sequence gap、duplicate、tx failure、offline 统计不能回归；
- 可以新增 policy rejected、pose unavailable、vision expired 等诊断计数，但不要改变协议。

### 本批最重要的硬边界

即使测试 FIXTURE 可以得到 pose OK，`smart_hand_comm_init` 创建的生产状态必须调用正常
init，保持 pose bank 空白。因此真实运行时 `actionable` 仍应为 false，且文件中不应有
任何 SCS0009 写包调用。

## 7. 阶段 D：同步与构建边界

1. 先修改规范源并通过主机测试。
2. 将本任务第 2 节列出的依赖文件原样复制到 Studio `src`。
3. 扩展 `check_titan_sync.ps1`，让它至少核对上述八个运行时文件的 SHA-256，而不是仍只
   核对旧的三个文件。
4. 运行 `check_titan_sync.ps1`，所有列出文件必须一致。
5. 如果能通过 RT-Thread Studio 正常刷新、Clean、Build，则保存完整结果和新资源占用。
6. 如果只能使用旧的 `Debug/src/subdir.mk`，不要手改它，也不要声称新文件已被固件链接；
   把“需在 Studio 中刷新后重建”列为环境级待验证项。主机 GCC 测试通过不能替代 ARM
   工程链接。

## 8. 阶段 E：统一验证与结果文档

运行：

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\run_offline_rehearsal.py
```

期望：

- Python 仍不少于 89 个并全部通过；
- C 测试程序变为 11 个并全部通过；
- Titan 扩展后的源同步检查通过；
- 离线演练 `hardware_accessed=false`；
- `physical_motion.authorized=false`，原因仍为校准不完整；
- 校准 CSV 与生产 pose bank 仍为空白/未配置；
- 项目中没有从 `smart_hand_uart.c` 到 `scs0009_build_*` 或 UART 舵机写入的调用路径。

新建 `TITAN_VISION_RUNTIME_INTEGRATION_RESULT_2026-08-12.md`，记录：

- 修改前后运行时调用路径；
- 正常路径、拒绝路径、目标过期路径和断联路径；
- 测试数量和命令；
- 同步到 Studio 的文件；
- Studio ARM Build 是否真实执行，若没有必须写“未执行”；
- 仍待实物的全部接口；
- 明确声明本批没有物理写包能力。

同步更新 README 和原 gap audit 的状态，但不要删除历史审计结论；可标注哪些缺口本批已
在规范源完成、哪些仍待 Studio 构建和真机。

## 9. 无需中途询问的修复权限

如果测试暴露以下问题，可直接在本批允许范围内修复并继续：

- null、非法 payload 或拒绝目标没有清旧 actionable；
- PING 意外刷新视觉 freshness；
- 视觉超时没有清 targets；
- `uint32_t` 回绕判断错误；
- ACK/统计因接线发生回归；
- `run_all_checks.ps1` 没有正确纳入新 C 测试；
- `check_titan_sync.ps1` 没有覆盖新增运行时依赖；
- README 测试数字或成熟度陈述过时。

## 10. 必须停止并交 Codex 的条件

遇到下列任一情况，不扩大范围：

- 需要真实舵机参数或安全停止策略才能继续；
- 需要修改 Maix 协议或 Python 发送端；
- 需要调用 SCS0009、开启舵机 UART 或产生运动；
- 需要完整移植执行状态机或新增线程体系；
- 发现已有模块 API 必须破坏性重构；
- Studio 工程需要手改自动生成 Debug makefile 才能伪装构建成功；
- 基线中出现与本批无关的用户文件冲突；
- 完整检查无法恢复通过。

## 11. 最终一次性交付格式

做完阶段 A～E 后再返回：

1. 修改文件完整列表；
2. 纯状态模块的 API 和 fail-closed 规则；
3. UART 修改前后路径；
4. 新增的 11 项以上状态模块测试路径；
5. Python/C 测试数量和完整摘要；
6. `check_titan_sync` 的文件清单与结果；
7. Studio ARM 工程是否真实 Clean/Build；不能用主机测试代替；
8. 搜索证明 `smart_hand_uart.c` 没有 SCS0009 写包调用；
9. 校准 CSV 与生产 pose bank 仍未配置的证明；
10. 剩余实物缺口；
11. 任何偏离本任务书之处及理由。

完成本任务书后停止，不继续实现真实舵机执行层。把结果交 Codex 做下一次方向核验。
