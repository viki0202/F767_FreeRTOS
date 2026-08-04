#pragma once

#ifdef __cplusplus

#include <cstdarg>

enum class LogLevel
{
    Error = 0,
    Warning,
    Info,
    Debug
};

void Logger_Log(LogLevel level, const char* format, ...);
void Logger_Log(LogLevel level, const char* format, std::va_list arguments);

#endif // __cplusplus
