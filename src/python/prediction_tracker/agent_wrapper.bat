@echo off
setlocal EnableDelayedExpansion

rem Wrapper for direct prediction loop that injects hint generator (Windows)
rem Usage: agent_wrapper.bat <agent_id> <interval_seconds>

set AGENT_ID=%1
set INTERVAL=%2

if "%AGENT_ID%"=="" (
    echo [Wrapper] ERROR: agent_id argument is required.
    echo [Wrapper] Usage: agent_wrapper.bat ^<agent_id^> ^<interval_seconds^>
    exit /b 1
)

if "%INTERVAL%"=="" (
    echo [Wrapper] ERROR: interval argument is required.
    echo [Wrapper] Usage: agent_wrapper.bat ^<agent_id^> ^<interval_seconds^>
    exit /b 1
)

rem Derive project root using git (must be run inside the repo)
for /f "tokens=*" %%a in ('git rev-parse --show-toplevel') do set PROJECT_ROOT=%%a

if "%PROJECT_ROOT%"=="" (
    echo [Wrapper] ERROR: Could not determine PROJECT_ROOT. Make sure you are inside a git repository.
    exit /b 1
)

echo [Wrapper] PROJECT_ROOT=%PROJECT_ROOT%

rem Load global config/.env via temp batch file (safer than for/f parsing)
set ENV_LOADER=%PROJECT_ROOT%\src\python\prediction_tracker\load_env.py
set GLOBAL_ENV=%PROJECT_ROOT%\config\.env
if exist "%GLOBAL_ENV%" (
    python "%ENV_LOADER%" "%GLOBAL_ENV%" > "%TEMP%\awp_env_global.bat" 2>nul
    if exist "%TEMP%\awp_env_global.bat" (
        call "%TEMP%\awp_env_global.bat"
        del "%TEMP%\awp_env_global.bat"
    )
)

rem Load agent-specific .env (overrides)
set AGENT_ENV=%PROJECT_ROOT%\agents\%AGENT_ID%\.env
if exist "%AGENT_ENV%" (
    python "%ENV_LOADER%" "%AGENT_ENV%" > "%TEMP%\awp_env_agent.bat" 2>nul
    if exist "%TEMP%\awp_env_agent.bat" (
        call "%TEMP%\awp_env_agent.bat"
        del "%TEMP%\awp_env_agent.bat"
    )
)

rem Set HOME for wallet operations
set HOME=%PROJECT_ROOT%\agents\%AGENT_ID%\home

rem Activate Python virtual environment if present
if exist "%PROJECT_ROOT%\.venv\Scripts\activate.bat" (
    call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
)

rem Verify Rust binary exists (cargo build --release produces predict-agent.exe on Windows)
if exist "%PROJECT_ROOT%\predict-agent.exe" (
    set PREDICT_BIN=%PROJECT_ROOT%\predict-agent.exe
) else if exist "%PROJECT_ROOT%\predict-agent" (
    set PREDICT_BIN=%PROJECT_ROOT%\predict-agent
) else (
    echo [Wrapper] ERROR: predict-agent binary not found. Run: cargo build --release
    exit /b 1
)

echo [Wrapper] Predict binary: %PREDICT_BIN%

:loop
    echo [Wrapper] Starting iteration for %AGENT_ID% at %date% %time%

    rem 1. Run hint generator (Python)
    python "%PROJECT_ROOT%\src\python\prediction_tracker\hint_generator.py" --agent %AGENT_ID%

    rem 2. Run prediction (Rust) - single iteration
    "%PREDICT_BIN%" loop --agent-id %AGENT_ID% --interval %INTERVAL% --max-iterations 1

    echo [Wrapper] Iteration complete, sleeping for %INTERVAL%s...
    timeout /t %INTERVAL% /nobreak >nul
    goto loop
