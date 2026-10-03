#ifndef SMART_HAND_TESTS_STUBS_SERVO_RTDEVICE_H
#define SMART_HAND_TESTS_STUBS_SERVO_RTDEVICE_H

/*
 * 主机桩：RT-Thread 设备框架头
 *   rt-thread/components/drivers/include/rtdevice.h
 *   rt-thread/include/rtthread.h 里的设备 API 段（655-691 行）
 *   rt-thread/components/drivers/include/drivers/pin.h
 *   rt-thread/components/drivers/include/drivers/serial_v2.h
 *
 * 被测文件 src/servo_bus_readonly_rt.c 用到的只有：
 *   rt_device_find / rt_device_control / rt_device_set_rx_indicate /
 *   rt_device_open / rt_device_close / rt_device_read（drain_servo_uart 用）
 *   rt_pin_mode / rt_pin_write（set_leds 用）
 *   RT_SERIAL_CONFIG_DEFAULT + serial_configure（servo_bus_readonly_init 用）
 *   RT_DEVICE_OFLAG_RDWR / RT_DEVICE_FLAG_INT_RX / RT_DEVICE_CTRL_CONFIG
 *
 * 数值全部照抄真实头文件（行号在下面），因为它们参与断言：
 * rt_config 里的 oflag 组合、PIN_LOW/PIN_HIGH 决定 set_leds 写进引脚的
 * 电平值，测试会校验这些值，桩里填错就等于断言错。
 *
 * 与真实头文件的差异：
 *   - struct rt_device 只留前置声明（真实是完整类型）。被测文件只把
 *     rt_device_t 当句柄传递，从不读 dev->xxx，所以不完整类型足够。
 *   - pin.h 只搬了本文件用到的四个宏，没有搬 rt_pin_ops / PIN_DEV 之类。
 *   - serial_configure 的位域布局照抄 serial_v2.h:105-119。
 *   - 没有桩 rt_ringbuffer / rt_serial_rx_fifo：被测文件不碰它们
 *     （那是 drv_usart_v2.c 的面，见 tests/stubs_usart/）。
 */

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/* rtdef.h:1262 / 1270 / 1282 */
#define RT_DEVICE_FLAG_INT_RX   (0x100)
#define RT_DEVICE_OFLAG_RDWR    (0x003)
#define RT_DEVICE_CTRL_CONFIG   (0x03)

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

/* pin.h:44-52 */
#define PIN_LOW                 0x00
#define PIN_HIGH                0x01
#define PIN_MODE_OUTPUT         0x00

/* pin.h:147-148 */
void rt_pin_mode(rt_base_t pin, rt_uint8_t mode);
void rt_pin_write(rt_base_t pin, rt_ssize_t value);

/* rtthread.h:655-691 */
rt_device_t rt_device_find(const char *name);
rt_err_t    rt_device_set_rx_indicate(rt_device_t dev,
                                      rt_err_t (*rx_ind)(rt_device_t dev,
                                                         rt_size_t size));
rt_err_t    rt_device_open(rt_device_t dev, rt_uint16_t oflag);
rt_err_t    rt_device_close(rt_device_t dev);
rt_ssize_t  rt_device_read(rt_device_t dev,
                           rt_off_t    pos,
                           void       *buffer,
                           rt_size_t   size);
rt_err_t    rt_device_control(rt_device_t dev, int cmd, void *arg);

#ifdef __cplusplus
}
#endif

#endif /* SMART_HAND_TESTS_STUBS_SERVO_RTDEVICE_H */
