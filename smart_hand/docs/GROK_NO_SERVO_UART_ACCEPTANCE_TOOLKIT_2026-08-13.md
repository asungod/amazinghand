# Grok 离线实施包：无舵机 UART 验收工具与函数级 ARM 链接证据

日期：2026-08-13  
前置结论：序号防重放、非法 VISION 失效、视觉过期和断联重置已通过主机测试；当前
92 个 Python 测试、12 个 C 测试全部通过。Studio MAP 仍是 2026-08-10 的旧产物，
所以尚未批准烧录。

请连续完成阶段 A～D 后一次性交付。不要修改 Titan 运行时生产 C，不要连接串口，不要
烧录，不要接舵机。

## A. 强化 ARM 链接证据检查器

当前 `titan_linkage_check.py` 只搜索模块名，可能因 MAP 中出现 LOAD/调试文本而高估“实际
代码已保留”。将检查提升为关键函数/初始化符号级证据，至少要求：

```text
smart_hand_comm_init 或 __rt_init_smart_hand_comm_init
shp_parser_feed
smart_hand_vision_state_init
smart_hand_vision_state_note_vision
smart_hand_vision_state_expire
smart_hand_vision_state_invalidate
smart_hand_sequence_guard_init
smart_hand_sequence_guard_note
smart_hand_sequence_guard_reset
grip_policy_decide
grip_pose_bank_init
grip_pose_bank_resolve
```

检查规则：

- MAP 时间必须不早于本批运行时 `.c`；
- 缺任一关键符号失败并列出缺项；
- 如果 ELF 存在且 `arm-none-eabi-nm` 可用，可选增加 ELF 符号交叉验证；不可用时如实标注
  `map_only`，不要失败；
- 不得把模块名字符串等同于函数实际链接；
- 不得手改 MAP/ELF。

扩展测试覆盖：全部函数、仅模块名但缺函数、缺一个函数、stale MAP、MAP missing；若实现
可选 nm，再用 mock 输出测试 nm 正常与缺符号。

## B. 新建默认 dry-run 的 UART 验收器

建议文件：

```text
smart_hand/host/titan_uart_acceptance.py
smart_hand/tests/test_titan_uart_acceptance.py
smart_hand/host/titan_uart_acceptance_vectors.json
```

必须复用 `maixcam2/protocol.py` 的帧编码/解析能力，禁止复制第二套 CRC/协议。

默认不打开串口。无参数或 `--dry-run` 时只输出：步骤、发送帧、期望 ACK、期望业务副作用
和明确的 `hardware_accessed=false`。

测试向量至少包括：

1. FIRST PING -> ACK0，link 可在线；
2. 正常 VISION bottle/cup/remote -> ACK0，正确 action，但生产 pose 未配置所以
   actionable=0；
3. 低置信和不支持类别 -> ACK0、NO_ACTION；
4. payload 非法（例如 width=0）-> ACK1、清视觉；
5. duplicate -> ACK0、业务不刷新；
6. old -> ACK0、业务不刷新；
7. forward gap -> ACK0、接受并记 gap；
8. 只 PING 维持链路但约 750ms 后视觉 stale；
9. 停止所有帧约 1500ms 后 offline；
10. offline 后低序号重新成为 FIRST。

注意：750/1500ms 行为无法只靠 UART ACK 证明，工具的期望表必须标注“需要同时保存 Titan
shell 的 `sh_status`/日志”，不得凭 PC 端 ACK 自动宣布通过。

### 可选 live 模式的硬门槛

允许实现但本批禁止运行。live 必须同时要求：

```text
--port COMx
--live-no-servo-confirmed
--baud 115200（默认且只允许项目通信链路速率）
```

- 未给确认参数立即退出，且在打开 serial 之前退出；
- 不自动枚举或猜 COM；
- 不默认 COM4，防止误连舵机转接板；
- 串口库必须惰性导入，dry-run 不要求 pyserial；
- live 开始前打印“舵机 6V 必须关闭且总线不得连接”；
- 只发送 Smart Hand ASCII PING/VISION 协议帧，绝不发送 SCS0009 二进制命令；
- 每次用例有限次数、有限超时，禁止无限循环；
- 保存 JSON 结果时明确区分 ACK 观测、Titan shell 人工证据和未验证项。

使用 fake serial/内存流测试：正常 ACK、ACK1、超时、CRC 错误、分片回复、意外序号和串口
异常。测试不得访问真实硬件。

## C. 证据与操作文档

新建：

```text
smart_hand/docs/TITAN_NO_SERVO_UART_ACCEPTANCE_RUNBOOK.md
smart_hand/competition_2026/evidence/titan_uart_acceptance_template.json
```

Runbook 必须说明：

- 先完成 Studio Refresh/Clean/Build、函数级 linkage 和资源检查；
- 再烧录；烧录阶段不连接 Maix 和舵机；
- 先观察 Titan 启动日志和 `sh_status`；
- 后接 TX/RX/GND，双方不接 5V/VBUS；
- 舵机电源保持关闭、舵机总线完全断开；
- 先 Maix mock，再使用 PC 验收器注入故障帧；
- 每个断言所需证据来自 ACK、Titan shell 或计时观察中的哪一种；
- 失败时断开通信线，不要尝试接舵机“继续验证”。

模板所有结论默认 `not_run`；禁止预填 pass。

## D. 一致性、测试和交付

把新 Python 文件加入语法/单元测试。更新 README 的工具清单，但保持成熟度为“待 ARM
Build/待真机”。不要修改测试数量为固定值，除非实际运行后据输出填写。

运行：

```powershell
cd "C:\Users\zzh\OneDrive\Desktop\PCBBOM\嵌赛物联网"
pwsh -File smart_hand\host\run_all_checks.ps1
python smart_hand\host\titan_uart_acceptance.py --dry-run
python smart_hand\host\run_offline_rehearsal.py
```

最终交付：

1. 修改文件列表；
2. 函数级 linkage 必需符号清单；
3. 新增测试及总测试数量；
4. dry-run 完整摘要和 `hardware_accessed=false`；
5. live 模式在打开串口前的三重门槛测试；
6. 证明未新增/修改 Titan 生产运行时 C；
7. 证明未运行 live、未烧录、未访问硬件；
8. ARM Build 仍未完成的明确声明；
9. 上板后需要用户人工提供的最小证据清单。

完成后停止。不要继续写舵机执行层，不要以验收器 dry-run 代替 ARM Build 或实物 UART。
