#ifndef SMART_HAND_TESTS_STUBS_SERVO_RTTHREAD_H
#define SMART_HAND_TESTS_STUBS_SERVO_RTTHREAD_H

/*
 * 主机桩：RT-Thread 内核头（rt-thread/include/rtdef.h + rtthread.h + rthw.h）。
 *
 * 被测文件 src/servo_bus_readonly_rt.c 是固件里的舵机总线线程，编译单元里并进
 * tests/test_run_one_cycle_d2_c.c 后，本头文件负责提供它引用的全部内核面：
 *
 *   - 基础类型 / RT_NULL / 错误码常量
 *   - rt_mutex_t（g_snapshot_mutex 是文件内 static 实例，需要完整类型）
 *   - rt_thread_t / rt_device_t（只用指针，不 deref）
 *   - rt_tick_get()/rt_thread_yield()/rt_thread_mdelay() —— 三个时间原语，
 *     它们的实现是本测试的"时钟"，见 test_run_one_cycle_d2_c.c
 *   - INIT_APP_EXPORT()：真实展开是往 .rti_fn.5 段里放一个初始化函数指针，
 *     主机上没有这个段；这里展开成"取地址 + used 属性"的等价物，效果是
 *     servo_bus_readonly_init() 被引用（-Wunused-function 不报警），但 main()
 *     不会自动跑它。
 *
 * 真实出处逐条标注在下面，凡是照抄数值的地方都给了 rtdef.h 的行号。
 * 实现（rt_tick_get 等）在 tests/test_run_one_cycle_d2_c.c，与被测文件同 TU。
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* rt-thread/include/rtdef.h 的基础类型 */
typedef int8_t   rt_int8_t;
typedef uint8_t  rt_uint8_t;
typedef int16_t  rt_int16_t;
typedef uint16_t rt_uint16_t;
typedef int32_t  rt_int32_t;
typedef uint32_t rt_uint32_t;
typedef int64_t  rt_int64_t;
typedef uint64_t rt_uint64_t;
/*
 * rttypes.h:36-37 里 rt_base_t/rt_ubase_t 是 long/unsigned long —— 目标机是
 * 32 位 ARM，long 恰好与指针同宽；主机是 64 位而 Windows 的 long 只有 32 位。
 * 被测文件不用它们做指针算术，但保持"与指针同宽"能避免整型提升差异，且
 * rt_size_t 在真实内核里就是 rt_ubase_t。
 */
typedef intptr_t     rt_base_t;
typedef uintptr_t    rt_ubase_t;
typedef rt_base_t    rt_err_t;
typedef rt_ubase_t   rt_size_t;
typedef rt_base_t    rt_ssize_t;
/* rtdef.h:58-59 的 rt_off_t 在无 RT_USING_LIBC 时就是 rt_base_t 的别名 */
typedef rt_base_t    rt_off_t;
/* rtdef.h:97，tick 是 uint32_t */
typedef rt_uint32_t  rt_tick_t;
typedef int          rt_bool_t;

#define RT_NULL  ((void *)0)
#define RT_TRUE  (1)
#define RT_FALSE (0)

/*
 * 错误码取自 rtdef.h:269-276 的"非 libc"分支（本 BSP 未定义 RT_USING_LIBC）。
 * 被测代码只做 `return -RT_ERROR` / `return -RT_ENOMEM`，测试断言的是
 * "返回值是某个非 RT_EOK 的错误码"，不依赖这些数字的具体取值。
 */
#define RT_EOK    (0)
#define RT_ERROR  (1)
#define RT_ENOMEM (5)
#define RT_EBUSY  (7)

/* rtdef.h:973 / 980 */
#define RT_IPC_FLAG_PRIO    (0x01)
#define RT_WAITING_FOREVER  (-1)

/* rtconfig.h:13 */
#define RT_TICK_PER_SECOND  (1000)

/*
 * rtdef.h:824 的 rt_container_of()。被测文件用不到，但保留它代价为零，
 * 且能让"桩掉了什么"这条留痕更完整。
 */
#define rt_container_of(ptr, type, member) \
    ((type *)((char *)(ptr) - (rt_ubase_t)(&((type *)0)->member)))

/* 真实 rtthread.h:429-443。g_snapshot_mutex 是本文件里的 static 实例，
 * 所以 struct rt_mutex 必须是完整类型；字段只为让主机上的桩能记录状态。 */
struct rt_mutex
{
    const char *name;
    rt_uint8_t  flag;
    int         taken;
};
typedef struct rt_mutex *rt_mutex_t;

/* 真实 rtthread.h:156-167。被测文件只保存/传递指针，不 deref。 */
struct rt_thread;
typedef struct rt_thread *rt_thread_t;

/* 真实 rtthread.h:655-691。struct rt_device 在真实内核里是完整类型，
 * 但被测文件从不 deref（只把它当 rt_device_t 句柄传给设备 API），
 * 所以这里留成不完整类型，桩实现里也不碰它。 */
struct rt_device;
typedef struct rt_device *rt_device_t;

/* 真实 rthw.h 的临界区，被测文件不用，不桩。 */

void  *rt_memset(void *s, int c, rt_ubase_t count);
void  *rt_memcpy(void *dst, const void *src, rt_ubase_t count);

/* 本文档顶部说的三个时间原语：真实实现由内核的 tick 中断驱动，主机上由
 * test_run_one_cycle_d2_c.c 里的假时钟驱动，语义见那里的注释。 */
rt_tick_t rt_tick_get(void);
rt_err_t  rt_thread_yield(void);
rt_err_t  rt_thread_mdelay(rt_int32_t ms);
rt_thread_t rt_thread_create(const char *name,
                             void (*entry)(void *parameter),
                             void       *parameter,
                             rt_uint32_t stack_size,
                             rt_uint8_t  priority,
                             rt_uint32_t tick);
rt_err_t rt_thread_startup(rt_thread_t thread);
rt_err_t rt_thread_delete(rt_thread_t thread);

rt_err_t rt_mutex_init(rt_mutex_t mutex, const char *name, rt_uint8_t flag);
rt_err_t rt_mutex_detach(rt_mutex_t mutex);
rt_err_t rt_mutex_take(rt_mutex_t mutex, rt_int32_t timeout);
rt_err_t rt_mutex_release(rt_mutex_t mutex);

/*
 * 真实 rtdef.h:128/161/169 的 INIT_EXPORT()：
 *   typedef int (*init_fn_t)(void);
 *   #define INIT_EXPORT(fn, level) \
 *       rt_used const init_fn_t __rt_init_##fn rt_section(".rti_fn." level) = fn
 * 注意 init_fn_t 的返回类型是 int（与 servo_bus_readonly_init() 的签名一致）。
 * 主机上没有 .rti_fn.5 这个段（PE 目标），所以去掉 section 属性，只保留
 * "一个被引用的函数指针"。副作用有两处，都是想要的：
 *   1. servo_bus_readonly_init() 因此"被使用"，不会报 -Wunused-function；
 *   2. main() 不会自动调用它——本测试要自己把 g_group 摆到指定状态，
 *      不能让它跑真实初始化。
 */
typedef int (*init_fn_t)(void);
#define INIT_EXPORT(fn, level) \
    static const init_fn_t __rt_init_##fn __attribute__((used)) = fn
#define INIT_APP_EXPORT(fn)    INIT_EXPORT(fn, "5")

/* 真实 rtthread.h 的断言面。被测文件里没有 RT_ASSERT，但保留它可以让
 * 变异体（如果将来有人往里加断言）不会静默编过。 */
void rt_assert_handler(const char *ex_string, const char *func, rt_size_t line);
#define RT_ASSERT(EX)                                                \
    ((EX) ? (void)0                                                  \
          : rt_assert_handler(#EX, __func__, (rt_size_t)__LINE__))

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_SERVO_RTTHREAD_H */
