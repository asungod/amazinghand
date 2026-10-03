/*
 * 主机桩测试：libraries/HAL_Drivers/drv_usart_v2.c 的 UART RX 回调与
 * ra_uart_queue_rx_char() 空指针防护。
 *
 * 被测文件（只读，不修改）：
 *   D:/Micu/RTTWorkspace/titan_uart_test/libraries/HAL_Drivers/drv_usart_v2.c
 * 路径由包装脚本用 -DDRV_USART_V2_C_PATH="..." 注入，默认值见下面 #ifndef。
 *
 * 背景（补丁要保住的行为）：R_SCI_B_UART_Open() 在返回前就使能了接收与 RXI/ERI
 * （r_sci_b_uart.c:381-388），而 serial->serial_rx 要等 rt_device_open() 的
 * RX-enable 阶段才发布（serial_v2.c:779-785）。窗口内到达一个字节，原来会命中
 * RT_ASSERT(rx_fifo != RT_NULL)；RT_USING_DEBUG 已定义（rtconfig.h:28）⇒ 断言
 * 是活的 ⇒ 启动期停机。补丁把这条路径换成"丢弃该字节 + 只读计数器递增"。
 *
 * 为什么这份测试是白盒（把被测 .c 直接并进本 TU）：
 *   1. 任务书要求断言"丢弃计数器递增"，而 g_uart_rx_dropped_before_fifo 是文件内
 *      static，从另一个 TU 里读不到（编成独立目标文件就只能看外部可见行为）。
 *   2. serial == RT_NULL 分支在回调路径上不可达 —— 回调里的 serial 恒为
 *      &uart_obj[i].serial —— 只能直接调 ra_uart_queue_rx_char()，它同样是 static。
 *   两点都需要同 TU 可见性。源文件本身仍然只读、不改。
 *   代价：本 TU 与"独立编译被测文件"不是同一种编译单元，见测试报告里的说明；
 *   包装脚本另外单独跑一次 `gcc -fsyntax-only` 编译被测文件，保证它脱离本 TU
 *   也能独立编过。
 *
 * 测试替身模拟到哪一步（越界的地方明说）：
 *   - rt_hw_serial_register()/rt_ringbuffer_putchar()/rt_hw_serial_isr() 由本文件
 *     实现，不是 RT-Thread 的真实实现。ring 的 mirror 语义照抄 ringbuffer.h 的算法；
 *     isr 会真的把 ring 里已有的字节"搬走"（真实 isr 就是这么干的），所以
 *     "先 isr 后 putchar"这种顺序错误能被抓到。
 *   - FIFO 的"发布"由用例直接写 serial->serial_rx 模拟（真实发生在
 *     rt_device_open() 的 RX-enable 里）。本测试不链接 serial_v2.c，
 *     因此不覆盖 "rt_device_open() 是否真的会发布 FIFO" 这件事。
 */

#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <rtthread.h>
#include <rtdevice.h>
#include <rthw.h>
#include <hal_data.h>

#ifndef DRV_USART_V2_C_PATH
#define DRV_USART_V2_C_PATH \
    "D:/Micu/RTTWorkspace/titan_uart_test/libraries/HAL_Drivers/drv_usart_v2.c"
#endif

#include DRV_USART_V2_C_PATH

/* ===================================================================== */
/* 桩状态                                                                */
/* ===================================================================== */

/* 用例框架状态：rt_assert_handler() 在下面就要用到，所以先声明。
 * 全部放静态存储期，避免 setjmp/longjmp 撞上 -Wclobbered。 */
static jmp_buf g_case_jmp;
static int     g_case_active;

unsigned usart_stub_assert_hits;
char     usart_stub_assert_expr[128];
char     usart_stub_assert_func[64];
int      usart_stub_assert_line;

unsigned              usart_stub_putchar_calls;
unsigned              usart_stub_putchar_success;
unsigned              usart_stub_putchar_null_rb;
struct rt_ringbuffer *usart_stub_putchar_last_rb;
rt_uint8_t            usart_stub_putchar_last_data;

unsigned                 usart_stub_isr_calls;
int                      usart_stub_isr_last_event;
struct rt_serial_device *usart_stub_isr_last_serial;
unsigned                 usart_stub_isr_seen_empty_ring;
unsigned                 usart_stub_isr_ring_bytes_first;
unsigned                 usart_stub_isr_null_fifo;
unsigned                 usart_stub_isr_drain_enabled = 1;
unsigned                 usart_stub_isr_drained_total;
unsigned                 usart_stub_first_op;

#define USART_STUB_DELIVERED_CAP 1024
rt_uint8_t usart_stub_delivered[USART_STUB_DELIVERED_CAP];
unsigned   usart_stub_delivered_count;

unsigned usart_stub_enter_calls;
unsigned usart_stub_leave_calls;
int      usart_stub_irq_depth;
unsigned usart_stub_leave_without_enter;

unsigned    usart_stub_open_calls;
void       *usart_stub_open_last_ctrl;
const void *usart_stub_open_last_cfg;
fsp_err_t   usart_stub_open_result = FSP_SUCCESS;
unsigned    usart_stub_open_inject_bytes;
rt_uint8_t  usart_stub_open_inject_first;
void      (*usart_stub_open_inject_callback)(uart_callback_args_t *p_args);
unsigned    usart_stub_open_injected;

unsigned                 usart_stub_reg_calls;
const char              *usart_stub_reg_names[4];
struct rt_serial_device *usart_stub_reg_serials[4];
rt_uint32_t              usart_stub_reg_flags[4];

/* 两个 UART 控制块，与 ra_gen/hal_data.c 里同名对象同类型。 */
static R_SCI_B0_Type       g_uart1_regs;
static R_SCI_B0_Type       g_uart2_regs;
sci_b_uart_instance_ctrl_t g_uart1_ctrl = { .p_reg = &g_uart1_regs };
const uart_cfg_t           g_uart1_cfg = { .channel = 1 };
sci_b_uart_instance_ctrl_t g_uart2_ctrl = { .p_reg = &g_uart2_regs };
const uart_cfg_t           g_uart2_cfg = { .channel = 2 };

/* ===================================================================== */
/* 桩实现                                                                */
/* ===================================================================== */

/* rtthread.h 的断言处理。RT_USING_DEBUG 下真实实现会停机；这里记录后把控制权
 * 交回当前用例，让失败以 "[case] ... FAILED" 的形式报出来（变异验证依赖它）。 */
void rt_assert_handler(const char *ex_string, const char *func, rt_size_t line)
{
    usart_stub_assert_hits++;
    snprintf(usart_stub_assert_expr, sizeof(usart_stub_assert_expr), "%s",
             ex_string != NULL ? ex_string : "?");
    snprintf(usart_stub_assert_func, sizeof(usart_stub_assert_func), "%s",
             func != NULL ? func : "?");
    usart_stub_assert_line = (int)line;

    fprintf(stderr, "RT_ASSERT(%s) 在 %s():%d 触发\n",
            usart_stub_assert_expr, usart_stub_assert_func, usart_stub_assert_line);

    if (g_case_active)
    {
        longjmp(g_case_jmp, 1);
    }
    /* 没有活动用例可回退，等同固件里的停机 */
    exit(3);
}

void rt_interrupt_enter(void)
{
    usart_stub_enter_calls++;
    usart_stub_irq_depth++;
}

void rt_interrupt_leave(void)
{
    usart_stub_leave_calls++;
    if (usart_stub_irq_depth > 0)
    {
        usart_stub_irq_depth--;
    }
    else
    {
        /* leave 多于 enter：配对断言会立刻抓到 */
        usart_stub_leave_without_enter++;
    }
}

/* ringbuffer.h 的已用字节数（含 mirror 位，算法照抄真实实现） */
static unsigned ring_bytes(const struct rt_ringbuffer *rb)
{
    if (rb->buffer_size <= 0)
    {
        return 0;
    }
    if (rb->read_index == rb->write_index)
    {
        return (rb->read_mirror == rb->write_mirror)
                   ? 0u
                   : (unsigned)rb->buffer_size;
    }
    if (rb->write_index > rb->read_index)
    {
        return rb->write_index - rb->read_index;
    }
    return (unsigned)rb->buffer_size - rb->read_index + rb->write_index;
}

rt_size_t rt_ringbuffer_putchar(struct rt_ringbuffer *rb, const rt_uint8_t ch)
{
    usart_stub_putchar_calls++;
    usart_stub_putchar_last_rb = rb;
    usart_stub_putchar_last_data = ch;
    if (usart_stub_first_op == 0)
    {
        usart_stub_first_op = 1; /* 先 putchar */
    }

    if (rb == RT_NULL || rb->buffer_ptr == RT_NULL || rb->buffer_size <= 0)
    {
        usart_stub_putchar_null_rb++;
        return 0;
    }

    if (ring_bytes(rb) >= (unsigned)rb->buffer_size)
    {
        return 0; /* 满：真实实现同样返回 0 */
    }

    rb->buffer_ptr[rb->write_index] = ch;
    if ((rt_int32_t)rb->write_index == rb->buffer_size - 1)
    {
        rb->write_mirror ^= 1;
        rb->write_index = 0;
    }
    else
    {
        rb->write_index++;
    }
    usart_stub_putchar_success++;
    return 1;
}

void rt_hw_serial_isr(struct rt_serial_device *serial, int event)
{
    struct rt_serial_rx_fifo *fifo = RT_NULL;
    unsigned                  avail;

    usart_stub_isr_calls++;
    usart_stub_isr_last_event = event;
    usart_stub_isr_last_serial = serial;
    if (usart_stub_first_op == 0)
    {
        usart_stub_first_op = 2; /* 先 isr：把顺序错误记下来 */
    }

    if (serial == RT_NULL || serial->serial_rx == RT_NULL)
    {
        usart_stub_isr_null_fifo++;
        return;
    }

    fifo = (struct rt_serial_rx_fifo *)serial->serial_rx;
    avail = ring_bytes(&fifo->rb);

    if (avail == 0)
    {
        /* 真 isr 进 RX_IND 时 ring 里必然有货；空着说明调用方顺序反了 */
        usart_stub_isr_seen_empty_ring++;
    }
    if (usart_stub_isr_calls == 1)
    {
        usart_stub_isr_ring_bytes_first = avail;
    }

    if (!usart_stub_isr_drain_enabled)
    {
        return; /* 纯观测模式：留给用例自己去 drain */
    }

    usart_stub_isr_drained_total += avail;
    while (avail > 0)
    {
        rt_uint8_t byte = fifo->rb.buffer_ptr[fifo->rb.read_index];
        if ((rt_int32_t)fifo->rb.read_index == fifo->rb.buffer_size - 1)
        {
            fifo->rb.read_mirror ^= 1;
            fifo->rb.read_index = 0;
        }
        else
        {
            fifo->rb.read_index++;
        }
        if (usart_stub_delivered_count < USART_STUB_DELIVERED_CAP)
        {
            usart_stub_delivered[usart_stub_delivered_count++] = byte;
        }
        avail--;
    }
}

/* 真实驱动返回前已使能接收与 RXI/ERI（r_sci_b_uart.c:381-388）。
 * 这里在 return 之前同步回调若干字节，把那个窗口如实复现出来。 */
fsp_err_t R_SCI_B_UART_Open(uart_ctrl_t *const p_api_ctrl,
                            uart_cfg_t const *const p_cfg)
{
    unsigned i;
    unsigned n;

    usart_stub_open_calls++;
    usart_stub_open_last_ctrl = (void *)p_api_ctrl;
    usart_stub_open_last_cfg = (const void *)p_cfg;

    if (usart_stub_open_result == FSP_SUCCESS &&
        usart_stub_open_inject_callback != RT_NULL &&
        usart_stub_open_inject_bytes > 0)
    {
        n = usart_stub_open_inject_bytes;
        usart_stub_open_inject_bytes = 0; /* 只注入一次，避免重入叠加 */
        for (i = 0; i < n; i++)
        {
            uart_callback_args_t args;
            memset(&args, 0, sizeof(args));
            args.channel = 0;
            args.event = UART_EVENT_RX_CHAR;
            args.data = (uint32_t)(usart_stub_open_inject_first + i);
            usart_stub_open_injected++;
            usart_stub_open_inject_callback(&args);
        }
    }

    return usart_stub_open_result;
}

rt_err_t rt_hw_serial_register(struct rt_serial_device *serial,
                               const char              *name,
                               rt_uint32_t              flag,
                               void                    *data)
{
    unsigned idx = usart_stub_reg_calls;

    (void)data;
    usart_stub_reg_calls++;
    if (idx < 4)
    {
        usart_stub_reg_names[idx] = name;
        usart_stub_reg_serials[idx] = serial;
        usart_stub_reg_flags[idx] = flag;
    }
    return RT_EOK;
}

/* ===================================================================== */
/* 测试侧工具                                                            */
/* ===================================================================== */

static unsigned g_checks;
static unsigned g_failures;
static unsigned g_case_checks;
static unsigned g_case_failures;
static const char *g_case_name;
/* g_case_jmp / g_case_active 定义在文件上部，rt_assert_handler() 要用 */

#define CHECK(cond, ...)                                    \
    do {                                                    \
        g_checks++;                                         \
        g_case_checks++;                                    \
        if (!(cond)) {                                      \
            g_case_failures++;                              \
            g_failures++;                                   \
            printf("    FAIL: %s:%d: ", __func__, __LINE__); \
            printf(__VA_ARGS__);                            \
            printf("\n");                                   \
        }                                                   \
    } while (0)

void usart_stub_reset(void)
{
    usart_stub_assert_hits = 0;
    usart_stub_assert_expr[0] = '\0';
    usart_stub_assert_func[0] = '\0';
    usart_stub_assert_line = 0;

    usart_stub_putchar_calls = 0;
    usart_stub_putchar_success = 0;
    usart_stub_putchar_null_rb = 0;
    usart_stub_putchar_last_rb = RT_NULL;
    usart_stub_putchar_last_data = 0;

    usart_stub_isr_calls = 0;
    usart_stub_isr_last_event = -1;
    usart_stub_isr_last_serial = RT_NULL;
    usart_stub_isr_seen_empty_ring = 0;
    usart_stub_isr_ring_bytes_first = 0;
    usart_stub_isr_null_fifo = 0;
    usart_stub_isr_drain_enabled = 1;
    usart_stub_isr_drained_total = 0;
    usart_stub_first_op = 0;

    usart_stub_delivered_count = 0;
    memset(usart_stub_delivered, 0, sizeof(usart_stub_delivered));

    usart_stub_enter_calls = 0;
    usart_stub_leave_calls = 0;
    usart_stub_irq_depth = 0;
    usart_stub_leave_without_enter = 0;

    usart_stub_open_calls = 0;
    usart_stub_open_last_ctrl = RT_NULL;
    usart_stub_open_last_cfg = RT_NULL;
    usart_stub_open_result = FSP_SUCCESS;
    usart_stub_open_inject_bytes = 0;
    usart_stub_open_inject_first = 0;
    usart_stub_open_inject_callback = RT_NULL;
    usart_stub_open_injected = 0;

    usart_stub_reg_calls = 0;

    /* 回到"rt_device_open() 还没跑到 RX-enable"的真实状态：serial_rx 未发布 */
    uart_obj[UART1_INDEX].serial.serial_rx = RT_NULL;
    uart_obj[UART2_INDEX].serial.serial_rx = RT_NULL;

    (void)g_uart_rx_dropped_before_fifo; /* 只读计数器刻意不清零 */
}

void usart_stub_fifo_init(struct rt_serial_rx_fifo *fifo)
{
    memset(fifo, 0, sizeof(*fifo));
    fifo->rb.buffer_ptr = fifo->buffer;
    fifo->rb.buffer_size = (rt_int32_t)sizeof(fifo->buffer);
    fifo->rb.read_mirror = 0;
    fifo->rb.read_index = 0;
    fifo->rb.write_mirror = 0;
    fifo->rb.write_index = 0;
}

unsigned usart_stub_fifo_drain(struct rt_serial_rx_fifo *fifo,
                               rt_uint8_t *out,
                               unsigned    out_cap)
{
    unsigned n = 0;

    while (ring_bytes(&fifo->rb) > 0 && n < out_cap)
    {
        out[n++] = fifo->rb.buffer_ptr[fifo->rb.read_index];
        if ((rt_int32_t)fifo->rb.read_index == fifo->rb.buffer_size - 1)
        {
            fifo->rb.read_mirror ^= 1;
            fifo->rb.read_index = 0;
        }
        else
        {
            fifo->rb.read_index++;
        }
    }
    return n;
}

/* 被测回调 + 它对应的 uart_obj 下标 + 可读名字 */
struct uart_slot
{
    int   index;
    void (*cb)(uart_callback_args_t *p_args);
    const char *name;
};

static const struct uart_slot g_uarts[2] = {
    { UART1_INDEX, user_uart1_callback, "uart1" },
    { UART2_INDEX, user_uart2_callback, "uart2" },
};

/* 两个测试用 FIFO：只在用例里"发布"到某个串口上 */
static struct rt_serial_rx_fifo g_fifo[2];

static struct rt_serial_device *slot_serial(int i)
{
    return &uart_obj[g_uarts[i].index].serial;
}

/* 发出一个 UART 回调（模拟 FSP 中断里调用 user_uartN_callback） */
static void fire(int i, uart_event_t event, uint32_t data)
{
    uart_callback_args_t args;

    memset(&args, 0, sizeof(args));
    args.channel = (uint32_t)i;
    args.event = event;
    args.data = data;
    g_uarts[i].cb(&args);
}

/* 模拟 rt_device_open() 的 RX-enable：把 FIFO 发布到设备上 */
static void publish(int i)
{
    usart_stub_fifo_init(&g_fifo[i]);
    slot_serial(i)->serial_rx = &g_fifo[i];
}

/* 每个用例收尾都要查的公共不变量 */
static void check_case_invariants(void)
{
    CHECK(usart_stub_assert_hits == 0,
          "本用例触发了 RT_ASSERT(%s)（%s():%d）——空指针防护没兜住",
          usart_stub_assert_expr, usart_stub_assert_func,
          usart_stub_assert_line);
    CHECK(usart_stub_enter_calls == usart_stub_leave_calls,
          "rt_interrupt_enter/leave 不配对：enter=%u leave=%u",
          usart_stub_enter_calls, usart_stub_leave_calls);
    CHECK(usart_stub_irq_depth == 0,
          "用例结束时中断嵌套深度应为 0，实际 %d", usart_stub_irq_depth);
    CHECK(usart_stub_leave_without_enter == 0,
          "出现了 %u 次没有 enter 的 leave", usart_stub_leave_without_enter);
    CHECK(usart_stub_putchar_null_rb == 0,
          "rt_ringbuffer_putchar 收到过空的 ringbuffer（%u 次）",
          usart_stub_putchar_null_rb);
    CHECK(usart_stub_isr_null_fifo == 0,
          "rt_hw_serial_isr 被调用时 serial_rx 还是 NULL（%u 次）",
          usart_stub_isr_null_fifo);
}

#define RUN_CASE(name, fn)                                                 \
    do {                                                                   \
        usart_stub_reset();                                                \
        g_case_name = (name);                                              \
        g_case_checks = 0;                                                 \
        g_case_failures = 0;                                               \
        g_case_active = 1;                                                 \
        printf("[run ] %s\n", g_case_name);                                \
        if (setjmp(g_case_jmp) == 0) {                                     \
            fn();                                                          \
        } else {                                                           \
            g_checks++;                                                     \
            g_case_checks++;                                                \
            g_case_failures++;                                              \
            g_failures++;                                                   \
            printf("    FAIL: RT_ASSERT(%s) 在 %s():%d 被执行，"             \
                   "空指针防护失效\n",                                      \
                   usart_stub_assert_expr, usart_stub_assert_func,          \
                   usart_stub_assert_line);                                 \
        }                                                                  \
        g_case_active = 0;                                                 \
        check_case_invariants();                                           \
        printf("[case] %s: %s (%u checks)\n", g_case_name,                 \
               g_case_failures == 0 ? "ok" : "FAILED", g_case_checks);     \
    } while (0)

/* ===================================================================== */
/* 用例                                                                  */
/* ===================================================================== */

/* 1. serial_rx == RT_NULL 时注入 UART_EVENT_RX_CHAR：
 *    不触发断言、不写 ringbuffer、不通知 isr、enter/leave 配对、丢弃计数 +1。
 *    UART1 与 UART2 各跑一遍。 */
static void case_1_null_fifo_drops_rx_char(void)
{
    int i;

    for (i = 0; i < 2; i++)
    {
        struct rt_serial_device *serial = slot_serial(i);
        unsigned   put0 = usart_stub_putchar_calls;
        unsigned   isr0 = usart_stub_isr_calls;
        unsigned   enter0 = usart_stub_enter_calls;
        unsigned   leave0 = usart_stub_leave_calls;
        rt_uint32_t drop0 = g_uart_rx_dropped_before_fifo;

        serial->serial_rx = RT_NULL; /* 启动窗口：FIFO 还没发布 */

        fire(i, UART_EVENT_RX_CHAR, 0xA5);

        CHECK(usart_stub_assert_hits == 0,
              "%s: 空 FIFO 注入字节触发了断言（这正是补丁要避免的启动期停机）",
              g_uarts[i].name);
        CHECK(usart_stub_putchar_calls == put0,
              "%s: 空 FIFO 时不得调用 rt_ringbuffer_putchar()（多了 %u 次）",
              g_uarts[i].name, usart_stub_putchar_calls - put0);
        CHECK(usart_stub_isr_calls == isr0,
              "%s: 空 FIFO 时不得调用 rt_hw_serial_isr()（多了 %u 次）",
              g_uarts[i].name, usart_stub_isr_calls - isr0);
        CHECK(usart_stub_delivered_count == 0,
              "%s: 空 FIFO 时不得有任何字节被交付给上层", g_uarts[i].name);
        CHECK(usart_stub_enter_calls == enter0 + 1,
              "%s: rt_interrupt_enter() 应恰好 1 次，实际 %u 次",
              g_uarts[i].name, usart_stub_enter_calls - enter0);
        CHECK(usart_stub_leave_calls == leave0 + 1,
              "%s: rt_interrupt_leave() 应恰好 1 次，实际 %u 次",
              g_uarts[i].name, usart_stub_leave_calls - leave0);
        CHECK(usart_stub_enter_calls == usart_stub_leave_calls,
              "%s: enter/leave 次数必须相等", g_uarts[i].name);
        CHECK(usart_stub_irq_depth == 0,
              "%s: 回调返回后中断嵌套深度必须归零，实际 %d",
              g_uarts[i].name, usart_stub_irq_depth);
        CHECK(g_uart_rx_dropped_before_fifo == drop0 + 1,
              "%s: 丢弃计数器应恰好 +1（%u -> %u）",
              g_uarts[i].name, (unsigned)drop0,
              (unsigned)g_uart_rx_dropped_before_fifo);
    }
}

/* 2. 发布有效 FIFO 后注入字节：字节准确写入 ringbuffer、isr 恰好通知一次。 */
static void case_2_published_fifo_queues_and_notifies(void)
{
    int i;

    for (i = 0; i < 2; i++)
    {
        struct rt_serial_device *serial = slot_serial(i);
        rt_uint8_t               byte = (rt_uint8_t)(0x5A + i);
        rt_uint32_t              drop0;
        unsigned                 put0, isr0, delivered0, enter0, leave0;

        publish(i);
        drop0 = g_uart_rx_dropped_before_fifo;
        put0 = usart_stub_putchar_calls;
        isr0 = usart_stub_isr_calls;
        delivered0 = usart_stub_delivered_count;
        enter0 = usart_stub_enter_calls;
        leave0 = usart_stub_leave_calls;

        fire(i, UART_EVENT_RX_CHAR, byte);

        CHECK(usart_stub_putchar_calls == put0 + 1,
              "%s: 应恰好写一次 ringbuffer，实际 %u 次",
              g_uarts[i].name, usart_stub_putchar_calls - put0);
        CHECK(usart_stub_putchar_last_data == byte,
              "%s: 写进 ringbuffer 的字节应为 0x%02X，实际 0x%02X",
              g_uarts[i].name, (unsigned)byte,
              (unsigned)usart_stub_putchar_last_data);
        CHECK(usart_stub_putchar_last_rb == &g_fifo[i].rb,
              "%s: 写入的必须是该串口已发布的那个 FIFO 的 ringbuffer",
              g_uarts[i].name);
        CHECK(usart_stub_putchar_success == put0 + 1,
              "%s: ringbuffer 写入应成功（返回 1）", g_uarts[i].name);

        CHECK(usart_stub_isr_calls == isr0 + 1,
              "%s: rt_hw_serial_isr 应恰好通知 1 次，实际 %u 次",
              g_uarts[i].name, usart_stub_isr_calls - isr0);
        CHECK(usart_stub_isr_last_event == RT_SERIAL_EVENT_RX_IND,
              "%s: isr 事件应为 RT_SERIAL_EVENT_RX_IND(0x%02X)，实际 0x%02X",
              g_uarts[i].name, (unsigned)RT_SERIAL_EVENT_RX_IND,
              (unsigned)usart_stub_isr_last_event);
        CHECK(usart_stub_isr_last_serial == serial,
              "%s: isr 必须作用在本串口的设备对象上", g_uarts[i].name);
        CHECK(usart_stub_isr_ring_bytes_first == 1,
              "%s: isr 第一次被调用时 ring 里应有 1 字节（说明 putchar 在先），"
              "实际 %u", g_uarts[i].name, usart_stub_isr_ring_bytes_first);
        CHECK(usart_stub_first_op == 1,
              "%s: 必须先 rt_ringbuffer_putchar 再 rt_hw_serial_isr", g_uarts[i].name);

        CHECK(usart_stub_delivered_count == delivered0 + 1,
              "%s: 上层应恰好收到 1 个字节", g_uarts[i].name);
        CHECK(usart_stub_delivered[delivered0] == byte,
              "%s: 上层收到的字节应为 0x%02X，实际 0x%02X",
              g_uarts[i].name, (unsigned)byte,
              (unsigned)usart_stub_delivered[delivered0]);

        CHECK(g_uart_rx_dropped_before_fifo == drop0,
              "%s: FIFO 已发布就不得丢字节", g_uarts[i].name);
        CHECK(usart_stub_enter_calls == enter0 + 1 &&
                  usart_stub_leave_calls == leave0 + 1,
              "%s: enter/leave 应各 1 次（实际 %u/%u）", g_uarts[i].name,
              usart_stub_enter_calls - enter0, usart_stub_leave_calls - leave0);
    }
}

/* 3. 非 RX_CHAR 事件：行为不变（不写 ringbuffer、不通知、不丢计数）。 */
static void case_3_non_rx_char_events_untouched(void)
{
    static const uart_event_t events[] = {
        UART_EVENT_TX_COMPLETE,
        UART_EVENT_RX_COMPLETE,
        UART_EVENT_ERR_PARITY,
        UART_EVENT_ERR_FRAMING,
        UART_EVENT_ERR_OVERFLOW,
        UART_EVENT_BREAK_DETECT,
        UART_EVENT_TX_DATA_EMPTY,
    };
    unsigned e;
    int      i;
    rt_uint8_t sink[8];

    for (i = 0; i < 2; i++)
    {
        publish(i);
        for (e = 0; e < sizeof(events) / sizeof(events[0]); e++)
        {
            unsigned   put0 = usart_stub_putchar_calls;
            unsigned   isr0 = usart_stub_isr_calls;
            unsigned   delivered0 = usart_stub_delivered_count;
            unsigned   enter0 = usart_stub_enter_calls;
            unsigned   leave0 = usart_stub_leave_calls;
            rt_uint32_t drop0 = g_uart_rx_dropped_before_fifo;

            fire(i, events[e], 0x7E);

            CHECK(usart_stub_putchar_calls == put0,
                  "%s: 事件 0x%02X 不得写 ringbuffer",
                  g_uarts[i].name, (unsigned)events[e]);
            CHECK(usart_stub_isr_calls == isr0,
                  "%s: 事件 0x%02X 不得通知 isr",
                  g_uarts[i].name, (unsigned)events[e]);
            CHECK(usart_stub_delivered_count == delivered0,
                  "%s: 事件 0x%02X 不得交付字节",
                  g_uarts[i].name, (unsigned)events[e]);
            CHECK(g_uart_rx_dropped_before_fifo == drop0,
                  "%s: 事件 0x%02X 不得动丢弃计数器",
                  g_uarts[i].name, (unsigned)events[e]);
            CHECK(usart_stub_enter_calls == enter0 + 1 &&
                      usart_stub_leave_calls == leave0 + 1,
                  "%s: 事件 0x%02X 下 enter/leave 仍要各 1 次",
                  g_uarts[i].name, (unsigned)events[e]);
            CHECK(usart_stub_assert_hits == 0,
                  "%s: 事件 0x%02X 下不得触发断言",
                  g_uarts[i].name, (unsigned)events[e]);
        }
        CHECK(usart_stub_fifo_drain(&g_fifo[i], sink, sizeof(sink)) == 0,
              "%s: 非 RX_CHAR 事件跑完，FIFO 里不该有任何字节",
              g_uarts[i].name);
    }
}

/* 4. UART1 / UART2 互不串台：一个口没发布 FIFO 时，另一个口的 FIFO 不得被动。 */
static void case_4_per_uart_isolation(void)
{
    rt_uint8_t sink[8];
    unsigned   n;
    rt_uint32_t drop0;

    /* uart1 已发布，uart2 未发布 */
    publish(0);
    slot_serial(1)->serial_rx = RT_NULL;
    drop0 = g_uart_rx_dropped_before_fifo;

    fire(1, UART_EVENT_RX_CHAR, 0x11); /* 只打 uart2 */

    CHECK(usart_stub_putchar_calls == 0,
          "uart2 空 FIFO 时不得写任何 ringbuffer，实际写了 %u 次",
          usart_stub_putchar_calls);
    CHECK(usart_stub_isr_calls == 0,
          "uart2 空 FIFO 时不得通知 isr，实际 %u 次", usart_stub_isr_calls);
    n = usart_stub_fifo_drain(&g_fifo[0], sink, sizeof(sink));
    CHECK(n == 0, "uart2 的字节不得写进 uart1 的 FIFO（发现了 %u 字节）", n);
    CHECK(g_uart_rx_dropped_before_fifo == drop0 + 1,
          "uart2 那一字节应被丢弃并计数（%u -> %u，应 +1）",
          (unsigned)drop0, (unsigned)g_uart_rx_dropped_before_fifo);

    /* 反过来：uart2 已发布，uart1 未发布 */
    usart_stub_reset();
    publish(1);
    slot_serial(0)->serial_rx = RT_NULL;

    fire(0, UART_EVENT_RX_CHAR, 0x22);

    CHECK(usart_stub_putchar_calls == 0,
          "uart1 空 FIFO 时不得写任何 ringbuffer，实际写了 %u 次",
          usart_stub_putchar_calls);
    n = usart_stub_fifo_drain(&g_fifo[1], sink, sizeof(sink));
    CHECK(n == 0, "uart1 的字节不得写进 uart2 的 FIFO（发现了 %u 字节）", n);

    /* 两个都发布：各写各的 */
    usart_stub_reset();
    publish(0);
    publish(1);
    fire(0, UART_EVENT_RX_CHAR, 0x33);
    fire(1, UART_EVENT_RX_CHAR, 0x44);

    CHECK(usart_stub_putchar_calls == 2, "两个口各写一次，实际 %u 次",
          usart_stub_putchar_calls);
    CHECK(usart_stub_putchar_last_rb == &g_fifo[1].rb,
          "最后一次写入应落在 uart2 已发布的 FIFO 上");
    CHECK(usart_stub_isr_calls == 2 && usart_stub_delivered_count == 2,
          "两个口应各通知一次、各交付一个字节（isr=%u delivered=%u）",
          usart_stub_isr_calls, usart_stub_delivered_count);
    CHECK(usart_stub_delivered[0] == 0x33 && usart_stub_delivered[1] == 0x44,
          "交付顺序/内容应为 0x33 然后 0x44，实际 0x%02X,0x%02X",
          (unsigned)usart_stub_delivered[0], (unsigned)usart_stub_delivered[1]);
}

/* 5. serial == RT_NULL 分支（辅助函数里的第一个防护）+ 返回值契约。
 *    这条分支在回调路径上不可达：回调里的 serial 恒为 &uart_obj[i].serial，
 *    所以只能直接调辅助函数（白盒）。 */
static void case_5_null_serial_direct_helper(void)
{
    rt_err_t   rc;
    rt_uint32_t drop0;
    unsigned   put0, isr0;

    drop0 = g_uart_rx_dropped_before_fifo;
    put0 = usart_stub_putchar_calls;
    isr0 = usart_stub_isr_calls;

    rc = ra_uart_queue_rx_char(RT_NULL, 0x33);

    CHECK(rc == -RT_ERROR,
          "serial == RT_NULL 时返回值应为 -RT_ERROR，实际 %d", (int)rc);
    CHECK(usart_stub_putchar_calls == put0,
          "serial == RT_NULL 时不得写 ringbuffer");
    CHECK(usart_stub_isr_calls == isr0,
          "serial == RT_NULL 时不得通知 isr");
    CHECK(g_uart_rx_dropped_before_fifo == drop0 + 1,
          "serial == RT_NULL 时丢弃计数器应 +1（%u -> %u）",
          (unsigned)drop0, (unsigned)g_uart_rx_dropped_before_fifo);
    CHECK(usart_stub_assert_hits == 0,
          "serial == RT_NULL 不得触发断言");

    /* 同一个辅助函数的第二条分支：serial 非空但 serial_rx 未发布，
     * 返回值契约一致，且不碰硬件侧任何东西。 */
    slot_serial(0)->serial_rx = RT_NULL;
    drop0 = g_uart_rx_dropped_before_fifo;
    rc = ra_uart_queue_rx_char(slot_serial(0), 0x44);

    CHECK(rc == -RT_ERROR,
          "FIFO 未发布时返回值也应为 -RT_ERROR，实际 %d", (int)rc);
    CHECK(g_uart_rx_dropped_before_fifo == drop0 + 1,
          "FIFO 未发布时丢弃计数器应 +1（%u -> %u）",
          (unsigned)drop0, (unsigned)g_uart_rx_dropped_before_fifo);
    CHECK(usart_stub_putchar_calls == put0 && usart_stub_isr_calls == isr0,
          "FIFO 未发布时不得写 ringbuffer / 通知 isr");

    /* FIFO 已发布：返回值应为 RT_EOK，且确实进了 ring */
    publish(0);
    drop0 = g_uart_rx_dropped_before_fifo;
    rc = ra_uart_queue_rx_char(slot_serial(0), 0x55);

    CHECK(rc == RT_EOK, "FIFO 已发布时返回值应为 RT_EOK，实际 %d", (int)rc);
    CHECK(usart_stub_delivered_count == 1 && usart_stub_delivered[0] == 0x55,
          "FIFO 已发布时字节应经 isr 交付给上层");
    CHECK(g_uart_rx_dropped_before_fifo == drop0,
          "FIFO 已发布时不得动丢弃计数器");
}

/* 6. 真实窗口：rt_hw_usart_init() 注册设备 → ops->configure() → R_SCI_B_UART_Open()
 *    在返回前回调字节。这就是补丁修的那个启动期停机路径。 */
static void case_6_open_window_byte_dropped(void)
{
    struct serial_configure cfg = RT_SERIAL_CONFIG_DEFAULT;
    int i;

    (void)rt_hw_usart_init();

    CHECK(usart_stub_reg_calls == 2,
          "rt_hw_usart_init() 应注册 2 个串口设备，实际 %u 个",
          usart_stub_reg_calls);
    CHECK(usart_stub_reg_names[0] != RT_NULL &&
              strcmp(usart_stub_reg_names[0], "uart1") == 0 &&
              usart_stub_reg_names[1] != RT_NULL &&
              strcmp(usart_stub_reg_names[1], "uart2") == 0,
          "设备名应为 uart1 / uart2（实际 %s / %s）",
          usart_stub_reg_names[0] ? usart_stub_reg_names[0] : "(null)",
          usart_stub_reg_names[1] ? usart_stub_reg_names[1] : "(null)");

    for (i = 0; i < 2; i++)
    {
        struct rt_serial_device *serial = slot_serial(i);
        rt_uint32_t drop0 = g_uart_rx_dropped_before_fifo;
        unsigned    enter0 = usart_stub_enter_calls;
        unsigned    leave0 = usart_stub_leave_calls;
        unsigned    open0 = usart_stub_open_calls;
        unsigned    injected0 = usart_stub_open_injected;

        CHECK(serial->ops != RT_NULL && serial->ops->configure != RT_NULL,
              "%s: rt_hw_usart_init() 必须装上 configure 回调", g_uarts[i].name);
        CHECK(serial->serial_rx == RT_NULL,
              "%s: rt_device_open() 之前 serial_rx 必须是 NULL", g_uarts[i].name);

        usart_stub_open_inject_bytes = 3;
        usart_stub_open_inject_first = 0x11;
        usart_stub_open_inject_callback = g_uarts[i].cb;

        CHECK(serial->ops->configure(serial, &cfg) == RT_EOK,
              "%s: configure 应返回 RT_EOK", g_uarts[i].name);

        CHECK(usart_stub_open_calls == open0 + 1,
              "%s: configure 必须一路走到 R_SCI_B_UART_Open（实际多了 %u 次）",
              g_uarts[i].name, usart_stub_open_calls - open0);
        CHECK(usart_stub_open_injected == injected0 + 3,
              "%s: 窗口内应真的注入了 3 个字节（实际 %u）——为 0 说明这条路径没走到",
              g_uarts[i].name, usart_stub_open_injected - injected0);
        CHECK(usart_stub_open_last_ctrl ==
                  (void *)((i == 0) ? &g_uart1_ctrl : &g_uart2_ctrl),
              "%s: 传给 R_SCI_B_UART_Open 的 ctrl 必须是该口的控制块",
              g_uarts[i].name);
        CHECK(usart_stub_open_last_cfg ==
                  (const void *)((i == 0) ? &g_uart1_cfg : &g_uart2_cfg),
              "%s: 传给 R_SCI_B_UART_Open 的 cfg 必须是该口的配置块",
              g_uarts[i].name);

        CHECK(usart_stub_assert_hits == 0,
              "%s: 启动窗口内收到字节不得触发断言（补丁的核心）", g_uarts[i].name);
        CHECK(usart_stub_putchar_calls == 0,
              "%s: 窗口内的字节无 FIFO 可写，不得调用 ringbuffer", g_uarts[i].name);
        CHECK(usart_stub_isr_calls == 0,
              "%s: 窗口内的字节不得通知 isr", g_uarts[i].name);
        CHECK(g_uart_rx_dropped_before_fifo == drop0 + 3,
              "%s: 窗口内 3 个字节应全部计入丢弃计数（%u -> %u）",
              g_uarts[i].name, (unsigned)drop0,
              (unsigned)g_uart_rx_dropped_before_fifo);
        CHECK(usart_stub_enter_calls == enter0 + 3 &&
                  usart_stub_leave_calls == leave0 + 3,
              "%s: 3 次回调应各带来一次 enter/leave（enter=%u leave=%u）",
              g_uarts[i].name, usart_stub_enter_calls - enter0,
              usart_stub_leave_calls - leave0);

        usart_stub_open_inject_callback = RT_NULL;
    }
}

/* 7. 同一个窗口，但 FIFO 已发布：字节必须原样收下（"发布之后逐字节不变"）。 */
static void case_7_open_window_after_publish_delivers(void)
{
    struct serial_configure cfg = RT_SERIAL_CONFIG_DEFAULT;
    static const rt_uint8_t expect[3] = { 0x11, 0x12, 0x13 };
    int i;

    (void)rt_hw_usart_init();

    for (i = 0; i < 2; i++)
    {
        struct rt_serial_device *serial = slot_serial(i);
        rt_uint32_t drop0;
        unsigned    put0, isr0, delivered0, injected0;

        publish(i);
        drop0 = g_uart_rx_dropped_before_fifo;
        put0 = usart_stub_putchar_calls;
        isr0 = usart_stub_isr_calls;
        delivered0 = usart_stub_delivered_count;
        injected0 = usart_stub_open_injected;

        usart_stub_open_inject_bytes = 3;
        usart_stub_open_inject_first = 0x11;
        usart_stub_open_inject_callback = g_uarts[i].cb;

        CHECK(serial->ops->configure(serial, &cfg) == RT_EOK,
              "%s: configure 应返回 RT_EOK", g_uarts[i].name);

        CHECK(usart_stub_open_injected == injected0 + 3,
              "%s: 窗口内应真的注入了 3 个字节（实际 %u）",
              g_uarts[i].name, usart_stub_open_injected - injected0);
        CHECK(usart_stub_putchar_calls == put0 + 3 &&
                  usart_stub_putchar_success == put0 + 3,
              "%s: 3 个字节应全部写进 ring（putchar=%u success=%u）",
              g_uarts[i].name, usart_stub_putchar_calls - put0,
              usart_stub_putchar_success - put0);
        CHECK(usart_stub_isr_calls == isr0 + 3,
              "%s: 应通知 3 次 isr（实际 %u）",
              g_uarts[i].name, usart_stub_isr_calls - isr0);
        CHECK(usart_stub_delivered_count == delivered0 + 3 &&
                  memcmp(&usart_stub_delivered[delivered0], expect, 3) == 0,
              "%s: 上层收到的字节应为 11 12 13，实际 %02X %02X %02X",
              g_uarts[i].name,
              usart_stub_delivered_count > delivered0
                  ? usart_stub_delivered[delivered0] : 0,
              usart_stub_delivered_count > delivered0 + 1
                  ? usart_stub_delivered[delivered0 + 1] : 0,
              usart_stub_delivered_count > delivered0 + 2
                  ? usart_stub_delivered[delivered0 + 2] : 0);
        CHECK(g_uart_rx_dropped_before_fifo == drop0,
              "%s: FIFO 已发布时这些字节不得被丢弃", g_uarts[i].name);

        usart_stub_open_inject_callback = RT_NULL;
    }
}

/* 8. 逐字节保真：0x00..0xFF 全序写入，ring 层与 isr 层各校验一遍。 */
static void case_8_byte_exactness_256(void)
{
    rt_uint8_t  sink[RT_SERIAL_RX_STUB_BUFSZ];
    unsigned    n;
    unsigned    i;
    unsigned    bad = 0;
    rt_uint32_t drop0;

    publish(0);

    /* 8a. isr 关掉搬移，纯看 ring 内容 —— 直接回答"字节是否准确写入 ringbuffer" */
    usart_stub_isr_drain_enabled = 0;
    drop0 = g_uart_rx_dropped_before_fifo;
    for (i = 0; i < 256; i++)
    {
        fire(0, UART_EVENT_RX_CHAR, (uint32_t)i);
    }
    CHECK(usart_stub_putchar_calls == 256 && usart_stub_putchar_success == 256,
          "256 个字节应全部写入 ring（calls=%u success=%u）",
          usart_stub_putchar_calls, usart_stub_putchar_success);
    CHECK(usart_stub_isr_calls == 256,
          "256 个字节应通知 256 次 isr（实际 %u）", usart_stub_isr_calls);
    CHECK(usart_stub_isr_seen_empty_ring == 0,
          "isr 观测模式下每次进入都应有数据，实际空 %u 次",
          usart_stub_isr_seen_empty_ring);

    n = usart_stub_fifo_drain(&g_fifo[0], sink, sizeof(sink));
    CHECK(n == 256, "ring 里应正好取出 256 字节，实际 %u", n);
    for (i = 0; i < n && i < 256; i++)
    {
        if (sink[i] != (rt_uint8_t)i)
        {
            bad++;
        }
    }
    CHECK(bad == 0, "ring 内容应严格等于 0x00..0xFF，实际有 %u 个字节不符", bad);
    CHECK(g_uart_rx_dropped_before_fifo == drop0,
          "FIFO 已发布时 256 个字节一个都不该丢");

    /* 8b. isr 打开搬移：同样的 256 字节必须原样交付到上层 */
    usart_stub_reset();
    publish(0);
    drop0 = g_uart_rx_dropped_before_fifo;
    for (i = 0; i < 256; i++)
    {
        fire(0, UART_EVENT_RX_CHAR, (uint32_t)i);
    }
    CHECK(usart_stub_delivered_count == 256,
          "上层应收到 256 字节，实际 %u", usart_stub_delivered_count);
    bad = 0;
    for (i = 0; i < usart_stub_delivered_count; i++)
    {
        if (usart_stub_delivered[i] != (rt_uint8_t)i)
        {
            bad++;
        }
    }
    CHECK(bad == 0, "交付序列应严格等于 0x00..0xFF，实际有 %u 个字节不符", bad);
    CHECK(usart_stub_isr_drained_total == 256,
          "isr 累计搬运应为 256 字节，实际 %u", usart_stub_isr_drained_total);
    CHECK(g_uart_rx_dropped_before_fifo == drop0,
          "isr 搬移路径下也不该有任何字节被丢");
    CHECK(usart_stub_irq_depth == 0, "256 次回调后嵌套深度应归零");
}

/* 9. 丢弃计数器：只增不减、不受清零影响、总数与操作次数严格对账。 */
static void case_9_drop_counter_accounted(void)
{
    rt_uint32_t d;
    unsigned    k;
    const unsigned null_fifo_hits = 5;
    const unsigned null_serial_hits = 4;

    publish(0);
    slot_serial(1)->serial_rx = RT_NULL;

    d = g_uart_rx_dropped_before_fifo;

    /* 9a. 每次丢弃都恰好 +1，且从不下落 */
    for (k = 0; k < null_fifo_hits; k++)
    {
        rt_uint32_t prev = g_uart_rx_dropped_before_fifo;
        fire(1, UART_EVENT_RX_CHAR, (uint32_t)k);
        CHECK(g_uart_rx_dropped_before_fifo == prev + 1,
              "第 %u 次丢弃应让计数器恰好 +1（%u -> %u）", k + 1,
              (unsigned)prev, (unsigned)g_uart_rx_dropped_before_fifo);
        CHECK(g_uart_rx_dropped_before_fifo > prev,
              "丢弃计数器不得回落");
    }

    /* 9b. 直接调辅助函数的 serial == RT_NULL 分支，同样逐次 +1 */
    for (k = 0; k < null_serial_hits; k++)
    {
        rt_uint32_t prev = g_uart_rx_dropped_before_fifo;
        (void)ra_uart_queue_rx_char(RT_NULL, (rt_uint8_t)k);
        CHECK(g_uart_rx_dropped_before_fifo == prev + 1,
              "serial==NULL 分支第 %u 次丢弃应恰好 +1（%u -> %u）", k + 1,
              (unsigned)prev, (unsigned)g_uart_rx_dropped_before_fifo);
    }

    /* 9c. 期间穿插一次成功接收：不得影响计数 */
    fire(0, UART_EVENT_RX_CHAR, 0x99);
    CHECK(usart_stub_delivered_count == 1 && usart_stub_delivered[0] == 0x99,
          "uart1 的字节应正常交付");
    CHECK(g_uart_rx_dropped_before_fifo == d + null_fifo_hits + null_serial_hits,
          "计数器总数应为起始值 + %u（丢弃 %u 次）——实际 %u",
          null_fifo_hits + null_serial_hits, null_fifo_hits + null_serial_hits,
          (unsigned)(g_uart_rx_dropped_before_fifo - d));

    /* 9d. 计数器的"只读"性质：用例级复位（usart_stub_reset）不得清它 */
    usart_stub_reset();
    CHECK(g_uart_rx_dropped_before_fifo == d + null_fifo_hits + null_serial_hits,
          "丢弃计数器是只读累计值，跨用例不得被清零/回退");
}

/* 10. 注册与配置表接线：注册的必须是 uart_obj 自己的设备对象，
 *     配置必须来自 uart_config[]，且 ra_uart_get_config() 用了 rtconfig 的 bufsize。 */
static void case_10_registration_and_config(void)
{
    struct serial_configure cfg = RT_SERIAL_CONFIG_DEFAULT;
    unsigned i;

    (void)rt_hw_usart_init();

    CHECK(usart_stub_reg_calls == 2, "应注册 2 个设备，实际 %u",
          usart_stub_reg_calls);

    for (i = 0; i < 2; i++)
    {
        struct rt_serial_device *serial = slot_serial(i);

        CHECK(usart_stub_reg_serials[i] == serial,
              "%s: 注册给设备框架的必须是 uart_obj[%d].serial 本体",
              g_uarts[i].name, g_uarts[i].index);
        CHECK(usart_stub_reg_flags[i] == RT_DEVICE_FLAG_RDWR,
              "%s: 注册 flag 应为 RT_DEVICE_FLAG_RDWR(0x%X)，实际 0x%X",
              g_uarts[i].name, (unsigned)RT_DEVICE_FLAG_RDWR,
              (unsigned)usart_stub_reg_flags[i]);
        CHECK(uart_obj[g_uarts[i].index].config == &uart_config[g_uarts[i].index],
              "%s: uart_obj[%d].config 必须指向 uart_config[%d]",
              g_uarts[i].name, g_uarts[i].index, g_uarts[i].index);
        CHECK(uart_config[g_uarts[i].index].name != RT_NULL &&
                  strcmp(uart_config[g_uarts[i].index].name, g_uarts[i].name) == 0,
              "%s: uart_config[%d].name 应为 \"%s\"，实际 \"%s\"",
              g_uarts[i].name, g_uarts[i].index, g_uarts[i].name,
              uart_config[g_uarts[i].index].name);
        CHECK(serial->config.rx_bufsz == 256 && serial->config.tx_bufsz == 0,
              "%s: ra_uart_get_config() 应带上 rtconfig 的 bufsize(256/0)，"
              "实际 %u/%u", g_uarts[i].name,
              (unsigned)serial->config.rx_bufsz,
              (unsigned)serial->config.tx_bufsz);
        CHECK(serial->config.baud_rate == 115200,
              "%s: 初始波特率应为 115200，实际 %u", g_uarts[i].name,
              (unsigned)serial->config.baud_rate);
        CHECK(serial->serial_rx == RT_NULL,
              "%s: 注册完成后 serial_rx 仍应为 NULL（FIFO 由 rt_device_open 发布）",
              g_uarts[i].name);
    }

    /* configure 的返回值在 R_SCI_B_UART_Open 失败时必须透传 -RT_ERROR */
    usart_stub_open_result = FSP_ERR_ABORTED;
    CHECK(slot_serial(0)->ops->configure(slot_serial(0), &cfg) == -RT_ERROR,
          "R_SCI_B_UART_Open 失败时 configure 应返回 -RT_ERROR");
    CHECK(usart_stub_putchar_calls == 0 && usart_stub_isr_calls == 0,
          "configure 失败路径不得写 ringbuffer / 通知 isr");
}

/* ===================================================================== */

int main(void)
{
    printf("drv_usart_v2.c UART 回调防护桩测试（主机 gcc）\n");
    printf("被测文件: %s\n", DRV_USART_V2_C_PATH);
    printf("配置    : RT_USING_SERIAL_V2 + BSP_USING_UART1/2 + SOC_SERIES_R7KA8P1\n\n");

    RUN_CASE("1-null-fifo-drops-rx-char", case_1_null_fifo_drops_rx_char);
    RUN_CASE("2-published-fifo-queues-and-notifies",
             case_2_published_fifo_queues_and_notifies);
    RUN_CASE("3-non-rx-char-events-untouched",
             case_3_non_rx_char_events_untouched);
    RUN_CASE("4-per-uart-isolation", case_4_per_uart_isolation);
    RUN_CASE("5-null-serial-direct-helper", case_5_null_serial_direct_helper);
    RUN_CASE("6-open-window-byte-dropped", case_6_open_window_byte_dropped);
    RUN_CASE("7-open-window-after-publish-delivers",
             case_7_open_window_after_publish_delivers);
    RUN_CASE("8-byte-exactness-256", case_8_byte_exactness_256);
    RUN_CASE("9-drop-counter-accounted", case_9_drop_counter_accounted);
    RUN_CASE("10-registration-and-config", case_10_registration_and_config);

    printf("\n");
    if (g_failures == 0)
    {
        printf("C drv_usart_v2 tests passed (%u checks)\n", g_checks);
        return 0;
    }
    printf("FAIL %u of %u checks failed\n", g_failures, g_checks);
    return 1;
}
