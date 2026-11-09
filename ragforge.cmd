@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Run setup.cmd first. 1>&2
    exit /b 2
)
set "PYTHONIOENCODING=utf-8"
set "OTEL_SDK_DISABLED=true"
"%~dp0.venv\Scripts\python.exe" -m ragforge.quickstart --project "%~dp0." %*
exit /b %errorlevel%
