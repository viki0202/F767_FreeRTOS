#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "core_cm7.h"
#include "stm32f7xx_hal.h"

#define TRACE_UART_HEADER_0 0xAAu
#define TRACE_UART_HEADER_1 0x55u

typedef enum
{
    TRACE_CONTEXT_UNKNOWN = 0,
    TRACE_CONTEXT_UART_DEMO = 1
} TraceContextId;

typedef enum
{
    TRACE_TASK_UNKNOWN = 0,
    TRACE_TASK_DEFAULT = 1,
    TRACE_TASK_UART_A = 2,
    TRACE_TASK_UART_B = 3,
    TRACE_TASK_UART_C = 4
} TraceTaskId;

typedef enum
{
    TRACE_TASK_START         = 1,
    TRACE_TASK_STOP          = 2,
    TRACE_TASK_WAKE          = 3,
    TRACE_TASK_CREATE        = 4,
    TRACE_TASK_DELETE        = 5,
    TRACE_MUTEX_WAIT_BEGIN   = 10,
    TRACE_MUTEX_ACQUIRED     = 11,
    TRACE_MUTEX_RELEASED     = 12,
    TRACE_QUEUE_SEND         = 20,
    TRACE_QUEUE_RECEIVE      = 21,
    TRACE_QUEUE_FULL         = 22,
    TRACE_ISR_ENTER          = 30,
    TRACE_ISR_EXIT           = 31,
    TRACE_OPERATION_BEGIN    = 40,
    TRACE_OPERATION_END      = 41,
    TRACE_USER_MARKER        = 100,
    TRACE_BUFFER_OVERFLOW    = 101
} TraceEventId;

typedef struct
{
    uint32_t timestamp;
    uint16_t eventId;
    uint8_t contextId;
    uint8_t flags;
    uint32_t value;
} TraceEvent;

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

/*
 * CELOWO BLEDNE API DEMONSTRACYJNE.
 * Funkcje nie posiadaja mutexu, kolejki, jednego taska TX ani arbitrazu DMA.
 */
void Trace_UnsafeUartWrite(UART_HandleTypeDef *huart, const char *text);
void Trace_UnsafeUartWriteSlow(UART_HandleTypeDef *huart,
                               const char *text,
                               uint32_t pauseTicks);
void Trace_UnsafeUartWriteFromISR(UART_HandleTypeDef *huart, const char *text);

#define TRACE_EVENT(eventId, contextId, value) \
    Trace_Write((eventId), (uint8_t)(contextId), (uint32_t)(value))

#define TRACE_EVENT_FROM_ISR(eventId, contextId, value, hpw) \
    Trace_WriteFromISR((eventId), (uint8_t)(contextId), (uint32_t)(value), (hpw))
