# AgentNexus-J 操作手册

## 目录

1. [环境要求](#1-环境要求)
2. [安装依赖](#2-安装依赖)
3. [配置环境变量](#3-配置环境变量)
4. [启动数据库](#4-启动数据库)
5. [启动后端服务](#5-启动后端服务)
6. [启动前端控制台](#6-启动前端控制台)
7. [首次使用](#7-首次使用)
8. [日常操作](#8-日常操作)
9. [常见问题](#9-常见问题)

---

## 1. 环境要求

| 工具 | 版本要求 | 安装方式 |
|------|---------|---------|
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) |
| uv | 最新版 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker Desktop | 最新版 | [docker.com](https://www.docker.com/products/docker-desktop/) |

验证安装：

```bash
python --version    # Python 3.12.x
uv --version        # uv x.x.x
docker --version    # Docker version xx.x.x
```

---

## 2. 安装依赖

进入项目根目录，执行：

```bash
cd /path/to/agent_nexus_j

# uv 自动读取 pyproject.toml，创建虚拟环境并安装全部依赖
uv sync
```

安装完成后会生成 `.venv/` 目录。**后续所有命令均需在此目录下执行。**

> 如需更新依赖（例如新增了包），重新执行 `uv sync` 即可。

---

## 3. 配置环境变量

复制示例文件并按需修改：

```bash
cp .env.example .env
```

`.env` 关键字段说明：

```env
# 运行环境（development / production）
APP_ENV=development
APP_PORT=8000

# PostgreSQL 连接串（与 docker-compose.yml 保持一致）
DATABASE_URL=postgresql+asyncpg://nexus_admin:nexus_admin@localhost:5432/agent_nexus

# 以下为可选预填项，也可在界面中配置
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-7
```

> **LLM 的 API Key、模型名称、接口地址也可以完全通过界面配置，无需在 `.env` 中填写。**

---

## 4. 启动数据库

```bash
# 后台启动 PostgreSQL 容器
docker compose up -d
```

验证是否正常运行：

```bash
docker compose ps
# 看到 agent_nexus_postgres   running (healthy) 即为成功
```

### 重置数据库（首次使用或结构变更后需执行）

当模型结构发生变更（如新增字段），需要重置数据库表，重启后端会自动重建：

```bash
docker exec -it agent_nexus_postgres psql -U postgres -d agent_nexus
```

进入 psql 后执行：

```sql
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
\q
```

---

## 5. 启动后端服务

**方式一：使用 `uv run`（推荐，无需激活虚拟环境）**

```bash
uv run python main.py
```

**方式二：激活虚拟环境后直接运行**

```bash
source .venv/bin/activate   # macOS / Linux
# 或
.venv\Scripts\activate      # Windows

python main.py
```

启动成功后终端输出：

```
INFO     | Starting AgentNexus-J [development]
INFO     | Database tables initialized
INFO     | Uvicorn running on http://0.0.0.0:8000
```

API 文档地址（开发模式）：http://localhost:8000/docs

---

## 6. 启动前端控制台

**新开一个终端窗口**，进入项目目录：

```bash
uv run streamlit run app.py
# 或激活环境后：
streamlit run app.py
```

启动成功后自动打开浏览器，或手动访问：

```
http://localhost:8501
```

---

## 7. 首次使用

### 7.1 配置模型

1. 打开 http://localhost:8501
2. 左侧侧边栏展开 **「➕ 添加新配置」**
3. 填写以下信息：

   | 字段 | 说明 | 示例 |
   |------|------|------|
   | 配置名称 | 自定义标识 | `DeepSeek 生产` |
   | 模型名称 | 模型 ID | `deepseek-chat` |
   | API Key | 对应平台的密钥 | `sk-...` |
   | API URL（可选） | 非官方 Anthropic 时必填 | `https://api.deepseek.com` |

4. 点击 **「💾 保存并激活」**

> **URL 填写规则：**
> - 使用 Anthropic 官方模型（Claude 系列）：**留空**
> - 使用 DeepSeek：`https://api.deepseek.com`
> - 使用阿里云 Qwen：`https://dashscope.aliyuncs.com/compatible-mode/v1`
> - 使用其他 OpenAI 兼容接口：填写对应 base URL

### 7.2 配置 System Prompt（可选）

1. 从下拉框选中已激活的配置
2. 在 **「📋 System Prompt」** 区域选择 **「自定义」**
3. 在文本框中输入 prompt 内容
4. 点击 **「💾 保存 System Prompt」**

选择 **「无」** 则不携带 System Prompt，直接透传用户消息给模型。

### 7.3 开始对话

1. 点击 **「＋ 新建会话」**
2. 在底部输入框输入消息，按回车发送
3. 回复以流式方式实时显示

---

## 8. 日常操作

### 管理模型配置

| 操作 | 步骤 |
|------|------|
| 切换模型 | 从下拉框选择配置 → 点击 **「⚡ 激活」** |
| 修改配置 | 选中配置 → 点击 **「✏️ 编辑」** → 修改后保存 |
| 修改 API Key | 编辑表单中填写新 Key（留空保持不变） |

### 管理会话

| 操作 | 步骤 |
|------|------|
| 新建会话 | 点击 **「＋ 新建会话」** |
| 切换会话 | 点击会话名称 |
| 重命名会话 | 点击会话右侧 **「✏️」** → 输入新名称 → 确认 |
| 删除会话 | 点击会话右侧 **「🗑」** |

### 停止服务

```bash
# 停止 Streamlit：在其终端按 Ctrl+C
# 停止 FastAPI：在其终端按 Ctrl+C
# 停止数据库容器：
docker compose down
```

---

## 9. 常见问题

### `ModuleNotFoundError: No module named 'uvicorn'`

未使用 uv 的虚拟环境执行命令。解决方式：

```bash
# 方式一
uv run python main.py

# 方式二
source .venv/bin/activate && python main.py
```

### 启动后端报 `column xxx does not exist`

数据库表结构与代码不一致，需要重置数据库（见第 4 节）。

### 对话报错 `❌ 模型接口错误: Error code: 404`

检查以下项：
- **模型名称**是否正确（区分大小写）
- **API URL** 是否填写（DeepSeek、Qwen 等需要填写，Anthropic 留空）
- **API Key** 是否有效且有余额

### 无法连接后台服务

确认 FastAPI 已启动并监听 8000 端口：

```bash
curl http://localhost:8000/health
# 预期返回：{"status":"ok","env":"development"}
```

### 数据库连接失败

确认 Docker 容器正在运行：

```bash
docker compose ps
# 若未运行：
docker compose up -d
```

---

## 附录：项目目录结构

```
agent_nexus_j/
├── main.py                  # 后端启动入口
├── app.py                   # Streamlit 前端
├── pyproject.toml           # 依赖配置（uv）
├── docker-compose.yml       # PostgreSQL 容器
├── .env.example             # 环境变量模板
└── api/app/
    ├── core/                # 配置、日志
    ├── domain/              # Pydantic schemas
    ├── infrastructure/
    │   ├── database/        # SQLAlchemy 模型与会话
    │   ├── llm/             # LLM 适配层（Anthropic / OpenAI 兼容）
    │   └── tools/           # 内置工具（系统时间、终端执行）
    ├── application/         # Agent 编排逻辑
    └── api/routers/         # FastAPI 路由
```
