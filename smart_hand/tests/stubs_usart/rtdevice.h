#ifndef SMART_HAND_TESTS_STUBS_USART_RTDEVICE_H
#define SMART_HAND_TESTS_STUBS_USART_RTDEVICE_H

/*
 * 主机桩：RT-Thread 设备框架头（rt-thread/include/rtdevice.h +
 * rt-thread/components/drivers/include/drivers/serial_v2.h +
 * rt-thread/components/drivers/include/ipc/ringbuffer.h 的相关部分）。
 *
 * 被测文件用到的面：
 *   struct rt_serial_device   .config / .ops / .serial_rx
 *   struct rt_uart_ops        configure/control/putc/getc/transmit
 *   struct rt_serial_rx_fifo  .rb
 *   struct rt_ringbuffer      （只是被取地址后交给 rt_ringbuffer_putchar）
 *   RT_SERIAL_CONFIG_DEFAULT  ra_uart_get_config() 用它做初始配置
 *   RT_SERIAL_EVENT_RX_IND    rt_hw_serial_isr() 的事件号
 *   RT_DEVICE_FLAG_RDWR       rt_hw_serial_register() 的 flag
 *
 * 与真实头文件的差异（都不影响被测代码，逐条列出以免误以为桩得更全）：
 *   - struct rt_device / struct rt_device_notify 只留占位字段。被测代码从不碰
 *     serial->parent 与 rx_notify，真实结构体里的字段名与布局对本测试无意义。
 *   - struct rt_serial_rx_fifo 的 buffer 在真实头里是柔性数组 buffer[]（由
 *     rt_malloc 分配），这里给成固定容量数组，好让测试能静态分配一个 FIFO。
 *   - rt_device 的引用计数/类型/rt_ringbuffer 的 mirror 位算法都按真实语义实现
 *     （putchar 会真的写进 ring 并推进 write_index），因为"字节准确写入"这条
 *     断言的证据就是它。
 *   - struct serial_configure 的位域布局照抄 serial_v2.h:105-119。
 */

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* rtdef.h */
#define RT_DEVICE_FLAG_RDWR  (0x003)

/* rtdef.h:1280-1287，被测文件在 ra_uart_transmit() 里用到 SET_INT */
#define RT_DEVICE_CTRL_RESUME    0x01
#define RT_DEVICE_CTRL_SUSPEND   0x02
#define RT_DEVICE_CTRL_CONFIG    0x03
#define RT_DEVICE_CTRL_CLOSE     0x04
#define RT_DEVICE_CTRL_SET_INT   0x06
#define RT_DEVICE_CTRL_CLR_INT   0x07
#define RT_DEVICE_CTRL_GET_INT   0x08

/* serial_v2.h:69-75 */
#define RT_SERIAL_EVENT_RX_IND      0x01
#define RT_SERIAL_EVENT_TX_DONE     0x02
#define RT_SERIAL_EVENT_RX_DMADONE  0x03
#define RT_SERIAL_EVENT_TX_DMADONE  0x04
#define RT_SERIAL_EVENT_RX_TIMEOUT  0x05

/* serial_v2.h:78-88 */
#define BAUD_RATE_115200            115200
#define DATA_BITS_8                 8
#define STOP_BITS_1                 0
#define PARITY_NONE                 0
#define BIT_ORDER_LSB               0
#define NRZ_NORMAL                  0
#define RT_SERIAL_RX_MINBUFSZ       64
#define RT_SERIAL_TX_MINBUFSZ       64
#define RT_SERIAL_FLOWCONTROL_NONE  0

/* serial_v2.h:92-103，字段顺序与真实宏一致 */
#define RT_SERIAL_CONFIG_DEFAULT                      \
{                                                     \
    BAUD_RATE_115200,           /* 115200 bits/s */   \
    DATA_BITS_8,                /* 8 databits */      \
    STOP_BITS_1,                /* 1 stopbit */       \
    PARITY_NONE,                /* No parity  */      \
    BIT_ORDER_LSB,              /* LSB first sent */  \
    NRZ_NORMAL,                 /* Normal mode */     \
    RT_SERIAL_RX_MINBUFSZ,      /* rxBuf size */      \
    RT_SERIAL_TX_MINBUFSZ,      /* txBuf size */      \
    RT_SERIAL_FLOWCONTROL_NONE, /* Off flowcontrol */ \
    0                                                 \
}

/* 测试用的 FIFO 容量；真实容量来自 BSP_UARTn_RX_BUFSIZE（rtconfig.h 里是 256）。 */
#define RT_SERIAL_RX_STUB_BUFSZ 256

/* ringbuffer.h:21-56 */
struct rt_ringbuffer
{
    rt_uint8_t *buffer_ptr;

    rt_uint32_t read_mirror : 1;
    rt_uint32_t read_index : 31;
    rt_uint32_t write_mirror : 1;
    rt_uint32_t write_index : 31;
    rt_int32_t  buffer_size;
};

/* serial_v2.h:105-119 */
struct serial_configure
{
    rt_uint32_t baud_rate;

    rt_uint32_t data_bits   : 4;
    rt_uint32_t stop_bits   : 2;
    rt_uint32_t parity      : 2;
    rt_uint32_t bit_order   : 1;
    rt_uint32_t invert      : 1;
    rt_uint32_t rx_bufsz    : 16;
    rt_uint32_t tx_bufsz    : 16;
    rt_uint32_t flowcontrol : 1;
    rt_uint32_t reserved    : 5;
};

/* serial_v2.h:132-141 */
struct rt_serial_rx_fifo
{
    struct rt_ringbuffer rb;

    rt_uint8_t buffer[RT_SERIAL_RX_STUB_BUFSZ]; /* 真实头是柔性数组 */
};

/* 前置声明：rt_uart_ops 的回调签名里要引用它 */
struct rt_serial_device;

struct rt_uart_ops
{
    rt_err_t (*configure)(struct rt_serial_device *serial,
                          struct serial_configure *cfg);

    rt_err_t (*control)(struct rt_serial_device *serial, int cmd, void *arg);

    int (*putc)(struct rt_serial_device *serial, char c);
    int (*getc)(struct rt_serial_device *serial);

    rt_ssize_t (*transmit)(struct rt_serial_device *serial,
                           rt_uint8_t *buf,
                           rt_size_t   size,
                           rt_uint32_t tx_flag);
};

/* rtdef.h 的 rt_device：只留占位。被测文件从不读 serial->parent 的字段，
 * 所以 type/flag/ref_count/open_flag/... 全不桩。 */
struct rt_device
{
    void *user_data;
};

/* serial_v2.h:161-174，只保留被测文件引用的字段 */
struct rt_serial_device
{
    struct rt_device          parent;

    const struct rt_uart_ops *ops;
    struct serial_configure   config;

    void *serial_rx;
    void *serial_tx;
};

/* serial_v2.h:195-200 */
void rt_hw_serial_isr(struct rt_serial_device *serial, int event);

rt_err_t rt_hw_serial_register(struct rt_serial_device *serial,
                               const char              *name,
                               rt_uint32_t              flag,
                               void                    *data);

/* ringbuffer.h:70 */
rt_size_t rt_ringbuffer_putchar(struct rt_ringbuffer *rb, const rt_uint8_t ch);

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_USART_RTDEVICE_H */
