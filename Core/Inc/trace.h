#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "core_cm7.h"


/* ---------------------------------------------------------
 *  Event identifiers (unikalne kody zdarzeń)
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

    TRACE_USER_MARKER      = 100
} TraceEventId;

/* ---------------------------------------------------------
 *  Minimalny rekord trace (12 bajtów)
 * --------------------------------------------------------- */
typedef struct
{
    uint32_t timestamp;   // DWT->CYCCNT
    uint16_t eventId;     // unikalny kod zdarzenia
    uint8_t  contextId;   // np. taskId, ISR, priorytet
    uint8_t  flags;       // bitowe flagi (np. ISR=1)
    uint32_t value;       // argument zdarzenia
} TraceEvent;

/* ---------------------------------------------------------
 *  Timestamp (DWT CYCCNT)
 * --------------------------------------------------------- */
static inline uint32_t TraceTimestamp_Get(void)
{
    return DWT->CYCCNT;
}

void Trace_Init(void);

/* ---------------------------------------------------------
 *  API do zapisu zdarzeń
 * --------------------------------------------------------- */
bool Trace_Write(
    TraceEventId eventId,
    uint8_t contextId,
    uint32_t value);

bool Trace_WriteFromISR(
    TraceEventId eventId,
    uint8_t contextId,
    uint32_t value,
    void *hpw);

/* ---------------------------------------------------------
 *  Makra użytkownika
 * --------------------------------------------------------- */
#define TRACE_EVENT(eventId, contextId, value) \
    Trace_Write((eventId), (contextId), (value))

#define TRACE_EVENT_FROM_ISR(eventId, contextId, value, hpw) \
    Trace_WriteFromISR((eventId), (contextId), (value), (hpw))

