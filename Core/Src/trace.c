#include "main.h"
#include "trace.h"
#include "cmsis_os.h"

/* ---------------------------------------------------------
 * Konfiguracja bufora, prosty ring buffer
 * --------------------------------------------------------- */
#define TRACE_BUFFER_SIZE 512u

static TraceEvent traceBuffer[TRACE_BUFFER_SIZE];
static volatile uint32_t traceWriteIndex = 0;
static volatile uint32_t traceReadIndex = 0;
static volatile uint32_t traceLostCount = 0;

/* Handle z main.c wygenerowany przez CubeMX. Dodaj kolejne externy przy kolejnych taskach. */
extern osThreadId defaultTaskHandle;

/* ---------------------------------------------------------
 * Sekcja krytyczna bardzo krotka, bez FreeRTOS API.
 * Dzieki temu Trace_Write moze byc wywolany z hookow kernela.
 * --------------------------------------------------------- */
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

/* ---------------------------------------------------------
 * Inicjalizacja DWT i trace
 * --------------------------------------------------------- */
void Trace_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;

    *((volatile uint32_t *)0xE0001FB0UL) = 0xC5ACCE55UL;

    DWT->CYCCNT = 0u;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    traceWriteIndex = 0u;
    traceReadIndex = 0u;
    traceLostCount = 0u;
}

/* ---------------------------------------------------------
 * Wspolna funkcja zapisu rekordu
 * --------------------------------------------------------- */
static bool Trace_WriteInternal(TraceEventId eventId, uint8_t contextId, uint32_t value, uint8_t flags)
{
    uint32_t primask = Trace_Lock();

    uint32_t idx = traceWriteIndex;
    uint32_t nextIdx = (idx + 1u) % TRACE_BUFFER_SIZE;

    /* Bufor pelny: nie nadpisujemy nieodczytanych danych, tylko zliczamy utracone rekordy. */
    if (nextIdx == traceReadIndex)
    {
        traceLostCount++;
        Trace_Unlock(primask);
        return false;
    }

    TraceEvent *e = &traceBuffer[idx];
    e->timestamp = TraceTimestamp_Get();
    e->eventId   = (uint16_t)eventId;
    e->contextId = contextId;
    e->flags     = flags;
    e->value     = value;

    traceWriteIndex = nextIdx;

    Trace_Unlock(primask);
    return true;
}

/* ---------------------------------------------------------
 * Zapis zdarzenia z kontekstu taska/hooka
 * --------------------------------------------------------- */
bool Trace_Write(TraceEventId eventId, uint8_t contextId, uint32_t value)
{
    return Trace_WriteInternal(eventId, contextId, value, 0u);
}

/* ---------------------------------------------------------
 * Zapis zdarzenia z ISR
 * hpw zostawione w API, zeby pasowalo do typowych wzorcow FreeRTOS FromISR.
 * --------------------------------------------------------- */
bool Trace_WriteFromISR(TraceEventId eventId, uint8_t contextId, uint32_t value, void *hpw)
{
    (void)hpw;
    return Trace_WriteInternal(eventId, contextId, value, 1u);
}

/* ---------------------------------------------------------
 * Zrzut trace przez UART.
 * Format ramki: 0xAA 0x55 + 12 bajtow TraceEvent.
 * Nie wywolywac z hookow ani ISR. Wywolywac z taska.
 * --------------------------------------------------------- */
void Trace_FlushUart(UART_HandleTypeDef *huart)
{
    const uint8_t header[2] = { TRACE_UART_HEADER_0, TRACE_UART_HEADER_1 };

    while (traceReadIndex != traceWriteIndex)
    {
        uint32_t primask = Trace_Lock();

        if (traceReadIndex == traceWriteIndex)
        {
            Trace_Unlock(primask);
            break;
        }

        TraceEvent e = traceBuffer[traceReadIndex];
        traceReadIndex = (traceReadIndex + 1u) % TRACE_BUFFER_SIZE;

        Trace_Unlock(primask);

        (void)HAL_UART_Transmit(huart, (uint8_t *)header, sizeof(header), 10u);
        (void)HAL_UART_Transmit(huart, (uint8_t *)&e, sizeof(e), 10u);
    }
}

uint32_t Trace_GetLostCount(void)
{
    return traceLostCount;
}

/* ---------------------------------------------------------
 * Mapowanie TCB/handle taska na male ID do wyslania w contextId.
 * Rozszerzaj te if-y przy dodawaniu taskow.
 * --------------------------------------------------------- */
uint8_t Trace_GetTaskId(void *tcb)
{
    if (tcb == (void *)defaultTaskHandle)
    {
        return (uint8_t)TRACE_TASK_DEFAULT;
    }

    return (uint8_t)TRACE_TASK_UNKNOWN;
}
