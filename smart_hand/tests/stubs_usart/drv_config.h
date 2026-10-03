#ifndef SMART_HAND_TESTS_STUBS_USART_DRV_CONFIG_H
#define SMART_HAND_TESTS_STUBS_USART_DRV_CONFIG_H

/*
 * 主机桩：libraries/HAL_Drivers/config/drv_config.h + config/ra8/uart_config.h。
 *
 * 真实链路是 drv_config.h 按 SOC_SERIES_* 选 config/<系列>/uart_config.h，
 * uart_config.h 再把 UARTn_CONFIG 展开成 { .name = "uartn",
 * .p_api_ctrl = &g_uartn_ctrl, .p_cfg = &g_uartn_cfg }。本桩把这一层的效果
 * 直接写出来，值逐字对过真实文件：
 *   - config/ra8/uart_config.h:32-52 的 UART1_CONFIG / UART2_CONFIG
 *   - rtconfig.h:359-363 的 BSP_UART1_RX_BUFSIZE 256 / TX 0、
 *     BSP_UART2_RX_BUFSIZE 256 / TX 0
 *
 * 只有 UART1、UART2 有定义 —— 与工程实际启用的口一致（rtconfig.h:359,362）。
 * 编译时若有人加上 -DBSP_USING_UART3，这里会立刻因 UART3_CONFIG 未定义而报错，
 * 而不是给出一个假的口。
 */

#include <drv_common.h>
#include <hal_data.h>

#define BSP_UART1_RX_BUFSIZE 256
#define BSP_UART1_TX_BUFSIZE 0
#define BSP_UART2_RX_BUFSIZE 256
#define BSP_UART2_TX_BUFSIZE 0

#define UART1_CONFIG                    \
    {                                   \
        .name = "uart1",                \
        .p_api_ctrl = &g_uart1_ctrl,    \
        .p_cfg = &g_uart1_cfg,          \
    }

#define UART2_CONFIG                    \
    {                                   \
        .name = "uart2",                \
        .p_api_ctrl = &g_uart2_ctrl,    \
        .p_cfg = &g_uart2_cfg,          \
    }

#endif /* SMART_HAND_TESTS_STUBS_USART_DRV_CONFIG_H */
