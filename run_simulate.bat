@echo off
rem 切换到 UTF-8 代码页，避免中文乱码
chcp 65001 >nul
rem ============================================================
rem  psych-sandbox 模拟运行脚本
rem  双击即可打开 CMD、进入项目目录并执行 simulate 指令
rem ============================================================

rem 切换到脚本所在目录（即项目根目录）
cd /d "%~dp0"

rem 激活虚拟环境
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] 虚拟环境激活失败，请确认 .venv 目录存在。
    pause
    exit /b 1
)

rem 执行模拟指令
psych-sandbox simulate --case psycheval-cbt-001 --sessions 1 --rollouts 3 --rollout-concurrency 2 --judge-concurrency 2

rem 结束前暂停，方便查看运行结果
echo.
echo ============================================================
echo 运行结束，按任意键关闭窗口...
pause >nul
