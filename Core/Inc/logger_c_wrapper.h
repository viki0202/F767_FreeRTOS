#pragma once

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    LOG_LEVEL_C_Error = 0,
    LOG_LEVEL_C_Warning,
    LOG_LEVEL_C_Info,
    LOG_LEVEL_C_Debug
} LogLevel_C;

void Logger_Log_C(LogLevel_C level, const char* format, ...);

#define LOGE_C(format, ...) \
    Logger_Log_C(LOG_LEVEL_C_Error, format, ##__VA_ARGS__)

#define LOGW_C(format, ...) \
    Logger_Log_C(LOG_LEVEL_C_Warning, format, ##__VA_ARGS__)

#define LOGI_C(format, ...) \
    Logger_Log_C(LOG_LEVEL_C_Info, format, ##__VA_ARGS__)

#define LOGD_C(format, ...) \
    Logger_Log_C(LOG_LEVEL_C_Debug, format, ##__VA_ARGS__)

#ifdef __cplusplus
}
#endif
