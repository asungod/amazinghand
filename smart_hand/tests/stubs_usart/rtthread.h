#ifndef SMART_HAND_TESTS_STUBS_USART_RTTHREAD_H
#define SMART_HAND_TESTS_STUBS_USART_RTTHREAD_H

/*
 * 主机桩：RT-Thread 内核头（rt-thread/include/rtthread.h + rtdef.h）。
 *
 * 被测文件 libraries/HAL_Drivers/drv_usart_v2.c 通过 drv_usart_v2.h 间接
 * include 本文件，用到的东西只有下面这些：基础类型、RT_NULL、rt_container_of、
 * RT_ASSERT、rt_interrupt_enter/leave。真实内核把它们散落在 rtdef.h /
 * rtthread.h / rthw.h 三个头里，本桩合并到 rtthread.h，并在注释里标出真实出处，
 * 这样"桩掉了什么"一眼可查。
 *
 * 实现（rt_interrupt_enter/leave、rt_assert_handler）在
 * tests/test_drv_usart_v2_c.c，与被测文件编到同一个 TU。
 *
 * 关键取舍 —— RT_ASSERT 必须是"活的"：
 *   rtconfig.h:28 定义了 RT_USING_DEBUG，真实 rtthread.h 在这个宏下把 RT_ASSERT
 *   展开成 rt_assert_handler(...)，断言失败即停机。本补丁修的就是"启动窗口里
 *   这个断言会打死固件"，所以桩不能把 RT_ASSERT 变成 no-op，否则变异验证
 *   （把空指针防护恢复成断言）会静默通过。rt_assert_handler() 的实现记录一次
 *   失败并让当前用例立刻判负（见 test_drv_usart_v2_c.c 里的 setjmp）。
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* rt-thread/include/rtdef.h */
typedef int8_t        rt_int8_t;
typedef uint8_t       rt_uint8_t;
typedef int16_t       rt_int16_t;
typedef uint16_t      rt_uint16_t;
typedef int32_t       rt_int32_t;
typedef uint32_t      rt_uint32_t;
typedef int64_t       rt_int64_t;
typedef uint64_t      rt_uint64_t;
/*
 * rttypes.h:36-37 里这两个是 signed/unsigned long —— 目标机是 32 位 ARM，
 * long 恰好与指针同宽。主机是 64 位而 Windows 的 long 只有 32 位，照抄会让
 * rt_container_of() 的指针减法被截断（编译告警 -Wpointer-to-int-cast，
 * 运行期则是错地址），所以这里换成与指针同宽的 intptr_t/uintptr_t。
 * 相对被测代码是等价替换：它只用这两个类型做 rt_container_of 的算术。
 */
typedef intptr_t      rt_base_t;
typedef uintptr_t     rt_ubase_t;
typedef rt_base_t     rt_err_t;
typedef rt_ubase_t    rt_size_t;
typedef rt_base_t     rt_ssize_t;
typedef int           rt_bool_t;

#define RT_NULL   ((void *)0)
#define RT_TRUE   (1)
#define RT_FALSE  (0)

/*
 * 错误码取自 rtdef.h 的"非 libc"分支（rtconfig.h 未定义 RT_USING_LIBC）。
 * 被测代码只做 `return -RT_ERROR`，测试断言的是"非 RT_EOK 且等于 -RT_ERROR"，
 * 不依赖这个数字具体是 1 还是 255。
 */
#define RT_EOK    (0)
#define RT_ERROR  (1)

/* rthw.h 的超时常量，被测文件不用，这里不桩。 */

/* rtthread.h:698-699，由 BSP/内核维护中断嵌套计数 */
void rt_interrupt_enter(void);
void rt_interrupt_leave(void);

/* rtdef.h 的 rt_container_of()。被测文件用它从 rt_serial_device 反查 struct ra_uart。 */
#define rt_container_of(ptr, type, member) \
    ((type *)((char *)(ptr) - (rt_ubase_t)(&((type *)0)->member)))

/*
 * rtthread.h 的断言面。RT_USING_DEBUG 已定义 ⇒ 与固件一致地"活"。
 * 参数与真实 rt_assert_handler 同形（表达式文本、函数名、行号）。
 */
void rt_assert_handler(const char *ex_string, const char *func, rt_size_t line);

#define RT_ASSERT(EX)                                                \
    ((EX) ? (void)0                                                  \
          : rt_assert_handler(#EX, __func__, (rt_size_t)__LINE__))

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_USART_RTTHREAD_H */
