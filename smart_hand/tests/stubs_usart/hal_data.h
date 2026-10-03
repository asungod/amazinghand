#ifndef SMART_HAND_TESTS_STUBS_USART_HAL_DATA_H
#define SMART_HAND_TESTS_STUBS_USART_HAL_DATA_H

/*
 * 主机桩：ra_gen/hal_data.h + FSP 的 UART 接口面。
 *
 * 这里有两类东西，规则不同。
 *
 * 1. 驱动面（字面取自真实 FSP 头，被测文件才编得过）：
 *
 *      ra/fsp/inc/api/r_uart_api.h   fsp_err_t、FSP_SUCCESS、uart_event_t、
 *                                    uart_callback_args_t、uart_ctrl_t(== void)
 *      ra/fsp/inc/instances/r_sci_b_uart.h
 *                                    sci_b_uart_instance_ctrl_t（只留 p_reg）
 *      ra_gen/hal_data.h:98-100,340   g_uart1_ctrl/g_uart1_cfg/g_uart2_ctrl/g_uart2_cfg
 *      R7KA8P1KF_core0.h:75925-75937  R_SCI_B0_CCR0_*_Msk
 *
 *    uart_cfg_t 在真实头里是一大坨（baud/data_bits/callback/p_extend...），
 *    被测文件只拿它的地址（uart->config->p_cfg）转交给 R_SCI_B_UART_Open，
 *    从不读字段，所以这里退化成只有 channel 的占位结构，并在测试里用
 *    "地址是否等于 uart_config[] 里那一项"来验证传参没错。
 *
 * 2. 测试控制面（usart_stub_* 符号）：实现全部在 tests/test_drv_usart_v2_c.c。
 *    这些不是对 FSP 的模拟，而是插桩：它们记录被测代码调了谁、按什么顺序、
 *    参数是什么，供断言读取。
 *
 * 关于 R_SCI_B_UART_Open：真实驱动在返回前就使能了接收与 RXI/ERI 中断
 * （ra/fsp/src/r_sci_b_uart/r_sci_b_uart.c:381-388），这正是本补丁要处理的启动窗口。
 * 桩函数保留了这个语义：可以在"返回前"同步回调一个字节，把那个窗口真实地复现出来
 * （见 usart_stub_open_inject_*）。
 */

#include <stddef.h>
#include <stdint.h>

#include <rtthread.h>
#include <rtdevice.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---------------------------------------------------------------------- */
/* FSP 公共类型（r_fsp_error.h / r_uart_api.h） */

typedef int32_t fsp_err_t;

#define FSP_SUCCESS (0)
#define FSP_ERR_ABORTED (1)

/* r_uart_api.h:155 */
typedef void uart_ctrl_t;

/* r_uart_api.h:46-56，取值与真实枚举一致（UART_EVENT_RX_CHAR == 1<<2） */
typedef enum e_sf_event
{
    UART_EVENT_RX_COMPLETE   = (1UL << 0),
    UART_EVENT_TX_COMPLETE   = (1UL << 1),
    UART_EVENT_RX_CHAR       = (1UL << 2),
    UART_EVENT_ERR_PARITY    = (1UL << 3),
    UART_EVENT_ERR_FRAMING   = (1UL << 4),
    UART_EVENT_ERR_OVERFLOW  = (1UL << 5),
    UART_EVENT_BREAK_DETECT  = (1UL << 6),
    UART_EVENT_TX_DATA_EMPTY = (1UL << 7)
} uart_event_t;

/* r_uart_api.h:107-117 */
typedef struct st_uart_callback_arg
{
    uint32_t     channel;
    uart_event_t event;
    uint32_t     data;
    void        *p_context;
} uart_callback_args_t;

/* r_uart_api.h 的 uart_cfg_t：只留占位字段，见文件头说明。 */
typedef struct st_uart_cfg
{
    uint32_t channel;
} uart_cfg_t;

/* R7KA8P1 的 SCI_B 寄存器面：只保留 drv_usart_v2.c:ra_uart_putc() 引用的位。
 * 位序号与真实设备头一致（CCR0 的 TE=bit4 / TIE=bit20 / TEIE=bit21）。 */
#define R_SCI_B0_CCR0_TE_Msk   (0x10UL)
#define R_SCI_B0_CCR0_TIE_Msk  (0x100000UL)
#define R_SCI_B0_CCR0_TEIE_Msk (0x200000UL)

typedef struct
{
    uint32_t TEND : 1;
    uint32_t TDRE : 1;
    uint32_t reserved : 30;
} r_sci_b_csr_b_t;

typedef struct
{
    uint32_t TIST : 1;
    uint32_t reserved : 31;
} r_sci_b_cesr_b_t;

typedef struct
{
    volatile uint32_t          CCR0;
    volatile uint32_t          TDR;
    volatile r_sci_b_csr_b_t   CSR_b;
    volatile r_sci_b_cesr_b_t  CESR_b;
} R_SCI_B0_Type;

/* r_sci_b_uart.h:70-87：真实结构体还有 p_cfg/p_callback/p_context 等，
 * 被测文件只引用 p_reg，其余不桩。 */
typedef struct
{
    R_SCI_B0_Type *p_reg;
} sci_b_uart_instance_ctrl_t;

/* ra_gen/hal_data.h:98-100, 340-341 */
extern sci_b_uart_instance_ctrl_t g_uart1_ctrl;
extern const uart_cfg_t           g_uart1_cfg;
extern sci_b_uart_instance_ctrl_t g_uart2_ctrl;
extern const uart_cfg_t           g_uart2_cfg;

/* ra/fsp/inc/api/r_uart_api.h：drv_usart_v2.c:215 在 SOC_SERIES_R7KA8P1 下调用它 */
fsp_err_t R_SCI_B_UART_Open(uart_ctrl_t *const p_api_ctrl,
                            uart_cfg_t const *const p_cfg);

/* 被测文件定义的回调（BSP 把它注册进 FSP） */
void user_uart1_callback(uart_callback_args_t *p_args);
void user_uart2_callback(uart_callback_args_t *p_args);

/* ---------------------------------------------------------------------- */
/* 测试控制面。实现见 tests/test_drv_usart_v2_c.c */

/* RT_ASSERT 触发次数。正常路径下必须恒为 0；变异版本（把空指针防护恢复成断言）
 * 会让它变成 1，测试随即判负。 */
extern unsigned usart_stub_assert_hits;
extern char     usart_stub_assert_expr[128];
extern char     usart_stub_assert_func[64];
extern int      usart_stub_assert_line;

/* rt_ringbuffer_putchar() 观测 */
extern unsigned                usart_stub_putchar_calls;
extern unsigned                usart_stub_putchar_success;
extern unsigned                usart_stub_putchar_null_rb;
extern struct rt_ringbuffer   *usart_stub_putchar_last_rb;
extern rt_uint8_t              usart_stub_putchar_last_data;

/* rt_hw_serial_isr() 观测 */
extern unsigned                   usart_stub_isr_calls;
extern int                        usart_stub_isr_last_event;
extern struct rt_serial_device   *usart_stub_isr_last_serial;
/* isr 被调用时 serial_rx 竟然还没发布 */
extern unsigned                   usart_stub_isr_null_fifo;
/* isr 被调用时 ring 里没有新字节 ⇒ 调用顺序反了（先 isr 后 putchar） */
extern unsigned                   usart_stub_isr_seen_empty_ring;
/* 进 isr 时 ring 里已有的字节数（真实 isr 就是搬这些） */
extern unsigned                   usart_stub_isr_ring_bytes_first;
/* 0 = 纯观测：isr 只记账，不把 ring 里的字节搬走 */
extern unsigned                   usart_stub_isr_drain_enabled;
/* isr 累计搬走的字节数 */
extern unsigned                   usart_stub_isr_drained_total;
/* 第一次 putchar / 第一次 isr 的相对先后：1 = 先 putchar，2 = 先 isr，0 = 未发生 */
extern unsigned                   usart_stub_first_op;

/* isr 搬走的字节（也就是真实串口层会交给上层应用的数据） */
#define USART_STUB_DELIVERED_CAP 1024
extern rt_uint8_t usart_stub_delivered[USART_STUB_DELIVERED_CAP];
extern unsigned   usart_stub_delivered_count;

/* rt_interrupt_enter()/rt_interrupt_leave() 观测 */
extern unsigned usart_stub_enter_calls;
extern unsigned usart_stub_leave_calls;
extern int      usart_stub_irq_depth;
extern unsigned usart_stub_leave_without_enter;

/* R_SCI_B_UART_Open() 观测 */
extern unsigned    usart_stub_open_calls;
extern void       *usart_stub_open_last_ctrl;
extern const void *usart_stub_open_last_cfg;
extern fsp_err_t   usart_stub_open_result;
/* 让桩函数在"返回前"注入若干个接收字节，复现 r_sci_b_uart.c:381-388 的窗口 */
extern unsigned    usart_stub_open_inject_bytes;
extern rt_uint8_t  usart_stub_open_inject_first;
extern void      (*usart_stub_open_inject_callback)(uart_callback_args_t *p_args);
/* 实际注入成功的字节数：为 0 就说明那个窗口根本没进过，用例是空跑的 */
extern unsigned    usart_stub_open_injected;

/* rt_hw_serial_register() 观测 */
extern unsigned                   usart_stub_reg_calls;
extern const char                *usart_stub_reg_names[4];
extern struct rt_serial_device   *usart_stub_reg_serials[4];
extern rt_uint32_t                usart_stub_reg_flags[4];

/* 每个用例开头清零（断言/enter-leave/调用计数都归零，FIFO 内容由用例自己铺） */
void usart_stub_reset(void);

/* 把 rt_serial_rx_fifo 初始化成一个可用的环形缓冲 */
void usart_stub_fifo_init(struct rt_serial_rx_fifo *fifo);

/* 从环形缓冲里按真实 mirror 语义取出已写入的字节，返回取出的个数 */
unsigned usart_stub_fifo_drain(struct rt_serial_rx_fifo *fifo,
                               rt_uint8_t *out,
                               unsigned    out_cap);

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_USART_HAL_DATA_H */
