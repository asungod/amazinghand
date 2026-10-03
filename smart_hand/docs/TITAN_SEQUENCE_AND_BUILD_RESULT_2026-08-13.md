# Titan 序号防重放、非法目标失效与 ARM 构建证据（2026-08-13）

任务书：`GROK_SEQUENCE_FAILSAFE_AND_ARM_BUILD_BATCH_2026-08-13.md`

## 1. 两缺口修改前后

### 缺口一：非法 VISION payload

| | 前 | 后 |
|--|----|----|
| 行为 | ACK=1，计 invalid_payloads，**不清**旧目标 | 立即 `invalidate` 候选/actionable/targets；ACK=1；**不**刷新 link/序号/视觉时间 |
| CRC 坏帧 | 仍仅计 invalid_frames | 不变（依赖 750 ms freshness，避免噪声抖动） |

### 缺口二：重复/旧序号

| | 前 | 后 |
|--|----|----|
| 行为 | 仅统计，仍 `note_vision` 刷新时间 | `sequence_guard`：DUPLICATE/OLD 只 ACK=0 + 日志，**不** mark_link / note_vision |
| 接受 | 任意序号推进 last | FIRST / IN_ORDER / FORWARD_GAP 才接受 |
| 断联 | 仅清 vision | 清 vision **并** `sequence_guard_reset` |

## 2. sequence guard API

- `smart_hand_sequence_guard_init`
- `smart_hand_sequence_guard_note` → FIRST | IN_ORDER | FORWARD_GAP | DUPLICATE | OLD  
  规则：`delta=(seq-last)&0xFFFF`；0→dup；`0<d<0x8000`→newer；`d>=0x8000`→old
- `smart_hand_sequence_guard_reset`（断联后允许新 FIRST）

## 3. 处理表

| 事件 | ACK | link | vision | seq 基线 |
|------|-----|------|--------|----------|
| VISION 合法 + FIRST/IN_ORDER/GAP | 0 | 刷新 | note_vision | 更新 |
| VISION 合法 + DUPLICATE/OLD | 0 | 不 | 不 | 不更新 |
| VISION 非法 payload | 1 | 不 | **invalidate** | 不 |
| PING 合法 + 接受 | 0 | 刷新 | 不刷新 freshness | 更新 |
| PING 非法 | 1 | 不 | 不 | 不 |
| PING/VISION dup/old | 0 | 不 | 不 | 不 |
| 750 ms 无新 VISION | — | 可 ONLINE | expire 清除 | 不变 |
| 1500 ms 无合法帧 | — | OFFLINE | invalidate | **reset** |
| 65535→0 | 0 | 可 | 可 | 接受 IN_ORDER |
| 0→65535 | 0 | 不 | 不 | OLD |

## 4. 测试与命令

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\run_offline_rehearsal.py
pwsh -File smart_hand\host\check_titan_sync.ps1
```

- Python：不少于 **90**（原 89 + linkage 3 条）  
- C 程序：**12**（+ sequence_guard）  
- 离线演练：`hardware_accessed=false`，`physical_motion.authorized=false`

## 5. 同步清单

`check_titan_sync.ps1` 覆盖：protocol c/h、uart、vision_state c/h、sequence_guard c/h、
grip_policy c/h、grip_pose_bank c/h、servo_safety_gate.h。  
**哈希一致 ≠ 已链接 ARM 固件。**

## 6. ARM Build

**未执行成功。**

- 已找到 `D:\RT-ThreadStudio\eclipsec.exe`，尝试 CDT headless `-cleanBuild titan_uart_test`，
  **5 分钟超时退出**，`Debug/rtthread.map` 时间仍为 **2026-08-10**（早于本批源）。
- **未**手改 Debug makefile / 对象 / MAP。
- 主机 GCC 通过 **不能** 代替 ARM Build。

### 人工 5 步（下次）

1. 打开 RT-Thread Studio → 工作空间 `D:\Micu\RTTWorkspace`  
2. 对 `titan_uart_test`：**Refresh**（确认 src 含 sequence_guard / vision_state 等）  
3. **Project → Clean**  
4. **Build**，记录 0 errors / warnings  
5. 电脑执行：  
   `pwsh -File smart_hand\host\check_titan_linkage.ps1`  
   `pwsh -File smart_hand\host\check_titan_resources.ps1`  
   保存 MAP/ELF 哈希与时间；**不烧录**

## 7. linkage checker

`host/titan_linkage_check.py` + `check_titan_linkage.ps1`  
单测三条：正常全符号 / 缺 sequence_guard / 过期 MAP → 均 FAIL/OK 符合预期。

当前真实 MAP：预期 **stale**（源已新、MAP 旧）。

## 8. 无写包 / 空校准 / 空姿态

- `smart_hand_uart.c` 无 `scs0009` / plan / motion 写路径  
- 校准 CSV 仅表头  
- 生产 `vision_state_init` → pose 全未配置  

## 9. 无舵机联调卡

已写入 `LAB_BRINGUP_CHECKLIST.md` §0 与 §5 扩展（STALE / dup / old / OFFLINE reset）。

## 10. 剩余缺口

- Studio 成功 ARM Build + 新 MAP 链接证据  
- 批准后的无舵机烧录与 Maix mock 联调  
- 机械校准、舵机执行层（另批授权）

## 11. 偏离

- Headless ARM 构建超时失败 → 如实记录未执行，不伪造。  
- linkage 对“工程内是否存在无关 scs0009 对象”不做全局误杀，只要求 UART 路径必需符号出现在 **新** MAP 中。
