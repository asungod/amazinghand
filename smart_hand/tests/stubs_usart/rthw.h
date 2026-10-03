#ifndef SMART_HAND_TESTS_STUBS_USART_RTHW_H
#define SMART_HAND_TESTS_STUBS_USART_RTHW_H

/*
 * 主机桩：rt-thread/include/rthw.h。
 *
 * 被测文件只通过 drv_usart_v2.h 间接包含它，并不直接引用其中任何符号；
 * rt_interrupt_enter/leave 在真实工程里声明于 rtthread.h（rtthread.h:698），
 * 本桩集把它们放在 rtthread.h 里。这里只保留真实 rthw.h 里与中断开关相关的
 * 声明，便于日后被测代码加临界区时无需再改桩头。
 *
 * rt_hw_interrupt_disable/enable 只声明不实现：被测文件没有调用它们，
 * 一旦有人调用就会在链接期报错（而不是悄悄返回假值），这是刻意的。
 */

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

rt_base_t rt_hw_interrupt_disable(void);
void      rt_hw_interrupt_enable(rt_base_t level);

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_USART_RTHW_H */
