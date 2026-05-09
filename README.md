# AgentNexus-J (企业级多智能体协作系统)

## 📖 项目简介
**AgentNexus-J** 是一个基于 **Jude** 个人特色打造的企业级多智能体 (Multi-Agent) 协作枢纽。
本项目采用核心“大脑调度”与“执行沙箱”分离的架构，支持 MCP 协议与 A2A (Agent-to-Agent) 通信，旨在实现一个安全、高性能且具备自我进化能力的 AI 助理系统。

## 🛠 技术栈选型 (Sprint 1)
* **核心框架**: Python 3.12 + FastAPI
* **包管理器**: `uv` (极速 Rust 编写的 Python 包管理工具)
* **数据库与 ORM**: PostgreSQL + SQLAlchemy 2.0 (全异步 `asyncpg` 驱动)
* **配置与验证**: Pydantic v2 + Pydantic-settings
* **日志系统**: Loguru
* **数据库迁移**: Alembic (待初始化)

## 📂 目录结构 (基于 DDD 领域驱动设计)
```text
agent_nexus_j/
├── api/                        # 后端核心微服务
│   ├── app/
│   │   ├── core/               # 全局配置 (config.py)、日志 (logger.py)
│   │   ├── domain/             # 领域层：业务逻辑、实体模型 (待开发)
│   │   ├── application/        # 应用层：服务编排、TaskRunner (待开发)
│   │   ├── infrastructure/     # 基础设施层：数据库连接池 (session.py)、ORM模型 (models.py)
│   │   └── main.py             # FastAPI 启动入口
│   ├── .venv/                  # uv 虚拟环境 (如果在根目录初始化，则在最外层)
│   └── pyproject.toml          # 现代化 Python 依赖声明
├── docs/                       # 架构文档与开发日志
│   └── daily_logs/             # 每日开发总结 (ADR)
├── .env                        # 全局环境变量配置 (注意防泄漏)
└── README.md                   # 项目说明文档

