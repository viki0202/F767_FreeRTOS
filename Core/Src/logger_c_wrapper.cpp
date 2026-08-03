#include "logger.hpp"
#include "logger_c_wrapper.h"
#include <cstdarg>

extern "C" void Logger_Log_C(LogLevel_C level_c, const char* format, ...)
{
    LogLevel level_cpp = static_cast<LogLevel>(level_c);

    va_list args;
    va_start(args, format);

    Logger_Log(level_cpp, format, args);

    va_end(args);
}
