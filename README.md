# F767 FreeRTOS Trace Lab

Eksperymentalny projekt dla **STM32F767 + FreeRTOS**, którego celem jest zbudowanie lekkiego i praktycznego mechanizmu logowania zdarzeń czasu rzeczywistego w kodzie C i C++.

Projekt ma pomóc zobaczyć to, czego zwykle nie widać w klasycznym logu tekstowym:

- kiedy task został uruchomiony i wywłaszczony,
- który task wykonywał się pomiędzy dwoma przełączeniami kontekstu,
- gdzie task czekał na kolejkę, mutex lub semafor,
- jak przerwania wpływają na kolejność wykonywania tasków,
- ile czasu zajmują wybrane operacje,
- gdzie system traci zdarzenia z powodu ograniczonej przepustowości,
- jaki jest praktyczny koszt samego logowania.

To nie jest pełny profiler ani produkt klasy tracing framework. Jest to **inżynierskie laboratorium trace**, rozwijane krok po kroku, z naciskiem na obserwowalność, powtarzalne eksperymenty i świadome kompromisy typowe dla systemów embedded.

> Drugim celem projektu jest zebranie praktycznego materiału do rozwijania książki o sztuce logowania: przykładów, błędów, pomiarów i wniosków wynikających z działania systemu na rzeczywistym mikrokontrolerze.

## Główne cele

### 1. Zależności pomiędzy taskami

Rejestrowanie zdarzeń pozwalających odtworzyć przybliżoną oś czasu działania schedulera:

- utworzenie i usunięcie taska,
- wejście taska na CPU,
- zejście taska z CPU,
- wywłaszczenie,
- blokowanie i odblokowanie,
- zależności wynikające z kolejek i mechanizmów synchronizacji.

### 2. Zrozumienie synchronizacji

Projekt ma umożliwić obserwację praktycznego użycia:

- kolejek,
- mutexów,
- semaforów,
- operacji wykonywanych z ISR,
- sekcji krytycznych,
- oczekiwania z timeoutem,
- relacji producent-konsument.

Celem nie jest jedynie zapis informacji, że funkcja została wywołana. Ważniejsze jest pokazanie **dlaczego task przestał się wykonywać, na co czekał i co pozwoliło mu ruszyć dalej**.

### 3. Prosta analiza wydajności

Na podstawie timestampów i kolejności rekordów planowana jest analiza:

- czasu wykonywania tasków,
- czasu obsługi wybranych ISR,
- liczby i częstotliwości przełączeń kontekstu,
- opóźnienia pomiędzy zdarzeniem a reakcją taska,
- okresów oczekiwania na zasoby,
- obciążenia generowanego przez trace,
- utraconych rekordów,
- wpływu transportu UART na wiarygodność pomiaru.

Analiza ma pozostać prosta i możliwa do zweryfikowania. Najpierw poprawne dane i znane ograniczenia, później wykresy i bardziej zaawansowane metryki.

### 4. Logowanie inżynierskie, nie laboratoryjny ideał

Projekt świadomie uwzględnia ograniczenia typowego firmware:

- ograniczoną pamięć RAM,
- koszt wykonania hooków,
- ograniczoną przepustowość UART,
- współbieżność tasków i ISR,
- możliwość przepełnienia bufora,
- konieczność pracy bez dynamicznej alokacji,
- potrzebę zachowania działania aplikacji podczas zbierania logów.

Każda funkcja trace powinna mieć określony koszt, zakres bezpieczeństwa i scenariusz testowy.

## Założenia architektury

Mechanizm jest podzielony na dwie części:

```text
FreeRTOS hooks / kod C / kod C++ / ISR
                  |
                  v
          zapis rekordu do RAM
                  |
                  v
              ring buffer
                  |
                  v
          task transportowy UART
                  |
                  v
        dekoder i analiza na PC
```

### Szybka ścieżka: zapis do RAM

Hook kernela, ISR lub instrumentowany fragment aplikacji tworzy mały rekord binarny i zapisuje go do ring buffera.

W tej ścieżce nie powinno być:

- `printf()`,
- transmisji UART,
- dynamicznej alokacji pamięci,
- oczekiwania na mutex,
- długich pętli,
- formatowania napisów.

### Wolna ścieżka: transport

Osobny task pobiera rekordy z bufora i wysyła je przez UART. Transmisja nie może odbywać się przy wyłączonych przerwaniach.

Docelowo transport może przejść przez kolejne warianty:

1. blokujący UART,
2. jedna transmisja na całą ramkę,
3. transmisja blokowa,
4. UART z DMA.

### Analiza po stronie PC

Dekoder wyszukuje nagłówek ramki, odczytuje rekordy binarne i zamienia je na postać przydatną do analizy, na przykład CSV lub JSON.

Planowane wyniki analizy:

- oś czasu tasków,
- pary rozpoczęcia i zakończenia wykonywania,
- liczba wywłaszczeń,
- czas oczekiwania na synchronizację,
- zdarzenia ISR,
- utracone rekordy,
- podstawowe statystyki czasowe.

## Format rekordu

Aktualna koncepcja wykorzystuje rekord o rozmiarze 12 bajtów:

```c
typedef struct
{
    uint32_t timestamp;
    uint16_t eventId;
    uint8_t  contextId;
    uint8_t  flags;
    uint32_t value;
} TraceEvent;
```

Znaczenie pól:

- `timestamp`: licznik cykli procesora, obecnie oparty na `DWT->CYCCNT`,
- `eventId`: rodzaj zdarzenia,
- `contextId`: mały identyfikator taska lub kontekstu,
- `flags`: dodatkowe informacje, między innymi znacznik ISR,
- `value`: wartość zależna od zdarzenia, na przykład licznik, adres obiektu RTOS lub identyfikator operacji.

Przykładowa ramka UART:

```text
AA 55 | 12 bajtów TraceEvent
```

Wartości wielobajtowe są przesyłane w kolejności little-endian właściwej dla STM32.

> Layout struktury musi być sprawdzany podczas kompilacji, na przykład przez `_Static_assert(sizeof(TraceEvent) == 12u, ...)`. Protokół nie powinien opierać się na niezweryfikowanym założeniu dotyczącym wyrównania pól.

## Przykładowe klasy zdarzeń

Planowany zakres instrumentacji obejmuje:

```text
TASK_CREATE
TASK_DELETE
TASK_START
TASK_STOP

QUEUE_SEND
QUEUE_RECEIVE
QUEUE_SEND_BLOCK
QUEUE_RECEIVE_BLOCK

MUTEX_WAIT_BEGIN
MUTEX_ACQUIRED
MUTEX_RELEASED

ISR_ENTER
ISR_EXIT

OPERATION_BEGIN
OPERATION_END
USER_MARKER
BUFFER_OVERFLOW
```

Lista będzie rozwijana stopniowo. Każdy nowy typ zdarzenia powinien mieć:

- jednoznaczną semantykę,
- opis pól rekordu,
- kontrolowany scenariusz testowy,
- obsługę w dekoderze,
- oszacowany wpływ na system.

## Logowanie z kodu C

Przykład ręcznego markera:

```c
TRACE_EVENT(TRACE_USER_MARKER,
            TRACE_CTX_NONE,
            0x12345678u);
```

Przykład pomiaru operacji:

```c
TRACE_EVENT(TRACE_OPERATION_BEGIN,
            TRACE_CTX_TASK,
            operationId);

RunOperation();

TRACE_EVENT(TRACE_OPERATION_END,
            TRACE_CTX_TASK,
            operationId);
```

## Logowanie z kodu C++

API trace powinno być dostępne z C++ przez deklaracje z C linkage:

```c
#ifdef __cplusplus
extern "C" {
#endif

#include "trace.h"

#ifdef __cplusplus
}
#endif
```

Dla kodu C++ planowany jest również mały wrapper RAII, który automatycznie rejestruje początek i koniec zakresu:

```cpp
class TraceScope
{
public:
    TraceScope(uint32_t operationId, uint8_t contextId)
        : operationId_(operationId), contextId_(contextId)
    {
        TRACE_EVENT(TRACE_OPERATION_BEGIN,
                    contextId_,
                    operationId_);
    }

    ~TraceScope()
    {
        TRACE_EVENT(TRACE_OPERATION_END,
                    contextId_,
                    operationId_);
    }

private:
    uint32_t operationId_;
    uint8_t contextId_;
};
```

Przykład użycia:

```cpp
void ProcessFrame()
{
    TraceScope traceScope(PROCESS_FRAME_OPERATION,
                          TRACE_CTX_TASK);

    // Kod operacji.
}
```

Wrapper jest planowany jako wygoda dla kodu aplikacyjnego. Hooki FreeRTOS i ISR pozostają oparte na możliwie krótkiej ścieżce C.

## Najważniejsze reguły bezpieczeństwa

1. **UART nie jest wywoływany z hooka FreeRTOS ani z ISR.**
2. **Sekcja krytyczna obejmuje tylko operacje na ring bufferze.**
3. **Rekord jest kompletny przed opublikowaniem indeksu zapisu.**
4. **Slot nie może zostać zwolniony przed wykonaniem bezpiecznej kopii rekordu.**
5. **Pełny bufor powoduje zwiększenie licznika strat, a nie nadpisanie nieodczytanych danych.**
6. **Trace nie używa dynamicznej alokacji w szybkiej ścieżce.**
7. **Każda optymalizacja jest porównywana z mierzalnym punktem odniesienia.**
8. **Utrata rekordu i przekłamanie rekordu są raportowane jako dwa różne problemy.**

## Strategia rozwoju

Projekt jest rozwijany małymi krokami. Każdy etap powinien dać się osobno:

- skompilować,
- uruchomić na płytce,
- przetestować,
- zmierzyć,
- zatwierdzić osobnym commitem.

Planowana kolejność:

- [ ] uporządkowanie typów, makr i konfiguracji FreeRTOS,
- [ ] ręczny zapis testowego rekordu do RAM,
- [ ] poprawny `Trace_FlushUart()`,
- [ ] osobny task transportowy,
- [ ] `TASK_SWITCHED_IN`,
- [ ] `TASK_SWITCHED_OUT`,
- [ ] tworzenie i usuwanie tasków,
- [ ] blokowanie oraz poprawne operacje na kolejkach,
- [ ] operacje kolejki wykonywane z ISR,
- [ ] instrumentacja mutexów,
- [ ] wejście i wyjście z wybranych ISR,
- [ ] raportowanie przepełnienia bufora,
- [ ] optymalizacja transmisji,
- [ ] dekoder po stronie PC,
- [ ] prosta oś czasu i raport wydajności,
- [ ] długotrwały test regresji.

## Metodyka eksperymentów

Projekt ma dokumentować nie tylko poprawną wersję, ale również drogę do jej uzyskania.

Przykładowy eksperyment:

1. przygotowanie celowo błędnej wersji odczytu ring buffera,
2. zwiększenie współbieżności i prawdopodobieństwa wyścigu,
3. zarejestrowanie przekłamanego rekordu,
4. odróżnienie przekłamania od zwykłego overflow,
5. dodanie lokalnej kopii i krótkiej sekcji krytycznej,
6. powtórzenie identycznego testu,
7. porównanie wyników.

Takie podejście daje materiał znacznie bardziej użyteczny niż sama końcowa implementacja. Pokazuje przyczynę błędu, warunki jego wystąpienia i dowód skuteczności poprawki.

## Budowanie projektu

Repozytorium zawiera projekt STM32, plik `.ioc`, sterowniki, źródła FreeRTOS, skrypt linkera i `Makefile`.

Wymagane narzędzia zależą od lokalnej konfiguracji, typowo:

- GNU Arm Embedded Toolchain,
- `make`,
- STM32CubeProgrammer lub OpenOCD,
- debug probe, na przykład ST-LINK,
- terminal lub skrypt zapisujący binarny strumień UART.

Podstawowy build:

```bash
git clone https://github.com/viki0202/F767_FreeRTOS.git
cd F767_FreeRTOS
make clean
make
```

Przed użyciem sprawdź nazwy targetów i ustawienia toolchaina w aktualnym `Makefile`.

## Test bazowy po każdej zmianie

1. Wykonaj clean build.
2. Sprawdź warningi w plikach trace.
3. Uruchom firmware przez co najmniej 30 sekund.
4. Zweryfikuj podstawowe działanie aplikacji.
5. Sprawdź licznik utraconych rekordów.
6. Sprawdź nagłówki ramek `0xAA 0x55`.
7. Zweryfikuj kolejność i spójność pól rekordu.
8. Upewnij się, że po flushu przerwania są włączone.

## Jak interpretować wyniki

Należy rozróżniać co najmniej cztery sytuacje:

- **utracony rekord**: bufor był pełny i producent świadomie odrzucił zdarzenie,
- **przekłamany rekord**: pola jednego rekordu pochodzą z różnych zapisów lub zostały zmienione w trakcie odczytu,
- **niepełna ramka**: transport wysłał nagłówek, ale nie wysłał kompletnego payloadu,
- **nieznany event**: dekoder nie zna identyfikatora, ale nadal może kontynuować analizę strumienia.

To rozróżnienie jest kluczowe. Sam brak zdarzenia nie dowodzi wyścigu, a błąd ramki UART nie musi oznaczać uszkodzenia ring buffera.

## Czego ten projekt ma nauczyć

Projekt ma prowadzić do praktycznych odpowiedzi na pytania:

- Jak mały może być rekord, aby nadal był użyteczny?
- Ile kosztuje timestamp i zapis do bufora?
- Kiedy trace zaczyna zmieniać zachowanie obserwowanego systemu?
- Jak udowodnić, że rekord jest spójny?
- Jak odróżnić problem synchronizacji od ograniczeń transportu?
- Które hooki FreeRTOS dają wartość, a które generują głównie szum?
- Jak zaprojektować logi, które pomagają po tygodniu, a nie tylko w chwili ich dodawania?
- Jak opisać ograniczenia logowania uczciwie i w sposób przydatny dla kolejnego inżyniera?

## Status

Projekt jest rozwijany eksperymentalnie. Interfejs, format rekordu i układ katalogów mogą się zmieniać wraz z kolejnymi testami.

Na obecnym etapie priorytetem jest:

1. poprawność ring buffera,
2. kontrolowana reprodukcja błędów współbieżności,
3. bezpieczny flush przez UART,
4. stopniowe dodawanie hooków FreeRTOS,
5. automatyczna walidacja logów po stronie PC.

## Repozytorium

Kod źródłowy:

<https://github.com/viki0202/F767_FreeRTOS>

## Autor i kontekst

Projekt powstaje jako praktyczne laboratorium embedded oraz materiał roboczy do rozwijania książki o sztuce logowania. Nacisk jest położony na rzeczywiste ograniczenia, błędy i kompromisy, a nie na prezentowanie wyłącznie idealnego wyniku końcowego.

## Licencja

Repozytorium zawiera również komponenty dostarczane przez STMicroelectronics, ARM/CMSIS i FreeRTOS, które mogą podlegać własnym licencjom i informacjom copyright zawartym w odpowiednich plikach źródłowych.

Przed dodaniem licencji dla kodu autorskiego należy sprawdzić zgodność z licencjami komponentów zależnych. Jeśli projekt ma być publicznie rozwijany, warto dodać osobny plik `LICENSE` oraz jasno określić, które pliki są kodem autorskim projektu.

## Współpraca

Issue i pull requesty są mile widziane, szczególnie w obszarach:

- poprawności współbieżnej,
- testów ring buffera,
- hooków FreeRTOS,
- dekodera i walidacji ramek,
- pomiaru narzutu,
- prezentacji osi czasu,
- przykładów błędów, które warto opisać w materiale o logowaniu.
