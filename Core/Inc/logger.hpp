#pragma once

#ifdef __cplusplus

enum class LogLevel
{
    Error = 0,
    Warning,
    Info,
    Debug
};

void Logger_Log(LogLevel level, const char* format, ...);

#endif // __cplusplus
