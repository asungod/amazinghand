# DeepSeek → Codex 交付：Titan UART D1 启动窗口最小修复

任务书：`DEEPSEEK_TASK_TITAN_UART_D1_MINIMAL_FIX_2026-09-22.md`
日期：2026-09-22

---

## ⚠️ 烧写前必读：工程根目录那个 hex 是旧的

工程里存在**两份** `rtthread.hex`，文件名完全相同、内容不同。刷错就是刷回旧固件。

| 路径 | 状态 | SHA-256 | 时间 |
|---|---|---|---|
| `D:\Micu\RTTWorkspace\titan_uart_test\Debug\rtthread.hex` | ✅ **构建产物** | 见 §5 | 每次 `make` 更新 |
| `D:\Micu\RTTWorkspace\titan_uart_test\rtthread.hex` | ⛔ **陈旧，勿用** | `121262e133e6a54f3baf7d32204fbabf52f6ede367e4e00e9c165697e28db016` | 2026-09-21 12:52 |

成因是工程里有**两套构建系统**：CDT/make 的产物落在 `Debug/`，SCons 的产物落在工程根（`rtconfig.py:56` 的 `POST_ACTION` 会在工程根再生成一份 hex）。两者互不覆盖，于是长期共存。

**约定：统一以 `Debug\rtthread.hex` 为构建产物**，每次烧写前先核对 SHA-256。待 D2 与语音集成完成、生成唯一候选固件后，再同步最终版本，避免任何一次刷错。

（本次 D1 与 D2 均**未烧写**。）

**约束遵守**：只改驱动层一个文件，未集成语音模块，**未烧写**，D2 未夹带修改。

---

## 1. 实际修改文件

| 文件 | 说明 |
|---|---|
| `D:/Micu/RTTWorkspace/titan_uart_test/libraries/HAL_Drivers/drv_usart_v2.c` | **唯一被修改的固件文件** |

原始副本备份：`tmp/d1fix/drv_usart_v2.c.orig`；补丁后副本：`tmp/d1fix/drv_usart_v2.c.patched`；diff：`tmp/d1fix/drv_usart_v2.c.diff`（69 增 / 71 删）。

新增的测试文件（不改动任何既有文件）：

```
smart_hand/tests/stubs_usart/{rtthread.h, rthw.h, rtdevice.h, rtdbg.h,
                              drv_common.h, drv_config.h, hal_data.h}
smart_hand/tests/test_drv_usart_v2_c.c       294 断言 / 10 用例
smart_hand/tests/test_drv_usart_v2.py        unittest 包装（含 3 个变异体）
```

---

## 2. 根因与补丁说明

**根因链**（逐环节读过源码）：

1. `smart_hand_uart.c:694`、`servo_bus_readonly_rt.c:1608` 调 `RT_DEVICE_CTRL_CONFIG`；
2. `serial_v2.c:1143-1156` 把它直接转给 `serial->ops->configure()`；
3. `drv_usart_v2.c:215` → `R_SCI_B_UART_Open()`；
4. **`r_sci_b_uart.c:381-388` 在 Open 内就使能 RX、RXI、ERI**；
5. 但 `serial->serial_rx` 直到 `rt_device_open()` 的 RX-enable 阶段才分配并发布（`serial_v2.c:779-785`）；
6. 回调里是 `RT_ASSERT(rx_fifo != RT_NULL)`，而 `RT_USING_DEBUG` 已定义 ⇒ **断言是活的**。

→ 窗口内到达任意一字节即启动期停机。UART1 是舵机总线，UART2 接 MaixCAM2。

**为什么"换序"是假修复**（采纳你的裁决）：`rt_device_open()` 会先跑 `rt_serial_init()`，其 configure 步骤**仍会在 FIFO 发布之前**调用 `R_SCI_B_UART_Open()`。换序只是把窗口挪个位置，没有关闭它。

**补丁**：在 `drv_usart_v2.c` 增加文件内静态辅助函数 `ra_uart_queue_rx_char(serial, data)`：

- `serial == RT_NULL` → 丢弃、计数 +1、返回 `-RT_ERROR`；
- `serial->serial_rx == RT_NULL` → 丢弃、计数 +1、返回 `-RT_ERROR`；
- 否则 `rt_ringbuffer_putchar()` + `rt_hw_serial_isr()`，与**原行为逐字节一致**。

10 个 UART 回调的 `if (UART_EVENT_RX_CHAR == ...)` 块统一改为：

```c
    if (UART_EVENT_RX_CHAR == p_args->event)
    {
        (void)ra_uart_queue_rx_char(serial, (rt_uint8_t)p_args->data);
    }
```

**边界遵守明细**：

| 要求 | 落实 |
|---|---|
| 正常执行 `rt_interrupt_leave()` | ✅ 10 个回调的 `rt_interrupt_enter()`/`rt_interrupt_leave()` **原样未动** |
| FIFO 非空时行为完全不变 | ✅ 用例 7 覆盖（窗口内但已发布 ⇒ 逐字节不变） |
| 至少覆盖 UART1/UART2；可抽小函数 | ✅ 抽了函数，10 个回调全覆盖 |
| 只读丢字节计数器 | ✅ `static volatile rt_uint32_t g_uart_rx_dropped_before_fifo`（+4 B `.bss`），**无日志、无动态分配、无 ISR 阻塞** |
| 不得关 `RT_ASSERT` | ✅ 10 处的 `RT_ASSERT(serial != RT_NULL)` 全部保留；仅替换那条**实际可达**的 `rx_fifo != RT_NULL` |
| 不得改 FSP | ✅ `ra/` 下未动 |
| 不得用延时规避 | ✅ 无 |
| 不重构整个串口驱动 | ✅ 只加一个静态函数 + 改 10 个回调体 |

活代码中已**无** `RT_ASSERT(rx_fifo != RT_NULL)`（唯一一处出现在补丁自己的注释里，描述旧行为）。

---

## 3. 补丁 diff

完整 diff：`tmp/d1fix/drv_usart_v2.c.diff`。核心：

```diff
+static rt_err_t ra_uart_queue_rx_char(struct rt_serial_device *serial, rt_uint8_t data)
+{
+    struct rt_serial_rx_fifo *rx_fifo;
+
+    if (serial == RT_NULL)
+    {
+        g_uart_rx_dropped_before_fifo++;
+        return -RT_ERROR;
+    }
+
+    rx_fifo = (struct rt_serial_rx_fifo *) serial->serial_rx;
+
+    if (rx_fifo == RT_NULL)
+    {
+        g_uart_rx_dropped_before_fifo++;
+        return -RT_ERROR;
+    }
+
+    rt_ringbuffer_putchar(&(rx_fifo->rb), data);
+    rt_hw_serial_isr(serial, RT_SERIAL_EVENT_RX_IND);
+    return RT_EOK;
+}

 // 每个回调（共 10 处，模式完全一致）：
     if (UART_EVENT_RX_CHAR == p_args->event)
     {
-        struct rt_serial_rx_fifo *rx_fifo;
-        rx_fifo = (struct rt_serial_rx_fifo *) serial->serial_rx;
-        RT_ASSERT(rx_fifo != RT_NULL);
-
-        rt_ringbuffer_putchar(&(rx_fifo->rb), (rt_uint8_t)p_args->data);
-
-        rt_hw_serial_isr(serial, RT_SERIAL_EVENT_RX_IND);
+        (void)ra_uart_queue_rx_char(serial, (rt_uint8_t)p_args->data);
     }
```

---

## 4. 桩测试及变异测试结果

### 4.1 桩测试

```bash
pip 依赖：无（纯 gcc + stdlib）
cd <项目根>
python -m unittest smart_hand.tests.test_drv_usart_v2
# Ran 7 tests ... OK
```

直接运行 C 程序：

```
[case] 1-null-fifo-drops-rx-char: ok (24 checks)
[case] 2-published-fifo-queues-and-notifies: ok (32 checks)
[case] 3-non-rx-char-events-untouched: ok (92 checks)
[case] 4-per-uart-isolation: ok (16 checks)
[case] 5-null-serial-direct-helper: ok (17 checks)
[case] 6-open-window-byte-dropped: ok (32 checks)
[case] 7-open-window-after-publish-delivers: ok (18 checks)
[case] 8-byte-exactness-256: ok (17 checks)
[case] 9-drop-counter-accounted: ok (23 checks)
[case] 10-registration-and-config: ok (23 checks)
C drv_usart_v2 tests passed (294 checks)
```

对应任务书 §验证要求：

| 要求 | 用例 |
|---|---|
| 空 FIFO 注入 → 无断言/无 ring write/无 ISR 通知/enter-leave 配对 | 1（UART1+UART2 各一遍） |
| 发布有效 FIFO 后 → 字节准确写入且通知一次 | 2（含**顺序**断言：先 putchar 后 isr） |
| 非 RX_CHAR 事件行为不变 | 3（7 种事件 × 2 口） |
| UART1 与 UART2 都覆盖 | 1、2、4 |
| **删掉防护测试必须失败** | 见 4.2 |

第 4 条额外覆盖了"回调里用错 uart_obj 下标"这类复制粘贴错误（一口未发布时字节不得落进另一口的 FIFO）。
第 6 条是最贴近真缺陷的一条：`rt_hw_usart_init → ops->configure → R_SCI_B_UART_Open` **在返回前同步回调 3 个字节**，复现 `r_sci_b_uart.c:381-388` 的真实重入窗口，并用 `open_injected == 3` 反证窗口真的进了（防止空跑）。

### 4.2 变异测试（我**独立复做**了一遍，不采信子 agent 自述）

我自己把防护还原成历史断言，用同一套桩与测试编译运行：

```
变异体退出码: 1
[case] 1-null-fifo-drops-rx-char: FAILED (7 checks)
[case] 4-per-uart-isolation:      FAILED (7 checks)
[case] 5-null-serial-direct-helper: FAILED (12 checks)
[case] 6-open-window-byte-dropped: FAILED (12 checks)
[case] 2 / 3 / 7 / 8:             ok        ← 不需要防护的路径仍通过
```

**靶向正确**：红的正是"无 FIFO 时来字节"这条路径，套件其余部分不受影响——说明不是整个套件失灵。

子 agent 另做了两个变异（`serial == RT_NULL` 防护换成断言、字面删除防护），均被拒。**验收判据成立：删掉防护，测试必红。**

### 4.3 桩测试的诚实边界（子 agent 自列，我认同）

- **"字节准确写入 ringbuffer"整体隔着一层**：ring 是桩实现（mirror 语义照抄 `ringbuffer.h` 算法，但终究不是 RT-Thread 代码）。这些断言证明的是"被测文件把正确的字节、正确的 `&rx_fifo->rb` 交给了 API，且顺序对"，**不是**"RT-Thread 的 ringbuffer 正确"。
- **用例 8（256 字节）基本是浅水**：走的是与用例 2 相同的路径，验的主要是桩自己的环绕逻辑。
- **用例 3 天然浅**：一个 `==` 比较，能抓到的最坏情况是判断被写反/删掉，深度有限。
- **用例 10 的波特率/缓冲尺寸几条是常量回抄**，只防"整段被删/被短路"，防不了值抄错。
- **`serial_v2.c` 真实的 FIFO 发布不在测试范围**：用例是直接写 `serial->serial_rx` 模拟发布，所以"字段改名"这类变化本测试抓不到。
- **UART0、UART3..9 的 8 个回调根本没编译进来**（与 rtconfig 一致）。今后若有人打开 UART3，本主机测试**不会自动扩大覆盖，也没有机制提醒**——已知维护盲点。
- `ra_uart_putc/control/getc/transmit` 编译进二进制但**未被调用**（需可用寄存器模型，即使调用也无验证意义）。

---

## 5. 完整构建结果和新固件哈希

```bash
# 正确 PATH（注意是 platform/env_released，斜杠；不是下划线版）
export PATH="/d/RT-ThreadStudio/repo/Extract/ToolChain_Support_Packages/ARM/GNU_Tools_for_ARM_Embedded_Processors/13.3/bin:/d/RT-ThreadStudio/platform/env_released/env/tools/bin:$PATH"
cd /d/Micu/RTTWorkspace/titan_uart_test/Debug && make all
```

**`make` 退出码 0**，`drv_usart_v2.c` 编译（`-Wall`）**零告警**，链接 → objcopy → hex 全部完成。

| 项 | 改动前 | 改动后 | 变化 |
|---|---|---|---|
| `.text` | 125676 | 125668 | **−8** |
| `.data` | 1024 | 1024 | 0 |
| `.bss` | 137200 | 137204 | **+4** |
| `rtthread.hex` | 356497 B | 356468 B | −29 |

`text` 减 8 字节来自 10 份重复回调体被抽成一个共享函数；`bss` 加 4 字节是丢字节计数器。

**新固件 SHA-256**

```
rtthread.elf  ca26b6f1c3e68dce9a5cf80ef6d9377d80149070699b928664b9ad17f06f5548
rtthread.hex  a21d0cedc82c95b01f0d7cec37fd2d4c3e8ace1505e6a9e33fb58fe05be9227c
```

> **过程记录（值得记一笔）**：我第一次报告的"构建成功 exit 0"是**假的**——PATH 用了不存在的 `platform_env_released`（下划线），且 `make all | tail -25` 后面跟的 `$?` 取的是 `tail` 的退出码。核验产物时才发现（`drv_usart_v2.o` 的 mtime 未变、hex 哈希与改动前完全相同）。**教训：构建是否真的发生，要看产物的 mtime 与哈希，不能只看退出码。** 上面这组数字来自修正后的真实构建。

---

## 6. 尚未完成的真机验证（按任务书由你/用户执行）

未烧写。集成刷写后需要验证：

1. MaixCAM2 保持连接并持续发帧，Titan **连续冷启动 20 次**；
2. 每次启动后均能重新建立 UART ACK；
3. 舵机总线轮询与手势动作均正常；
4. 无断言、无永久离线、无新增 RX 错误；
5. 通过后再与 D2 修复及语音集成合并刷写。

**主机侧无法验证的**：真实中断时序、真实 ringbuffer 行为、`RT_ASSERT` 在目标上的实际表现、以及"窗口内字节确实被丢弃而非被别的路径接收"。

---

## 7. 对 D2 的独立建议（**本次未做任何修改**）

D2 是 `servo_bus_readonly_rt.c` 的 `run_one_cycle()`：两处早退（`prepare` 失败、TX 20 ms 超时）**直接 `return` 而未收尾**，把 `cycle_active` 留在 1；而唯一的复位入口 `servo_group_readonly_begin_cycle()` 的前置条件正是 `cycle_active` 非零即拒绝 ⇒ 一次 TX 超时后舵机总线到重启前永久静默。

建议（供你决策，不含实现）：

1. **收尾而非绕过**：早退前把当前周期的索引推进到末尾并置 `cycle_active = 0`（即调用与正常结束相同的收尾路径），而不是让 `begin_cycle` 去接管半途状态。后者会把"未完成"的语义扩散到更多调用点。
2. **加一个显式的故障计数**（复用现有 `error` 通道或新增只读字段），使"曾经发生过 TX 超时"在遥测里可见——否则该故障自愈后无痕迹，事后无法判断是否发生过。
3. **与 D1 类似的取舍需要明确**：总线静默是 fail-closed（运动请求全部拒绝），比"带着不确定状态继续跑"安全，所以**不建议**改成自动重试；建议保持 fail-closed，但让它在有限期内可恢复而不是永久。
4. **验证方式**：这类"超时后卡死"在真机上难以按需触发，建议用与 D1 相同的手法——把 `run_one_cycle` 的 TX 超时路径做成可在主机驱动的桩测试（`servo_group_readonly.c` 是纯逻辑、依赖很轻，比 D1 更适合主机覆盖）。
5. **同类模式值得一并扫**：本次排查还发现 `g_servo_pair_commission_result` 被六条路径共用、可能让上位机收到"从未发生的 TRAIN SUCCEEDED"，以及 pair/group/index 四条分支无忙标志就调长阻塞函数（运动期间仍回 `ACCEPTED` 而非 `BUSY`）。**这两条属 servo 模块，建议单独立项，不要塞进 D2 补丁。**

---

## 8. 回归确认

改动只涉及 `drv_usart_v2.c`。既有语音模块测试套件**全部仍然通过**（base 43 项 / venv 36 项 / C 自检 4 个 / titan 桩测试 287 checks），说明本补丁对语音侧无影响。
