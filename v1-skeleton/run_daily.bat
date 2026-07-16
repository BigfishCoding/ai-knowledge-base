@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ═══════════════════════════════════════════════════════════════
::  AI Knowledge Base — 每日定时执行启动脚本
::  由 Windows 任务计划程序在每天 09:00 调用
:: ═══════════════════════════════════════════════════════════════

:: 切换到项目目录
cd /d "E:\openCode\ai-knowledge-base\v1-skeleton"

:: 创建日志目录
if not exist "logs" mkdir logs

:: 生成当日日志文件名
for /f "tokens=1-3 delims=/" %%a in ("%date%") do (
    set LOGDATE=%%c%%a%%b
)

:: 激活虚拟环境（如果存在）
if exist ".venv\Scripts\activate.bat" (
    echo [%date% %time%] 激活虚拟环境...
    call .venv\Scripts\activate.bat
) else (
    echo [%date% %time%] 未找到虚拟环境，使用系统 Python
)

:: 加载 .env 环境变量
if exist ".env" (
    echo [%date% %time%] 加载 .env 环境变量...
    for /f "usebackq tokens=1,2 delims== eol=#" %%a in (".env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
) else (
    echo [%date% %time%] 警告: .env 文件不存在
)

:: 执行 pipeline
echo [%date% %time%] 开始执行 Pipeline...
python run_pipeline.py >> "logs\pipeline-%LOGDATE%.log" 2>&1

:: 检查执行结果
if %ERRORLEVEL% neq 0 (
    echo [%date% %time%] Pipeline 失败! exit code: %ERRORLEVEL% >> "logs\pipeline-error.log"
) else (
    echo [%date% %time%] Pipeline 执行成功 >> "logs\pipeline-%LOGDATE%.log"
)

endlocal
