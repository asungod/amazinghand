# DeepSeek 任务：Titan UART D1 启动窗口最小修复

日期：2026-09-22

## 结论

D1 需要修复，优先级高于语音模块集成，但本任务只生成、验证补丁，不烧写设备。

不要只把业务代码中的 `rt_device_open()` 移到 `RT_DEVICE_CTRL_CONFIG` 前。该改法不完整：首次 `rt_device_open()` 会在 `device.c:228-243` 先调用 `rt_serial_init()`，而 `serial_v2.c:928-930` 的初始化仍先执行底层 `configure()`；RA8P1 的 `R_SCI_B_UART_Open()` 会立即启用 RX，因此接收 FIFO 依然可能尚未发布。

## 已确认的故障链

1. `smart_hand_uart.c:694` 和 `servo_bus_readonly_rt.c:1608` 在业务层先调用 `RT_DEVICE_CTRL_CONFIG`；
2. `serial_v2.c:1143-1156` 将 CONFIG 直接传给 `serial->ops->configure()`；
3. `drv_usart_v2.c:215` 调用 `R_SCI_B_UART_Open()`；
4. `r_sci_b_uart.c:381-388` 在 Open 内启用 RX、RXI、ERI；
5. `serial_v2.c:779-785` 直到设备 open 的 RX enable 阶段才分配并发布 `serial->serial_rx`；
6. `drv_usart_v2.c` 的 UART1/UART2 回调直接 `RT_ASSERT(rx_fifo != RT_NULL)`。

因此在 FIFO 发布前收到任意字节，会触发有效断言。UART1 是舵机总线，UART2 是 MaixCAM2 链路。

## 要求的最小补丁

优先在 `libraries/HAL_Drivers/drv_usart_v2.c` 的 RX_CHAR 回调路径增加空 FIFO 防护：

- `serial->serial_rx == RT_NULL` 时丢弃当前启动期字节，不调用 `rt_ringbuffer_putchar()`，也不调用 `rt_hw_serial_isr()`；
- 必须正常执行 `rt_interrupt_leave()`，不可在它之前直接 return；
- FIFO 非空时保持现有行为完全不变；
- 至少覆盖当前启用的 UART1、UART2；若抽成内部小函数能同时消除所有 UART 回调的重复风险，可以做，但不要重构整个串口驱动；
- 可增加只读启动丢字节计数器供调试，但不得引入日志打印、动态分配或 ISR 阻塞；
- 不得关闭 `RT_ASSERT`，不得修改 FSP，不能以延时规避竞态。

该策略的取舍是：启动窗口中的字节可能丢失，但不会把系统打进断言。MaixCAM2 协议具有帧同步和重发；舵机总线在请求前通常不会主动回包。系统完成初始化后必须恢复正常接收。

## 验证要求

### 主机/桩验证

1. `serial_rx == NULL` 时注入 `UART_EVENT_RX_CHAR`：无断言、无 ring write、无 serial ISR 通知，enter/leave 配对；
2. 发布有效 FIFO 后注入字节：字节准确写入且通知一次；
3. 非 RX_CHAR 事件行为不变；
4. UART1 和 UART2 都覆盖；
5. 将空指针防护变异删除后，测试必须失败。

### 构建验证

- 使用工程真实 ARM 工具链和真实编译参数编译；
- 完整固件链接成功；
- 记录 `.elf/.hex` SHA-256、Flash/RAM 变化；
- 不烧写。

### 后续真机验证（由 Codex/用户执行）

1. MaixCAM2 保持连接并持续发帧，Titan 连续冷启动 20 次；
2. 每次启动后均能重新建立 UART ACK；
3. 舵机总线轮询与手势动作均正常；
4. 无断言、无永久离线、无新增 RX 错误；
5. 验证通过后再与 D2 修复及语音集成合并刷写，避免为单一补丁反复刷机。

## 明确禁止

- 不把 `open`/`CONFIG` 简单换序后就宣称修复；
- 不烧写当前设备；
- 不改 UART 波特率、协议、CRC、ACK、超时和舵机动作参数；
- 不顺带集成语音模块；
- 不删除现有断言来掩盖问题。

## 交付格式

1. 实际修改文件；
2. 根因与补丁说明；
3. 补丁 diff；
4. 桩测试及变异测试结果；
5. 完整构建结果和新固件哈希；
6. 尚未完成的真机验证；
7. 对 D2 只给独立建议，不在本补丁中夹带修改。
