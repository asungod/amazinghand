#ifndef SMART_HAND_TESTS_STUBS_SERVO_BOARD_H
#define SMART_HAND_TESTS_STUBS_SERVO_BOARD_H

/*
 * 主机桩：RT-Thread BSP 的 board/board.h。
 *
 * 真实的 board/board.h 只做三件事：include "hal_data.h"、定义堆边界
 * （RA_SRAM_SIZE / HEAP_BEGIN / HEAP_END），以及一片与 RT-Thread 启动
 * 相关的 weak 符号。被测文件 src/servo_bus_readonly_rt.c 只是因为固件的
 * 惯例把 <board.h> 列进 include，它自己没有用到 board.h 里的任何东西
 * （g_ioport_ctrl / g_uart1_ctrl 来自 hal_data.h —— 真实 board.h 也是转
 * 手 include hal_data.h 才让它们可见的）。
 *
 * 所以这里只保留"转手 include hal_data.h"这一条。堆边界属于 RT-Thread
 * 内核启动路径，本测试根本不进内核，桩掉它是诚实的选择而不是遗漏。
 */

#include "hal_data.h"

#endif /* SMART_HAND_TESTS_STUBS_SERVO_BOARD_H */
