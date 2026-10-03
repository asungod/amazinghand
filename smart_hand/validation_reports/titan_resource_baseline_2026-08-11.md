# Titan Mini 固件资源基线（2026-08-11）

## 结论

本报告只分析 `D:\Micu\RTTWorkspace\titan_uart_test\Debug` 中 2026-08-10 的
`rtthread.elf`、`rtthread.map` 和工程配置。它能证明当前固件的链接布局及 Smart Hand
代码已进入最终镜像，但不能证明真机栈水位、堆峰值、时序、中断负载或硬件稳定性。

- GNU `size` 结果为 `text=121420`、`data=1296`、`bss=135956`。
- 主 FLASH 已用地址范围为 `0x02000000..0x0201DF5C`，跨度 122,716 B
  （119.84 KiB），占 1 MiB 区域的 11.70%。
- GNU 口径的静态 RAM 为 `data+bss=137252` B；计入段间对齐后的实际地址跨度为
  137,256 B（134.04 KiB）。
- RT-Thread 实际初始化的片上系统堆约为 387,032 B（377.96 KiB），但这是初始化
  区间，不是运行时可用水位结论，实际还会扣除分配器元数据和动态对象。
- Smart Hand 两个对象合计约占 4,186 B FLASH、134 B 静态 RAM；接收线程还会在
  启动时从堆申请 2,048 B 栈以及线程控制块/分配器开销。
- Smart Hand 初始化入口、`sh_status` shell 命令和四个协议 API 均出现在 ELF 中。

当前没有资源容量阻塞烧录和最小 UART bring-up 的静态证据。最明显的配置问题不是
Smart Hand 占用，而是 RT-Thread 的通用 `board.h` 仍把 SRAM 写成 512 KiB，未跟随
本工程 CPU0 的 1,488 KiB BSP 分区；另外 128 KiB BSP 主栈是否确有必要也尚无运行
数据。在首次上板取得基线前仍不直接缩栈或扩大堆。

## 构建证据

| 产物 | 大小 | 构建时间 | SHA-256 |
|---|---:|---|---|
| `rtthread.elf` | 2,610,620 B | `2026-08-10 22:36:59 +08:00` | `812D3BB5D87446BFDCFFEAE43E7586EBA161EEB4A93CB64340214D7CB0F98D5B` |
| `rtthread.map` | 965,421 B | `2026-08-10 22:36:59 +08:00` | `2F93A538B5FAB00303D03BC2EAA64A4C54F246B57346383C27684C38CCE994C7` |
| `rtthread.hex` | 345,292 B | `2026-08-10 22:37:00 +08:00` | `C17F55331ED20977AB912769E4E802D880245F2C7FA1BB9CE5F0D9C2F2B27183` |

MAP 文件显示镜像由 ARM GNU 13.3.1 生成，编译参数包含 `-O0`、
`-ffunction-sections`、`-fdata-sections` 和链接器 `--gc-sections`。因此这是 Debug
基线；切换优化等级、BSP 配置或工具链后必须重新采集，不能把本文数字当成固定值。

本次只读检查使用系统现存的 GNU binutils 2.42（GNU Tools for STM32 13.3.rel1）读取
ELF；未重新链接或修改产物。

## FLASH 布局

MAP 声明主 FLASH 为：

```text
FLASH  origin=0x02000000  length=0x00100000 (1,048,576 B)
```

| 项目 | 字节 | 说明 |
|---|---:|---|
| `text` | 121,420 | GNU `size` 口径，包含代码/只读内容及 4 B option setting |
| `data` 的加载镜像 | 1,296 | 启动时复制到 RAM |
| `text + data` | 122,716 | GNU 总加载口径，119.84 KiB |
| 主 FLASH 已用地址跨度 | 122,716 | `0x02000000..0x0201DF5C`，含 4 B 对齐空洞 |
| 主 FLASH 名义剩余 | 925,860 | 仅为链接地址容量差，不代表升级/bootloader 预留策略 |

另有 4 B option setting 位于 `0x02C9F040`。它已计入 GNU `text` 分类，但不位于上述
1 MiB 主 FLASH 地址范围内，不应在总数上再次相加。

按 ELF 符号大小，当前较大的代码/只读项是：

| 符号 | 字节 |
|---|---:|
| `_svfprintf_r` | 6,988 |
| `_dtoa_r` | 3,260 |
| `rt_vsnprintf` | 1,574 |
| `finsh_thread_entry` | 1,504 |
| `ra_pin_get_irqx` | 1,454 |
| `timegm` | 1,440 |
| `g_bsp_pin_cfg_data` | 1,120 |

这些主要来自 newlib、FinSH 和 BSP。当前 FLASH 余量充足，不建议为最小通信 bring-up
专门裁剪它们；未来若加入模型或大表，再用相同口径比较增量。

## RAM 与系统堆

当前存在两套不同的 RAM 边界，必须分开理解：

```text
链接脚本 RAM: 0x22000000..0x22174000  (1,523,712 B / 1,488 KiB)
board.h 堆上限: HEAP_END=0x22080000   (RA_SRAM_SIZE=512 KiB)
已链接静态区末端: __RAM_segment_used_end__=0x22021828
```

| 项目 | 字节 | 口径 |
|---|---:|---|
| GNU `data + bss` | 137,252 | 不含段间对齐空洞 |
| RAM 静态地址跨度 | 137,256 | `0x22000000..0x22021828` |
| 其中 `g_main_stack` | 131,072 | `BSP_CFG_STACK_MAIN_BYTES=0x20000` |
| RT-Thread 系统堆初始化区间 | 387,032 | `0x22021828..0x22080000` |
| CPU0 RAM 中高于 `HEAP_END` 的区间 | 999,424 | 已确认属于 CPU0 分区，但当前不属于 RT-Thread 系统堆 |

`rt_hw_board_init()` 以 `HEAP_BEGIN=&__RAM_segment_used_end__`、
`HEAP_END=0x22080000` 调用 `rt_system_heap_init()`。因此不能按链接器的 1,488 KiB RAM
直接宣称系统堆余量。`BSP_USING_SDRAM` 当前未启用，板载 SDRAM 也没有作为后备堆。

FSP 配置里的 `BSP_CFG_HEAP_BYTES=0x4000` 对应 `g_heap`，但当前 ELF/MAP 中没有
`g_heap` 符号，说明该未引用段已被 `--gc-sections` 丢弃；不能把这 16 KiB 再加入
静态 RAM 或系统堆统计。

本地 `libraries/Common/ports/bsp_linker_info.h` 给出了同一工程的分区证据：

```text
BSP_PARTITION_RAM_CPU0_S_START  = 0x22000000
BSP_PARTITION_RAM_CPU0_S_SIZE   = 0x174000
BSP_PARTITION_SHARED_MEM_START  = 0x22174000
BSP_PARTITION_SHARED_MEM_SIZE   = 0x20000
BSP_PARTITION_RAM_CPU1_S_START  = 0x22194000
```

这确认 `0x22080000..0x22174000` 的 999,424 B 仍位于 CPU0 分区内，并在共享内存
起点前结束。相反，`board/board.h` 使用通用模板值 `RA_SRAM_SIZE=512`，其同行注释为
“The SRAM size of the chip needs to be modified”。因此当前是明确的堆容量未同步，而
不是未知内存归属。

把 `RA_SRAM_SIZE` 调整为 1,488 可使 `HEAP_END` 对齐 CPU0 分区末端，但这会改变
首次上板的运行时内存范围；现有约 378 KiB 系统堆足以进行最小 UART bring-up，故
本轮只记录问题，不修改 D 盘工程。首次烧录取得 `free`/`ps` 基线后，再单独修改、
重建并做堆边界读写/长时间验证，且绝不能越过 `0x22174000` 进入共享内存。

## Smart Hand 增量

| 对象 | FLASH | 静态 RAM | 组成 |
|---|---:|---:|---|
| `smart_hand_protocol.o` | 1,719 B | 0 B | 1,664 B 代码 + 55 B 只读数据 |
| `smart_hand_uart.o` | 2,467 B | 134 B | 1,728 B 代码 + 719 B 只读数据 + 20 B RT/FinSH 表项 |
| 合计 | 4,186 B | 134 B | FLASH 占主区域约 0.40% |

已确认链接的关键入口/符号：

- `__rt_init_smart_hand_comm_init` 和 `smart_hand_comm_init`
- `__fsym_sh_status` 和 `sh_status`
- `shp_crc16_ccitt`
- `shp_parser_init`
- `shp_parser_feed`
- `shp_encode`

接收线程由 `rt_thread_create("sh_uart", ...)` 动态创建，配置为：

| 项目 | 值 |
|---|---:|
| 栈 | 2,048 B |
| 优先级 | 18 |
| 时间片 | 10 ticks |

2,048 B 只是申请值。ELF/MAP 无法给出真实最大栈深度，且线程控制块、栈对齐和堆
分配器元数据会带来额外开销。

工程中其他已配置线程栈包括 idle 256 B、timer 512 B、RT main 2,048 B 和 FinSH
4,096 B。是否都在同一时刻动态占用、实际峰值多少，应以上板后的 `ps`/`free`
输出为准，不能把配置值简单相加后当成运行时结论。

## 上板后补齐的数据

首次 Titan 烧录成功后，在 UART1 msh 中依次保存：

```text
free
ps
sh_status
```

至少在三个时点记录同一组输出：刚启动、UART2 连续通信 10 分钟后、断联并恢复后。
`ps` 当前实现会输出各线程的 `stack size` 和 `max used`，重点检查 `sh_uart`；`free`
在本配置下会列出 memheap 的 total/used/max_used/available。若 `sh_uart` 栈余量低于
25%、`max used` 持续增长或 `free` 峰值异常，应先分析调用深度/动态分配，再决定加栈
或调整内存边界。

仍需真机或实验室设备才能验证：

- 128 KiB FSP 主栈真实高水位及是否可安全缩小；
- `sh_uart` 的真实栈高水位；
- 系统堆启动、稳态和故障恢复峰值；
- 把堆上限扩到 CPU0 分区末端后的边界读写和长时间稳定性；
- 中断负载、UART2 吞吐、1.5 s 离线时序和长时间稳定性。

## 当前建议

1. 首次上板前不修改 RAM、主栈、Smart Hand 线程栈或 SDRAM 配置，保持已构建基线。
2. 上板后先收集 `free`、`ps`、`sh_status`，再单独把 `RA_SRAM_SIZE` 从 512 调整为
   1,488 并重建验证；不要越过共享内存起点 `0x22174000`。
3. 后续每次加入动作控制、NPU或大缓冲区后，保存新 ELF/MAP 哈希并以本报告为增量基线。
