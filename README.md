# 💠 AgentNexus-J

**企业级多智能体协作系统** — 基于 Jude 个人特色打造的 AI 助理枢纽。

支持主流 LLM 接入、多模型协作辩论、RAG 知识库检索、多模态文件解析、工具调用，提供流式响应的 Web 控制台。

📘 **完整操作手册（安装 · 配置 · 功能说明 · 故障排查）→ [MANUAL.md](./MANUAL.md)**

---

## ✨ 功能特性

| 功能 | 说明 |
|------|------|
| **多 LLM 接入** | Anthropic Claude、DeepSeek、通义 Qwen、任意 OpenAI 兼容接口，随时切换 |
| **多模型协作** | 圆桌模式（多模型迭代辩论 + 综合者汇总）/ 主从模式（主模型作答 + 评委打分改进） |
| **RAG 知识库** | 上传 PDF/DOCX/XLSX/TXT 文档，内置本地 ONNX 嵌入模型，对话自动检索相关内容 |
| **多模态附件** | 上传图片（需视觉模型）、PDF、Office、代码文件，自动提取文本随消息发送 |
| **工具调用** | 内置终端执行、系统时间；支持自定义 HTTP 工具，LLM 自动选择调用 |
| **System Prompt 库** | 可复用提示词库，按需分配给会话 |
| **长对话压缩** | Token 超限时自动摘要历史，无感保持上下文连贯 |
| **流式输出** | 实时逐字输出，工具调用结果内联显示 |
| **重试 / 复制** | 一键重新生成回答，一键复制到剪贴板 |
| **自动主题** | 白天浅色 / 夜晚深色自动切换 |

---

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.12 · FastAPI · Uvicorn |
| **前端** | Streamlit 1.40+ |
| **包管理** | `uv`（Rust 编写，替代 pip/venv） |
| **数据库** | PostgreSQL 16 + pgvector · SQLAlchemy 2.0（全异步 asyncpg） |
| **LLM 适配** | Anthropic SDK · OpenAI SDK（兼容 DeepSeek / Qwen / vLLM 等） |
| **本地嵌入** | fastembed + ONNX Runtime（默认 `BAAI/bge-small-zh-v1.5`，无需 PyTorch） |
| **文件解析** | pypdf · python-docx · openpyxl |
| **配置校验** | Pydantic v2 · pydantic-settings |
| **日志** | Loguru |

---

## 🚀 快速开始

```bash
# 1. 克隆并进入目录
cd agent_nexus_j

# 2. 安装依赖
uv sync

# 3. 启动数据库（含 pgvector）
docker compose up -d

# 4. 执行数据库迁移
uv run alembic -c api/alembic.ini upgrade head

# 5. 启动后端（新终端）
uv run python main.py

# 6. 启动前端（新终端）
uv run streamlit run app.py
```

访问 http://localhost:8501 开始使用。

---

## 📁 目录结构

```
agent_nexus_j/
├── main.py                      # 后端启动入口
├── app.py                       # Streamlit 前端控制台
├── pyproject.toml               # 依赖配置（uv）
├── docker-compose.yml           # PostgreSQL + pgvector 容器
└── api/app/
    ├── core/                    # 配置、日志
    ├── domain/schemas.py        # Pydantic 数据模型
    ├── infrastructure/
    │   ├── database/            # SQLAlchemy 模型与会话
    │   ├── llm/adapters.py      # LLM 适配层（Anthropic / OpenAI 兼容）
    │   ├── embedding/           # 本地嵌入服务（fastembed）
    │   ├── files/processor.py   # 多模态文件提取
    │   └── tools/               # 内置工具 + HTTP 工具注册
    ├── application/
    │   ├── agent_orchestrator.py       # 单模型 Agent 编排
    │   ├── collaboration_orchestrator.py # 多模型协作编排
    │   └── rag_pipeline.py             # RAG 摄取与检索
    └── api/routers/             # FastAPI 路由（chat / sessions / knowledge / …）
```
