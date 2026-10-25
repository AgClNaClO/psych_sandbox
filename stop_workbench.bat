@echo off
chcp 65001 >nul
echo [PsychSandbox] 正在停止科研 Web 工作台及相关后台 Worker 进程...

:: 查找监听 8000 端口的进程并终止
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo [停止] 正在终止监听端口 8000 的 Web 服务进程 (PID: %%a)...
    taskkill /F /PID %%a >nul 2>&1
)

:: 查找后台 Worker 进程并终止
powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*psychsandbox.workbench.worker*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

echo [PsychSandbox] 科研 Web 工作台服务及后台 Worker 已全部停止。
