@echo off
rem ============================================================
rem  psych-sandbox simulate launcher
rem  Double-click to open a CMD window in the project root and run
rem  one simulation. Adjustable parameters are grouped below.
rem  Probability-weighted (logprob) scoring is on by default.
rem
rem  Usage:
rem    run_simulate.bat          run one simulation with the parameters below
rem    run_simulate.bat probe    run only the endpoint logprobs probe and print
rem                              the full record
rem
rem  Maintenance: this file must stay ASCII-only, and must not call chcp.
rem  cmd re-reads a batch file with the codepage that is active while reading
rem  it, so any non-ASCII byte makes the parser lose its line position and it
rem  then executes fragments of this file as commands ("... is not recognized",
rem  and a stray "cmd" fragment can even spawn a nested shell).
rem  User-facing Chinese text is therefore printed through Python unicode
rem  escapes below, which CMD windows and redirected logs both render fine.
rem ============================================================

rem Work in the project root (the directory of this script)
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe

rem Activate the virtual environment
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo [ERROR] Virtual environment activation failed; check that .venv exists.
    pause
    exit /b 1
)

rem ---------- Adjustable parameters ----------
set CASE_ID=psycheval-cbt-001
set SESSIONS=3
rem Max counselor turns per session (1..50); 8 matches the runtime default
set TURNS=8
set ROLLOUTS=3
rem Candidate generation/scoring concurrency. Leave empty to follow ROLLOUTS
rem (no trailing wave with fewer candidates than slots); a number caps the load.
set ROLLOUT_CONCURRENCY=
set JUDGE_CONCURRENCY=
rem 1 = probability-weighted (logprob) scoring ON (default); 0 = item average
set LOGPROB_SCORING=1
rem 1 = probe the endpoint and keep the record before simulating (default);
rem     0 = skip the probe
set PROBE_LOGPROB=1
rem Instrument used by the probe: any non-composite key, e.g. wai/ctrs/bdi_ii
set PROBE_INSTRUMENT=wai
rem Transient retry attempts per model call (3 = the previous fixed budget).
rem Raise it to survive a 5xx storm; the OpenAI SDK adds its own retries.
set MODEL_MAX_ATTEMPTS=6

if /i "%~1"=="probe" set PROBE_ONLY=1

rem "run_simulate.bat probe": probe only and print the full record
if defined PROBE_ONLY (
    psych-sandbox probe logprob-scoring --case %CASE_ID% --instrument %PROBE_INSTRUMENT% --json
    goto :done
)

rem Step 1: verify the endpoint returns logprobs (record kept under runs\runtime)
if "%PROBE_LOGPROB%"=="1" (
    psych-sandbox probe logprob-scoring --case %CASE_ID% --instrument %PROBE_INSTRUMENT%
    if errorlevel 1 (
        echo.
        %PY% -c "print('\u7aef\u70b9\u672a\u8fd4\u56de\u53ef\u7528\u7684 logprobs\uff0clogprob \u8bc4\u5206\u4f1a\u660e\u786e\u5931\u8d25\uff0c\u5df2\u4e2d\u6b62\u672c\u6b21\u8fd0\u884c\u3002')"
        echo   Check MODEL_BASE_URL and SUPERVISOR_MODEL, or set LOGPROB_SCORING=0 and rerun.
        pause
        exit /b 1
    )
)

rem Step 2: assemble the logprob scoring switch
set LOGPROB_ARG=
if "%LOGPROB_SCORING%"=="1" set LOGPROB_ARG=--logprob-scoring

rem Step 2b: pass concurrency overrides only when they were set above
set CONCURRENCY_ARGS=
if not "%ROLLOUT_CONCURRENCY%"=="" set CONCURRENCY_ARGS=%CONCURRENCY_ARGS% --rollout-concurrency %ROLLOUT_CONCURRENCY%
if not "%JUDGE_CONCURRENCY%"=="" set CONCURRENCY_ARGS=%CONCURRENCY_ARGS% --judge-concurrency %JUDGE_CONCURRENCY%

rem Step 3: run the simulation (session candidates and weighted scoring)
psych-sandbox simulate ^
  --case %CASE_ID% ^
  --sessions %SESSIONS% ^
  --max-turns %TURNS% ^
  --rollouts %ROLLOUTS% ^
  %CONCURRENCY_ARGS% ^
  %LOGPROB_ARG%

:done
set RUN_EXIT=%ERRORLEVEL%
echo.
echo ============================================================
%PY% -c "print('\u8fd0\u884c\u7ed3\u675f\uff0c\u6309\u4efb\u610f\u952e\u5173\u95ed\u7a97\u53e3...')"
pause >nul
exit /b %RUN_EXIT%
