@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LOG_DIR=%~dp0logs"
set "LOG_FILE=%LOG_DIR%\backend_stdout.log"
set "PID_FILE=%~dp0.backend.pid"

echo.
echo AgentNexus-J - Windows 启动脚本
echo =========================================================

:: ── 1. 前置检查 ────────────────────────────────────────────────
echo.
echo ^> 检查依赖...

where docker >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 docker，请先安装 Docker Desktop
    echo          https://www.docker.com/products/docker-desktop
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo   [错误] Docker 未运行，请先启动 Docker Desktop
    exit /b 1
)
where uv >nul 2>&1
if errorlevel 1 (
    echo   [错误] 未找到 uv
    echo          安装方式：powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
    exit /b 1
)
echo   [OK] 依赖检查通过

:: ── 2. 检查 .env ────────────────────────────────────────────────
if not exist "%~dp0.env" (
    copy "%~dp0.env.example" "%~dp0.env" >nul
    echo   [提示] .env 不存在，已从 .env.example 自动复制
    echo          LLM API Key 可在界面中配置，无需手动填写
)

:: ── 3. 启动数据库 ──────────────────────────────────────────────
echo.
echo ^> 启动 PostgreSQL...
docker compose up -d
if errorlevel 1 (
    echo   [错误] docker compose up 失败
    exit /b 1
)

set /a WAITED=0
echo   等待数据库就绪...
:WAIT_DB
docker compose ps 2>nul | findstr /c:"(healthy)" >nul
if not errorlevel 1 goto DB_READY
if !WAITED! geq 30 (
    echo   [错误] 数据库启动超时（30s），请检查：docker compose logs
    exit /b 1
)
timeout /t 2 /nobreak >nul
set /a WAITED+=2
goto WAIT_DB
:DB_READY
echo   [OK] 数据库已就绪

:: ── 4. 数据库迁移 ──────────────────────────────────────────────
echo.
echo ^> 执行数据库迁移...
uv run alembic -c api/alembic.ini upgrade head
if errorlevel 1 (
    echo   [错误] 数据库迁移失败
    exit /b 1
)
echo   [OK] 迁移完成

:: ── 5. 启动后端 ────────────────────────────────────────────────
echo.
echo ^> 启动后端（http://localhost:8000）...
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: 清理残留进程
if exist "%PID_FILE%" (
    for /f "usebackq" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F >nul 2>&1
    )
    del "%PID_FILE%" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

:: 后台启动并通过 PowerShell 捕获 PID（/T /F 清理时可杀整个进程树）
powershell -NoProfile -Command ^
    "$p = Start-Process cmd -ArgumentList '/c','uv run python main.py >> \"%LOG_FILE%\" 2>&1' -PassThru -NoNewWindow; $p.Id" ^
    > "%PID_FILE%"
for /f "usebackq" %%p in ("%PID_FILE%") do set BACKEND_PID=%%p
echo   [后台] PID=%BACKEND_PID%，日志：%LOG_FILE%

echo   等待后端就绪（首次启动会下载嵌入模型，约需 1-2 分钟）...
set /a WAITED=0
:WAIT_BACKEND
curl -sf http://localhost:8000/health >nul 2>&1
if not errorlevel 1 goto BACKEND_READY
if !WAITED! geq 120 (
    echo   [错误] 后端启动超时，请查看日志：%LOG_FILE%
    goto CLEANUP
)
timeout /t 2 /nobreak >nul
set /a WAITED+=2
goto WAIT_BACKEND
:BACKEND_READY
echo   [OK] 后端已就绪

:: ── 6. 启动前端 ────────────────────────────────────────────────
echo.
echo =========================================================
echo   AgentNexus-J 启动完成
echo   控制台：http://localhost:8501
echo   API：   http://localhost:8000/docs
echo   日志：  logs\backend_stdout.log
echo   Ctrl+C 停止前端（按 Y 确认退出批处理）
echo =========================================================
echo.

uv run streamlit run app.py

:: ── 退出清理 ──────────────────────────────────────────────────
:CLEANUP
echo.
echo   正在关闭服务...
if exist "%PID_FILE%" (
    for /f "usebackq" %%p in ("%PID_FILE%") do (
        taskkill /PID %%p /T /F >nul 2>&1
    )
    del "%PID_FILE%" >nul 2>&1
    echo   [OK] 后端已停止
)
echo   [提示] 数据库仍在后台运行，如需关闭：docker compose down
endlocal
