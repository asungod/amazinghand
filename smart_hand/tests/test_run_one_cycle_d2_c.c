/*
 * 主机桩测试：src/servo_bus_readonly_rt.c 的 run_one_cycle() 是否真的在
 * "无法推进"的两条路径上调用了 servo_group_readonly_abort_cycle()（D2 接线）。
 *
 * 被测文件（只读，不修改）：
 *   D:/Micu/RTTWorkspace/titan_uart_test/src/servo_bus_readonly_rt.c
 * 路径由包装脚本用 -DSERVO_BUS_READONLY_RT_C_PATH="..." 注入，默认值见下面。
 *
 * 被测的三条路径（run_one_cycle，源码 1157-1269 行）：
 *   (A) servo_group_readonly_prepare() 返回 0
 *         → 必须先 servo_group_readonly_abort_cycle(&g_group) 再 return；
 *   (B) 发送完成等待超过 SERVO_BUS_TX_TIMEOUT_MS（20 ms）
 *         → 同上；
 *   (C) R_SCI_B_UART_Write() != FSP_SUCCESS
 *         → 必须保持原本的 note_tx_failed() + continue（逐舵机推进），
 *           绝不能改成 abort —— 本条是"别把三条路径搞混"的对照组。
 *
 * 为什么是白盒（把被测 .c 直接并进本 TU）：
 *   run_one_cycle() 与 g_group 都是文件内 static，从另一个 TU 既调不到也读不到。
 *   源文件本身仍然只读、一个字节都不改；改的是"编译单元"的形状。
 *   代价：本 TU 与"固件里独立编译 servo_bus_readonly_rt.c"不是同一种编译单元，
 *   包装脚本因此另外跑一次 -fsyntax-only 独立语法检查来兜底。
 *
 * 三条路径怎么被驱动起来（控制点，全部是"摆状态"而不是改源码）：
 *   (A) 往 g_group.ids[0] 写一个超出 SCS0009 id 空间的值（0xFF > 253）。
 *       begin_cycle() 不校验 id，但 prepare() 内部的 scs0009_build_read()
 *       会拒绝 ⇒ packet_length == 0 ⇒ prepare() 返回 0，正是这条分支
 *       注释里"the request could not be built"的情形。
 *       注意：任务书提示的"让 g_group 处于非 IDLE 事务状态"这条路走不通 ——
 *       begin_cycle() 与 prepare() 用的是同一个前置条件，事务非 IDLE 时
 *       begin_cycle() 先返回 0，run_one_cycle() 在函数开头就 return 了，
 *       根本到不了 prepare()。这是本次实测出来的差异，见随手报告。
 *   (B) 让 R_SCI_B_UART_Write() 返回 FSP_SUCCESS 但把 tx_src_bytes / CSR.TEND
 *       留在"没发完"的状态（ISR 永远不搬完 FIFO），配合假时钟越过 20 ms。
 *   (C) 让 R_SCI_B_UART_Write() 返回非 FSP_SUCCESS。
 *
 * 测试替身模拟到哪一步（越界的地方明说）：
 *   - RT-Thread 内核：本 TU 不跑内核。rt_tick_get()/rt_thread_yield()/
 *     rt_thread_mdelay() 由一个"假时钟"实现（每次 yield +1 ms，每次 mdelay
 *     +ms ms，与固件 1 kHz tick 下的真实语义同量级）。这不是 1:1 的时间模拟，
 *     但只要被测代码用这三个原语计时，超时判断的因果就与固件一致。
 *   - FSP：R_SCI_B_UART_Write() 不搬任何字节。它把请求字节抄一份留证，并按
 *     用例设定决定"发完"还是"永远发不完"。RX 侧的字节由 rt_device_read() 桩
 *     从一个队列里供给，队列内容是本文件合成的合法 SCS0009 状态帧。
 *     真实硬件里这些帧来自舵机，本测试不覆盖"舵机是否回了正确数据"。
 *   - servo_group_readonly.c / scs0009_*.c / eight_servo_*.c 全部链接真实实现
 *     （它们是纯逻辑、可在主机编译），所以状态机内部的行为没有被替换。
 *   - 没被执行的代码：任何真实 UART/GPIO/中断路径、FreeRTOS 线程调度、
 *     stdin 之外的协议层（smart_hand_uart.c 等）都不参与。见报告"没被执行到
 *     的路径"一节。
 */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <board.h>
#include <hal_data.h>
#include <rtdevice.h>
#include <rtthread.h>

#ifndef SERVO_BUS_READONLY_RT_C_PATH
#define SERVO_BUS_READONLY_RT_C_PATH \
    "D:/Micu/RTTWorkspace/titan_uart_test/src/servo_bus_readonly_rt.c"
#endif

#include SERVO_BUS_READONLY_RT_C_PATH

/* ===================================================================== */
/* 桩状态                                                                */
/* ===================================================================== */

/* --- 假时钟：RT_TICK_PER_SECOND == 1000（rtconfig.h:13），1 tick = 1 ms，
 *     所以 servo_now_ms() 就是 rt_tick_get() 本身。 --- */
static uint32_t g_stub_tick_ms = 5000u;
static uint32_t g_stub_yield_calls;
static uint32_t g_stub_yield_step_ms = 1u;
static uint32_t g_stub_mdelay_calls;
static uint32_t g_stub_mdelay_total_ms;

/* --- 互斥量：只记次数，不阻塞（单线程测试，阻塞没有意义） --- */
static uint32_t g_stub_mutex_take_calls;
static uint32_t g_stub_mutex_release_calls;
static uint32_t g_stub_mutex_depth;
static uint32_t g_stub_mutex_unbalanced;

/* --- 引脚：set_leds() 的可观测面 --- */
static uint32_t g_stub_pin_write_calls;
static int32_t  g_stub_pin_last_value[3]; /* [0]=RED [1]=GREEN [2]=BLUE，-1 表示还没写过 */
static uint32_t g_stub_pin_unknown;       /* 写了非 LED 引脚：说明桩的引脚常量对不上 */

/* --- 发送：每次 R_SCI_B_UART_Write() 的完整取证 --- */
#define STUB_WRITE_CAP 16u
typedef struct
{
    uint8_t  called;
    uint8_t  id;            /* 请求包第 3 字节（舵机 id） */
    uint8_t  length;        /* bytes 参数 */
    uint8_t  cycle_active;  /* 调用瞬间 g_group.cycle_active */
    uint8_t  current_index; /* 调用瞬间 g_group.current_index */
    uint8_t  txn_state;     /* 调用瞬间 g_group.transaction.state */
    uint8_t  ids_after;     /* 调用瞬间 g_group.ids[0]（用于确认控制点） */
} stub_write_record_t;

static stub_write_record_t g_stub_writes[STUB_WRITE_CAP];
static uint32_t            g_stub_write_calls;
static uint32_t            g_stub_write_overflows;
static fsp_err_t           g_stub_write_result = FSP_SUCCESS;

/* 发送完成后是否把 TX 置"完成"（1）还是"永远发不完"（0）。
 * 0 会驱动路径 (B)。 */
static int g_stub_tx_completes = 1;
/* 发送成功后是否把对应的合法状态帧塞进 RX 队列（回环模型）。 */
static int g_stub_rx_loopback = 1;

/* --- 接收队列 --- */
#define STUB_RXQ_CAP 256u
static uint8_t g_stub_rxq[STUB_RXQ_CAP];
static size_t  g_stub_rxq_head;
static size_t  g_stub_rxq_tail;
static uint32_t g_stub_read_calls;
static uint32_t g_stub_read_bytes_served;
static uint32_t g_stub_read_null_buffer;
static uint32_t g_stub_rxq_overflow;

/* --- FSP 对象：与固件同名同类型，本 TU 提供唯一一份定义 --- */
static R_SCI_B0_Type             g_uart1_regs;
sci_b_uart_instance_ctrl_t       g_uart1_ctrl;
ioport_instance_ctrl_t           g_ioport_ctrl;

/* --- 假时钟下"另一个用例已经留下的状态"的观测计数 --- */
static uint32_t g_stub_assert_hits;

/* ===================================================================== */
/* 桩实现                                                                */
/* ===================================================================== */

rt_tick_t rt_tick_get(void)
{
    return (rt_tick_t)g_stub_tick_ms;
}

rt_err_t rt_thread_yield(void)
{
    g_stub_yield_calls++;
    g_stub_tick_ms += g_stub_yield_step_ms; /* 让出 CPU 的时间里时间在走 */
    return RT_EOK;
}

rt_err_t rt_thread_mdelay(rt_int32_t ms)
{
    if (ms > 0)
    {
        g_stub_mdelay_calls++;
        g_stub_mdelay_total_ms += (uint32_t)ms;
        g_stub_tick_ms += (uint32_t)ms;
    }
    return RT_EOK;
}

/* 真实 rtthread.h 的 rt_thread_create 会分配 TCB 并挂到调度器上；本测试不跑
 * 内核，也不需要假线程：run_one_cycle() 是由用例直接调用的。这里返回一个
 * 非空哨兵，保证 servo_bus_readonly_init() 若要编译/运行都不会因为空指针
 * 走进错误分支。 */
static int g_stub_fake_thread;
rt_thread_t rt_thread_create(const char *name,
                             void (*entry)(void *parameter),
                             void       *parameter,
                             rt_uint32_t stack_size,
                             rt_uint8_t  priority,
                             rt_uint32_t tick)
{
    (void)name; (void)entry; (void)parameter;
    (void)stack_size; (void)priority; (void)tick;
    return (rt_thread_t)&g_stub_fake_thread;
}

rt_err_t rt_thread_startup(rt_thread_t thread)
{
    (void)thread;
    return RT_EOK;
}

rt_err_t rt_thread_delete(rt_thread_t thread)
{
    (void)thread;
    return RT_EOK;
}

rt_err_t rt_mutex_init(rt_mutex_t mutex, const char *name, rt_uint8_t flag)
{
    if (mutex == RT_NULL)
    {
        return -RT_ERROR;
    }
    mutex->name = name;
    mutex->flag = flag;
    mutex->taken = 0;
    return RT_EOK;
}

rt_err_t rt_mutex_detach(rt_mutex_t mutex)
{
    (void)mutex;
    return RT_EOK;
}

rt_err_t rt_mutex_take(rt_mutex_t mutex, rt_int32_t timeout)
{
    (void)timeout;
    if (mutex == RT_NULL)
    {
        return -RT_ERROR;
    }
    g_stub_mutex_take_calls++;
    g_stub_mutex_depth++;
    mutex->taken = 1;
    return RT_EOK;
}

rt_err_t rt_mutex_release(rt_mutex_t mutex)
{
    if (mutex == RT_NULL)
    {
        return -RT_ERROR;
    }
    g_stub_mutex_release_calls++;
    if (g_stub_mutex_depth > 0u)
    {
        g_stub_mutex_depth--;
    }
    else
    {
        g_stub_mutex_unbalanced++;
    }
    mutex->taken = 0;
    return RT_EOK;
}

static uint32_t led_slot(rt_base_t pin, int *known)
{
    *known = 1;
    if (pin == SERVO_BUS_LED_RED)
    {
        return 0u;
    }
    if (pin == SERVO_BUS_LED_GREEN)
    {
        return 1u;
    }
    if (pin == SERVO_BUS_LED_BLUE)
    {
        return 2u;
    }
    *known = 0;
    return 0u;
}

void rt_pin_mode(rt_base_t pin, rt_uint8_t mode)
{
    (void)pin;
    (void)mode;
}

void rt_pin_write(rt_base_t pin, rt_ssize_t value)
{
    int      known = 0;
    uint32_t slot = led_slot(pin, &known);

    g_stub_pin_write_calls++;
    if (!known)
    {
        g_stub_pin_unknown++;
        return;
    }
    g_stub_pin_last_value[slot] = (int32_t)value;
}

void *rt_memcpy(void *dst, const void *src, rt_ubase_t count)
{
    return memcpy(dst, src, (size_t)count);
}

void *rt_memset(void *dst, int c, rt_ubase_t count)
{
    return memset(dst, c, (size_t)count);
}

void rt_assert_handler(const char *ex_string, const char *func, rt_size_t line)
{
    g_stub_assert_hits++;
    fprintf(stderr, "RT_ASSERT(%s) 在 %s():%d 触发（本测试里没有断言路径，"
                    "出现即说明桩缺了防护）\n",
            ex_string != NULL ? ex_string : "?", func != NULL ? func : "?",
            (int)line);
}

static void stub_enqueue_status_frame(uint8_t id);

/* 真实的 R_SCI_B_UART_Write() 把 p_src 记进 ctrl->p_tx_src/tx_src_bytes 并启动
 * 发送，由 TX ISR 逐段搬空；这里保留"记账 + 决定发不发得完"两件事。
 * 请求字节本身不留存（长度/首字节足够断言），只有 id 与 length 进记录。 */
fsp_err_t R_SCI_B_UART_Write(uart_ctrl_t *const p_api_ctrl,
                             uint8_t const *const p_src,
                             uint32_t const bytes)
{
    sci_b_uart_instance_ctrl_t *ctrl = (sci_b_uart_instance_ctrl_t *)p_api_ctrl;
    uint32_t idx = g_stub_write_calls;

    g_stub_write_calls++;

    if (idx < STUB_WRITE_CAP)
    {
        stub_write_record_t *rec = &g_stub_writes[idx];
        rec->called = 1u;
        rec->id = (p_src != RT_NULL && bytes > 2u) ? p_src[2] : 0u;
        rec->length = (uint8_t)bytes;
        rec->cycle_active = g_group.cycle_active;
        rec->current_index = (uint8_t)g_group.current_index;
        rec->txn_state = (uint8_t)g_group.transaction.state;
        rec->ids_after = g_group.ids[0];
    }
    else
    {
        g_stub_write_overflows++;
    }

    if (g_stub_write_result != FSP_SUCCESS)
    {
        return g_stub_write_result;
    }
    if (ctrl == NULL)
    {
        return FSP_ERR_INVALID_POINTER;
    }

    if (g_stub_tx_completes)
    {
        ctrl->p_tx_src = p_src;
        ctrl->tx_src_bytes = 0u;       /* ISR 已搬完 */
        ctrl->p_reg->CSR_b.TEND = 1u;  /* 发送结束标志置位 */
        if (g_stub_rx_loopback && p_src != RT_NULL && bytes > 2u)
        {
            stub_enqueue_status_frame(p_src[2]);
        }
    }
    else
    {
        /* FIFO 永远搬不完：tx_src_bytes 保持非 0、TEND 保持 0。 */
        ctrl->p_tx_src = p_src;
        ctrl->tx_src_bytes = bytes;
        ctrl->p_reg->CSR_b.TEND = 0u;
    }
    return FSP_SUCCESS;
}

fsp_err_t R_SCI_B_UART_BaudSet(uart_ctrl_t *const p_api_ctrl,
                               void const *const p_baud_setting)
{
    (void)p_api_ctrl;
    (void)p_baud_setting;
    return FSP_SUCCESS;
}

fsp_err_t R_SCI_B_UART_BaudCalculate(uint32_t baudrate,
                                     bool bitrate_modulation,
                                     uint32_t baud_rate_error_x_1000,
                                     sci_b_baud_setting_t *const p_baud_setting)
{
    (void)baudrate;
    (void)bitrate_modulation;
    (void)baud_rate_error_x_1000;
    if (p_baud_setting != NULL)
    {
        p_baud_setting->baudrate_bits = 0u;
    }
    return FSP_SUCCESS;
}

fsp_err_t R_IOPORT_PinCfg(ioport_ctrl_t *const p_ctrl,
                          uint16_t pin,
                          uint32_t cfg)
{
    (void)p_ctrl;
    (void)pin;
    (void)cfg;
    return FSP_SUCCESS;
}

rt_device_t rt_device_find(const char *name)
{
    (void)name;
    /* 固件用 rt_device_find("uart1") 拿句柄；本测试不跑初始化，返回哨兵即可。 */
    return (rt_device_t)&g_stub_fake_thread;
}

rt_err_t rt_device_set_rx_indicate(rt_device_t dev,
                                   rt_err_t (*rx_ind)(rt_device_t dev,
                                                      rt_size_t size))
{
    (void)dev;
    (void)rx_ind;
    return RT_EOK;
}

rt_err_t rt_device_open(rt_device_t dev, rt_uint16_t oflag)
{
    (void)dev;
    (void)oflag;
    return RT_EOK;
}

rt_err_t rt_device_close(rt_device_t dev)
{
    (void)dev;
    return RT_EOK;
}

rt_err_t rt_device_control(rt_device_t dev, int cmd, void *arg)
{
    (void)dev;
    (void)cmd;
    (void)arg;
    return RT_EOK;
}

/* drain_servo_uart() 与 RX 突发读都走这里：一次给一个字节，队列空则返回 0
 * （真实驱动在无数据时也是 0，不是 -1）。 */
rt_ssize_t rt_device_read(rt_device_t dev,
                          rt_off_t    pos,
                          void       *buffer,
                          rt_size_t   size)
{
    (void)dev;
    (void)pos;
    g_stub_read_calls++;

    if (buffer == RT_NULL)
    {
        g_stub_read_null_buffer++;
        return 0;
    }
    if (size == 0u || g_stub_rxq_head == g_stub_rxq_tail)
    {
        return 0;
    }
    ((uint8_t *)buffer)[0] = g_stub_rxq[g_stub_rxq_head];
    g_stub_rxq_head = (g_stub_rxq_head + 1u) % STUB_RXQ_CAP;
    g_stub_read_bytes_served++;
    return 1;
}

/* ===================================================================== */
/* 测试侧工具                                                            */
/* ===================================================================== */

static unsigned    g_checks;
static unsigned    g_failures;
static unsigned    g_case_checks;
static unsigned    g_case_failures;
static const char *g_case_name;

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

static void stub_rxq_push(const uint8_t *bytes, size_t count)
{
    size_t i;

    for (i = 0u; i < count; ++i)
    {
        size_t next = (g_stub_rxq_tail + 1u) % STUB_RXQ_CAP;
        if (next == g_stub_rxq_head)
        {
            g_stub_rxq_overflow++; /* 队列满：本测试的帧都短，溢出即模型出错 */
            return;
        }
        g_stub_rxq[g_stub_rxq_tail] = bytes[i];
        g_stub_rxq_tail = next;
    }
}

/*
 * 合成一个合法的 SCS0009 状态帧（8 个参数，与 servo_group_readonly.c 的
 * SCS_FEEDBACK_BLOCK_LENGTH 一致）：
 *   FF FF <id> 0A <err> <pos hi> <pos lo> <spd hi> <spd lo>
 *   <load hi> <load lo> <volt> <temp> <chk>
 * packet[3] = 参数个数 + 2 = 10 ⇒ 总长 14；校验和 = ~sum(packet[2..len-2])，
 * 与 scs0009_packet.c 的 checksum() 同一算法。
 */
static void stub_enqueue_status_frame(uint8_t id)
{
    uint8_t frame[14];
    uint8_t sum = 0u;
    size_t  i;

    memset(frame, 0, sizeof(frame));
    frame[0] = 0xFFu;
    frame[1] = 0xFFu;
    frame[2] = id;
    frame[3] = 10u;         /* 8 个参数 + 2 */
    frame[4] = 0u;          /* error：0 表示无舵机错误 */
    frame[5] = 0x01u;       /* position_raw = 500 */
    frame[6] = 0xF4u;
    frame[7] = 0x00u;       /* speed_raw = 0 */
    frame[8] = 0x00u;
    frame[9] = 0x00u;       /* load_raw = 0 */
    frame[10] = 0x00u;
    frame[11] = 50u;        /* voltage_raw */
    frame[12] = 25u;        /* temperature_raw */
    for (i = 2u; i + 1u < sizeof(frame); ++i)
    {
        sum = (uint8_t)(sum + frame[i]);
    }
    frame[13] = (uint8_t)(~sum);

    stub_rxq_push(frame, sizeof(frame));
}

static void stub_reset(void)
{
    g_stub_tick_ms = 5000u;
    g_stub_yield_calls = 0u;
    g_stub_yield_step_ms = 1u;
    g_stub_mdelay_calls = 0u;
    g_stub_mdelay_total_ms = 0u;

    g_stub_mutex_take_calls = 0u;
    g_stub_mutex_release_calls = 0u;
    g_stub_mutex_depth = 0u;
    g_stub_mutex_unbalanced = 0u;

    g_stub_pin_write_calls = 0u;
    g_stub_pin_last_value[0] = -1;
    g_stub_pin_last_value[1] = -1;
    g_stub_pin_last_value[2] = -1;
    g_stub_pin_unknown = 0u;

    memset(g_stub_writes, 0, sizeof(g_stub_writes));
    g_stub_write_calls = 0u;
    g_stub_write_overflows = 0u;
    g_stub_write_result = FSP_SUCCESS;
    g_stub_tx_completes = 1;
    g_stub_rx_loopback = 1;

    g_stub_rxq_head = 0u;
    g_stub_rxq_tail = 0u;
    g_stub_read_calls = 0u;
    g_stub_read_bytes_served = 0u;
    g_stub_read_null_buffer = 0u;
    g_stub_rxq_overflow = 0u;

    memset(&g_uart1_ctrl, 0, sizeof(g_uart1_ctrl));
    g_uart1_ctrl.p_reg = &g_uart1_regs;
    g_uart1_regs.CSR = 0u;
}

/* 把 g_group 摆回"8 个合法 id、周期未开始"的干净状态。
 * g_group 是被测文件里的 static 实例，白盒直接可用。 */
static void group_reset(void)
{
    static const uint8_t ids[SERVO_GROUP_READONLY_MAX_COUNT] =
        {1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u};

    CHECK(servo_group_readonly_init(&g_group, ids,
                                    SERVO_GROUP_READONLY_MAX_COUNT,
                                    SERVO_BUS_RESPONSE_TIMEOUT_MS) == 1,
          "servo_group_readonly_init() 必须成功");
    g_ready = 0u;
    g_published_count = 0u;
}

/* 每个用例收尾都查的公共不变量 */
static void check_case_invariants(void)
{
    CHECK(g_stub_assert_hits == 0u,
          "本用例触发了 RT_ASSERT（%u 次）", g_stub_assert_hits);
    CHECK(g_stub_pin_unknown == 0u,
          "set_leds() 写了 %u 次非 LED 引脚 —— 桩的引脚常量与固件对不上",
          g_stub_pin_unknown);
    CHECK(g_stub_read_null_buffer == 0u,
          "rt_device_read() 收到过 %u 次空缓冲区", g_stub_read_null_buffer);
    CHECK(g_stub_rxq_overflow == 0u,
          "RX 队列溢出 %u 次 —— 合成帧比预期多", g_stub_rxq_overflow);
    CHECK(g_stub_write_overflows == 0u,
          "写入记录数组溢出 %u 次（%u > %u）", g_stub_write_overflows,
          g_stub_write_calls, (unsigned)STUB_WRITE_CAP);
    CHECK(g_stub_mutex_unbalanced == 0u,
          "rt_mutex_release() 比 take() 多 %u 次", g_stub_mutex_unbalanced);
    CHECK(g_stub_mutex_take_calls == g_stub_mutex_release_calls,
          "rt_mutex_take/release 不配对：take=%u release=%u",
          g_stub_mutex_take_calls, g_stub_mutex_release_calls);
    CHECK(g_stub_mutex_depth == 0u,
          "用例结束时互斥量嵌套深度应为 0，实际 %u", g_stub_mutex_depth);
}

/* set_leds() 的最后一次三色状态：LED 低电平点亮（SERVO_BUS_LED_ON == PIN_LOW） */
static int led_is(int32_t r, int32_t g, int32_t b)
{
    return g_stub_pin_last_value[0] == r && g_stub_pin_last_value[1] == g &&
           g_stub_pin_last_value[2] == b;
}

#define RUN_CASE(name, fn)                                             \
    do {                                                               \
        stub_reset();                                                  \
        g_case_name = (name);                                          \
        g_case_checks = 0;                                             \
        g_case_failures = 0;                                           \
        printf("[run ] %s\n", g_case_name);                            \
        fn();                                                          \
        check_case_invariants();                                       \
        printf("[case] %s: %s (%u checks)\n", g_case_name,             \
               g_case_failures == 0 ? "ok" : "FAILED", g_case_checks); \
    } while (0)

/* ===================================================================== */
/* 用例                                                                  */
/* ===================================================================== */

/*
 * 0. 装置自检：先证明"测试能看见东西"，再谈 D2。
 *    这一条是防"空转通过"的：如果 run_one_cycle() 因为 include 出错/桩不对而
 *    根本没跑起来，下面 1、2 里所有 "cycle_active == 0" 都会因为"状态本来
 *    就没变"而假绿。
 */
static void case_0_harness_selfcheck(void)
{
    uint8_t packet[8];

    /* 0a. CSR.TEND 的位序：R7KA8P1KF_core0.h:25766-25770 里 TEND 是 CSR 的
     *     bit 30。桩的位域如果填错，路径 (B) 的等待条件读的就不是那一位。 */
    g_uart1_regs.CSR = 0u;
    g_uart1_regs.CSR_b.TEND = 1u;
    CHECK(g_uart1_regs.CSR == (1u << 30),
          "桩的 CSR_b.TEND 必须落在 CSR 的 bit 30（对应固件同一位）；实际 0x%08X",
          (unsigned)g_uart1_regs.CSR);
    g_uart1_regs.CSR = 0u;
    g_uart1_regs.CSR_b.TEND = 0u;

    /* 0b. 路径 (A) 的控制点是真的：超范围 id 会让 scs0009_build_read() 返回 0，
     *     prepare() 才会返回 0。 */
    CHECK(scs0009_build_read(0xFFu, 56u, 8u, packet, sizeof(packet)) == 0u,
          "id=0xFF 超出 SCS0009_MAX_ID(%u)，scs0009_build_read() 必须返回 0",
          (unsigned)SCS0009_MAX_ID);
    CHECK(scs0009_build_read(1u, 56u, 8u, packet, sizeof(packet)) == 8u,
          "合法 id 的读请求必须是 8 字节（run_one_cycle 的 request[8] 刚好装下）");

    /* 0c. 反空转：一个干净周期必须真的走完 8 个舵机、发出 8 个请求、
     *     并通过 publish_cycle() 发布 8 个样本。 */
    group_reset();
    run_one_cycle();

    CHECK(g_stub_write_calls == SERVO_GROUP_READONLY_MAX_COUNT,
          "一个完整周期应发出 %u 个请求，实际 %u 个",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, g_stub_write_calls);
    CHECK(g_stub_read_bytes_served ==
              SERVO_GROUP_READONLY_MAX_COUNT * 14u,
          "8 个舵机各回一个 14 字节状态帧，应被读走 112 字节，实际 %u",
          g_stub_read_bytes_served);
    CHECK(g_group.completed_cycles == 1u && g_group.cycle_valid == 1u,
          "完整周期应记为 completed+valid（completed=%u valid=%u）",
          (unsigned)g_group.completed_cycles, (unsigned)g_group.cycle_valid);
    CHECK(g_group.aborted_cycles == 0u,
          "顺畅通行的周期不得被 abort（aborted=%u）",
          (unsigned)g_group.aborted_cycles);
    CHECK(g_group.successful_reads == SERVO_GROUP_READONLY_MAX_COUNT,
          "应有 %u 次成功读取，实际 %u", (unsigned)SERVO_GROUP_READONLY_MAX_COUNT,
          (unsigned)g_group.successful_reads);
    CHECK(g_ready == 1u && g_published_count == SERVO_GROUP_READONLY_MAX_COUNT,
          "publish_cycle() 应发布 %u 个样本（g_ready=%u count=%u）",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, (unsigned)g_ready,
          (unsigned)g_published_count);

    /* 0d. RX 通路（含 run_one_cycle 里那段"抑制本地回显"的分支）确实被走到了：
     *     合成的状态帧与请求包在第 4 字节分叉（请求 0x04 vs 状态帧 0x0A），
     *     所以复现"回显不匹配 → 回放公共前缀 → 继续喂解析器"这条路径。
     *     如果它坏了，帧会被解析器丢掉：rejected_frames 会涨、frames_ok 会掉。 */
    CHECK(g_servo_rx_trace_length ==
              SERVO_GROUP_READONLY_MAX_COUNT * 14u,
          "RX 侧应原样记录 %u 个原始字节（g_servo_rx_trace_length=%u）——"
          "字节数不对说明回显抑制分支把字节吞掉了",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT * 14u,
          (unsigned)g_servo_rx_trace_length);
    CHECK(g_group.transaction.transactions_complete ==
              SERVO_GROUP_READONLY_MAX_COUNT,
          "应完成 %u 次事务（即 8 个状态帧都被解析成 COMPLETE），实际 %u。"
          "注意不能用 parser.frames_ok：scs0009_stream_init() 每次开事务都会"
          "memset 解析器，只有 transaction 上的累计计数是跨舵机保留的",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT,
          (unsigned)g_group.transaction.transactions_complete);
    CHECK(g_group.transaction.transactions_started ==
              SERVO_GROUP_READONLY_MAX_COUNT,
          "应发起 %u 次事务，实际 %u",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT,
          (unsigned)g_group.transaction.transactions_started);
    CHECK(g_group.transaction.rejected_frames == 0u,
          "回显抑制/回放分支不得让帧被拒（实际拒了 %u 个）",
          (unsigned)g_group.transaction.rejected_frames);

    /* 0e. 发布出来的数据要与合成帧里的值一致（把"喂进去的字节"和"发布的样本"
     *     钉在一起，防止 RX 桩喂了别的东西还可以假绿）。 */
    CHECK(g_published[0].read_ok == 1u && g_published[0].position_raw == 500u &&
              g_published[0].voltage_raw == 50u &&
              g_published[0].temperature_raw == 25u,
          "发布样本应与合成状态帧一致（read_ok=%u pos=%u volt=%u temp=%u）",
          (unsigned)g_published[0].read_ok,
          (unsigned)g_published[0].position_raw,
          (unsigned)g_published[0].voltage_raw,
          (unsigned)g_published[0].temperature_raw);
    CHECK(g_published[7].id == 8u && g_published[7].generation != 0u,
          "第 8 个样本应属于 id=8（id 实测 %u）",
          (unsigned)g_published[7].id);
    /* 成功周期最后落在 publish_cycle() 的 set_leds(0,1,0)：红灯灭、绿灯亮。 */
    CHECK(led_is(SERVO_BUS_LED_OFF, SERVO_BUS_LED_ON, SERVO_BUS_LED_OFF) == 1,
          "成功周期结束时应是绿灯（R/G/B 实测 %d/%d/%d）",
          (int)g_stub_pin_last_value[0], (int)g_stub_pin_last_value[1],
          (int)g_stub_pin_last_value[2]);
}

/*
 * 1. 路径 (A)：prepare() 返回 0。
 *    断言：周期自己结束（cycle_active == 0）；下一次 begin_cycle() 成功
 *    （这正是 D2 修复存在的理由 —— 在此之前它到重启前一直返回 0）。
 */
static void case_1_prepare_zero_aborts_and_recovers(void)
{
    group_reset();

    /* 控制点：把第 1 个舵机的 id 改成超范围值，begin_cycle() 不校验 id，
     * prepare() 里的 scs0009_build_read() 会拒绝。 */
    g_group.ids[0] = 0xFFu;

    run_one_cycle();

    /* 先证明走的确实是 (A)：一个字节都没发出去，也没进 TX 等待。 */
    CHECK(g_stub_write_calls == 0u,
          "prepare() 返回 0 的分支不应发出任何请求，实际发了 %u 个",
          g_stub_write_calls);
    CHECK(g_stub_yield_calls == 0u,
          "prepare() 返回 0 的分支不应进入 TX 等待循环，实际 yield 了 %u 次",
          g_stub_yield_calls);

    /* D2 主断言：周期必须自己结束。 */
    CHECK(g_group.cycle_active == 0u,
          "prepare() 返回 0 后周期必须自己结束（D2：否则 cycle_active 永久为 1，"
          "舵机总线静默到重启）；实际 cycle_active=%u",
          (unsigned)g_group.cycle_active);
    CHECK(g_group.aborted_cycles == 1u,
          "prepare() 返回 0 必须记一次 abort，实际 aborted_cycles=%u",
          (unsigned)g_group.aborted_cycles);
    CHECK(g_group.completed_cycles == 0u && g_group.cycle_complete == 0u,
          "被 abort 的周期不得记成完成（completed=%u complete=%u）",
          (unsigned)g_group.completed_cycles, (unsigned)g_group.cycle_complete);
    CHECK(g_group.transaction.state == SCS0009_TXN_IDLE,
          "abort 之后事务必须回到 IDLE，实际 %d",
          (int)g_group.transaction.state);
    CHECK(g_group.failed_reads == 1u,
          "被弃掉的那个舵机应计入 failed_reads（实际 %u）",
          (unsigned)g_group.failed_reads);
    CHECK(led_is(SERVO_BUS_LED_ON, SERVO_BUS_LED_OFF, SERVO_BUS_LED_OFF) == 1,
          "abort 路径应点亮红灯（R/G/B 实测 %d/%d/%d）",
          (int)g_stub_pin_last_value[0], (int)g_stub_pin_last_value[1],
          (int)g_stub_pin_last_value[2]);

    /* D2 的目的：下一次 begin_cycle() 必须成功。 */
    CHECK(servo_group_readonly_begin_cycle(&g_group) == 1,
          "abort 之后 begin_cycle() 必须返回 1（可恢复）；"
          "返回 0 就是 D2 未修复：舵机总线到重启前永久静默");
    CHECK(g_group.cycle_active == 1u,
          "恢复起来的周期应处于 active（实际 %u）", (unsigned)g_group.cycle_active);

    /* 收尾 + 反空转：上面那次 begin_cycle() 真的把周期开起来了，用同一个公开
     * 入口把它关掉（abort 幂等，且这正是产品代码的用法），把 id 恢复，然后证明
     * "总线真的活着" —— 同一个 g_group，不做任何重新初始化，直接跑完整周期。
     * 注意：这一段的断言不是变异体的检测点（它前面的 abort 顺手清掉了卡住的标志），
     * 变异体由上面那两条主断言负责抓；这里负责证明装置非空转。 */
    servo_group_readonly_abort_cycle(&g_group);
    g_group.ids[0] = 1u;
    g_ready = 0u;
    g_published_count = 0u;

    run_one_cycle();

    CHECK(g_ready == 1u && g_published_count == SERVO_GROUP_READONLY_MAX_COUNT,
          "abort 之后下一个周期必须正常走完并发布 %u 个样本"
          "（g_ready=%u count=%u）",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, (unsigned)g_ready,
          (unsigned)g_published_count);
}

/*
 * 2. 路径 (B)：发送完成等待超时（SERVO_BUS_TX_TIMEOUT_MS == 20 ms）。
 *    断言同 (1)：周期自己结束、可以恢复、下一次完整周期跑通。
 */
static void case_2_tx_timeout_aborts_and_recovers(void)
{
    uint32_t t0;

    group_reset();
    g_stub_tx_completes = 0;   /* FIFO 永远搬不完：tx_src_bytes != 0、TEND == 0 */
    g_stub_rx_loopback = 0;    /* 这条路径到不了 RX 阶段，关掉回环让意图明确 */

    t0 = g_stub_tick_ms;
    run_one_cycle();

    CHECK(g_stub_write_calls == 1u,
          "超时前应只发出第 1 个请求（返回发生在等待循环内部，不会轮到第 2 个）；"
          "实际 %u 个", g_stub_write_calls);
    CHECK(g_stub_read_bytes_served == 0u,
          "这条路径不应处理任何 RX 字节（只有 drain_servo_uart 的空读），"
          "实际读走 %u 字节", g_stub_read_bytes_served);
    CHECK(g_stub_yield_calls >= SERVO_BUS_TX_TIMEOUT_MS,
          "等待必须真的耗掉 %u ms（yield 次数 %u，步长 %u ms）——"
          "次数不足说明 abort 不是超时触发的",
          (unsigned)SERVO_BUS_TX_TIMEOUT_MS, g_stub_yield_calls,
          g_stub_yield_step_ms);
    CHECK(g_stub_tick_ms - t0 >= SERVO_BUS_TX_TIMEOUT_MS,
          "假时钟至少推进 %u ms（实际 %u ms）",
          (unsigned)SERVO_BUS_TX_TIMEOUT_MS, g_stub_tick_ms - t0);

    /* D2 主断言 */
    CHECK(g_group.cycle_active == 0u,
          "TX 超时后周期必须自己结束（D2：否则 cycle_active 永久为 1，"
          "舵机总线静默到重启）；实际 cycle_active=%u",
          (unsigned)g_group.cycle_active);
    CHECK(g_group.aborted_cycles == 1u,
          "TX 超时必须记一次 abort，实际 aborted_cycles=%u",
          (unsigned)g_group.aborted_cycles);
    CHECK(g_group.completed_cycles == 0u && g_group.cycle_complete == 0u,
          "超时的周期不得记成完成（completed=%u complete=%u）",
          (unsigned)g_group.completed_cycles, (unsigned)g_group.cycle_complete);
    CHECK(g_group.transaction.state == SCS0009_TXN_IDLE,
          "abort 之后事务必须回到 IDLE，实际 %d", (int)g_group.transaction.state);
    CHECK(g_group.failed_reads == 1u,
          "超时那一轮的那个舵机应计入 failed_reads（实际 %u）",
          (unsigned)g_group.failed_reads);
    CHECK(g_group.current_index == 0u,
          "超时路径是「整周期结束」，不是「推进到下一个舵机」；"
          "current_index 应保持 0，实际 %u", (unsigned)g_group.current_index);
    CHECK(led_is(SERVO_BUS_LED_ON, SERVO_BUS_LED_OFF, SERVO_BUS_LED_OFF) == 1,
          "abort 路径应点亮红灯（R/G/B 实测 %d/%d/%d）",
          (int)g_stub_pin_last_value[0], (int)g_stub_pin_last_value[1],
          (int)g_stub_pin_last_value[2]);

    /* D2 的目的：下一个周期必须能重新开始，并且真的能把总线上跑满 8 个舵机。 */
    CHECK(servo_group_readonly_begin_cycle(&g_group) == 1,
          "TX 超时 abort 之后 begin_cycle() 必须返回 1（可恢复）");
    servo_group_readonly_abort_cycle(&g_group); /* 收尾，让下一个完整周期干净开始 */
    g_stub_tx_completes = 1;
    g_stub_rx_loopback = 1;
    g_ready = 0u;
    g_published_count = 0u;

    run_one_cycle();

    CHECK(g_stub_write_calls == 1u + SERVO_GROUP_READONLY_MAX_COUNT,
          "恢复后的周期应再发出 %u 个请求（累计 %u）",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, g_stub_write_calls);
    CHECK(g_ready == 1u && g_published_count == SERVO_GROUP_READONLY_MAX_COUNT,
          "TX 超时之后下一个周期必须正常走完并发布 %u 个样本"
          "（g_ready=%u count=%u）",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, (unsigned)g_ready,
          (unsigned)g_published_count);
}

/*
 * 3. 对照组：R_SCI_B_UART_Write() != FSP_SUCCESS。
 *    这条路径**不是**"无法推进"：note_tx_failed() 会把当前舵机记为失败并推进到
 *    下一个，周期只在最后一个舵机处理完后自然结束。这里逐次取证：
 *      - 每次 Write 调用时 cycle_active 仍为 1、current_index 正好等于调用序号、
 *        事务正处于 WAIT_STATUS（note_tx_failed 生效的前置条件）；
 *      - 8 次调用覆盖 8 个舵机；
 *      - 结束时 aborted_cycles == 0、completed_cycles == 1 —— 即它是"正常走完
 *        但数据无效"，不是被 abort 掐掉的。
 *    如果有人把这条路径也改成 abort，aborted_cycles 会变成 1、completed 变 0，
 *    本用例立刻失败。
 */
static void case_3_write_failure_does_not_abort(void)
{
    uint32_t k;

    group_reset();
    g_stub_write_result = FSP_ERR_ABORTED; /* 任意非 FSP_SUCCESS */
    g_stub_tx_completes = 0;
    g_stub_rx_loopback = 0;

    run_one_cycle();

    CHECK(g_stub_write_calls == SERVO_GROUP_READONLY_MAX_COUNT,
          "发送失败路径应对 %u 个舵机各尝试一次，实际 %u 次",
          (unsigned)SERVO_GROUP_READONLY_MAX_COUNT, g_stub_write_calls);

    for (k = 0u; k < SERVO_GROUP_READONLY_MAX_COUNT; ++k)
    {
        const stub_write_record_t *rec = &g_stub_writes[k];

        CHECK(rec->called == 1u, "第 %u 次 Write 记录缺失", k + 1u);
        CHECK(rec->cycle_active == 1u,
              "第 %u 次 Write 时 cycle_active 仍应为 1（这条路径不得结束周期），"
              "实际 %u", k + 1u, (unsigned)rec->cycle_active);
        CHECK(rec->current_index == (uint8_t)k,
              "第 %u 次 Write 应作用在第 %u 个舵机上（current_index 实测 %u）——"
              "说明失败后确实推进到了下一个",
              k + 1u, k + 1u, (unsigned)rec->current_index);
        CHECK(rec->txn_state == SCS0009_TXN_WAIT_STATUS,
              "第 %u 次 Write 时事务应为 WAIT_STATUS（note_tx_failed 生效的前提），"
              "实际 %u", k + 1u, (unsigned)rec->txn_state);
        CHECK(rec->id == (uint8_t)(k + 1u),
              "第 %u 次请求的舵机 id 应为 %u，实际 %u",
              k + 1u, k + 1u, (unsigned)rec->id);
        CHECK(rec->length == 8u,
              "读请求长度应为 8 字节，第 %u 次实测 %u",
              k + 1u, (unsigned)rec->length);
    }

    /* 这是"别把三条路径搞混"的核心断言。 */
    CHECK(g_group.aborted_cycles == 0u,
          "发送失败路径不得 abort 周期（aborted_cycles=%u）——"
          "abort 是「无法推进」用的，逐舵机失败用 note_tx_failed()",
          (unsigned)g_group.aborted_cycles);
    CHECK(g_group.completed_cycles == 1u && g_group.cycle_complete == 1u,
          "8 个舵机都失败后周期应自然走完（completed=%u complete=%u）",
          (unsigned)g_group.completed_cycles, (unsigned)g_group.cycle_complete);
    CHECK(g_group.failed_reads == SERVO_GROUP_READONLY_MAX_COUNT,
          "8 个舵机都应计入 failed_reads，实际 %u",
          (unsigned)g_group.failed_reads);
    CHECK(g_group.successful_reads == 0u,
          "没有一次成功读取，successful_reads 应为 0，实际 %u",
          (unsigned)g_group.successful_reads);
    CHECK(g_group.cycle_active == 0u,
          "周期应在最后一个舵机处理完后自然结束，实际 cycle_active=%u",
          (unsigned)g_group.cycle_active);
    CHECK(g_group.cycle_valid == 0u,
          "全失败的周期不得标记为 valid，实际 %u", (unsigned)g_group.cycle_valid);
    CHECK(g_stub_yield_calls == 0u,
          "发送失败路径不应进入 TX 等待（yield %u 次）", g_stub_yield_calls);
    CHECK(g_ready == 0u && g_published_count == 0u,
          "无效周期不得发布样本（g_ready=%u count=%u）", (unsigned)g_ready,
          (unsigned)g_published_count);
}

/* ===================================================================== */

int main(void)
{
    printf("run_one_cycle() D2 接线桩测试（主机 gcc）\n");
    printf("被测文件: %s\n", SERVO_BUS_READONLY_RT_C_PATH);
    printf("接线断言: prepare()==0 与 TX 超时两条路径必须调用 "
           "servo_group_readonly_abort_cycle()；Write 失败路径必须不调用\n\n");

    RUN_CASE("0-harness-selfcheck", case_0_harness_selfcheck);
    RUN_CASE("1-prepare-zero-aborts-and-recovers",
             case_1_prepare_zero_aborts_and_recovers);
    RUN_CASE("2-tx-timeout-aborts-and-recovers",
             case_2_tx_timeout_aborts_and_recovers);
    RUN_CASE("3-write-failure-does-not-abort",
             case_3_write_failure_does_not_abort);

    printf("\n");
    if (g_failures == 0)
    {
        printf("C run_one_cycle D2 wiring tests passed (%u checks)\n", g_checks);
        return 0;
    }
    printf("FAIL %u of %u checks failed\n", g_failures, g_checks);
    return 1;
}
