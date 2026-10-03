#ifndef SMART_HAND_TESTS_STUBS_RTHW_H
#define SMART_HAND_TESTS_STUBS_RTHW_H

/*
 * Host stub for the RT-Thread hardware layer.
 *
 * Only the interrupt mask pair is needed. It is modelled as a nesting counter
 * so the tests can check that the module's critical sections are balanced --
 * an unbalanced rt_hw_interrupt_disable() is a silent bug on hardware and the
 * counter is the only way a host build can see it.
 *
 * The real signature returns the *previous* mask state and takes it back in
 * rt_hw_interrupt_enable; the stub returns the nesting depth it is about to
 * leave, which is the same contract for a single-level mask model.
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
