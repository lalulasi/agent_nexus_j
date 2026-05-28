#!/usr/bin/env bash
# AgentNexus-J 一键启动脚本
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"
BACKEND_PID_FILE="$SCRIPT_DIR/.backend.pid"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

step() { echo -e "\n${CYAN}▶ $1${NC}"; }
ok()   { echo -e "${GREEN}  ✓ $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $1${NC}"; }
err()  { echo -e "${RED}  ✗ $1${NC}" >&2; }

cleanup() {
    echo ""
    warn "正在关闭服务..."
    if [ -f "$BACKEND_PID_FILE" ]; then
        pid=$(cat "$BACKEND_PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            ok "后端已停止"
        fi
        rm -f "$BACKEND_PID_FILE"
    fi
    warn "数据库仍在后台运行，如需关闭：docker compose down"
}

trap cleanup EXIT

cd "$SCRIPT_DIR"

# ── 1. 前置检查 ────────────────────────────────────────────────
step "检查依赖..."

if ! command -v docker >/dev/null 2>&1; then
    err "未找到 docker，请先安装 Docker Desktop"; exit 1
fi
if ! docker info >/dev/null 2>&1; then
    err "Docker 未运行，请先启动 Docker Desktop"; exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
    err "未找到 uv，安装方式：curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1
fi
ok "依赖检查通过"

# ── 2. 检查 .env ───────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    warn ".env 不存在，已从 .env.example 自动复制，LLM API Key 可在界面中配置"
fi

# ── 3. 启动数据库 ──────────────────────────────────────────────
step "启动 PostgreSQL..."
docker compose up -d

printf "  等待数据库就绪"
waited=0
until docker compose ps 2>/dev/null | grep -q "(healthy)"; do
    if [ "$waited" -ge 30 ]; then
        echo ""
        err "数据库启动超时（30s），请检查：docker compose logs"
        exit 1
    fi
    printf "."
    sleep 2
    waited=$((waited + 2))
done
echo ""
ok "数据库已就绪"

# ── 4. 数据库迁移 ──────────────────────────────────────────────
step "执行数据库迁移..."
uv run alembic -c api/alembic.ini upgrade head
ok "迁移完成"

# ── 5. 启动后端 ────────────────────────────────────────────────
step "启动后端（http://localhost:8000）..."
mkdir -p "$LOG_DIR"

# 清理残留进程
if [ -f "$BACKEND_PID_FILE" ]; then
    old_pid=$(cat "$BACKEND_PID_FILE")
    kill "$old_pid" 2>/dev/null || true
    rm -f "$BACKEND_PID_FILE"
    sleep 1
fi

uv run python main.py >> "$LOG_DIR/backend_stdout.log" 2>&1 &
echo $! > "$BACKEND_PID_FILE"

printf "  等待后端就绪（首次启动会下载嵌入模型，约需 1-2 分钟）"
waited=0
until curl -sf http://localhost:8000/health >/dev/null 2>&1; do
    if [ "$waited" -ge 120 ]; then
        echo ""
        err "后端启动超时，请查看日志：$LOG_DIR/backend_stdout.log"
        exit 1
    fi
    printf "."
    sleep 2
    waited=$((waited + 2))
done
echo ""
ok "后端已就绪"

# ── 6. 启动前端 ────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  AgentNexus-J 启动完成                              ${NC}"
echo -e "${GREEN}  控制台：http://localhost:8501                      ${NC}"
echo -e "${GREEN}  API：   http://localhost:8000/docs                 ${NC}"
echo -e "${GREEN}  日志：  logs/backend_stdout.log                    ${NC}"
echo -e "${GREEN}  Ctrl+C 停止前端和后端（数据库继续运行）            ${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

uv run streamlit run app.py
