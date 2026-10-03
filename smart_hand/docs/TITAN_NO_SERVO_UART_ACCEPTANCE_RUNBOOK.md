# Titan 无舵机 UART 验收操作卡

日期：2026-08-13  
工具：`host/titan_uart_acceptance.py`（默认 dry-run）  
硬边界：**舵机 6V 关闭且总线不连接**；双方 **不接 5V/VBUS**；本卡不授权自动烧录。

## 0. 电脑门禁（先做）

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\titan_uart_acceptance.py --dry-run
pwsh -File smart_hand\host\check_titan_sync.ps1
```

Studio 人工：

1. Refresh `titan_uart_test`  
2. Clean  
3. Build（0 errors）  
4. `pwsh -File smart_hand\host\check_titan_linkage.ps1`（**函数级**符号）  
5. `pwsh -File smart_hand\host\check_titan_resources.ps1`  

未通过函数级 linkage / 资源检查 → **停止，不烧录**。

## 1. 烧录阶段（不接 Maix、不接舵机）

- Titan 仅 USB 和/或 J-Link 供电  
- **不连接** Maix TX/RX  
- **不连接** 舵机总线与 6V  
- 烧录后只看 UART1 控制台：启动日志含 policy+seq guard / no servo write  
- `list_device`、`sh_status`

## 2. 接线（仍无舵机）

```text
Maix A21 TX -> Titan UART2 RX
Maix A22 RX <- Titan UART2 TX
GND        -- GND
```

- 禁止 5V/VBUS  
- 舵机电源保持关闭、总线完全断开  

## 3. 联调顺序

1. Maix `VISION_MODE=mock`  
2. 观察 Titan `sh_status` / VISION 日志  
3. 可选：在**后续明确授权**后使用  
   `titan_uart_acceptance.py --port COMx --live-no-servo-confirmed`  
   （本批工具实现了门槛但**禁止实际 live 运行**）  
4. 注入/观察故障帧前后保存未剪辑终端  

## 4. 断言与证据类型

| 断言 | ACK | Titan shell | 计时观察 |
|------|-----|-------------|----------|
| PING ACK0 / link | 需要 | link=ONLINE | — |
| 三类 action + actionable=0 | 需要 | VISION 日志 | — |
| 低置信/不支持 NO_ACTION | 需要 | reason= | — |
| 非法 payload ACK1 清视觉 | 需要 | invalid/clear | — |
| duplicate/old 忽略 | 需要 | ignored_* | — |
| forward gap | 需要 | gaps++ | — |
| ~750ms STALE | **不够** | VISION_STALE | **需要** |
| ~1500ms OFFLINE | **不够** | OFFLINE + seq reset | **需要** |
| offline 后 FIRST | 需要 | sequence 基线 | 配合 shell |

**不得**仅凭 PC 端 ACK 宣布 750/1500ms 项通过。

## 5. 失败处理

- 断开 Maix–Titan 通信线  
- **不要**接舵机“继续验证”  
- 保存日志、固件/MAP 哈希、时间、操作人  
- 回电脑用 dry-run / 离线日志工具复盘  

## 6. 证据模板

填写：`competition_2026/evidence/titan_uart_acceptance_template.json`  
所有结论默认 `not_run`，禁止预填 pass。
