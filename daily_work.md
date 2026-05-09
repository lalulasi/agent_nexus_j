# AgentNexus-J (企业级多智能体协作系统)

## 📖 项目简介
**AgentNexus-J** 是一个基于 **Jude** 个人特色打造的企业级多智能体 (Multi-Agent) 协作枢纽。
本项目采用核心“大脑调度”与“执行沙箱”分离的架构，旨在实现一个安全、高性能且具备自我进化能力的 AI 助理系统。

---

## 🚀 快速启动指南 (Quick Start)

### 1. 前置要求
* **Python**: 3.12+
* **包管理**: 安装 [uv](https://github.com/astral-sh/uv)
* **环境**: 本地需运行 PostgreSQL (推荐使用 Docker)

### 2. 依赖安装与虚拟环境
在项目根目录（`agent_nexus_j`）下执行：
```bash
uv sync

```

*注意：这将会在根目录生成 `.venv`。*

### 3. 环境配置 (解决 ValidationError)

在**根目录**创建 `.env` 文件，确保包含以下数据库必需字段：

```env
POSTGRES_USER=nexus_admin
POSTGRES_PASSWORD=你的密码
POSTGRES_DB=agent_nexus
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

```

*代码已实现自动向上递归搜索 `.env`，无需在 `api` 目录下重复创建。*

### 4. IDE 消除红线 (针对 IntelliJ IDEA / PyCharm 专项)

**必须完成以下两步，否则导入 `app` 模块会报错：**

1. **关联解释器**：在 IDEA 设置中，将 Python 解释器指向根目录下的 `.venv/bin/python`。
2. **设置源码根目录**：在项目视图中，**右键点击 `api` 文件夹** -> **`Mark Directory as`** -> 选择 **`Sources Root`**。
* *完成后 `api` 文件夹会变蓝，所有红线将消失，且支持代码跳转。*



### 5. 启动后端服务 (解决 ModuleNotFoundError)

必须在 `api` 目录下使用**模块模式**启动：

```bash
cd api
uv run python -m app.main

```

*访问 `http://localhost:8000/health` 检查健康状态。*

---

## 🛠 技术栈

* **框架**: FastAPI
* **ORM**: SQLAlchemy 2.0 (全异步驱动 `asyncpg`)
* **配置**: Pydantic v2 (Settings)
* **日志**: Loguru (支持自动轮转与文件落地)

## 📂 目录结构

* **api/**: 后端核心代码。
* **docs/daily_logs/**: 每日详细开发日记 (ADR)。
* **logs/**: 系统运行产生的日志文件 (自动生成)。

## 📅 近期进展

* [x] 基础设施搭建 (Environment & Config)
* [x] 异步数据库连接池配置
* [x] 全局日志系统 (Loguru) 集成
* [ ] 数据库迁移 (Alembic) 与业务模型设计 (下一步任务)
"""

with open(readme_path, "w", encoding="utf-8") as f:
f.write(full_content)

```


```python?code_reference&code_event_index=3
import os

readme_path = "README.md"

full_content = """# AgentNexus-J (企业级多智能体协作系统)

## 📖 项目简介
**AgentNexus-J** 是一个基于 **Jude** 个人特色打造的企业级多智能体 (Multi-Agent) 协作枢纽。
本项目采用核心“大脑调度”与“执行沙箱”分离的架构，旨在实现一个安全、高性能且具备自我进化能力的 AI 助理系统。

---

## 🚀 快速启动指南 (Quick Start)

### 1. 前置要求
* **Python**: 3.12+
* **包管理**: 安装 [uv](https://github.com/astral-sh/uv)
* **环境**: 本地需运行 PostgreSQL (推荐使用 Docker)

### 2. 依赖安装与虚拟环境
在项目根目录（`agent_nexus_j`）下执行：
```bash
uv sync

```

*注意：这将会在根目录生成 `.venv`。*

### 3. 环境配置 (解决 ValidationError)

在**根目录**创建 `.env` 文件，确保包含以下数据库必需字段：

```env
POSTGRES_USER=nexus_admin
POSTGRES_PASSWORD=你的密码
POSTGRES_DB=agent_nexus
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

```

*代码已实现自动向上递归搜索 `.env`，无需在 `api` 目录下重复创建。*

### 4. IDE 消除红线 (针对 IntelliJ IDEA / PyCharm 专项)

**必须完成以下两步，否则导入 `app` 模块会报错：**

1. **关联解释器**：在 IDEA 设置中，将 Python 解释器指向根目录下的 `.venv/bin/python`。
2. **设置源码根目录**：在项目视图中，**右键点击 `api` 文件夹** -> **`Mark Directory as`** -> 选择 **`Sources Root`**。
* *完成后 `api` 文件夹会变蓝，所有红线将消失，且支持代码跳转。*



### 5. 启动后端服务 (解决 ModuleNotFoundError)

必须在 `api` 目录下使用**模块模式**启动：

```bash
cd api
uv run python -m app.main

```

*访问 `http://localhost:8000/health` 检查健康状态。*

---

## 🛠 技术栈

* **框架**: FastAPI
* **ORM**: SQLAlchemy 2.0 (全异步驱动 `asyncpg`)
* **配置**: Pydantic v2 (Settings)
* **日志**: Loguru (支持自动轮转与文件落地)

## 📂 目录结构

* **api/**: 后端核心代码。
* **docs/daily_logs/**: 每日详细开发日记 (ADR)。
* **logs/**: 系统运行产生的日志文件 (自动生成)。

## 📅 近期进展

* [x] 基础设施搭建 (Environment & Config)
* [x] 异步数据库连接池配置
* [x] 全局日志系统 (Loguru) 集成
* [ ] 数据库迁移 (Alembic) 与业务模型设计 (下一步任务)
