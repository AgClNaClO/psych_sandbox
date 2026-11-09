@echo off
setlocal
rem Opt-in only for this launcher. Existing launchers and defaults are unchanged.
set PSYCHSANDBOX_SKILL_EXPERIMENT=1
call "%~dp0run_workbench.bat"
endlocal
