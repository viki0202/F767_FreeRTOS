#include "main.h"
#include "trace.h"
#include "cmsis_os.h"
#include <string.h>

#define TRACE_BUFFER_SIZE 512u

static TraceEvent traceBuffer[TRACE_BUFFER_SIZE];
static volatile uint32_t traceWriteIndex = 0u;
static volatile uint32_t traceReadIndex = 0u;
static volatile uint32_t traceLostCount = 0u;

extern osThreadId defaultTaskHandle;

static inline uint32_t Trace_Lock(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    return primask;
}

static inline void Trace_Unlock(uint32_t primask)
{
    if (primask == 0u)
    {
        __enable_irq();
    }
}

void Trace_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0u;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    traceWriteIndex = 0u;
    traceReadIndex = 0u;
    traceLostCount = 0u;
}

static bool Trace_WriteInternal(TraceEventId eventId,
                                uint8_t contextId,
                                uint32_t value,
                                uint8_t flags)
{
    uint32_t primask = Trace_Lock();
    uint32_t idx = traceWriteIndex;
    uint32_t nextIdx = (idx + 1u) % TRACE_BUFFER_SIZE;

    if (nextIdx == traceReadIndex)
    {
        traceLostCount++;
        Trace_Unlock(primask);
        return false;
    }

    traceBuffer[idx].timestamp = TraceTimestamp_Get();
    traceBuffer[idx].eventId = (uint16_t)eventId;
    traceBuffer[idx].contextId = contextId;
    traceBuffer[idx].flags = flags;
    traceBuffer[idx].value = value;
    traceWriteIndex = nextIdx;

    Trace_Unlock(primask);
    return true;
}

bool Trace_Write(TraceEventId eventId, uint8_t contextId, uint32_t value)
{
    return Trace_WriteInternal(eventId, contextId, value, 0u);
}

bool Trace_WriteFromISR(TraceEventId eventId,
                        uint8_t contextId,
                        uint32_t value,
                        void *hpw)
{
    (void)hpw;
    return Trace_WriteInternal(eventId, contextId, value, 1u);
}

/*
 * CELOWO BLEDNA implementacja: wysylanie bajt po bajcie bez synchronizacji.
 * Inny task moze wywlaszczyc biezacy task pomiedzy dowolnymi bajtami.
 */
void Trace_UnsafeUartWrite(UART_HandleTypeDef *huart, const char *text)
{
    while (*text != '\0')
    {
        (void)HAL_UART_Transmit(huart, (uint8_t *)text, 1u, 20u);
        text++;
    }
}

/*
 * pauseTicks celowo rozszerza okno wyscigu. osDelay() powoduje oddanie CPU,
 * wiec drugi task moze wejsc do tego samego UART-u podczas trwania komunikatu.
 */
void Trace_UnsafeUartWriteSlow(UART_HandleTypeDef *huart,
                               const char *text,
                               uint32_t pauseTicks)
{
    while (*text != '\0')
    {
        (void)HAL_UART_Transmit(huart, (uint8_t *)text, 1u, 20u);
        text++;

        if (pauseTicks != 0u)
        {
            osDelay(pauseTicks);
        }
    }
}

/*
 * CELOWO BARDZO BLEDNE: blokujace HAL_UART_Transmit wywolane z ISR.
 * Funkcja sluzy jedynie do kontrolowanego eksperymentu laboratoryjnego.
 */
void Trace_UnsafeUartWriteFromISR(UART_HandleTypeDef *huart, const char *text)
{
    while (*text != '\0')
    {
        (void)HAL_UART_Transmit(huart, (uint8_t *)text, 1u, 1u);
        text++;
    }
}

/*
 * Zrzut binarny rowniez celowo korzysta z tego samego UART-u bez blokady.
 * Tekst z taskow moze wejsc pomiedzy naglowek i rekord, niszczac ramkowanie.
 */
void Trace_FlushUart(UART_HandleTypeDef *huart)
{
    const uint8_t header[2] = {TRACE_UART_HEADER_0, TRACE_UART_HEADER_1};

    while (traceReadIndex != traceWriteIndex)
    {
        TraceEvent eventCopy;
        uint32_t primask = Trace_Lock();

        if (traceReadIndex == traceWriteIndex)
        {
            Trace_Unlock(primask);
            break;
        }

        eventCopy = traceBuffer[traceReadIndex];
        traceReadIndex = (traceReadIndex + 1u) % TRACE_BUFFER_SIZE;
        Trace_Unlock(primask);

        /* Brak wspolnej blokady dla calej ramki. */
        (void)HAL_UART_Transmit(huart, (uint8_t *)&header[0], 1u, 20u);
        osThreadYield();
        (void)HAL_UART_Transmit(huart, (uint8_t *)&header[1], 1u, 20u);
        osThreadYield();

        const uint8_t *raw = (const uint8_t *)&eventCopy;
        for (uint32_t i = 0u; i < (uint32_t)sizeof(eventCopy); i++)
        {
            (void)HAL_UART_Transmit(huart, (uint8_t *)&raw[i], 1u, 20u);
            osThreadYield();
        }
    }
}

uint32_t Trace_GetLostCount(void)
{
    return traceLostCount;
}

uint8_t Trace_GetTaskId(void *tcb)
{
    if (tcb == (void *)defaultTaskHandle)
    {
        return (uint8_t)TRACE_TASK_DEFAULT;
    }

    return (uint8_t)TRACE_TASK_UNKNOWN;
}
