# AgentNexus-J 一键启动脚本（Windows PowerShell）
#Requires -Version 5.1

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir     = Join-Path $ScriptDir "logs"
$LogFile    = Join-Path $LogDir "backend_stdout.log"
$PidFile    = Join-Path $ScriptDir ".backend.pid"
$script:backendPid = 0

function Write-Step { param($msg) Write-Host "`n▶ $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "  ⚠ $msg" -ForegroundColor Yellow }
function Write-Err  { param($msg) Write-Host "  ✗ $msg" -ForegroundColor Red }

function Stop-Backend {
    if ($script:backendPid -gt 0) {
        # taskkill /T 同时终止整个进程树（cmd.exe + uvicorn + python）
        taskkill /PID $script:backendPid /T /F 2>$null | Out-Null
        Write-Ok "后端已停止"
        $script:backendPid = 0
    }
    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

Set-Location $ScriptDir

try {
    # ── 1. 前置检查 ────────────────────────────────────────────────
    Write-Step "检查依赖..."

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Err "未找到 docker，请先安装 Docker Desktop：https://www.docker.com/products/docker-desktop"
        exit 1
    }
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Err "Docker 未运行，请先启动 Docker Desktop"
        exit 1
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Err "未找到 uv，安装方式：powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""
        exit 1
    }
    Write-Ok "依赖检查通过"

    # ── 2. 检查 .env ───────────────────────────────────────────────
    if (-not (Test-Path (Join-Path $ScriptDir ".env"))) {
        Copy-Item (Join-Path $ScriptDir ".env.example") (Join-Path $ScriptDir ".env")
        Write-Warn ".env 不存在，已从 .env.example 自动复制，LLM API Key 可在界面中配置"
    }

    # ── 3. 启动数据库 ──────────────────────────────────────────────
    Write-Step "启动 PostgreSQL..."
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { Write-Err "docker compose up 失败"; exit 1 }

    Write-Host "  等待数据库就绪" -NoNewline
    $waited = 0
    while ($true) {
        $out = docker compose ps 2>$null | Out-String
        if ($out -match "\(healthy\)") { break }
        if ($waited -ge 30) {
            Write-Host ""
            Write-Err "数据库启动超时（30s），请检查：docker compose logs"
            exit 1
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
        $waited += 2
    }
    Write-Host ""
    Write-Ok "数据库已就绪"

    # ── 4. 数据库迁移 ──────────────────────────────────────────────
    Write-Step "执行数据库迁移..."
    uv run alembic -c api/alembic.ini upgrade head
    if ($LASTEXITCODE -ne 0) { Write-Err "数据库迁移失败"; exit 1 }
    Write-Ok "迁移完成"

    # ── 5. 启动后端 ────────────────────────────────────────────────
    Write-Step "启动后端（http://localhost:8000）..."
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

    # 清理残留进程
    if (Test-Path $PidFile) {
        $oldPid = [int](Get-Content $PidFile -ErrorAction SilentlyContinue)
        if ($oldPid -gt 0) {
            taskkill /PID $oldPid /T /F 2>$null | Out-Null
        }
        Remove-Item $PidFile -Force
        Start-Sleep -Seconds 1
    }

    # 用 cmd /c 启动，使 >> 重定向和 2>&1 合并输出到同一日志文件
    $proc = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList "/c", "uv run python main.py >> `"$LogFile`" 2>&1" `
        -PassThru -NoNewWindow
    $script:backendPid = $proc.Id
    $script:backendPid | Set-Content $PidFile

    Write-Host "  等待后端就绪（首次启动会下载嵌入模型，约需 1-2 分钟）" -NoNewline
    $waited = 0
    while ($true) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/health" `
                 -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
            if ($r.StatusCode -eq 200) { break }
        } catch {}
        if ($waited -ge 120) {
            Write-Host ""
            Write-Err "后端启动超时，请查看日志：$LogFile"
            exit 1
        }
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 2
        $waited += 2
    }
    Write-Host ""
    Write-Ok "后端已就绪"

    # ── 6. 启动前端 ────────────────────────────────────────────────
    Write-Host ""
    $line = "━" * 51
    Write-Host $line -ForegroundColor Green
    Write-Host "  AgentNexus-J 启动完成" -ForegroundColor Green
    Write-Host "  控制台：http://localhost:8501" -ForegroundColor Green
    Write-Host "  API：   http://localhost:8000/docs" -ForegroundColor Green
    Write-Host "  日志：  logs\backend_stdout.log" -ForegroundColor Green
    Write-Host "  Ctrl+C 停止前端和后端（数据库继续运行）" -ForegroundColor Green
    Write-Host $line -ForegroundColor Green
    Write-Host ""

    uv run streamlit run app.py

} finally {
    Write-Host ""
    Write-Warn "正在关闭服务..."
    Stop-Backend
    Write-Warn "数据库仍在后台运行，如需关闭：docker compose down"
}
