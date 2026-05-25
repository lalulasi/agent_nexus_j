# 💠 AgentNexus-J (企业级多智能体协作系统)

## 📖 项目简介
**AgentNexus-J** 是一个基于 **Jude** 个人特色打造的企业级多智能体 (Multi-Agent) 协作枢纽。
本项目采用核心“大脑调度”与“执行沙箱”分离的架构，支持 MCP 协议与 A2A (Agent-to-Agent) 通信，旨在实现一个安全、高性能且具备自我进化能力的 AI 助理系统。

为了实现极致的性能与确定性的依赖管理，项目全面拥抱了生态中领先的 Rust 级包管理工具 **`uv`**。

---

## 🛠 技术栈选型

* **核心框架**: Python 3.12 + FastAPI (后端) / Streamlit (前端极客控制台)
* **包管理器**: `uv` (极速 Rust 编写的 Python 依赖与环境管理工具，替代 traditional pip/venv)
* **数据库与 ORM**: PostgreSQL + SQLAlchemy 2.0 (全异步 `asyncpg` 驱动)
* **配置与验证**: Pydantic v2 + Pydantic-settings
* **日志系统**: Loguru
* **工具与沙箱**: 智能终端命令熔断机制 / MCP 协议兼容拓展接口

---
