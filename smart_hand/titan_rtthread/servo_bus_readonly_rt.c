#include "servo_bus_readonly_rt.h"
#include "eight_servo_pose_bank.h"
#include "eight_servo_safety_gate.h"

#include <board.h>
#include <hal_data.h>
#include <rtdevice.h>
#include <rtthread.h>

#ifndef SMART_HAND_SERVO_UART_NAME
#define SMART_HAND_SERVO_UART_NAME "uart1"
#endif

#define SERVO_BUS_THREAD_STACK 2048u
#define SERVO_BUS_BAUD_RATE 1000000u
#define SERVO_BUS_RESPONSE_TIMEOUT_MS 30u
#define SERVO_BUS_TX_TIMEOUT_MS 20u
#define SERVO_BUS_CYCLE_PERIOD_MS 500u
#define SERVO_BUS_DRAIN_MAX_BYTES 256u
#define SERVO_BUS_RX_BURST_MAX_BYTES 128u
#define SERVO_BUS_LED_GREEN BSP_IO_PORT_01_PIN_08
#define SERVO_BUS_LED_RED BSP_IO_PORT_01_PIN_09
#define SERVO_BUS_LED_BLUE BSP_IO_PORT_01_PIN_10
#define SERVO_BUS_LED_ON PIN_LOW
#define SERVO_BUS_LED_OFF PIN_HIGH
#define SERVO_PAIR_COMMISSION_MAGIC_FIRST 0x534D4B31u
#define SERVO_PAIR_COMMISSION_MAGIC_LAST 0x534D4B34u
#define SERVO_GROUP_COMMISSION_MAGIC 0x534D4B41u
#define SERVO_GROUP_CLOSE_MAGIC 0x534D4B43u
#define SERVO_GROUP_OPEN_MAGIC 0x534D4B4Fu
#define SERVO_INDEX_LATERAL_MAGIC 0x534D4C31u
#define SERVO_REHAB_DEMO_MAGIC 0x52484231u
#define SERVO_PAIR_COMMISSION_STEP 60u
#define SERVO_PAIR_COMMISSION_SPEED 80u
#define SERVO_PAIR_COMMISSION_TOLERANCE 8
#define SERVO_PAIR_COMMISSION_TIMEOUT_MS 5000u
#define SERVO_PAIR_COMMISSION_HOLD_MS 2500u
#define SERVO_GROUP_COMMISSION_STEP 30u
#define SERVO_GROUP_COMMISSION_HOLD_MS 2000u
#define SERVO_GROUP_MOTION_STEP 30u
#define SERVO_GROUP_MOTION_SETTLE_MS 50u
#define SERVO_GROUP_POSITION_TOLERANCE 12
#define SERVO_REHAB_DEMO_HOLD_MS 900u
#define SERVO_SIGN_DEMO_VERSION 1u
#define SERVO_SIGN_DEMO_HOLD_MS SERVO_REHAB_DEMO_HOLD_MS
#define SERVO_PAIR_CENTER_ODD 451u
#define SERVO_PAIR_CENTER_EVEN 571u

static const uint8_t g_servo_ids[SERVO_GROUP_READONLY_MAX_COUNT] =
    {1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u};
static const uint16_t g_servo_official_open[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 690u, 332u, 690u, 332u, 690u, 332u, 690u};
static const uint16_t g_servo_official_close[SERVO_GROUP_READONLY_MAX_COUNT] =
    {758u, 264u, 758u, 264u, 758u, 264u, 690u, 332u};
/* Pair mapping from the assembled right hand: index=1/2, middle=3/4,
 * ring=5/6, thumb=7/8.  The V pose retracts the two extended fingers enough
 * to create lateral headroom, then shifts their paired servos in opposite
 * directions.  Bench observation on 2026-09-21 showed the original polarity
 * moved both fingertips inward, so the two lateral endpoints are swapped here.
 * Point and thumbs-up remain fixed, bounded expression poses. */
static const uint16_t g_servo_v_sign[SERVO_GROUP_READONLY_MAX_COUNT] =
    {452u, 690u, 332u, 570u, 758u, 264u, 690u, 332u};
static const uint16_t g_servo_point[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 690u, 758u, 264u, 758u, 264u, 690u, 332u};
static const uint16_t g_servo_thumbs_up[SERVO_GROUP_READONLY_MAX_COUNT] =
    {758u, 264u, 758u, 264u, 758u, 264u, 332u, 690u};
/* L: index and thumb extended.  OK: index and thumb close toward a bounded
 * pinch while the remaining mechanically controlled fingers stay open. */
static const uint16_t g_servo_l_shape[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 690u, 758u, 264u, 758u, 264u, 332u, 690u};
static const uint16_t g_servo_ok_pinch[SERVO_GROUP_READONLY_MAX_COUNT] =
    {758u, 264u, 332u, 690u, 332u, 690u, 690u, 332u};
/* Multi-stage word/safety demonstrations only reuse bounded endpoints.  The
 * thanks midpoint bends the thumb without changing the closed finger pose;
 * the help pose tucks the thumb while the other fingers remain open. */
static const uint16_t g_servo_thanks_thumb_bend[SERVO_GROUP_READONLY_MAX_COUNT] =
    {758u, 264u, 758u, 264u, 758u, 264u, 511u, 511u};
static const uint16_t g_servo_help_thumb_tucked[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 690u, 332u, 690u, 332u, 690u, 690u, 332u};
/* Additional four-digit expression recipes.  No recipe depends on an
 * independently actuated little finger: the index performs the lateral
 * refusal/attention motion and the like gesture reuses the verified L/OK
 * endpoints. */
static const uint16_t g_servo_no_side_a[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 570u, 758u, 264u, 758u, 264u, 690u, 332u};
static const uint16_t g_servo_no_side_b[SERVO_GROUP_READONLY_MAX_COUNT] =
    {452u, 690u, 758u, 264u, 758u, 264u, 690u, 332u};
static const uint16_t g_servo_attention_bend[SERVO_GROUP_READONLY_MAX_COUNT] =
    {511u, 511u, 758u, 264u, 758u, 264u, 690u, 332u};
/* Bench-only index-finger lateral sweep.  At the fully-open endpoint there
 * is no same-direction travel left for a pure lateral movement, so first
 * retract both index servos by 60 raw units.  The two following poses keep
 * the pair separation constant and shift both servos together by 60 raw
 * units.  The motion engine still advances by at most 30 raw units per
 * checked step.  All other fingers remain at the verified open pose. */
static const uint16_t
    g_servo_index_lateral_center[SERVO_GROUP_READONLY_MAX_COUNT] =
    {392u, 630u, 332u, 690u, 332u, 690u, 332u, 690u};
static const uint16_t
    g_servo_index_lateral_side_a[SERVO_GROUP_READONLY_MAX_COUNT] =
    {332u, 570u, 332u, 690u, 332u, 690u, 332u, 690u};
static const uint16_t
    g_servo_index_lateral_side_b[SERVO_GROUP_READONLY_MAX_COUNT] =
    {452u, 690u, 332u, 690u, 332u, 690u, 332u, 690u};
static rt_device_t g_servo_uart;
static struct rt_mutex g_snapshot_mutex;
static servo_group_readonly_t g_group;
static servo_group_readonly_sample_t
    g_published[SERVO_GROUP_READONLY_MAX_COUNT];
static size_t g_published_count;
static uint8_t g_ready;
static uint8_t g_rehab_demo_active;
/* Sign-demo mailbox/state is independent from the TRAIN rehabilitation
 * mailbox.  The servo thread remains the sole owner of motion writes. */
static volatile uint8_t g_sign_demo_pending_action;
static volatile uint32_t g_sign_demo_pending_sequence_id;
static volatile uint8_t g_sign_demo_active;
static volatile uint8_t g_sign_demo_cancel_requested;
static volatile uint8_t g_sign_demo_home_requested;
static servo_sign_state_t g_sign_demo_state;
static servo_sign_result_t g_sign_demo_result;
static uint32_t g_sign_demo_sequence_id;
static uint32_t g_sign_demo_completed_count;
static servo_sign_action_t g_sign_demo_last_action;
static volatile uint32_t g_servo_rx_bytes_total;
static volatile uint32_t g_servo_rx_trace_length;
static uint8_t g_servo_rx_trace[128];
static eight_servo_safety_gate_t g_eight_servo_gate;
static eight_servo_pose_bank_t g_eight_servo_pose_bank;
/*
 * Right-hand calibration verified on the assembled JuxiTech AmazingHand.
 * The soft bounds are the repeatedly observed official open/close targets,
 * not the SCS0009 electrical limits.  Visual motion remains disabled because
 * the production write path is not present yet.
 */
static const eight_servo_calibration_t
    g_eight_servo_calibration[EIGHT_SERVO_COUNT] = {
        {.id = 1u, .configured = 1u, .direction_sign = 1,
         .center_raw = 451u, .soft_min_raw = 332u, .soft_max_raw = 758u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 2u, .configured = 1u, .direction_sign = -1,
         .center_raw = 571u, .soft_min_raw = 264u, .soft_max_raw = 690u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 3u, .configured = 1u, .direction_sign = 1,
         .center_raw = 451u, .soft_min_raw = 332u, .soft_max_raw = 758u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 4u, .configured = 1u, .direction_sign = -1,
         .center_raw = 571u, .soft_min_raw = 264u, .soft_max_raw = 690u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 5u, .configured = 1u, .direction_sign = 1,
         .center_raw = 451u, .soft_min_raw = 332u, .soft_max_raw = 758u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 6u, .configured = 1u, .direction_sign = -1,
         .center_raw = 571u, .soft_min_raw = 264u, .soft_max_raw = 690u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 7u, .configured = 1u, .direction_sign = 1,
         .center_raw = 451u, .soft_min_raw = 332u, .soft_max_raw = 690u,
         .max_step_raw = 30u, .speed_limit_raw = 80u},
        {.id = 8u, .configured = 1u, .direction_sign = -1,
         .center_raw = 571u, .soft_min_raw = 332u, .soft_max_raw = 690u,
         .max_step_raw = 30u, .speed_limit_raw = 80u}};
/* Written only by an attached debugger after the operator is watching.
 * Keep the mailbox in the FSP linker script's MPU non-cacheable RAM region;
 * Cortex-M85 cached SRAM is not coherent with debug-port writes. */
volatile uint32_t g_servo_pair_commission_request
    __attribute__((section(".ram_nocache"), aligned(32)));
volatile uint32_t g_servo_pair_commission_result
    __attribute__((section(".ram_nocache"), aligned(32)));
volatile uint32_t g_rehab_demo_completed_count
    __attribute__((section(".ram_nocache"), aligned(32)));

static void run_one_cycle(void);

static int sign_motion_abort_requested(
    const volatile uint8_t *cancel_requested)
{
    return cancel_requested != RT_NULL &&
           (*cancel_requested != 0u ||
            g_eight_servo_gate.fault_latched != 0u);
}

static uint32_t servo_now_ms(void)
{
    return (uint32_t)(((uint64_t)rt_tick_get() * 1000ULL) /
                      (uint64_t)RT_TICK_PER_SECOND);
}

static void set_leds(uint8_t red, uint8_t green, uint8_t blue)
{
    rt_pin_write(SERVO_BUS_LED_RED, red ? SERVO_BUS_LED_ON : SERVO_BUS_LED_OFF);
    rt_pin_write(SERVO_BUS_LED_GREEN,
                 green ? SERVO_BUS_LED_ON : SERVO_BUS_LED_OFF);
    rt_pin_write(SERVO_BUS_LED_BLUE,
                 blue ? SERVO_BUS_LED_ON : SERVO_BUS_LED_OFF);
}

static rt_err_t servo_uart_rx_indicate(rt_device_t device, rt_size_t size)
{
    (void)device;
    g_servo_rx_bytes_total += (uint32_t)size;
    return RT_EOK;
}

static void publish_cycle(void)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    int valid = servo_group_readonly_snapshot(
        &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count);

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    if (valid)
    {
        rt_memcpy(g_published, samples, count * sizeof(samples[0]));
        g_published_count = count;
        g_ready = 1u;
    }
    else
    {
        g_published_count = 0u;
        g_ready = 0u;
    }
    rt_mutex_release(&g_snapshot_mutex);
    set_leds(valid ? 0u : 1u, valid ? 1u : 0u, 0u);
}

static void drain_servo_uart(void)
{
    uint8_t byte;
    size_t drained = 0u;
    while (drained < SERVO_BUS_DRAIN_MAX_BYTES &&
           rt_device_read(g_servo_uart, 0, &byte, 1u) == 1u)
    {
        /* Discard local bridge echo and write-status traffic. */
        drained++;
    }
}

static int write_packet_no_reply(const uint8_t *packet, size_t length)
{
    uint32_t deadline;
    if (packet == RT_NULL || length == 0u ||
        R_SCI_B_UART_Write((uart_ctrl_t *)&g_uart1_ctrl,
                           packet,
                           (uint32_t)length) != FSP_SUCCESS)
    {
        return 0;
    }
    deadline = servo_now_ms() + 20u;
    while (g_uart1_ctrl.tx_src_bytes != 0u ||
           g_uart1_ctrl.p_reg->CSR_b.TEND == 0u)
    {
        if ((int32_t)(servo_now_ms() - deadline) >= 0)
        {
            return 0;
        }
        rt_thread_yield();
    }
    rt_thread_mdelay(3u);
    drain_servo_uart();
    return 1;
}

static int send_pair_positions(uint8_t odd_id,
                               uint16_t odd_position,
                               uint8_t even_id,
                               uint16_t even_position)
{
    uint8_t packet[13];
    uint8_t action[6];
    size_t length = scs0009_build_reg_write_position(
        odd_id, odd_position, 0u, SERVO_PAIR_COMMISSION_SPEED,
        packet, sizeof(packet));
    if (!write_packet_no_reply(packet, length))
    {
        return 0;
    }
    length = scs0009_build_reg_write_position(
        even_id, even_position, 0u, SERVO_PAIR_COMMISSION_SPEED,
        packet, sizeof(packet));
    if (!write_packet_no_reply(packet, length))
    {
        return 0;
    }
    length = scs0009_build_action(action, sizeof(action));
    return write_packet_no_reply(action, length);
}

static int send_group_positions(const uint16_t *positions)
{
    scs0009_sync_goal_t goals[SERVO_GROUP_READONLY_MAX_COUNT];
    uint8_t packet[SCS0009_SYNC_WRITE_POSITION_MAX_PACKET_SIZE];
    size_t index;
    size_t length;
    if (positions == RT_NULL)
    {
        return 0;
    }
    for (index = 0u; index < SERVO_GROUP_READONLY_MAX_COUNT; ++index)
    {
        goals[index].id = g_servo_ids[index];
        goals[index].position = positions[index];
        goals[index].time_raw = 0u;
        goals[index].speed_raw = SERVO_PAIR_COMMISSION_SPEED;
    }
    length = scs0009_build_sync_write_position_group(
        goals, SERVO_GROUP_READONLY_MAX_COUNT, packet, sizeof(packet));
    return write_packet_no_reply(packet, length);
}

static int send_torque(uint8_t id, uint8_t enable)
{
    uint8_t packet[8];
    size_t length = scs0009_build_torque(id, enable, packet, sizeof(packet));
    return write_packet_no_reply(packet, length);
}

static int pair_positions_match(uint8_t pair_index,
                                uint16_t expected_odd,
                                uint16_t expected_even)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    size_t odd_index = (size_t)pair_index * 2u;
    size_t even_index = odd_index + 1u;
    int32_t odd_delta;
    int32_t even_delta;
    if (!servo_group_readonly_snapshot(
            &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count) ||
        count != SERVO_GROUP_READONLY_MAX_COUNT ||
        samples[odd_index].id != (uint8_t)(odd_index + 1u) ||
        samples[even_index].id != (uint8_t)(even_index + 1u))
    {
        return 0;
    }
    odd_delta = (int32_t)samples[odd_index].position_raw -
                (int32_t)expected_odd;
    even_delta = (int32_t)samples[even_index].position_raw -
                 (int32_t)expected_even;
    if (odd_delta < 0) odd_delta = -odd_delta;
    if (even_delta < 0) even_delta = -even_delta;
    return odd_delta <= SERVO_PAIR_COMMISSION_TOLERANCE &&
           even_delta <= SERVO_PAIR_COMMISSION_TOLERANCE;
}

static int wait_pair_positions(uint8_t pair_index,
                               uint16_t expected_odd,
                               uint16_t expected_even)
{
    uint32_t deadline = servo_now_ms() + SERVO_PAIR_COMMISSION_TIMEOUT_MS;
    do
    {
        run_one_cycle();
        if (pair_positions_match(pair_index, expected_odd, expected_even))
        {
            return 1;
        }
        rt_thread_mdelay(100u);
    } while ((int32_t)(servo_now_ms() - deadline) < 0);
    return 0;
}

static int group_positions_match(const uint16_t *expected)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    size_t index;
    if (expected == RT_NULL || !servo_group_readonly_snapshot(
            &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count) ||
        count != SERVO_GROUP_READONLY_MAX_COUNT)
    {
        return 0;
    }
    for (index = 0u; index < count; ++index)
    {
        int32_t delta;
        if (!samples[index].read_ok || samples[index].id != g_servo_ids[index] ||
            samples[index].voltage_raw < 45u ||
            samples[index].voltage_raw > 60u ||
            samples[index].temperature_raw >= 45u)
        {
            return 0;
        }
        delta = (int32_t)samples[index].position_raw -
                (int32_t)expected[index];
        if (delta < 0) delta = -delta;
        if (delta > SERVO_GROUP_POSITION_TOLERANCE)
        {
            return 0;
        }
    }
    return 1;
}

static int wait_group_positions_ex(
    const uint16_t *expected,
    const volatile uint8_t *cancel_requested)
{
    uint32_t deadline = servo_now_ms() + SERVO_PAIR_COMMISSION_TIMEOUT_MS;
    do
    {
        if (sign_motion_abort_requested(cancel_requested))
        {
            return 0;
        }
        run_one_cycle();
        if (group_positions_match(expected))
        {
            return 1;
        }
        if (sign_motion_abort_requested(cancel_requested))
        {
            return 0;
        }
        rt_thread_mdelay(100u);
    } while ((int32_t)(servo_now_ms() - deadline) < 0);
    return 0;
}

static int wait_group_positions(const uint16_t *expected)
{
    return wait_group_positions_ex(expected, RT_NULL);
}

static int run_pair_commission(uint8_t pair_index)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    size_t odd_index = (size_t)pair_index * 2u;
    size_t even_index = odd_index + 1u;
    uint8_t odd_id = (uint8_t)(odd_index + 1u);
    uint8_t even_id = (uint8_t)(even_index + 1u);
    uint16_t start_odd;
    uint16_t start_even;
    uint16_t test_odd;
    uint16_t test_even;
    int torque_odd = 0;
    int torque_even = 0;
    int passed = 0;

    if (pair_index >= 4u || !servo_group_readonly_snapshot(
            &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count) ||
        count != SERVO_GROUP_READONLY_MAX_COUNT ||
        samples[odd_index].id != odd_id || samples[even_index].id != even_id ||
        !samples[odd_index].read_ok || !samples[even_index].read_ok ||
        samples[odd_index].voltage_raw < 45u ||
        samples[odd_index].voltage_raw > 60u ||
        samples[even_index].voltage_raw < 45u ||
        samples[even_index].voltage_raw > 60u ||
        samples[odd_index].temperature_raw >= 45u ||
        samples[even_index].temperature_raw >= 45u)
    {
        return 0;
    }
    start_odd = samples[odd_index].position_raw;
    start_even = samples[even_index].position_raw;
    /* The finished right hand arrived near +300/-300 from its documented
     * 451/571 centres.  Commission only toward centre, never farther closed. */
    if (start_odd <= SERVO_PAIR_CENTER_ODD + SERVO_PAIR_COMMISSION_STEP ||
        start_even + SERVO_PAIR_COMMISSION_STEP >= SERVO_PAIR_CENTER_EVEN)
    {
        return 0;
    }
    test_odd = (uint16_t)(start_odd - SERVO_PAIR_COMMISSION_STEP);
    test_even = (uint16_t)(start_even + SERVO_PAIR_COMMISSION_STEP);

    drain_servo_uart();
    if (!send_pair_positions(odd_id, start_odd, even_id, start_even) ||
        !send_torque(odd_id, 1u))
    {
        goto release;
    }
    torque_odd = 1;
    if (!send_torque(even_id, 1u))
    {
        goto release;
    }
    torque_even = 1;
    if (!send_pair_positions(odd_id, test_odd, even_id, test_even) ||
        !wait_pair_positions(pair_index, test_odd, test_even))
    {
        goto release;
    }
    rt_thread_mdelay(SERVO_PAIR_COMMISSION_HOLD_MS);
    if (!send_pair_positions(odd_id, start_odd, even_id, start_even))
    {
        goto release;
    }
    passed = wait_pair_positions(pair_index, start_odd, start_even);

release:
    if (torque_even) (void)send_torque(even_id, 0u);
    if (torque_odd) (void)send_torque(odd_id, 0u);
    drain_servo_uart();
    return passed;
}

static int run_group_commission(void)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    uint16_t start[SERVO_GROUP_READONLY_MAX_COUNT];
    uint16_t test[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    size_t index;
    int passed = 0;

    if (!servo_group_readonly_snapshot(
            &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count) ||
        count != SERVO_GROUP_READONLY_MAX_COUNT)
    {
        return 0;
    }
    for (index = 0u; index < count; ++index)
    {
        if (!samples[index].read_ok || samples[index].id != g_servo_ids[index] ||
            samples[index].voltage_raw < 45u ||
            samples[index].voltage_raw > 60u ||
            samples[index].temperature_raw >= 45u)
        {
            return 0;
        }
        start[index] = samples[index].position_raw;
        if ((index & 1u) == 0u)
        {
            if (start[index] <=
                SERVO_PAIR_CENTER_ODD + SERVO_GROUP_COMMISSION_STEP)
            {
                return 0;
            }
            test[index] = (uint16_t)(start[index] -
                                     SERVO_GROUP_COMMISSION_STEP);
        }
        else
        {
            if (start[index] + SERVO_GROUP_COMMISSION_STEP >=
                SERVO_PAIR_CENTER_EVEN)
            {
                return 0;
            }
            test[index] = (uint16_t)(start[index] +
                                     SERVO_GROUP_COMMISSION_STEP);
        }
    }

    drain_servo_uart();
    if (!send_group_positions(start))
    {
        goto release;
    }
    for (index = 0u; index < count; ++index)
    {
        if (!send_torque(g_servo_ids[index], 1u))
        {
            goto release;
        }
    }
    if (!send_group_positions(test) || !wait_group_positions(test))
    {
        goto release;
    }
    rt_thread_mdelay(SERVO_GROUP_COMMISSION_HOLD_MS);
    if (!send_group_positions(start))
    {
        goto release;
    }
    passed = wait_group_positions(start);

release:
    for (index = count; index > 0u; --index)
    {
        (void)send_torque(g_servo_ids[index - 1u], 0u);
    }
    drain_servo_uart();
    return passed;
}

static int run_group_target_commission_ex(
    const uint16_t *target,
    const volatile uint8_t *cancel_requested)
{
    servo_group_readonly_sample_t samples[SERVO_GROUP_READONLY_MAX_COUNT];
    uint16_t current[SERVO_GROUP_READONLY_MAX_COUNT];
    uint16_t next[SERVO_GROUP_READONLY_MAX_COUNT];
    size_t count = 0u;
    size_t index;
    int at_target = 0;
    int passed = 0;

    if ((target != g_servo_official_open &&
         target != g_servo_official_close &&
         target != g_servo_v_sign &&
         target != g_servo_point &&
         target != g_servo_thumbs_up &&
         target != g_servo_l_shape &&
         target != g_servo_ok_pinch &&
         target != g_servo_thanks_thumb_bend &&
         target != g_servo_help_thumb_tucked &&
         target != g_servo_no_side_a &&
         target != g_servo_no_side_b &&
         target != g_servo_attention_bend &&
         target != g_servo_index_lateral_center &&
         target != g_servo_index_lateral_side_a &&
         target != g_servo_index_lateral_side_b) ||
        sign_motion_abort_requested(cancel_requested) ||
        !servo_group_readonly_snapshot(
            &g_group, samples, SERVO_GROUP_READONLY_MAX_COUNT, &count) ||
        count != SERVO_GROUP_READONLY_MAX_COUNT)
    {
        return 0;
    }
    for (index = 0u; index < count; ++index)
    {
        if (!samples[index].read_ok || samples[index].id != g_servo_ids[index] ||
            samples[index].voltage_raw < 45u ||
            samples[index].voltage_raw > 60u ||
            samples[index].temperature_raw >= 45u)
        {
            return 0;
        }
        {
            uint16_t soft_min = g_servo_official_open[index] <
                                g_servo_official_close[index] ?
                                g_servo_official_open[index] :
                                g_servo_official_close[index];
            uint16_t soft_max = g_servo_official_open[index] >
                                g_servo_official_close[index] ?
                                g_servo_official_open[index] :
                                g_servo_official_close[index];
            int32_t position = (int32_t)samples[index].position_raw;
            if (position < (int32_t)soft_min -
                           SERVO_GROUP_POSITION_TOLERANCE ||
                position > (int32_t)soft_max +
                           SERVO_GROUP_POSITION_TOLERANCE)
            {
                return 0;
            }
        }
        if (target[index] < g_eight_servo_calibration[index].soft_min_raw ||
            target[index] > g_eight_servo_calibration[index].soft_max_raw)
        {
            return 0;
        }
        current[index] = samples[index].position_raw;
    }

    drain_servo_uart();
    if (!send_group_positions(current))
    {
        goto release;
    }
    for (index = 0u; index < count; ++index)
    {
        if (!send_torque(g_servo_ids[index], 1u))
        {
            goto release;
        }
    }

    while (!at_target)
    {
        if (sign_motion_abort_requested(cancel_requested))
        {
            goto release;
        }
        at_target = 1;
        for (index = 0u; index < count; ++index)
        {
            uint16_t target_raw = target[index];
            next[index] = current[index];
            if (current[index] > target_raw)
            {
                uint16_t delta = (uint16_t)(current[index] - target_raw);
                next[index] = (uint16_t)(current[index] -
                    (delta > SERVO_GROUP_MOTION_STEP ?
                     SERVO_GROUP_MOTION_STEP : delta));
                at_target = 0;
            }
            else if (current[index] < target_raw)
            {
                uint16_t delta = (uint16_t)(target_raw - current[index]);
                next[index] = (uint16_t)(current[index] +
                    (delta > SERVO_GROUP_MOTION_STEP ?
                     SERVO_GROUP_MOTION_STEP : delta));
                at_target = 0;
            }
        }
        if (at_target)
        {
            break;
        }
        if (!send_group_positions(next) ||
            !wait_group_positions_ex(next, cancel_requested))
        {
            goto release;
        }
        rt_memcpy(current, next, sizeof(current));
        if (sign_motion_abort_requested(cancel_requested))
        {
            goto release;
        }
        rt_thread_mdelay(SERVO_GROUP_MOTION_SETTLE_MS);
    }
    passed = 1;

release:
    for (index = count; index > 0u; --index)
    {
        (void)send_torque(g_servo_ids[index - 1u], 0u);
    }
    drain_servo_uart();
    return passed;
}

static int run_group_target_commission(const uint16_t *target)
{
    return run_group_target_commission_ex(target, RT_NULL);
}

/* Result: 1=complete, 2=sweep failed but open recovery succeeded,
 * 3=sweep and open recovery both failed.  This path is intentionally
 * debugger-mailbox-only until the physical direction is observed. */
static uint32_t run_index_lateral_test_once(void)
{
    const uint16_t *steps[] = {
        g_servo_official_open,
        g_servo_index_lateral_center,
        g_servo_index_lateral_side_a,
        g_servo_index_lateral_center,
        g_servo_index_lateral_side_b,
        g_servo_index_lateral_center,
        g_servo_official_open,
    };
    size_t index;

    for (index = 0u; index < sizeof(steps) / sizeof(steps[0]); ++index)
    {
        if (!run_group_target_commission(steps[index]))
        {
            return run_group_target_commission(g_servo_official_open) ?
                2u : 3u;
        }
        if (index == 2u || index == 4u)
        {
            rt_thread_mdelay(700u);
        }
        else if (index != sizeof(steps) / sizeof(steps[0]) - 1u)
        {
            rt_thread_mdelay(250u);
        }
    }
    return 1u;
}

static int decode_pair_commission_request(uint32_t request,
                                          uint8_t *pair_index)
{
    if (pair_index == RT_NULL || request < SERVO_PAIR_COMMISSION_MAGIC_FIRST ||
        request > SERVO_PAIR_COMMISSION_MAGIC_LAST)
    {
        return 0;
    }
    *pair_index = (uint8_t)(request - SERVO_PAIR_COMMISSION_MAGIC_FIRST);
    return 1;
}

/*
 * One explicitly requested rehabilitation demonstration repetition.
 * Result: 1=complete, 2=close failed but open recovery succeeded,
 * 3=final open failed, 4=close and open recovery both failed.
 * Every underlying target operation releases torque on every exit path.
 */
static uint32_t run_rehab_demo_once(void)
{
    if (!run_group_target_commission(g_servo_official_close))
    {
        return run_group_target_commission(g_servo_official_open) ? 2u : 4u;
    }

    rt_thread_mdelay(SERVO_REHAB_DEMO_HOLD_MS);
    if (!run_group_target_commission(g_servo_official_open))
    {
        return 3u;
    }

    return 1u;
}

/*
 * Every sign sequence uses only per-servo endpoints already admitted by the
 * open/close safety envelope.  No UART request carries raw positions.  A
 * cancel flag is sampled before/after every bounded target step; recovery
 * always returns to official_open before reporting a terminal state.
 */
static uint32_t sign_cancel_or_failure_result(void)
{
    volatile uint8_t no_cancel = 0u;

    if (g_sign_demo_cancel_requested)
    {
        if (run_group_target_commission_ex(g_servo_official_open, &no_cancel))
        {
            return g_sign_demo_home_requested ?
                SERVO_SIGN_RESULT_SUCCEEDED : SERVO_SIGN_RESULT_CANCELLED;
        }
        return g_sign_demo_home_requested ?
            SERVO_SIGN_RESULT_HOME_FAILED :
            SERVO_SIGN_RESULT_CANCEL_RECOVERY_FAILED;
    }
    (void)run_group_target_commission_ex(g_servo_official_open, &no_cancel);
    return SERVO_SIGN_RESULT_MOTION_FAILED;
}

static uint8_t hold_sign_duration(uint32_t duration_ms)
{
    uint32_t elapsed_ms = 0u;

    while (elapsed_ms < duration_ms)
    {
        uint32_t slice_ms = duration_ms - elapsed_ms;
        if (sign_motion_abort_requested(&g_sign_demo_cancel_requested))
        {
            return 0u;
        }
        if (slice_ms > 50u)
        {
            slice_ms = 50u;
        }
        rt_thread_mdelay(slice_ms);
        elapsed_ms += slice_ms;
    }
    return sign_motion_abort_requested(&g_sign_demo_cancel_requested) ? 0u : 1u;
}

static uint32_t run_sign_demo_once(uint32_t sequence_id)
{
    const uint16_t *prepare_target = g_servo_official_open;
    const uint16_t *demo_target;
    uint32_t hold_elapsed = 0u;

    if (sequence_id == SERVO_SIGN_SEQUENCE_HELLO_WORD)
    {
        if (!run_group_target_commission_ex(
                g_servo_official_open, &g_sign_demo_cancel_requested) ||
            !run_group_target_commission_ex(
                g_servo_point, &g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        if (!hold_sign_duration(400u) ||
            !run_group_target_commission_ex(
                g_servo_thumbs_up, &g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        if (!hold_sign_duration(600u) ||
            !run_group_target_commission_ex(
                g_servo_official_open, &g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_THANKS_WORD)
    {
        const uint16_t *thanks_targets[5] = {
            g_servo_thumbs_up,
            g_servo_thanks_thumb_bend,
            g_servo_thumbs_up,
            g_servo_thanks_thumb_bend,
            g_servo_thumbs_up,
        };
        uint32_t index;

        for (index = 0u; index < 5u; ++index)
        {
            if (!run_group_target_commission_ex(
                    thanks_targets[index], &g_sign_demo_cancel_requested))
            {
                return sign_cancel_or_failure_result();
            }
            if (!hold_sign_duration(index == 4u ? 500u : 220u))
            {
                return sign_cancel_or_failure_result();
            }
        }
        if (!run_group_target_commission_ex(
                g_servo_official_open, &g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_HELP_SIGNAL)
    {
        const uint16_t *help_targets[3] = {
            g_servo_official_open,
            g_servo_help_thumb_tucked,
            g_servo_official_close,
        };
        const uint32_t help_holds[3] = {300u, 350u, 600u};
        uint32_t index;

        for (index = 0u; index < 3u; ++index)
        {
            if (!run_group_target_commission_ex(
                    help_targets[index], &g_sign_demo_cancel_requested))
            {
                return sign_cancel_or_failure_result();
            }
            if (!hold_sign_duration(help_holds[index]))
            {
                return sign_cancel_or_failure_result();
            }
        }
        if (!run_group_target_commission_ex(
                g_servo_official_open, &g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_NO_WORD)
    {
        const uint16_t *no_targets[7] = {
            g_servo_point,
            g_servo_no_side_a,
            g_servo_no_side_b,
            g_servo_no_side_a,
            g_servo_no_side_b,
            g_servo_point,
            g_servo_official_open,
        };
        const uint32_t no_holds[7] = {250u, 180u, 180u, 180u, 180u, 350u, 0u};
        uint32_t index;

        for (index = 0u; index < 7u; ++index)
        {
            if (!run_group_target_commission_ex(
                    no_targets[index], &g_sign_demo_cancel_requested) ||
                !hold_sign_duration(no_holds[index]))
            {
                return sign_cancel_or_failure_result();
            }
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_ATTENTION_WORD)
    {
        const uint16_t *attention_targets[6] = {
            g_servo_point,
            g_servo_attention_bend,
            g_servo_point,
            g_servo_attention_bend,
            g_servo_point,
            g_servo_official_open,
        };
        const uint32_t attention_holds[6] = {
            300u, 180u, 180u, 180u, 400u, 0u,
        };
        uint32_t index;

        for (index = 0u; index < 6u; ++index)
        {
            if (!run_group_target_commission_ex(
                    attention_targets[index], &g_sign_demo_cancel_requested) ||
                !hold_sign_duration(attention_holds[index]))
            {
                return sign_cancel_or_failure_result();
            }
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_LIKE_WORD)
    {
        const uint16_t *like_targets[3] = {
            g_servo_l_shape,
            g_servo_ok_pinch,
            g_servo_official_open,
        };
        const uint32_t like_holds[3] = {300u, 650u, 0u};
        uint32_t index;

        for (index = 0u; index < 3u; ++index)
        {
            if (!run_group_target_commission_ex(
                    like_targets[index], &g_sign_demo_cancel_requested) ||
                !hold_sign_duration(like_holds[index]))
            {
                return sign_cancel_or_failure_result();
            }
        }
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }

    if (sequence_id == SERVO_SIGN_SEQUENCE_OPEN_PALM)
    {
        /* Close first so an already-open hand still gives a visible opening
         * demonstration; the presented/held pose itself is open. */
        prepare_target = g_servo_official_close;
        demo_target = g_servo_official_open;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_FIST)
    {
        demo_target = g_servo_official_close;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_V_SIGN)
    {
        demo_target = g_servo_v_sign;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_POINT)
    {
        demo_target = g_servo_point;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_THUMBS_UP)
    {
        demo_target = g_servo_thumbs_up;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_L_SHAPE)
    {
        demo_target = g_servo_l_shape;
    }
    else if (sequence_id == SERVO_SIGN_SEQUENCE_OK_PINCH)
    {
        demo_target = g_servo_ok_pinch;
    }
    else
    {
        return SERVO_SIGN_RESULT_MOTION_FAILED;
    }

    if (!run_group_target_commission_ex(
            prepare_target, &g_sign_demo_cancel_requested))
    {
        return sign_cancel_or_failure_result();
    }

    if (!run_group_target_commission_ex(
            demo_target, &g_sign_demo_cancel_requested))
    {
        return sign_cancel_or_failure_result();
    }

    while (hold_elapsed < SERVO_SIGN_DEMO_HOLD_MS)
    {
        if (sign_motion_abort_requested(&g_sign_demo_cancel_requested))
        {
            return sign_cancel_or_failure_result();
        }
        rt_thread_mdelay(50u);
        hold_elapsed += 50u;
    }

    if (demo_target != g_servo_official_open &&
        !run_group_target_commission_ex(
            g_servo_official_open, &g_sign_demo_cancel_requested))
    {
        return sign_cancel_or_failure_result();
    }
    return SERVO_SIGN_RESULT_SUCCEEDED;
}

static uint32_t run_sign_home_once(void)
{
    volatile uint8_t no_cancel = 0u;

    if (run_group_target_commission_ex(
            g_servo_official_open, &g_sign_demo_cancel_requested))
    {
        return SERVO_SIGN_RESULT_SUCCEEDED;
    }
    if (g_sign_demo_cancel_requested)
    {
        /* Cancellation may be raised by an operator or by link loss.  The
         * recovery target is still official_open, but this bounded attempt
         * must not inherit the cancellation flag. */
        return run_group_target_commission_ex(
                   g_servo_official_open, &no_cancel) ?
            SERVO_SIGN_RESULT_CANCELLED :
            SERVO_SIGN_RESULT_CANCEL_RECOVERY_FAILED;
    }
    return SERVO_SIGN_RESULT_HOME_FAILED;
}

static void process_sign_demo_request(void)
{
    uint8_t action;
    uint32_t sequence_id;
    uint32_t result;

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    action = g_sign_demo_pending_action;
    sequence_id = g_sign_demo_pending_sequence_id;
    if (action == 0u)
    {
        rt_mutex_release(&g_snapshot_mutex);
        return;
    }
    g_sign_demo_pending_action = 0u;
    g_sign_demo_pending_sequence_id = 0u;
    g_sign_demo_active = 1u;
    g_sign_demo_cancel_requested = 0u;
    g_sign_demo_home_requested = 0u;
    g_sign_demo_sequence_id = sequence_id;
    g_sign_demo_last_action = (servo_sign_action_t)action;
    g_sign_demo_result = SERVO_SIGN_RESULT_NONE;
    g_sign_demo_state = action == SERVO_SIGN_ACTION_HOME ?
        SERVO_SIGN_STATE_HOMING : SERVO_SIGN_STATE_RUNNING;
    rt_mutex_release(&g_snapshot_mutex);

    if (action == SERVO_SIGN_ACTION_HOME)
    {
        result = run_sign_home_once();
    }
    else
    {
        result = run_sign_demo_once(sequence_id);
    }

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    g_sign_demo_active = 0u;
    g_sign_demo_result = (servo_sign_result_t)result;
    if (result == SERVO_SIGN_RESULT_SUCCEEDED)
    {
        g_sign_demo_state = SERVO_SIGN_STATE_COMPLETED;
        ++g_sign_demo_completed_count;
    }
    else if (result == SERVO_SIGN_RESULT_CANCELLED)
    {
        g_sign_demo_state = SERVO_SIGN_STATE_CANCELLED;
    }
    else
    {
        g_sign_demo_state = SERVO_SIGN_STATE_FAILED;
    }
    g_sign_demo_cancel_requested = 0u;
    g_sign_demo_home_requested = 0u;
    rt_mutex_release(&g_snapshot_mutex);
}

static void run_one_cycle(void)
{
    uint8_t request[8];
    uint8_t byte;

    if (!servo_group_readonly_begin_cycle(&g_group))
    {
        set_leds(1u, 0u, 0u);
        return;
    }
    set_leds(0u, 0u, 1u);

    while (g_group.cycle_active)
    {
        size_t request_length = servo_group_readonly_prepare(
            &g_group, servo_now_ms(), request, sizeof(request));
        if (request_length == 0u)
        {
            /*
             * prepare() returns 0 only when the group cannot advance at all
             * (cycle not active, transaction not idle, or the request could
             * not be built). Returning here used to leave cycle_active set,
             * and begin_cycle() refuses to start while it is set, so a single
             * such failure silenced the servo bus until reboot.
             */
            servo_group_readonly_abort_cycle(&g_group);
            set_leds(1u, 0u, 0u);
            return;
        }
        if (R_SCI_B_UART_Write((uart_ctrl_t *)&g_uart1_ctrl,
                               request,
                               (uint32_t)request_length) != FSP_SUCCESS)
        {
            servo_group_readonly_note_tx_failed(&g_group);
            continue;
        }
        {
            uint32_t tx_deadline = servo_now_ms() + SERVO_BUS_TX_TIMEOUT_MS;
            while (g_uart1_ctrl.tx_src_bytes != 0u ||
                   g_uart1_ctrl.p_reg->CSR_b.TEND == 0u)
            {
                if ((int32_t)(servo_now_ms() - tx_deadline) >= 0)
                {
                    /*
                     * The transmit never completed within the deadline, which
                     * means the bus is not draining. End the cycle outright:
                     * note_tx_failed() would only advance to the next servo
                     * and burn another full timeout on each of the remaining
                     * ones, and this path sits inside the inner wait loop, so
                     * it cannot simply continue the outer cycle loop.
                     *
                     * Aborting clears cycle_active, so the next cycle starts
                     * cleanly instead of the group wedging until reboot.
                     */
                    servo_group_readonly_abort_cycle(&g_group);
                    set_leds(1u, 0u, 0u);
                    drain_servo_uart();
                    return;
                }
                rt_thread_yield();
            }
        }

        /*
         * The JuxiTech USB/TTL hand interface mirrors the controller's
         * request back onto RX before forwarding the servo status packet.
         * A request is packet-shaped, so feeding that echo to the status
         * parser makes instruction 0x02 look like a servo error.  Suppress
         * only an exact copy of the request.  If the incoming bytes diverge
         * (for example, a real status packet), replay the common prefix into
         * the parser and continue normally.
         */
        size_t echo_matched = 0u;
        uint8_t echo_candidate = 1u;

        while (g_group.transaction.state == SCS0009_TXN_WAIT_STATUS)
        {
            size_t rx_burst = 0u;
            while (rx_burst < SERVO_BUS_RX_BURST_MAX_BYTES &&
                   rt_device_read(g_servo_uart, 0, &byte, 1u) == 1u)
            {
                rx_burst++;
                if (g_servo_rx_trace_length < sizeof(g_servo_rx_trace))
                {
                    g_servo_rx_trace[g_servo_rx_trace_length++] = byte;
                }
                if (echo_candidate)
                {
                    if (byte == request[echo_matched])
                    {
                        echo_matched++;
                        if (echo_matched == request_length)
                        {
                            echo_candidate = 0u;
                            echo_matched = 0u;
                        }
                        continue;
                    }
                    {
                        size_t replay_index;
                        for (replay_index = 0u;
                             replay_index < echo_matched;
                             ++replay_index)
                        {
                            servo_group_readonly_feed(
                                &g_group, request[replay_index]);
                        }
                        echo_matched = 0u;
                    }
                    echo_candidate = 0u;
                }
                servo_group_readonly_feed(&g_group, byte);
            }
            servo_group_readonly_tick(&g_group, servo_now_ms());
            if (g_group.transaction.state == SCS0009_TXN_WAIT_STATUS)
            {
                /*
                 * Poll at a bounded cadence. A timed semaphore take races
                 * with the UART ISR release path in this RT-Thread build and
                 * can trip _thread_timeout's suspended-thread assertion.
                 */
                rt_thread_mdelay(1u);
            }
        }
    }
    publish_cycle();
}

static void servo_bus_thread_entry(void *parameter)
{
    (void)parameter;
    while (1)
    {
        uint8_t pair_index;
        uint32_t request = g_servo_pair_commission_request;
        if (g_sign_demo_pending_action != 0u)
        {
            process_sign_demo_request();
        }
        else if (request == SERVO_REHAB_DEMO_MAGIC)
        {
            uint32_t result;
            rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
            g_rehab_demo_active = 1u;
            g_servo_pair_commission_request = 0u;
            rt_mutex_release(&g_snapshot_mutex);
            result = run_rehab_demo_once();
            rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
            g_servo_pair_commission_result = result;
            if (result == 1u)
            {
                ++g_rehab_demo_completed_count;
            }
            g_rehab_demo_active = 0u;
            rt_mutex_release(&g_snapshot_mutex);
        }
        else if (request == SERVO_INDEX_LATERAL_MAGIC)
        {
            g_servo_pair_commission_request = 0u;
            g_servo_pair_commission_result = run_index_lateral_test_once();
        }
        else if (request == SERVO_GROUP_CLOSE_MAGIC)
        {
            g_servo_pair_commission_request = 0u;
            g_servo_pair_commission_result = run_group_target_commission(
                g_servo_official_close) ? 1u : 2u;
        }
        else if (request == SERVO_GROUP_OPEN_MAGIC)
        {
            g_servo_pair_commission_request = 0u;
            g_servo_pair_commission_result = run_group_target_commission(
                g_servo_official_open) ? 1u : 2u;
        }
        else if (request == SERVO_GROUP_COMMISSION_MAGIC)
        {
            g_servo_pair_commission_request = 0u;
            g_servo_pair_commission_result =
                run_group_commission() ? 1u : 2u;
        }
        else if (decode_pair_commission_request(request, &pair_index))
        {
            g_servo_pair_commission_request = 0u;
            g_servo_pair_commission_result =
                run_pair_commission(pair_index) ? 1u : 2u;
        }
        run_one_cycle();
        rt_thread_mdelay(SERVO_BUS_CYCLE_PERIOD_MS);
    }
}

int servo_bus_readonly_is_ready(void)
{
    int ready;
    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    ready = g_ready ? 1 : 0;
    rt_mutex_release(&g_snapshot_mutex);
    return ready;
}

int servo_bus_safety_gate_present(void)
{
    return g_eight_servo_gate.initialized ? 1 : 0;
}

int servo_bus_safety_gate_armed(void)
{
    return g_eight_servo_gate.armed ? 1 : 0;
}

int servo_bus_safety_gate_fault_latched(void)
{
    return g_eight_servo_gate.fault_latched ? 1 : 0;
}

servo_sign_request_result_t servo_bus_sign_demo_request(
    servo_sign_action_t action,
    uint32_t sequence_id)
{
    servo_sign_request_result_t result = SERVO_SIGN_REQUEST_ACCEPTED;

    if ((action != SERVO_SIGN_ACTION_START &&
         action != SERVO_SIGN_ACTION_CANCEL &&
         action != SERVO_SIGN_ACTION_HOME) ||
        (sequence_id != SERVO_SIGN_SEQUENCE_OPEN_PALM &&
         sequence_id != SERVO_SIGN_SEQUENCE_FIST &&
         sequence_id != SERVO_SIGN_SEQUENCE_V_SIGN &&
         sequence_id != SERVO_SIGN_SEQUENCE_POINT &&
         sequence_id != SERVO_SIGN_SEQUENCE_THUMBS_UP &&
         sequence_id != SERVO_SIGN_SEQUENCE_L_SHAPE &&
         sequence_id != SERVO_SIGN_SEQUENCE_OK_PINCH &&
         sequence_id != SERVO_SIGN_SEQUENCE_HELLO_WORD &&
         sequence_id != SERVO_SIGN_SEQUENCE_THANKS_WORD &&
         sequence_id != SERVO_SIGN_SEQUENCE_HELP_SIGNAL &&
         sequence_id != SERVO_SIGN_SEQUENCE_NO_WORD &&
         sequence_id != SERVO_SIGN_SEQUENCE_ATTENTION_WORD &&
         sequence_id != SERVO_SIGN_SEQUENCE_LIKE_WORD))
    {
        return SERVO_SIGN_REQUEST_UNSUPPORTED;
    }

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    if (action == SERVO_SIGN_ACTION_CANCEL)
    {
        /* CANCEL is intentionally idempotent.  It never starts motion. */
        if (g_sign_demo_active)
        {
            g_sign_demo_cancel_requested = 1u;
            g_sign_demo_last_action = SERVO_SIGN_ACTION_CANCEL;
            g_sign_demo_sequence_id = sequence_id;
            g_sign_demo_state = SERVO_SIGN_STATE_CANCELLING;
        }
        else if (g_sign_demo_pending_action != 0u)
        {
            g_sign_demo_pending_action = 0u;
            g_sign_demo_pending_sequence_id = 0u;
            g_sign_demo_sequence_id = sequence_id;
            g_sign_demo_last_action = SERVO_SIGN_ACTION_CANCEL;
            g_sign_demo_result = SERVO_SIGN_RESULT_CANCELLED;
            g_sign_demo_state = SERVO_SIGN_STATE_CANCELLED;
        }
        rt_mutex_release(&g_snapshot_mutex);
        return result;
    }

    if (action == SERVO_SIGN_ACTION_HOME && g_sign_demo_active)
    {
        /* A HOME request while START is moving becomes a bounded cancel plus
         * official_open recovery.  A HOME request while HOME is moving is a
        * normal idempotent cancel of that home operation. */
        g_sign_demo_cancel_requested = 1u;
        g_sign_demo_home_requested = 1u;
        g_sign_demo_last_action = SERVO_SIGN_ACTION_HOME;
        g_sign_demo_sequence_id = sequence_id;
        g_sign_demo_state = SERVO_SIGN_STATE_CANCELLING;
        rt_mutex_release(&g_snapshot_mutex);
        return result;
    }

    if (!g_ready || !g_eight_servo_gate.initialized)
    {
        result = SERVO_SIGN_REQUEST_NOT_READY;
    }
    else if (g_eight_servo_gate.fault_latched)
    {
        result = SERVO_SIGN_REQUEST_FAULT;
    }
    else if (g_rehab_demo_active || g_servo_pair_commission_request != 0u ||
             g_sign_demo_active)
    {
        result = SERVO_SIGN_REQUEST_BUSY;
    }
    else if (g_sign_demo_pending_action != 0u)
    {
        if (action == SERVO_SIGN_ACTION_HOME)
        {
            /* HOME supersedes a queued START/HOME without touching a servo. */
            g_sign_demo_pending_action = SERVO_SIGN_ACTION_HOME;
            g_sign_demo_pending_sequence_id = sequence_id;
            g_sign_demo_sequence_id = sequence_id;
            g_sign_demo_last_action = SERVO_SIGN_ACTION_HOME;
            g_sign_demo_result = SERVO_SIGN_RESULT_NONE;
            g_sign_demo_state = SERVO_SIGN_STATE_QUEUED;
        }
        else
        {
            result = SERVO_SIGN_REQUEST_BUSY;
        }
    }
    else
    {
        /* The servo thread owns all writes; this mailbox contains no raw
         * positions and is consumed at a deterministic cycle boundary. */
        g_sign_demo_pending_action = (uint8_t)action;
        g_sign_demo_pending_sequence_id = sequence_id;
        g_sign_demo_sequence_id = sequence_id;
        g_sign_demo_last_action = action;
        g_sign_demo_result = SERVO_SIGN_RESULT_NONE;
        g_sign_demo_state = SERVO_SIGN_STATE_QUEUED;
    }
    rt_mutex_release(&g_snapshot_mutex);
    return result;
}

int servo_bus_sign_demo_get_status(servo_sign_status_t *status)
{
    if (status == RT_NULL)
    {
        return 0;
    }
    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    status->state = g_sign_demo_state;
    status->result_code = g_sign_demo_result;
    status->sequence_id = g_sign_demo_sequence_id;
    status->completed_count = g_sign_demo_completed_count;
    status->last_action = g_sign_demo_last_action;
    rt_mutex_release(&g_snapshot_mutex);
    return 1;
}

servo_rehab_request_result_t servo_bus_rehab_demo_request(void)
{
    servo_rehab_request_result_t result = SERVO_REHAB_REQUEST_ACCEPTED;

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    if (!g_ready)
    {
        result = SERVO_REHAB_REQUEST_NOT_READY;
    }
    else if (g_eight_servo_gate.fault_latched)
    {
        result = SERVO_REHAB_REQUEST_FAULT;
    }
    else if (g_rehab_demo_active || g_servo_pair_commission_request != 0u ||
             g_sign_demo_active || g_sign_demo_pending_action != 0u)
    {
        result = SERVO_REHAB_REQUEST_BUSY;
    }
    else
    {
        /* The servo thread owns motion; the UART thread only queues a token. */
        g_servo_pair_commission_result = 0u;
        g_servo_pair_commission_request = SERVO_REHAB_DEMO_MAGIC;
    }
    rt_mutex_release(&g_snapshot_mutex);
    return result;
}

int servo_bus_rehab_demo_get_status(servo_rehab_status_t *status)
{
    if (status == RT_NULL)
    {
        return 0;
    }

    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    status->result_code = g_servo_pair_commission_result;
    status->completed_count = g_rehab_demo_completed_count;
    if (g_rehab_demo_active)
    {
        status->state = SERVO_REHAB_STATE_RUNNING;
    }
    else if (g_servo_pair_commission_request == SERVO_REHAB_DEMO_MAGIC)
    {
        status->state = SERVO_REHAB_STATE_QUEUED;
    }
    else if (g_servo_pair_commission_result == 1u)
    {
        status->state = SERVO_REHAB_STATE_SUCCEEDED;
    }
    else if (g_servo_pair_commission_result != 0u)
    {
        status->state = SERVO_REHAB_STATE_FAILED;
    }
    else
    {
        status->state = SERVO_REHAB_STATE_IDLE;
    }
    rt_mutex_release(&g_snapshot_mutex);
    return 1;
}

int servo_bus_readonly_get_snapshot(servo_group_readonly_sample_t *samples,
                                    size_t capacity,
                                    size_t *sample_count)
{
    int result = 0;
    if (samples == RT_NULL || sample_count == RT_NULL)
    {
        return 0;
    }
    *sample_count = 0u;
    rt_mutex_take(&g_snapshot_mutex, RT_WAITING_FOREVER);
    if (g_ready && capacity >= g_published_count)
    {
        rt_memcpy(samples, g_published,
                  g_published_count * sizeof(g_published[0]));
        *sample_count = g_published_count;
        result = 1;
    }
    rt_mutex_release(&g_snapshot_mutex);
    return result;
}

static int servo_bus_readonly_init(void)
{
    struct serial_configure config = RT_SERIAL_CONFIG_DEFAULT;
    rt_thread_t thread;
    rt_err_t result;

    rt_pin_mode(SERVO_BUS_LED_RED, PIN_MODE_OUTPUT);
    rt_pin_mode(SERVO_BUS_LED_GREEN, PIN_MODE_OUTPUT);
    rt_pin_mode(SERVO_BUS_LED_BLUE, PIN_MODE_OUTPUT);
    set_leds(1u, 0u, 0u);

    eight_servo_pose_bank_init(&g_eight_servo_pose_bank);
    (void)eight_servo_safety_gate_init(
        &g_eight_servo_gate, g_eight_servo_calibration,
        SERVO_BUS_CYCLE_PERIOD_MS * 2u, 45u, 60u, 45u);

    /* Use the high-drive setting for the 1 Mbps SCI1 TX signal. */
    if (R_IOPORT_PinCfg(&g_ioport_ctrl,
                        BSP_IO_PORT_07_PIN_07,
                        IOPORT_CFG_DRIVE_HIGH |
                            IOPORT_CFG_PERIPHERAL_PIN |
                            IOPORT_PERIPHERAL_SCI1_3_5_7_9) != FSP_SUCCESS)
    {
        return -RT_ERROR;
    }

    if (!servo_group_readonly_init(&g_group, g_servo_ids,
                                   SERVO_GROUP_READONLY_MAX_COUNT,
                                   SERVO_BUS_RESPONSE_TIMEOUT_MS))
    {
        return -RT_ERROR;
    }
    result = rt_mutex_init(&g_snapshot_mutex, "shsnap", RT_IPC_FLAG_PRIO);
    if (result != RT_EOK)
    {
        return result;
    }
    g_sign_demo_pending_action = 0u;
    g_sign_demo_pending_sequence_id = 0u;
    g_sign_demo_active = 0u;
    g_sign_demo_cancel_requested = 0u;
    g_sign_demo_home_requested = 0u;
    g_sign_demo_state = SERVO_SIGN_STATE_IDLE;
    g_sign_demo_result = SERVO_SIGN_RESULT_NONE;
    g_sign_demo_sequence_id = SERVO_SIGN_SEQUENCE_HELLO;
    g_sign_demo_completed_count = 0u;
    g_sign_demo_last_action = SERVO_SIGN_ACTION_START;
    g_servo_uart = rt_device_find(SMART_HAND_SERVO_UART_NAME);
    if (g_servo_uart == RT_NULL)
    {
        rt_mutex_detach(&g_snapshot_mutex);
        return -RT_ERROR;
    }
    /* RT-Thread serial_v2 omits the symbolic 1 Mbps constant. */
    config.baud_rate = SERVO_BUS_BAUD_RATE;
    config.data_bits = DATA_BITS_8;
    config.stop_bits = STOP_BITS_1;
    config.parity = PARITY_NONE;
    config.tx_bufsz = 0u;
    result = rt_device_control(g_servo_uart, RT_DEVICE_CTRL_CONFIG, &config);
    if (result != RT_EOK)
    {
        return result;
    }
    result = rt_device_set_rx_indicate(g_servo_uart, servo_uart_rx_indicate);
    if (result != RT_EOK)
    {
        return result;
    }
    result = rt_device_open(g_servo_uart,
                            RT_DEVICE_OFLAG_RDWR | RT_DEVICE_FLAG_INT_RX);
    if (result != RT_EOK)
    {
        return result;
    }

    /*
     * The RA8P1 RT-Thread UART adapter currently ignores serial_configure's
     * baud_rate field and opens SCI1 with the FSP-generated default (115200).
     * Program SCI1 explicitly so the Feetech bus actually runs at 1 Mbps.
     */
    {
        sci_b_baud_setting_t baud_setting;
        fsp_err_t fsp_result = R_SCI_B_UART_BaudCalculate(
            SERVO_BUS_BAUD_RATE, true, 15000u, &baud_setting);
        if (fsp_result == FSP_SUCCESS)
        {
            fsp_result = R_SCI_B_UART_BaudSet(
                (uart_ctrl_t *)&g_uart1_ctrl, &baud_setting);
        }
        if (fsp_result != FSP_SUCCESS)
        {
            rt_device_close(g_servo_uart);
            return -RT_ERROR;
        }
    }

    thread = rt_thread_create("sh_servo", servo_bus_thread_entry, RT_NULL,
                              SERVO_BUS_THREAD_STACK, 19u, 5u);
    if (thread == RT_NULL)
    {
        rt_device_close(g_servo_uart);
        return -RT_ENOMEM;
    }
    result = rt_thread_startup(thread);
    if (result != RT_EOK)
    {
        rt_thread_delete(thread);
        rt_device_close(g_servo_uart);
        return result;
    }
    return RT_EOK;
}
INIT_APP_EXPORT(servo_bus_readonly_init);
