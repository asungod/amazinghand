#ifndef SMART_HAND_TESTS_STUBS_USART_RTDBG_H
#define SMART_HAND_TESTS_STUBS_USART_RTDBG_H

/*
 * 主机桩：rt-thread/include/rtdbg.h。
 *
 * 被测文件包含它是为了 DBG_TAG/DBG_LVL + LOG_D/LOG_E 那一套。实查
 * drv_usart_v2.c 内部一次 LOG_* 都没有调用（DRV_DEBUG 也没打开），所以这里
 * 只提供宏定义让 #include <rtdbg.h> 通过，不做任何输出 —— 不会掩盖任何
 * 被测代码的日志路径，因为那条路径本来就没被走。
 */

#include <stdio.h>

#define DBG_ERROR           0
#define DBG_WARNING         1
#define DBG_INFO            2
#define DBG_LOG             3

#define DBG_SECTION_NAME    "drv.usart"

#define LOG_E(...)          do { } while (0)
#define LOG_W(...)          do { } while (0)
#define LOG_I(...)          do { } while (0)
#define LOG_D(...)          do { } while (0)
#define LOG_RAW(...)        do { } while (0)

#endif /* SMART_HAND_TESTS_STUBS_USART_RTDBG_H */
