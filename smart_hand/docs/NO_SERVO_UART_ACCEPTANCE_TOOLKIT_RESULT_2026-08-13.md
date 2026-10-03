# 无舵机 UART 离线验收工具包结果（2026-08-13）

## 关于任务书原文

原文件 `GROK_NO_SERVO_UART_ACCEPTANCE_TOOLKIT_2026-08-13.md` 曾被误覆盖。  
本批按用户消息硬约束重建并完成：

- 禁止 live 模式  
- 禁止访问串口  
- 禁止烧录  
- 禁止修改 Titan 生产运行时 C  

对齐既有协议（`maixcam2/protocol.py` ASCII `$TYPE,seq*CRC`）与  
`LAB_BRINGUP_CHECKLIST.md` / 序号防重放批的验收语义。

## 阶段 A：目录与框架

| 路径 | 作用 |
|------|------|
| `host/no_servo_uart_acceptance.py` | 核心：序号守卫、空 pose 视觉状态、场景评分、日志抽帧、uart.c 静态无写包证明 |
| `host/accept_uart_frame.py` | 兼容入口（转调 core，不开串口） |
| `tests/test_no_servo_uart_acceptance.py` | 单元/场景/CLI 测试 |
| 本结果文档 | 交付记录 |

## 阶段 B：行为模型（主机镜像，非 RTOS）

1. 协议合法 VISION → policy → 空 pose → **actionable 恒 false**  
2. 非法 VISION payload → 立即清候选，ACK status=1  
3. DUPLICATE/OLD → ACK=0，不刷新 vision 时间  
4. PING 只维持 link，**不**刷新 `last_vision_ms`  
5. 750 ms → VISION_STALE  
6. 1500 ms 无合法业务帧 → OFFLINE + sequence reset  
7. 65535→0 回绕接受  

## 阶段 C：内置场景（8）

- `ping_link_only`  
- `class_mapping_empty_pose`  
- `reject_low_and_unsupported`  
- `invalid_vision_clears`  
- `duplicate_and_old`  
- `stale_with_ping`  
- `offline_resets_sequence`  
- `rollover_65535_to_0`  

## 阶段 D：验收接入

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\no_servo_uart_acceptance.py --prove-no-servo-write
python -m unittest smart_hand.tests.test_no_servo_uart_acceptance -v
# 从已保存终端日志离线抽帧（仍无串口）：
python smart_hand\host\no_servo_uart_acceptance.py --log-file path\to\console.txt
```

## 硬边界声明

| 项 | 状态 |
|----|------|
| `hardware_accessed` | false |
| `serial_opened` | false |
| Titan 生产 C 修改 | **无** |
| 烧录 / J-Link | **无** |
| 舵机写包 | uart.c 静态扫描无 scs0009/plan/motion 命中 |

## 仍待实物

- Studio ARM Build 新 MAP  
- 批准后的无舵机烧录与 Maix mock 真机联调  
- 用本工具对**真实终端日志**做离线复盘（需人工采集日志文件）
