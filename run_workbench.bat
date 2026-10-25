@echo off
chcp 65001 >nul
echo [PsychSandbox] 正在准备启动科研 Web 工作台...

:: 检查并激活虚拟环境
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
) else (
    echo [警告] 未检测到 .venv 虚拟环境，将使用系统 Python 运行。
)

:: 确保运行产物目录存在
if not exist "%~dp0runs\runtime" mkdir "%~dp0runs\runtime"

echo [1/3] 正在启动后台长任务调度器 (Worker: long lane)...
start "PsychSandbox-Worker-Long" /b python -m psychsandbox.workbench.worker --lane long > "%~dp0runs\runtime\worker_long.log" 2>&1

echo [2/3] 正在启动交互短任务调度器 (Worker: short lane)...
start "PsychSandbox-Worker-Short" /b python -m psychsandbox.workbench.worker --lane short > "%~dp0runs\runtime\worker_short.log" 2>&1

echo [3/3] 正在启动 FastAPI Web 服务 (http://127.0.0.1:8000)...
echo ====================================================================
echo  PsychSandbox 科研工作台服务启动中...
echo  本地访问地址: http://127.0.0.1:8000
echo  要停止所有工作台后台进程，请运行: stop_workbench.bat
echo ====================================================================

python -m psychsandbox.workbench.server --host 127.0.0.1 --port 8000
