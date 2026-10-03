#ifndef SMART_HAND_TESTS_STUBS_USART_DRV_COMMON_H
#define SMART_HAND_TESTS_STUBS_USART_DRV_COMMON_H

/*
 * 主机桩：libraries/HAL_Drivers/drv_common.h。
 *
 * 真实文件把板级头（board.h）、FSP 头与一堆 rt_hw_* 声明串起来，整条链会把
 * 整个 BSP 拖进主机编译。被测文件 drv_usart_v2.c 只通过 drv_usart_v2.h 间接
 * 包含它，并不引用其中任何符号（实查：文件里没有 rt_hw_us_delay / rt_hw_* 调用），
 * 所以桩成空壳，只保留 rtthread.h。
 *
 * 一旦被测文件开始引用 drv_common.h 里的东西，会在编译/链接期直接暴露，
 * 而不是被桩悄悄糊过去。
 */

#include <rtthread.h>

#endif /* SMART_HAND_TESTS_STUBS_USART_DRV_COMMON_H */
