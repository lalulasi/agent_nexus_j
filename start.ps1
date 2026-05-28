# AgentNexus-J 一键启动脚本 (Windows)
$ErrorActionPreference = "Stop"
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$LogDir    = "$ScriptDir\logs"
$LogFile   = "$LogDir\backend_stdout.log"
$ErrFile   = "$LogDir\backend_stderr.log"
$PidFile   = "$ScriptDir\.backend.pid"

function step { param($m); Write-Host "`n> $m" -ForegroundColor Cyan }
function ok   { param($m); Write-Host "  [OK] $m" -ForegroundColor Green }
function warn { param($m); Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function fail { param($m); Write-Host "  [ERR] $m" -ForegroundColor Red; exit 1 }

function cleanup {
    Write-Host ""
    warn "Shutting down..."
    if (Test-Path $PidFile) {
        $p = (Get-Content $PidFile -Raw).Trim()
        if (Get-Process -Id ([int]$p) -ErrorAction SilentlyContinue) {
            & taskkill /PID $p /T /F 2>$null | Out-Null
            ok "Backend stopped"
        }
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
    warn "Database still running. To stop: docker compose down"
}

try {
    Set-Location $ScriptDir

    Write-Host ""
    Write-Host "AgentNexus-J - Windows Startup" -ForegroundColor Cyan
    Write-Host "===============================" -ForegroundColor Cyan

    # 1. Prerequisites
    step "Checking prerequisites..."
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        fail "docker not found. Install Docker Desktop: https://www.docker.com/products/docker-desktop"
    }
    cmd /c "docker info >nul 2>&1"
    if ($LASTEXITCODE -ne 0) { fail "Docker is not running. Please start Docker Desktop." }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        fail "uv not found. Install: powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""
    }
    ok "Prerequisites OK"

    # 2. Check .env
    if (-not (Test-Path "$ScriptDir\.env")) {
        Copy-Item "$ScriptDir\.env.example" "$ScriptDir\.env"
        warn ".env copied from .env.example - API keys can be configured in the UI"
    }

    # 3. Start database
    step "Starting PostgreSQL..."
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { fail "docker compose up failed" }

    Write-Host "  Waiting for database" -NoNewline
    $waited = 0
    while ($true) {
        Start-Sleep 2; $waited += 2
        if ((cmd /c "docker compose ps 2>nul") -match '\(healthy\)') {
            Write-Host " ready"; break
        }
        Write-Host "." -NoNewline
        if ($waited -ge 30) { Write-Host ""; fail "Database timeout. Check: docker compose logs" }
    }
    ok "Database ready"

    # 4. Migrations
    step "Running database migrations..."
    uv run alembic -c api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { fail "Migration failed" }
    ok "Migrations done"

    # 5. Start backend
    step "Starting backend (http://localhost:8000)..."
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory $LogDir | Out-Null }

    if (Test-Path $PidFile) {
        $oldPid = (Get-Content $PidFile -Raw).Trim()
        if (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue) {
            & taskkill /PID $oldPid /T /F 2>$null | Out-Null
            Start-Sleep 1
        }
        Remove-Item $PidFile -Force
    }

    # Prevent huggingface_hub from attempting symlinks (WinError 1314 without Developer Mode)
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

    $proc = Start-Process uv `
        -ArgumentList "run", "python", "main.py" `
        -WorkingDirectory $ScriptDir `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrFile `
        -PassThru -NoNewWindow
    $proc.Id | Set-Content $PidFile -NoNewline

    Write-Host "  Waiting for backend (first run downloads ~90MB model, up to 2 min)..." -NoNewline
    # Use a proxy-less session so corporate proxy settings don't block localhost
    $_noProxy = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $_noProxy.Proxy = New-Object System.Net.WebProxy
    $waited = 0
    while ($true) {
        Start-Sleep 2; $waited += 2
        try {
            Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -WebSession $_noProxy -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
            Write-Host " ready"; break
        } catch {}
        Write-Host "." -NoNewline
        if ($waited -ge 120) { Write-Host ""; fail "Backend timeout. Check log: $LogFile" }
    }
    ok "Backend ready"

    # 6. Start frontend
    Write-Host ""
    Write-Host "===============================" -ForegroundColor Green
    Write-Host "  AgentNexus-J is running" -ForegroundColor Green
    Write-Host "  UI:  http://localhost:8501" -ForegroundColor Green
    Write-Host "  API: http://localhost:8000/docs" -ForegroundColor Green
    Write-Host "  Log: logs\backend_stdout.log" -ForegroundColor Green
    Write-Host "  Ctrl+C to stop" -ForegroundColor Green
    Write-Host "===============================" -ForegroundColor Green
    Write-Host ""

    uv run streamlit run app.py

} finally {
    cleanup
}
