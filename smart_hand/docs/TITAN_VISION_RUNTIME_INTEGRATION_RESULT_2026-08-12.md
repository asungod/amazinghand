# Titan 视觉决策安全接线结果（2026-08-12）

授权任务书：`GROK_AUTHORIZED_OFFLINE_IMPLEMENTATION_BATCH_2026-08-12.md`  
依据审计：`TITAN_RUNTIME_INTEGRATION_GAP_AUDIT_2026-08-12.md`

## 1. 修改前后运行时调用路径

### 修改前
```text
VISION 合法
  -> mark_link_alive + ACK0
  -> grip = (conf>=70) ? "POWER_GRASP" : "NO_ACTION"   // 旧诊断
  -> 存 g_last_vision
  -> 无 policy / pose / 过期独立于 PING
断联: g_link_online=false；不清视觉目标
```

### 修改后
```text
VISION 合法
  -> mark_link_alive + ACK0（业务拒绝仍 ACK0）
  -> grip_vision_payload_t
  -> smart_hand_vision_state_note_vision
       -> grip_policy_decide
       -> grip_pose_bank_resolve（生产 bank 默认未配置）
       -> 仅 pose==OK 才 actionable；否则清旧 targets
  -> 日志: action / reason / pose / actionable

每次 RX 循环:
  -> smart_hand_vision_state_expire(now, 750ms)   // 与 PING 无关
  -> 链路 1500ms 超时 -> invalidate 视觉候选

PING: 只刷新 link，不刷新 last_vision_ms
生产 init: smart_hand_vision_state_init -> pose 全未配置 => actionable 恒 false
无 scs0009_* / safety_gate plan / 舵机写包
```

## 2. 路径覆盖

| 路径 | 行为 |
|------|------|
| 正常（空姿态） | 39/41/65 得正确 action；pose=NOT_CONFIGURED；actionable=0 |
| 拒绝 | 低置信/不支持/非法 → policy 拒绝；清旧 actionable；ACK 仍为 0 |
| 目标过期 | 无新 VISION 时 750ms 后 clear；PING 不能续命 |
| 断联 | ONLINE→OFFLINE 调用 invalidate；清候选与 actionable |
| FIXTURE（仅测试） | 可证明 pose=OK；生产源无 configured=1 |

## 3. 测试数量与命令

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\run_offline_rehearsal.py
```

- Python：**89** 全部通过  
- C 测试程序：**11** 全部通过（新增 `test_smart_hand_vision_state_c`）  
- `ALL LOCAL CHECKS PASSED`  
- `OFFLINE SINGLE-FINGER REHEARSAL PASSED`  
  - `hardware_accessed=false`  
  - `physical_motion.authorized=false`（calibration must contain exactly 2 rows）

## 4. 同步到 Studio 的文件

复制到 `D:\Micu\RTTWorkspace\titan_uart_test\src\`（与规范源 SHA-256 一致）：

- smart_hand_uart.c  
- smart_hand_vision_state.c / .h  
- grip_policy.c / .h  
- grip_pose_bank.c / .h  
- servo_safety_gate.h（类型依赖 only）  
- smart_hand_protocol.c / .h（既有协议）

`check_titan_sync.ps1` 现核对上述 **10** 个文件，本批结果：**全部 Match=True**。

## 5. Studio ARM Build

**未执行。**  
未手改 `Debug/*.mk`。主机 GCC 通过不能替代 ARM 链接。  
待办：在 RT-Thread Studio 中刷新工程使新 `.c` 进入构建，再 Clean/Build；确认 `grip_policy.c`、`grip_pose_bank.c`、`smart_hand_vision_state.c` 被链接。

## 6. 无物理写包能力（证明）

对 `smart_hand_uart.c` 检索 `scs0009`、`servo_safety_gate_plan`、`servo_motion`、`servo_feedback`：**无匹配**。  
运行时 include 仅：protocol、grip_policy、vision_state（pose_bank 经 vision_state）。

## 7. 校准与生产姿态仍空白

- `config/servo_calibration_template.csv`：仅表头，无数据行  
- `smart_hand_vision_state_init` → `grip_pose_bank_init`：三 profile `configured=0`  
- 规范 `titan_rtthread/` 内无生产 `configured = 1`

## 8. 仍待实物

- Studio 刷新后 ARM Clean/Build 与 Flash/RAM  
- J-Link 烧录、Maix↔Titan UART 联调  
- 舵机 UART/半双工/timeout/period  
- 软限位、方向、三种实测姿态  
- 装连杆冒烟与安全停止策略  
- 真实 `actionable=true` 路径（需校准后配置 pose，另批授权）

## 9. 声明

本批**没有**物理写包能力，**没有**实现真实舵机执行层，**没有**填写机械参数。  
结果交 Codex 做下一次方向核验。

## 10. 2026-08-13 续作（不删除上文）

已另批完成：非法 VISION payload 立即 invalidate；16 位序号防重放（dup/old 不刷新）；
断联 reset 序号基线。详见 `TITAN_SEQUENCE_AND_BUILD_RESULT_2026-08-13.md`。  
ARM Studio Build 仍未成功取得新 MAP 链接证据。
