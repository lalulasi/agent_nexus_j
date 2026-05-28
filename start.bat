@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LOG_DIR=%~dp0logs"
set "LOG_FILE=%LOG_DIR%\backend_stdout.log"
set "PID_FILE=%~dp0.backend.pid"

echo.
echo AgentNexus-J - Windows Startup Script
echo =========================================================

:: ── 1. Check prerequisites ─────────────────────────────────────
echo.
echo ^> Checking prerequisites...

where docker >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] docker not found. Please install Docker Desktop:
    echo          https://www.docker.com/products/docker-desktop
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Docker is not running. Please start Docker Desktop.
    exit /b 1
)
where uv >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] uv not found.
    echo          Install: powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    exit /b 1
)
echo   [OK] Prerequisites check passed

:: ── 2. Check .env ──────────────────────────────────────────────
if not exist "%~dp0.env" (
    copy "%~dp0.env.example" "%~dp0.env" >nul
    echo   [INFO] .env not found, copied from .env.example
    echo          LLM API keys can be configured in the UI
)

:: ── 3. Start database ──────────────────────────────────────────
echo.
echo ^> Starting PostgreSQL...
docker compose up -d
if errorlevel 1 (
    echo   [ERROR] docker compose up failed
    exit /b 1
)

set /a WAITED=0
echo   Waiting for database to be ready...
:WAIT_DB
docker compose ps 2>nul | findstr /c:"(healthy)" >nul
if not errorlevel 1 goto DB_READY
if !WAITED! geq 30 (
    echo.
    echo   [ERROR] Database startup timed out (30s). Check: docker compose logs
    exit /b 1
)
<nul set /p TEMP_DOT=.
timeout /t 2 /nobreak >nul
set /a WAITED+=2
goto WAIT_DB
:DB_READY
echo.
echo   [OK] Database is ready

:: ── 4. Run database migrations ─────────────────────────────────
echo.
echo ^> Running database migrations...
uv run alembic -c api/alembic.ini upgrade head
if errorlevel 1 (
    echo   [ERROR] Database migration failed
    exit /b 1
)
echo   [OK] Migrations complete

:: ── 5. Start backend ───────────────────────────────────────────
echo.
echo ^> Starting backend (http://localhost:8000)...
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Kill any leftover backend process
if exist "%PID_FILE%" (
    for /f "usebackq" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F >nul 2>&1
    )
    del "%PID_FILE%" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

:: Start backend in background, capture PID via PowerShell
powershell -NoProfile -Command ^
    "$p = Start-Process cmd -ArgumentList '/c','uv run python main.py >> \"%LOG_FILE%\" 2>&1' -PassThru -NoNewWindow; $p.Id" ^
    > "%PID_FILE%"
for /f "usebackq" %%p in ("%PID_FILE%") do set BACKEND_PID=%%p
echo   [INFO] Backend PID=%BACKEND_PID%, log: %LOG_FILE%

echo   Waiting for backend (first run downloads ~90MB model, up to 2 min)...
echo   Streaming log output below:
echo   -------------------------------------------------------
set /a WAITED=0
:WAIT_BACKEND
curl -sf http://localhost:8000/health >nul 2>&1
if not errorlevel 1 goto BACKEND_READY
if !WAITED! geq 120 (
    echo   -------------------------------------------------------
    echo   [ERROR] Backend startup timed out. Check log: %LOG_FILE%
    goto CLEANUP
)
timeout /t 2 /nobreak >nul
set /a WAITED+=2
powershell -NoProfile -Command ^
    "if (Test-Path '%LOG_FILE%') { $l = Get-Content '%LOG_FILE%' -Tail 1; if ($l) { Write-Host '  ' $l } }"
goto WAIT_BACKEND
:BACKEND_READY
echo   -------------------------------------------------------
echo   [OK] Backend is ready

:: ── 6. Start frontend ──────────────────────────────────────────
echo.
echo =========================================================
echo   AgentNexus-J is running
echo   UI:  http://localhost:8501
echo   API: http://localhost:8000/docs
echo   Log: logs\backend_stdout.log
echo   Press Ctrl+C to stop (enter Y to confirm)
echo =========================================================
echo.

uv run streamlit run app.py

:: ── Cleanup on exit ────────────────────────────────────────────
:CLEANUP
echo.
echo   Shutting down...
if exist "%PID_FILE%" (
    for /f "usebackq" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F >nul 2>&1
    )
    del "%PID_FILE%" >nul 2>&1
    echo   [OK] Backend stopped
)
echo   [INFO] Database is still running. To stop it: docker compose down
endlocal
