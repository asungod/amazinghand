# UART2 针脚证据审计（2026-08-14）

> 作者：grokA。本文件只审计本地资料与现有软件配置，**不裁决**互相冲突的条目，也不给出带电试脚指令。  
> 本批 `hardware_accessed=false`。真机短时双向 ACK 见 `validation_reports/uart2_bidirectional_acceptance_2026-08-14.md`（用户终端、主模型审核，不是本文件作者上机）。

## 0. 审计范围与证据等级

| 等级 | 含义 |
|---|---|
| `SCHEMATIC` | 本地原理图/拆页可直接读到网络名与连接器针号 |
| `SOFTWARE` | 仓库规范源或 BSP/FSP 配置写明设备名/引脚功能 |
| `PROJECT_DOC` | 项目接线卡/交接文档，不是原厂手册 |
| `HARDWARE_SESSION` | 2026-08-14 用户提供、主模型审核的真机终端 |
| `UNVERIFIED` | 本地官方资料不足以确认；禁止补全 |

工作区内**未找到** MaixCAM2 原厂针脚 PDF / 丝印图；Maix 侧丝印 `U2T/U2R` 与芯片名 `B0/B1` 的电气对应只能标 `UNVERIFIED`（官方资料缺失），不得写成已由本审计证明。

## 1. MaixCAM2

| 芯片信号名 | 板上网络名 | 连接器及物理针号 | 用户肉眼位置 | 证据等级 | 来源 |
|---|---|---|---|---|---|
| `UART2_TX`（软件功能名） | 软件配置为 `B0` | 前面板 UART2 的 TX 侧；丝印是否为 `U2T` = `UNVERIFIED` | 外壳正面 UART2 排针，具体哪一根相对外壳朝向 = `UNVERIFIED` | `SOFTWARE` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\smart_hand\maixcam2\main.py` 第 15、37–46 行：`UART_DEVICE="/dev/ttyS2"`，`pinmap.set_pin_function("B0","UART2_TX")` |
| `UART2_RX`（软件功能名） | 软件配置为 `B1` | 前面板 UART2 的 RX 侧；丝印是否为 `U2R` = `UNVERIFIED` | 同上，肉眼左右 = `UNVERIFIED` | `SOFTWARE` | 同上，`pinmap.set_pin_function("B1","UART2_RX")` |
| UART 设备节点 | `/dev/ttyS2` | 不适用 | 不适用 | `SOFTWARE` | `main.py:15`；`host\check_maix_deploy.py:42-43` 强制保持 `/dev/ttyS2` |
| 历史 UART4 TX | `A21` / `UART4_TX` | 裸板/隐藏 UART4，**不是**当前生产入口 | 与正面 UART2 不是同一组针 | `SOFTWARE` | `maixcam2\uart4_open_probe.py` 第 10–22 行：`DEVICE="/dev/ttyS4"`，`A21`/`A22` |
| 历史 UART4 RX | `A22` / `UART4_RX` | 同上 | 同上 | `SOFTWARE` | 同上 |
| 外壳丝印 `U2T`/`U2R` | `UNVERIFIED` | `UNVERIFIED` | 项目文档写成正面 UART2 | `UNVERIFIED` | 工作区无 Sipeed 官方 pinout PDF。`HARDWARE_WIRING_CARDS.md` 卡 3 把 `U2T/B0`、`U2R/B1` 写成同一针，证据等级仅 `PROJECT_DOC` |

功能侧旁证（不能代替官方针脚图）：2026-08-14 在 **H1 三线交叉、不接 VCC** 下，Maix 生产入口 `/dev/ttyS2` 已出现 `sent=104/acked=104`。这只证明当前软件 UART2 路径能和 Titan `uart2` 交换帧，**不证明** `U2T` 丝印等于 `B0`。

## 2. Titan Mini

### 2.1 芯片球 / 板上网络（原理图 MCU 页）

| 芯片信号名 | 板上网络名 | 封装球位 | 用户肉眼位置 | 证据等级 | 来源 |
|---|---|---|---|---|---|
| `TXD2` | `TXD2` | `P801`，文本提取为 `P6` | MCU 本体，用户不可直接当接线点 | `SCHEMATIC` | `C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网\tmp\pdfs\titan_mini_schematic.txt` 约第 260 行；拆页 `tmp\pdfs\titan_page03.png`；原件 `tmp\titan_bsp\sdk-bsp-ra8p1-titan-mini-main\docs\Titan_Mini_schematic_v1.0.pdf` |
| `RXD2` | `RXD2` | `P802`，文本提取为 `R6` | 同上 | `SCHEMATIC` | 同上，约第 262 行 |

`bsp_pin_cfg.h` 里的 `ETHERNET_TXD2`/`ETHERNET_RXD2` 是 **RGMII 以太网** 数据位（`P305`/`P908`），**不是** H1 的 `TXD2`/`RXD2`。不得把这两条宏当成 UART2 接线依据。

### 2.2 独立三针接口 H1（原理图 INTERFACE 页，Id 13/13）

| 芯片信号名 | 板上网络名 | 连接器及物理针号 | 用户肉眼位置 | 证据等级 | 来源 |
|---|---|---|---|---|---|
| 地 | `GND` | `H1` 原理图针号 `1` | 板载独立三针插座；**朝向/哪一头是 pin1 对用户当前握持方向** = `UNVERIFIED` | `SCHEMATIC`（针号）；肉眼朝向 `UNVERIFIED` | `titan_mini_schematic.txt` 约 1147–1169 行：标题 `UART`，`H1`，`1 1` 旁为 `GND`（DNP 标注在附近，需对照原 PDF）；`titan_page13.png` |
| `RXD2` | `RXD2` / `P802` | `H1` 原理图针号 `2` | 同上 | `SCHEMATIC` | 同上，`2 2 RXD2` |
| `TXD2` | `TXD2` / `P801` | `H1` 原理图针号 `3` | 同上 | `SCHEMATIC` | 同上，`3 3 TXD2` |

原理图页脚：`Sheet: /` `File: INTERFACE.kicad_sch` `Title: INTERFACE` `Rev: HW:V1.0` `Id: 13/13` `Date: 2026-03-26`。

### 2.3 软件设备名 `uart2`

| 名称 | 内容 | 证据等级 | 来源 |
|---|---|---|---|
| 规范源设备名 | `#define SMART_HAND_UART_NAME "uart2"` | `SOFTWARE` | `smart_hand\titan_rtthread\smart_hand_uart.c` 第 9–10 行 |
| BSP 开关 | `#define BSP_USING_UART2`，RX 缓冲 256，TX 缓冲 0 | `SOFTWARE` | `tmp\titan_bsp\...\project\Titan_Mini_template\rtconfig.h` 第 366–368 行 |
| FSP/HAL 登记 | `UART2_CONFIG` 的 `.name = "uart2"` | `SOFTWARE` | `tmp\titan_bsp\...\libraries\HAL_Drivers\config\ra8\uart_config.h` 第 43–51 行 |
| 启动日志（历史真机） | `smart_hand: listening on uart2 at 115200 ...` | `HARDWARE_SESSION` / 既有交接 | 发热边界文档 §2.1；`LAB_BRINGUP_CHECKLIST.md` |

FSP `uart_config.h` **只登记设备名**，不写 `P801`/`P802`。芯片脚到 `uart2` 的绑定以原理图网络 + Studio 引脚配置为准；本审计未在 `pin_data.c` 检索到 `P801`/`P802` 字符串。

## 3. 必须分开的接口（危险冲突）

| 接口 | 用途 | 与 UART2 链路关系 | 危险点 |
|---|---|---|---|
| **H1 独立三针** | Titan UART2：`GND` / `RXD2` / `TXD2` | **当前正确链路接口** | 唯一应用于 Maix↔Titan 通信的 Titan 侧插座 |
| **40 针 U18** | 含 UART1 控制台等（项目卡：pin8 `TXD1`、pin10 `RXD1`、pin6 `GND`） | **不是** UART2 链路 | 修订任务书要求写明：40 针 pin1 是**电源网络而非 GND**。本审计在 `titan_mini_schematic.txt` 中**未能抽出 U18 pin1 的精确网络名**，故网络名 = `UNVERIFIED`；**禁止**把 40 针 pin1 当 H1 pin1 或当 GND。历史发热与误把 40 针电源脚当 GND 相关 |
| Titan UART1 + USB-TTL | 控制台 `115200 8N1` | 调试口，不是两板链路 | 只接 TX/RX/GND，不接 USB-TTL 的 VCC |
| Maix UART4 `A21/A22` `/dev/ttyS4` | 历史单板打开探针 | **已不是**生产入口 | `uart4_open_probe.py` 保留作历史工具；`README.md` 在本批修订前仍把它写成“官方推荐”，属于文档过时，不是第二套生产接线 |

H1 与 40 针 U18 **不得混为一谈**。不得在 40 针上“找三个脚当 UART2”。

## 4. 文档互相冲突（只列，不裁决）

1. **生产入口 UART2 vs 历史 UART4**  
   - `main.py` / `check_maix_deploy.py` / 卡 3 / 检查表 §3：`B0/B1`、`/dev/ttyS2`。  
   - `README.md`（修订前）§MaixCAM2 上板、`uart4_open_probe.py`、`AmazingHand_MaixCAM2_Titan_完整上下文交接_2026-08-11.md` §7.3、`docs\TITAN_NO_SERVO_UART_ACCEPTANCE_RUNBOOK.md`：`A21/A22` UART4。  
   冲突成立。当前规范源以 `main.py` 为准；UART4 文件是历史探针。

2. **H1 原理图针号 vs 用户肉眼 pin1**  
   原理图：H1-1 `GND`，H1-2 `RXD2`，H1-3 `TXD2`。  
   用户板在当前朝向下“哪一根肉眼是 pin1”仍为 `UNVERIFIED`。2026-08-14 短时闭环只能证明**当时那组三线**工作，不能单独证明丝印方向。

3. **以太网 `TXD2` 宏 vs UART `TXD2` 网络**  
   见 §2.1。名称撞车，对象不同。

4. **旧“0 帧 / acked=0” vs 2026-08-14 双向 ACK**  
   发热当日曾记录 Titan `valid=0`、Maix `acked=0`（当时可能接错 40 针）。  
   之后在 **H1** 上出现短时双向 ACK。两份都是历史证据，后者更新；前者不得删。

## 5. 2026-08-14 已验证 / 仍未验证

| 项目 | 状态 |
|---|---|
| Titan 烧录 + UART1 控制台 | 已验证（pyOCD / WCH-Link，监听 `uart2`） |
| 正确接口是 **H1**，不是 40 针 U18 | 项目结论；原理图支持 H1 = UART2 |
| H1 三线交叉、不接 3V3/5V，15 秒无发热 | 已记录；**不能**外推长期热安全 |
| Maix↔Titan UART2 **短时双向闭环** | 已验证：`sent=104/acked=104`，`timeout=0`，`malformed=0`，`rx_errors=0`；ACK 后续到 `seq=129` |
| 官方针脚图证明 `U2T=B0`、`U2R=B1` | `UNVERIFIED` |
| H1 对用户当前朝向的肉眼 pin1 | `UNVERIFIED` |
| 10 分钟压力、断联恢复、舵机、姿态、校准 | 未验收 |
| 两板之间连接 VCC | **禁止** |

建议后续接线只引用：**H1 网络名 `GND`/`RXD2`/`TXD2`** + 实物 pin1 标记；不要引用 40 针针号，也不要再写 A21/A22 作为生产链路。
