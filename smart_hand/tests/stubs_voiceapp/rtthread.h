#ifndef SMART_HAND_TESTS_STUBS_VOICEAPP_RTTHREAD_H
#define SMART_HAND_TESTS_STUBS_VOICEAPP_RTTHREAD_H

/*
 * Host stub for the RT-Thread kernel header, sized for voice_app_titan.c.
 *
 * This is a second, larger stub set than tests/stubs/ on purpose. That one is
 * the PDM adaptation layer's model and deliberately stops at the interrupt
 * mask; voice_app_titan.c additionally creates a thread, so this header has to
 * describe struct rt_thread and the thread calls.
 *
 * What it is FOR is narrower than "make it link". A thread's priority, stack
 * size and name are not observable from the module's own state -- they are
 * arguments handed to the kernel -- so the stub records them and the test
 * asserts on what was actually passed. On the board, a voice thread that
 * outranks sh_uart would be a late UART byte under load, which is a protocol
 * fault rather than a missed keyword, and nothing in a normal host test would
 * have noticed.
 *
 * rt_thread_mdelay() is also the hook that makes the real thread entry
 * runnable: the entry is an infinite loop, so the test runs it under
 * setjmp/longjmp and has this function escape after a chosen number of
 * iterations. The loop body under test is still the module's own.
 *
 * The implementations live in tests/test_voice_app_titan_c.c, which the build
 * line compiles alongside the module under test.
 */

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef long rt_base_t;
typedef unsigned long rt_ubase_t;
typedef int32_t rt_int32_t;
typedef uint32_t rt_uint32_t;
typedef uint8_t rt_uint8_t;
typedef uint32_t rt_tick_t;
typedef long rt_err_t;

struct rt_thread;
typedef struct rt_thread *rt_thread_t;

/*
 * Only the fields rt_thread_init() is handed. The real struct is far larger;
 * none of it is needed to observe the call.
 */
struct rt_thread
{
    char name[16];
    void (*entry)(void *parameter);
    void *parameter;
    void *stack_start;
    rt_uint32_t stack_size;
    rt_uint8_t priority;
    rt_uint32_t tick;
};

#define RT_NULL ((void *)0)
#define RT_EOK 0
#define RT_ERROR 1

#define RT_TICK_PER_SECOND (1000U)

/* Everything the module told the kernel, kept for the assertions. */
typedef struct
{
    uint32_t init_calls;
    uint32_t startup_calls;
    uint32_t detach_calls;
    uint32_t sleep_calls;
    uint32_t last_sleep_ms;

    char name[16];
    void (*entry)(void *parameter);
    void *parameter;
    void *stack_start;
    rt_uint32_t stack_size;
    rt_uint8_t priority;
    rt_uint32_t tick;
} voice_thread_recorder_t;

extern voice_thread_recorder_t g_voice_thread_recorder;

/* Escape hatch for driving the infinite thread entry from the host. */
#define VOICE_STUB_ESCAPE_OK 0
#define VOICE_STUB_ESCAPE_DONE 1

rt_err_t rt_thread_init(struct rt_thread *thread,
                        const char *name,
                        void (*entry)(void *parameter),
                        void *parameter,
                        void *stack_start,
                        rt_uint32_t stack_size,
                        rt_uint8_t priority,
                        rt_uint32_t tick);
rt_err_t rt_thread_detach(rt_thread_t thread);
rt_err_t rt_thread_startup(rt_thread_t thread);
rt_err_t rt_thread_mdelay(rt_int32_t ms);

rt_tick_t rt_tick_get(void);
rt_tick_t rt_tick_get_millisecond(void);

int rt_kprintf(const char *fmt, ...);

#ifdef __cplusplus
}
#endif

#endif
