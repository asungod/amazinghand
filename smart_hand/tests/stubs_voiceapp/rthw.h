#ifndef SMART_HAND_TESTS_STUBS_VOICEAPP_RTHW_H
#define SMART_HAND_TESTS_STUBS_VOICEAPP_RTHW_H

/*
 * Host stub for the RT-Thread hardware layer.
 *
 * Only the interrupt mask pair is needed, and it is modelled as a nesting
 * counter for the same reason as tests/stubs/rthw.h: an unbalanced
 * rt_hw_interrupt_disable() is silent on hardware and a counter is the only
 * way a host build sees it. voice_app_titan_status() and
 * voice_app_titan_state() both take the mask, so the test can assert that
 * every snapshot leaves the depth back at zero -- a snapshot that returned
 * with interrupts still off would stop the whole scheduler.
 */

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

rt_base_t rt_hw_interrupt_disable(void);
void rt_hw_interrupt_enable(rt_base_t level);

#ifdef __cplusplus
}
#endif

#endif
