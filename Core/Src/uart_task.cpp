#include "uart_task.hpp"
#include "main.h"
#include "FreeRTOS.h"
#include "task.h"
#include <cstring>

extern "C" UART_HandleTypeDef huart3;

namespace
{
void uartTask(void* argument)
{
    (void)argument;

    const char* msg = "UART task alive!\r\n";

    while (true)
    {
        HAL_UART_Transmit(&huart3,
                          reinterpret_cast<const uint8_t*>(msg),
                          std::strlen(msg),
                          100);

        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
}

extern "C" void UartTask_Start(void)
{
    xTaskCreate(
        uartTask,
        "UART",
        256,
        nullptr,
        tskIDLE_PRIORITY + 1,
        nullptr
    );
}
