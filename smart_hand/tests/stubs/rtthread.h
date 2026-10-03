#ifndef SMART_HAND_TESTS_STUBS_RTTHREAD_H
#define SMART_HAND_TESTS_STUBS_RTTHREAD_H

/*
 * Host stub for the RT-Thread kernel header.
 *
 * voice_audio_titan.c is the FSP/RT-Thread adaptation layer, so it cannot be
 * exercised on the host without stand-ins for the handful of kernel primitives
 * it touches. This header provides exactly those and nothing else: a host test
 * that quietly pulled in the real rtthread.h would need the whole BSP to link,
 * and the point of this file set is to keep that dependency at zero.
 *
 * The implementations live in tests/test_voice_audio_titan_c.c, which the
 * build line already compiles alongside the module under test.
 *
 * What matters for the tests is not the delay semantics but the interrupt
 * masking: rt_hw_interrupt_disable/enable are modelled as a nesting counter so
 * a test can assert that every critical section in the module is balanced
 * (pdm_stub_irq_depth() back to zero), which is the one class of bug a host
 * build can still catch in that code.
 */

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef long               rt_base_t;
typedef unsigned long      rt_ubase_t;
typedef int32_t            rt_int32_t;
typedef uint32_t           rt_tick_t;
typedef rt_base_t          rt_err_t;

/* The firmware ticks at 1000 Hz; the probe in the module divides by this. */
#define RT_TICK_PER_SECOND (1000U)

void *rt_memset(void *s, int c, rt_ubase_t count);

/* Simulated millisecond tick, advanced by rt_thread_mdelay(). */
rt_tick_t rt_tick_get(void);

void rt_thread_mdelay(rt_int32_t ms);

#ifdef __cplusplus
}
#endif

#endif
