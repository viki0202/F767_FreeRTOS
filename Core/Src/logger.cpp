#include "logger.hpp"

#include "main.h"

#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>

extern "C" UART_HandleTypeDef huart3;

namespace
{

constexpr std::size_t LogBufferSize = 256U;

const char* levelToText(LogLevel level)
{
    switch (level)
    {
        case LogLevel::Error:
            return "ERROR";

        case LogLevel::Warning:
            return "WARN";

        case LogLevel::Info:
            return "INFO";

        case LogLevel::Debug:
            return "DEBUG";

        default:
            return "UNKNOWN";
    }
}

} // namespace

void Logger_Log(
    LogLevel level,
    const char* format,
    ...)
{
    if (format == nullptr)
    {
        return;
    }

    char buffer[LogBufferSize]{};

    const int prefixLength = std::snprintf(
        buffer,
        sizeof(buffer),
        "[%s] ",
        levelToText(level));

    if ((prefixLength < 0) ||
        (static_cast<std::size_t>(prefixLength) >= sizeof(buffer)))
    {
        return;
    }

    va_list arguments;
    va_start(arguments, format);

    const int messageLength = std::vsnprintf(
        buffer + prefixLength,
        sizeof(buffer) - static_cast<std::size_t>(prefixLength),
        format,
        arguments);

    va_end(arguments);

    if (messageLength < 0)
    {
        return;
    }

    std::size_t used = std::strlen(buffer);

    if ((used + 2U) < sizeof(buffer))
    {
        buffer[used++] = '\r';
        buffer[used++] = '\n';
        buffer[used] = '\0';
    }

    HAL_UART_Transmit(
        &huart3,
        reinterpret_cast<const std::uint8_t*>(buffer),
        static_cast<std::uint16_t>(used),
        100U);
}