@echo off
rem ============================================================
rem  PsychSandbox Scientific Workbench Stop Script
rem  Maintenance: this file must stay ASCII-only.
rem ============================================================

cd /d "%~dp0"

set PY=%~dp0.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

"%PY%" -m psychsandbox.workbench.stop
