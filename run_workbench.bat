@echo off
rem ============================================================
rem  PsychSandbox Scientific Workbench Launcher
rem  Maintenance: this file must stay ASCII-only.
rem ============================================================

cd /d "%~dp0"

set PY=%~dp0.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [ERROR] Virtual environment python not found at:
    echo   %PY%
    echo Please make sure .venv is created and packages are installed.
    pause
    exit /b 1
)

"%PY%" -B -m psychsandbox.workbench.stop --check
if errorlevel 1 (
    pause
    exit /b 1
)

if not exist "%~dp0runs\runtime" mkdir "%~dp0runs\runtime"

"%PY%" -B -c "from psychsandbox.workbench.db import init_db; init_db()"
if errorlevel 1 exit /b 1

echo [PsychSandbox] Starting Scientific Workbench...
echo.

echo [1/3] Starting background long-lane worker...
start "PsychSandbox-Worker-Long" /b "%PY%" -B -u -m psychsandbox.workbench.worker --lane long >> "%~dp0runs\runtime\worker_long.log" 2>&1

echo [2/3] Starting background short-lane worker...
start "PsychSandbox-Worker-Short" /b "%PY%" -B -u -m psychsandbox.workbench.worker --lane short >> "%~dp0runs\runtime\worker_short.log" 2>&1

echo [3/3] Starting Web server on http://127.0.0.1:8001 ...
echo ====================================================================
echo   PsychSandbox Scientific Workbench is running!
echo   Open in browser: http://127.0.0.1:8001
echo   To stop all workbench processes: run stop_workbench.bat
echo ====================================================================

"%PY%" -m psychsandbox.workbench.server --host 127.0.0.1 --port 8001
