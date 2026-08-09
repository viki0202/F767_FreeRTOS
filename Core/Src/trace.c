#include "main.h"
#include "trace.h"

/* ---------------------------------------------------------
 *  Konfiguracja bufora (prosty ring buffer)
 * --------------------------------------------------------- */
#define TRACE_BUFFER_SIZE 512

static TraceEvent traceBuffer[TRACE_BUFFER_SIZE];
static volatile uint32_t traceWriteIndex = 0;

/* ---------------------------------------------------------
 *  Inicjalizacja DWT i trace
 * --------------------------------------------------------- */
void Trace_Init(void)
{
    /* Włącz DWT */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;

    /* Wyzeruj licznik cykli */
    DWT->CYCCNT = 0;

    /* Włącz CYCCNT */
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    /* Wyzeruj indeks bufora */
    traceWriteIndex = 0;
}

/* ---------------------------------------------------------
 *  Zapis zdarzenia (z kontekstu taska)
 * --------------------------------------------------------- */
bool Trace_Write(TraceEventId eventId, uint8_t contextId, uint32_t value)
{
    uint32_t idx = traceWriteIndex;

    TraceEvent *e = &traceBuffer[idx];

    e->timestamp = TraceTimestamp_Get();
    e->eventId   = (uint16_t)eventId;
    e->contextId = contextId;
    e->flags     = 0;
    e->value     = value;

    traceWriteIndex = (idx + 1) % TRACE_BUFFER_SIZE;

    return true;
}

/* ---------------------------------------------------------
 *  Zapis zdarzenia (z ISR)
 * --------------------------------------------------------- */
bool Trace_WriteFromISR(TraceEventId eventId, uint8_t contextId, uint32_t value, void *hpw)
{
    uint32_t idx = traceWriteIndex;

    TraceEvent *e = &traceBuffer[idx];

    e->timestamp = TraceTimestamp_Get();
    e->eventId   = (uint16_t)eventId;
    e->contextId = contextId;
    e->flags     = 1;   /* ISR */
    e->value     = value;

    traceWriteIndex = (idx + 1) % TRACE_BUFFER_SIZE;

    return true;
}