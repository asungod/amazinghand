#ifndef SMART_HAND_TESTS_STUBS_SERVO_HAL_DATA_H
#define SMART_HAND_TESTS_STUBS_SERVO_HAL_DATA_H

/*
 * 主机桩：FSP 生成的板级数据头（ra_gen/hal_data.h + ra_gen/common_data.h）
 * 以及它背后真正定义这些类型的 FSP 头文件。
 *
 * 被测文件 src/servo_bus_readonly_rt.c 通过 <hal_data.h> 用到：
 *
 *   sci_b_uart_instance_ctrl_t  g_uart1_ctrl      （发送/等待 TEND 的寄存器句柄）
 *   ioport_instance_ctrl_t      g_ioport_ctrl     （servo_bus_readonly_init 里配 TX 引脚）
 *   fsp_err_t / FSP_SUCCESS                       （R_SCI_B_UART_Write 返回值）
 *   uart_ctrl_t                                   （FSP 的"void *"句柄，见 r_uart_api.h:155）
 *   R_SCI_B0_Type 的 CSR_b.TEND                   （发送完成标志）
 *   R_SCI_B_UART_Write / BaudCalculate / BaudSet
 *   R_IOPORT_PinCfg + IOPORT_CFG_* / IOPORT_PERIPHERAL_* + BSP_IO_PORT_*
 *
 * 数值与结构布局逐条照抄真实头文件（行号在注释里）。这些不是"随便给个值
 * 能编过就行"：CSR_b.TEND 的位序决定 while 循环读的是不是真正的那一位，
 * BSP_IO_PORT_xx 的值决定 set_leds 写的是不是正确引脚，测试会对着它们断言。
 *
 * 与真实头文件的差异：
 *   - uart_cfg_t / uart_callback_args_t / bsp_io_port_pin_t 在真实 FSP 里是
 *     完整类型；这里只留前置声明，因为被测文件只用到指向它们的指针成员。
 *   - sci_b_uart_instance_ctrl_t 逐字段照抄（r_sci_b_uart.h:52-87），
 *     只把 bsp_io_port_pin_t 换成 uint16_t（等价：真实定义是 uint16 的枚举，
 *     见 r_ioport.h 的 e_ioport_port_pin_t）；uart_cfg_t / uart_callback_args_t
 *     指针成员保留，用前置声明满足。
 *   - sci_b_baud_setting_t 逐字段照抄（r_sci_b_uart.h:138-160）。
 *   - R_SCI_B0_Type 只保留 CSR 这一个寄存器（真实结构体 124 字节，
 *     见 R7KA8P1KF_core0.h:25302-25840）。被读到的只有 CSR_b.TEND。
 *   - FSP 的错误码只保留测试可能用到的前几个（真实是 0x00000..0x40000 的
 *     长枚举）。FSP_SUCCESS 必须是 0，这是被断言的值。
 *   - g_uart1_ctrl / g_ioport_ctrl 在真实工程里定义在 ra_gen/hal_data.c 与
 *     common_data.c；本测试的 TU 自己提供同名对象（唯一的定义），所以链接
 *     不会去碰 ra_gen。
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ra/fsp/inc/api/fsp_common_api.h:59-63 的 e_fsp_err 枚举 */
typedef enum e_fsp_err
{
    FSP_SUCCESS                = 0,
    FSP_ERR_ASSERTION          = 1,  /* A critical assertion has failed */
    FSP_ERR_INVALID_POINTER    = 2,  /* Pointer points to invalid memory location */
    FSP_ERR_INVALID_ARGUMENT   = 3,  /* Invalid input parameter */
    FSP_ERR_INVALID_CHANNEL    = 4,  /* Selected channel does not exist */
    FSP_ERR_UNSUPPORTED        = 6,  /* Selected mode not supported by this API */
    FSP_ERR_ABORTED            = 13, /* Wait aborted. */
    FSP_ERR_NOT_OPEN           = 15, /* Peripheral is not open. */
    FSP_ERR_IN_USE             = 16  /* Peripheral is in use. */
} fsp_err_t;

/* ra/fsp/inc/api/r_uart_api.h:155 —— FSP 的 UART 句柄就是 void *。
 * 被测代码写 R_SCI_B_UART_Write((uart_ctrl_t *)&g_uart1_ctrl, ...)，
 * 桩实现必须再转回 sci_b_uart_instance_ctrl_t * 才能读它，与固件一致。 */
typedef void uart_ctrl_t;
/* ra/fsp/inc/api/r_ioport_api.h:63 */
typedef void ioport_ctrl_t;

/* 只留前置声明：被测文件不用它们的成员 */
typedef struct st_uart_cfg        uart_cfg_t;
typedef struct st_uart_callback_args uart_callback_args_t;

/* ra/fsp/src/bsp/mcu/all/bsp_io.h:99/109/111/200 的 e_bsp_io_port_pin_t。
 * 本桩只需要这四个；值照抄（0x0npp：端口号 << 8 | 引脚号）。 */
#define BSP_IO_PORT_01_PIN_08  (0x0108)
#define BSP_IO_PORT_01_PIN_09  (0x0109)
#define BSP_IO_PORT_01_PIN_10  (0x010A)
#define BSP_IO_PORT_07_PIN_07  (0x0707)

/* ra/fsp/inc/instances/r_ioport.h:475 / 481 / 337 */
#define IOPORT_CFG_DRIVE_HIGH          (0x00000C00)
#define IOPORT_CFG_PERIPHERAL_PIN      (0x00010000)
#define IOPORT_PERIPHERAL_SCI1_3_5_7_9 (0x05UL << 24)

/*
 * R7KA8P1KF_core0.h:25748-25772 里 R_SCI_B0_Type 的 CSR 寄存器。
 * 位序逐个照抄：4 位保留，ERS=4，10 位保留，RXDMON=15，DCMF=16，DPER=17，
 * DFER=18，5 位保留，ORER=24，1 位保留，MFF=26，PER=27，FER=28，TDRE=29，
 * TEND=30，RDRF=31。真实类型是 __IM（只读），桩里用 volatile 以便测试
 * 主动摆位置，语义差别只影响"写只读位"这件事，而本测试要写 TEND。
 */
typedef struct st_sci_b0_csr
{
    union
    {
        volatile uint32_t CSR;

        struct
        {
            volatile uint32_t       : 4;
            volatile uint32_t ERS   : 1;  /* [4]  Error Signal Status Flag */
            volatile uint32_t       : 10;
            volatile uint32_t RXDMON: 1;  /* [15] Serial input data monitor bit */
            volatile uint32_t DCMF  : 1;  /* [16] Data Compare Match Flag */
            volatile uint32_t DPER  : 1;  /* [17] Data Compare Match Parity Error */
            volatile uint32_t DFER  : 1;  /* [18] Data Compare Match Framing Error */
            volatile uint32_t       : 5;
            volatile uint32_t ORER  : 1;  /* [24] Overrun Error Flag */
            volatile uint32_t       : 1;
            volatile uint32_t MFF   : 1;  /* [26] Mode Fault Flag */
            volatile uint32_t PER   : 1;  /* [27] Parity Error Flag */
            volatile uint32_t FER   : 1;  /* [28] Framing Error Flag */
            volatile uint32_t TDRE  : 1;  /* [29] Transmit Data Empty Flag */
            volatile uint32_t TEND  : 1;  /* [30] Transmit End Flag */
            volatile uint32_t RDRF  : 1;  /* [31] Receive Data Full Flag */
        } CSR_b;
    };
} R_SCI_B0_Type;

/* ra/fsp/inc/instances/r_sci_b_uart.h:138-160，逐字段照抄 */
typedef struct st_sci_b_baud_setting_t
{
    union
    {
        uint32_t baudrate_bits;

        struct
        {
            uint32_t       : 3;
            uint32_t       : 1;
            uint32_t bgdm  : 1;  /* Baud Rate Generator Double-Speed Mode Select */
            uint32_t abcs  : 1;  /* Asynchronous Mode Base Clock Select */
            uint32_t abcse : 1;  /* Asynchronous Mode Extended Base Clock Select 1 */
            uint32_t       : 1;
            uint32_t brr   : 8;  /* Bit Rate Register setting */
            uint32_t brme  : 1;  /* Bit Rate Modulation Enable */
            uint32_t       : 3;
            uint32_t cks   : 2;  /* CKS value to get divisor (CKS = N) */
            uint32_t       : 2;
            uint32_t mddr  : 8;  /* Modulation Duty Register setting */
        } baudrate_bits_b;
    };
} sci_b_baud_setting_t;

/* ra/fsp/inc/instances/r_sci_b_uart.h:52-87，逐字段照抄（见本文件顶部说明） */
typedef struct st_sci_b_uart_instance_ctrl
{
    /* Parameters to control UART peripheral device */
    uint8_t  fifo_depth;               /* FIFO depth of the UART channel */
    uint8_t  rx_transfer_in_progress;  /* 1 if a receive transfer is in progress */
    uint8_t  data_bytes         : 2;   /* 1 byte for 7 or 8 bit data, 2 for 9 bit */
    uint8_t  bitrate_modulation : 1;   /* 1 if bit rate modulation is enabled */
    uint32_t open;                     /* Used to determine if the channel is configured */
    uint32_t delay_loops;

    uint16_t flow_pin;                 /* 真实类型 bsp_io_port_pin_t（uint16 枚举） */

    /* Source buffer pointer used to fill hardware FIFO from transmit ISR. */
    uint8_t const * p_tx_src;

    /* Size of source buffer pointer used to fill hardware FIFO from transmit ISR. */
    uint32_t tx_src_bytes;

    /* Destination buffer pointer used for receiving data. */
    uint8_t const * p_rx_dest;

    /* Size of destination buffer pointer used for receiving data. */
    uint32_t rx_dest_bytes;

    /* Pointer to the configuration block. */
    uart_cfg_t const * p_cfg;

    /* Base register for this channel */
    R_SCI_B0_Type * p_reg;

    void (* p_callback)(uart_callback_args_t *);
    uart_callback_args_t * p_callback_memory;

    /* Pointer to context to be passed into callback function */
    void * p_context;
} sci_b_uart_instance_ctrl_t;

/* ra/fsp/inc/instances/r_ioport.h:41-45 */
typedef struct st_ioport_instance_ctrl
{
    uint32_t open;
    void   * p_context;
} ioport_instance_ctrl_t;

/* ra_gen/hal_data.h:98 / ra_gen/common_data.h:228 —— 真实工程里这两个对象
 * 定义在 ra_gen 下的 .c 里。本测试的 TU 提供唯一一份定义
 * （见 test_run_one_cycle_d2_c.c），所以不需要 ra_gen 参与链接。 */
extern sci_b_uart_instance_ctrl_t g_uart1_ctrl;
extern ioport_instance_ctrl_t     g_ioport_ctrl;

/* ra/fsp/inc/instances/r_sci_b_uart.h:197-205 */
fsp_err_t R_SCI_B_UART_Write(uart_ctrl_t * const p_api_ctrl,
                             uint8_t const * const p_src,
                             uint32_t const bytes);
fsp_err_t R_SCI_B_UART_BaudSet(uart_ctrl_t * const p_api_ctrl,
                               void const * const p_baud_setting);
fsp_err_t R_SCI_B_UART_BaudCalculate(uint32_t baudrate,
                                     bool bitrate_modulation,
                                     uint32_t baud_rate_error_x_1000,
                                     sci_b_baud_setting_t * const p_baud_setting);

/* ra/fsp/inc/instances/r_ioport.h:519 */
fsp_err_t R_IOPORT_PinCfg(ioport_ctrl_t * const p_ctrl,
                          uint16_t pin,
                          uint32_t cfg);

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_SERVO_HAL_DATA_H */
