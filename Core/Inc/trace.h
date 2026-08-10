#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "core_cm7.h"
#include "stm32f7xx_hal.h"

/* ---------------------------------------------------------
 * Konfiguracja trace
 * --------------------------------------------------------- */
#define TRACE_UART_HEADER_0    0xAAu
#define TRACE_UART_HEADER_1    0x55u

/* Context IDs: contextId ma tylko 8 bitow, wiec trzymamy tu male ID,
 * a szczegoly, np. adres kolejki albo dodatkowa wartosc, w polu value.
 */
typedef enum
{
    TRACE_CTX_UNKNOWN = 0,
    TRACE_CTX_TASK    = 1,
    TRACE_CTX_QUEUE   = 2,
    TRACE_CTX_MUTEX   = 3,
    TRACE_CTX_NOTIFY  = 4,
    TRACE_CTX_ISR     = 5,
    TRACE_CTX_USER    = 100
} TraceContextId;

/* ID taskow do dekodowania po stronie PC/Pythona. Rozszerzaj przy dodawaniu taskow. */
typedef enum
{
    TRACE_TASK_UNKNOWN = 0,
    TRACE_TASK_DEFAULT = 1
} TraceTaskId;

/* ---------------------------------------------------------
 * Event identifiers, unikalne kody zdarzen
 * --------------------------------------------------------- */
typedef enum
{
    TRACE_TASK_START       = 1,
    TRACE_TASK_STOP        = 2,
    TRACE_TASK_WAKE        = 3,

    TRACE_MUTEX_WAIT_BEGIN = 10,
    TRACE_MUTEX_ACQUIRED   = 11,
    TRACE_MUTEX_RELEASED   = 12,

    TRACE_QUEUE_SEND       = 20,
    TRACE_QUEUE_RECEIVE    = 21,
    TRACE_QUEUE_FULL       = 22,

    TRACE_ISR_ENTER        = 30,
    TRACE_ISR_EXIT         = 31,

    TRACE_OPERATION_BEGIN  = 40,
    TRACE_OPERATION_END    = 41,

    TRACE_USER_MARKER      = 100,
    TRACE_BUFFER_OVERFLOW  = 101
} TraceEventId;

/* ---------------------------------------------------------
 * Minimalny rekord trace, 12 bajtow na STM32F7 przy typowym ABI
 * --------------------------------------------------------- */
typedef struct
{
    uint32_t timestamp;   /* DWT->CYCCNT */
    uint16_t eventId;     /* TraceEventId */
    uint8_t  contextId;   /* TraceContextId albo TraceTaskId */
    uint8_t  flags;       /* bit 0: ISR */
    uint32_t value;       /* argument zdarzenia */
} TraceEvent;

/* ---------------------------------------------------------
 * Timestamp, DWT CYCCNT
 * --------------------------------------------------------- */
static inline uint32_t TraceTimestamp_Get(void)
{
    return DWT->CYCCNT;
}

void Trace_Init(void);

bool Trace_Write(TraceEventId eventId, uint8_t contextId, uint32_t value);
bool Trace_WriteFromISR(TraceEventId eventId, uint8_t contextId, uint32_t value, void *hpw);

void Trace_FlushUart(UART_HandleTypeDef *huart);
uint32_t Trace_GetLostCount(void);
uint8_t Trace_GetTaskId(void *tcb);

/* ---------------------------------------------------------
 * Makra uzytkownika.
 * Wazne: backslash na koncu linii jest wymagany.
 * --------------------------------------------------------- */
#define TRACE_EVENT(eventId, contextId, value) \
    Trace_Write((eventId), (uint8_t)(contextId), (uint32_t)(value))

#define TRACE_EVENT_FROM_ISR(eventId, contextId, value, hpw) \
    Trace_WriteFromISR((eventId), (uint8_t)(contextId), (uint32_t)(value), (hpw))
