#ifndef SMART_HAND_TESTS_STUBS_BOARD_H
#define SMART_HAND_TESTS_STUBS_BOARD_H

/*
 * Host stub for the Titan board header.
 *
 * The real board/board.h only pulls in hal_data.h and defines the heap bounds;
 * the FSP delay primitive the module uses (R_BSP_SoftwareDelay) comes from
 * bsp_api.h, which board.h reaches transitively. Both are reproduced here so
 * the module's one BSP call compiles and can be observed.
 *
 * BSP_DELAY_UNITS_MICROSECONDS is copied from FSP's e_bsp_delay_units so a
 * wrong unit argument would be visible to the test rather than silently equal.
 */

#include <stdint.h>

#include "hal_data.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum e_bsp_delay_units
{
    /*
     * Values match ra/fsp/src/bsp/mcu/all/bsp_delay.h exactly. This is a
     * multiplier enum, not an ordinal one: MICROSECONDS is 1, not 2. An
     * earlier stub used 0/1/2 ordinals while claiming to be copied from FSP,
     * so the host test was asserting against a fake value.
     */
    BSP_DELAY_UNITS_SECONDS      = 1000000, /* Requested delay amount is in seconds */
    BSP_DELAY_UNITS_MILLISECONDS = 1000,    /* Requested delay amount is in milliseconds */
    BSP_DELAY_UNITS_MICROSECONDS = 1        /* Requested delay amount is in microseconds */
} bsp_delay_units_t;

void R_BSP_SoftwareDelay(uint32_t delay, bsp_delay_units_t units);

#ifdef __cplusplus
}
#endif

#endif
