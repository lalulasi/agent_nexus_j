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

:: Wait inside a single PowerShell process (avoids repeated-spawn Ctrl+C issues)
powershell -NoProfile -Command "$w=0; Write-Host -NoNewline '  Waiting for database'; while ($w -lt 30) { $o = docker compose ps 2>$null | Out-String; if ($o -match '\(healthy\)') { Write-Host ' ready'; exit 0 }; Write-Host -NoNewline '.'; Start-Sleep -Seconds 2; $w+=2 }; Write-Host ' timed out'; exit 1"
if errorlevel 1 (
    echo   [ERROR] Database startup timed out ^(30s^). Check: docker compose logs
    exit /b 1
)
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
    powershell -NoProfile -Command "Start-Sleep -Seconds 1"
)

:: Start backend in background, capture PID via PowerShell
powershell -NoProfile -Command "$p = Start-Process cmd -ArgumentList '/c','uv run python main.py >> \"%LOG_FILE%\" 2>&1' -PassThru -NoNewWindow; $p.Id" > "%PID_FILE%"
for /f "usebackq" %%p in ("%PID_FILE%") do set BACKEND_PID=%%p
echo   [INFO] Backend PID=%BACKEND_PID%, log: %LOG_FILE%

:: Wait inside a single PowerShell process, streaming new log lines as they appear
echo   Waiting for backend (first run downloads ~90MB model, up to 2 min)...
echo   -------------------------------------------------------
set "PS_LOG=%LOG_FILE%"
powershell -NoProfile -Command "$w=0; $n=0; while ($w -lt 120) { Start-Sleep -Seconds 2; $w+=2; try { $null = Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; exit 0 } catch {}; if (Test-Path $env:PS_LOG) { $lines = Get-Content $env:PS_LOG; if ($lines -and $lines.Count -gt $n) { foreach ($l in $lines[$n..($lines.Count-1)]) { Write-Host ('  ' + $l) }; $n = $lines.Count } } }; exit 1"
echo   -------------------------------------------------------
if errorlevel 1 (
    echo   [ERROR] Backend startup timed out. Check log: %LOG_FILE%
    goto CLEANUP
)
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
