# AgentNexus-J 操作手册

## 目录

1. [环境要求](#1-环境要求)
2. [安装依赖](#2-安装依赖)
3. [配置环境变量](#3-配置环境变量)
4. [启动数据库](#4-启动数据库)
5. [数据库迁移](#5-数据库迁移)
6. [启动后端服务](#6-启动后端服务)
7. [启动前端控制台](#7-启动前端控制台)
8. [首次使用：配置模型](#8-首次使用配置模型)
9. [普通对话](#9-普通对话)
10. [RAG 知识库](#10-rag-知识库)
11. [多模型协作](#11-多模型协作)
12. [多模态附件](#12-多模态附件)
13. [工具管理](#13-工具管理)
14. [System Prompt 库](#14-system-prompt-库)
15. [日常操作](#15-日常操作)
16. [常见问题](#16-常见问题)
17. [附录：目录结构](#17-附录目录结构)

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

```bash
cd /path/to/agent_nexus_j
uv sync
```

安装完成后生成 `.venv/` 目录。后续所有命令均需在此目录下执行，或以 `uv run` 前缀调用。

> 依赖更新后重新执行 `uv sync` 即可。

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

`.env` 关键字段：

```env
APP_ENV=development
APP_PORT=8000

# PostgreSQL 连接串（与 docker-compose.yml 保持一致）
DATABASE_URL=postgresql+asyncpg://nexus_admin:nexus_admin@localhost:5432/agent_nexus

# 可选预填（也可完全在界面中配置）
ANTHROPIC_API_KEY=sk-ant-...
```

> LLM 的 API Key、模型名称、接口地址可以完全通过界面配置，无需写入 `.env`。

---

## 4. 启动数据库

项目使用 **pgvector/pgvector:pg16** 镜像，内含 pgvector 向量扩展（RAG 功能依赖）。

```bash
docker compose up -d
```

验证：

```bash
docker compose ps
# 看到 agent_nexus_postgres   running (healthy) 即成功
```

---

## 5. 数据库迁移

**首次启动前必须执行，之后每次拉取新代码后若有新迁移文件也需执行。**

```bash
uv run alembic -c api/alembic.ini upgrade head
```

成功输出示例：

```
INFO  [alembic.runtime.migration] Running upgrade ...
```

> 不再需要手动 DROP/CREATE schema。迁移脚本会自动处理表结构变更，**现有数据不会丢失**。

---

## 6. 启动后端服务

```bash
uv run python main.py
```

启动成功输出：

```
INFO  | Starting AgentNexus-J [development]
INFO  | Database tables initialized
INFO  | 内置工具同步完成
INFO  | 本地嵌入模型已就绪: BAAI/bge-small-zh-v1.5
INFO  | Uvicorn running on http://0.0.0.0:8000
```

> **首次启动**时会自动下载本地嵌入模型（约 90 MB），请保持网络畅通，之后离线可用。

API 文档（开发模式）：http://localhost:8000/docs

---

## 7. 启动前端控制台

新开一个终端窗口：

```bash
uv run streamlit run app.py
```

访问：http://localhost:8501

---

## 8. 首次使用：配置模型

### 8.1 接入 LLM

在左侧侧边栏展开 **「＋ 接入新模型」**，填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| 配置名称 | 自定义标识 | `DeepSeek 生产` |
| 模型名称 | 模型 ID | `deepseek-chat` |
| API Key | 平台密钥 | `sk-...` |
| API URL（可选） | 非 Anthropic 官方时必填 | `https://api.deepseek.com` |
| 嵌入模型（可选） | 用于 RAG，从下拉列表选择 | 默认：bge-small-zh-v1.5 |

常见 API URL：

| 平台 | API URL |
|------|---------|
| Anthropic（Claude） | 留空 |
| DeepSeek | `https://api.deepseek.com` |
| 阿里云通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 硅基流动 | `https://api.siliconflow.cn/v1` |
| 本地 Ollama | `http://localhost:11434/v1` |

点击 **「💾 保存并激活」** 完成配置。

### 8.2 嵌入模型说明

嵌入模型用于 RAG 知识库的向量化，**默认内置，无需额外配置**。

| 选项 | 大小 | 适用场景 |
|------|------|---------|
| 默认：bge-small-zh-v1.5 | 90 MB | 中文，轻量，推荐默认 |
| bge-base-zh-v1.5 | 210 MB | 中文，质量更高 |
| jina-embeddings-v2-base-zh | 640 MB | 中英双语 |
| paraphrase-multilingual-MiniLM-L12-v2 | 220 MB | 50+ 语言多语言场景 |
| nomic-embed-text-v1.5-Q（量化） | 130 MB | 多语言，体积小 |
| bge-m3 | 570 MB | 多语言，最高质量 |

> 切换嵌入模型会导致旧文档的向量与新模型不兼容，建议切换前**清空知识库**再重新上传。

---

## 9. 普通对话

### 9.1 新建会话

在侧边栏点击 **「＋ 普通会话」**，可选开启：

- **🔍 启用 RAG**：勾选后该会话在每次对话前自动检索知识库

### 9.2 发送消息

在底部输入框输入文字，按 Enter 发送，回复以流式方式实时输出。

### 9.3 重试与复制

最后一条 AI 回复下方有两个图标按钮：

| 按钮 | 功能 |
|------|------|
| ↺（重播图标） | 重新生成上一条回答 |
| ⬜（复制图标） | 复制回答文本到剪贴板 |

### 9.4 长对话自动压缩

当会话 Token 累计超过阈值时，系统自动将历史消息压缩为摘要，对话框顶部会出现提示。全程无感，上下文始终保持连贯。

---

## 10. RAG 知识库

RAG（检索增强生成）让 AI 在回答时自动参考你上传的文档内容。

### 10.1 上传文档

在侧边栏 **「📚 知识库」** 区域展开 **「＋ 上传文档」**，选择文件后点击 **「📤 上传到知识库」**。

支持格式：PDF、DOCX、XLSX、TXT、MD、CSV、JSON、代码文件（.py/.js/.ts）

上传过程（后台自动完成）：
1. 提取文档文本
2. 按 1500 字符切片（200 字符重叠）
3. 调用本地嵌入模型生成向量
4. 存入 PostgreSQL（pgvector 扩展）

### 10.2 在会话中启用 RAG

**新建会话时**勾选 **「🔍 启用 RAG」**，或在现有会话的设置中开启。

启用后每次发送消息时：
1. 对用户问题生成向量
2. 从知识库检索 Top-5 最相关切片（余弦相似度）
3. 将检索结果拼入 System Prompt
4. AI 回答时可引用知识库内容

检索到内容时，回答前会显示引用来源：

```
📚 已从知识库检索到 3 条相关内容
> report.pdf · 相关度 0.87
> ...文本片段...
```

### 10.3 管理文档

知识库文档列表显示文件名和切片数量，点击 **「🗑」** 删除。知识库为全局共享，所有会话可用。

### 10.4 嵌入模型技术说明

- 基于 **fastembed + ONNX Runtime**，不依赖 PyTorch，不调用任何外部 API
- 模型文件缓存于 `~/.cache/fastembed/`，首次下载后离线可用
- 向量存储于 PostgreSQL（pgvector 扩展），无需额外向量数据库

---

## 11. 多模型协作

多个 LLM 协同处理同一问题，提升回答质量。

> 需要至少配置 **2 个模型**。在侧边栏点击 **「⚡ 协作会话」** 展开创建表单。

### 11.1 圆桌模式（B+C 迭代辩论）

多个模型从不同角色独立作答，经过多轮交叉审视后，由综合者汇总最终答案。

| 角色 | 职责 |
|------|------|
| 提案者（proposer） | 提出初始方案 |
| 批判者（critic） | 挑战和质疑 |
| 创意者（creative） | 发散创新思维 |
| 验证者（validator） | 逻辑验证 |
| 综合者（synthesizer） | 汇总最优答案（最后一个槽位固定） |

配置：
1. 选择 **「🔀 圆桌模式」**
2. 设置模型数量（2-5 个）和讨论轮次（1-2 轮）
3. 为每个槽位指定模型配置
4. 点击 **「✅ 创建圆桌会话」**

### 11.2 主从模式（主答 + 评委评分）

主模型先给出完整答案，评委模型从四个维度评分并提出改进版本，系统采用得分最高的改进版本作为最终答案。

评分维度：准确性 · 完整性 · 清晰度 · 逻辑性（满分各 2.5 分，共 10 分）

配置：
1. 选择 **「👑 主从模式」**
2. 指定主模型
3. 设置评委数量（1-4 个）并指定各评委模型
4. 点击 **「✅ 创建主从会话」**

### 11.3 查看协作过程

回答生成后，点击 **「🔄 协作决策过程」** 可折叠查看各模型的完整推理内容。

---

## 12. 多模态附件

在对话输入框上方可上传文件随消息一起发送。

支持格式：

| 类型 | 格式 | 说明 |
|------|------|------|
| 图片 | JPG · PNG · GIF · WEBP | **需要视觉模型**（Claude 3+、GPT-4o、qwen-vl-max 等） |
| 文档 | PDF · DOCX · XLSX | 自动提取文本，适用所有模型 |
| 文本 | TXT · MD · CSV · JSON · YAML | 直接读取内容 |
| 代码 | PY · JS · TS | 直接读取内容 |

> 上传图片时若模型不支持视觉功能，会返回友好提示，请切换到视觉模型后重试。

---

## 13. 工具管理

工具让 LLM 可以调用外部能力（查询时间、执行命令、调用 API 等）。

### 内置工具

| 工具名 | 功能 |
|--------|------|
| `get_system_time` | 获取当前系统时间 |
| `execute_terminal` | 在本地执行终端命令 |

### 接入自定义 HTTP 工具

在侧边栏 **「🛠 工具管理」** → **「＋ 接入新工具」**，填写：

| 字段 | 说明 |
|------|------|
| 工具标识符 | snake_case 函数名，供 LLM 识别调用 |
| 显示名称 | 界面展示用 |
| 功能描述 | 告诉 LLM 何时调用此工具 |
| 接口地址 | 工具服务的 HTTP URL |
| 请求方式 | GET 或 POST |
| 参数定义 | JSON Schema 格式，定义工具接受的参数 |

工具列表支持通过开关随时启用 / 禁用，HTTP 工具可编辑或删除。

---

## 14. System Prompt 库

可复用的 System Prompt 库，可跨会话复用。

1. 在侧边栏 **「📋 System Prompt 库」** → **「＋ 新建提示词」**
2. 填写名称和内容，保存
3. 从下拉列表选中后点击 **「✅ 应用到当前会话」**

---

## 15. 日常操作

### 管理模型配置

| 操作 | 步骤 |
|------|------|
| 切换模型 | 从下拉框选择 → 点击「⚡ 激活」 |
| 修改配置 | 选中配置 → 点击「✏️ 编辑」→ 修改后保存 |
| 更换 API Key | 编辑表单中填写新 Key（留空保持不变） |
| 切换嵌入模型 | 编辑表单中从下拉框选择（切换后建议清空知识库） |
| 删除配置 | 不能删除当前激活配置，请先切换到其他配置再删除 |

### 管理会话

| 操作 | 步骤 |
|------|------|
| 新建普通会话 | 点击「＋ 普通会话」|
| 新建 RAG 会话 | 勾选「🔍 启用 RAG」后点击「＋ 普通会话」|
| 新建协作会话 | 点击「⚡ 协作会话」→ 配置后创建 |
| 切换会话 | 点击会话名称 |
| 重命名 | 点击会话右侧「✏️」|
| 删除 | 点击会话右侧「🗑」|

### 停止服务

```bash
# Streamlit：Ctrl+C
# FastAPI：Ctrl+C
# 停止数据库：
docker compose down
```

---

## 16. 常见问题

### 启动后端报 `column xxx does not exist`

未执行数据库迁移，运行：

```bash
uv run alembic -c api/alembic.ini upgrade head
```

### `ModuleNotFoundError: No module named 'uvicorn'`

未在项目虚拟环境中执行，改用：

```bash
uv run python main.py
```

### 首次启动很慢 / 卡在嵌入模型下载

正在下载本地嵌入模型（约 90 MB），保持网络连接，等待日志输出 `本地嵌入模型已就绪` 后恢复正常。

### 上传图片报错 BalanceError / 500

当前激活的模型不支持视觉功能，请切换到以下模型之一：Claude 3+、GPT-4o、qwen-vl-max。

### RAG 检索结果不相关 / 无检索结果

- 确认已上传文档，知识库列表有文件
- 问题语言与文档语言一致时效果最好（中文问题 + 中文文档）
- 尝试切换质量更高的嵌入模型（如 bge-base-zh-v1.5）

### 嵌入模型报错 `is not supported in TextEmbedding`

不是所有 HuggingFace 模型都被 fastembed 支持，请在下拉列表中选择，不要手填模型名。

### 对话报错 `❌ 模型接口错误: Error code: 404`

- **模型名称**是否正确（区分大小写）
- **API URL** 是否填写（DeepSeek、Qwen 等需要填写，Anthropic 留空）
- **API Key** 是否有效且有余额

### 无法连接后台服务

```bash
curl http://localhost:8000/health
# 预期：{"status":"ok","env":"development"}
```

### 数据库连接失败

```bash
docker compose ps       # 确认容器运行
docker compose up -d    # 如未运行则启动
```

---

## 17. 附录：目录结构

```
agent_nexus_j/
├── main.py                      # 后端启动入口
├── app.py                       # Streamlit 前端控制台
├── pyproject.toml               # 依赖配置（uv）
├── docker-compose.yml           # PostgreSQL + pgvector 容器
├── .env.example                 # 环境变量模板
├── api/
│   ├── alembic.ini              # 数据库迁移配置
│   ├── migrations/              # Alembic 迁移文件
│   └── app/
│       ├── core/                # 配置（config.py）、日志（logger.py）
│       ├── domain/schemas.py    # 全局 Pydantic 数据模型
│       ├── infrastructure/
│       │   ├── database/        # SQLAlchemy 模型（models.py）与会话管理
│       │   ├── llm/adapters.py  # LLM 适配层（Anthropic / OpenAI 兼容）
│       │   ├── embedding/       # 本地嵌入服务（fastembed + ONNX）
│       │   ├── files/           # 多模态文件文本提取（processor.py）
│       │   └── tools/           # 内置工具注册 + HTTP 工具执行
│       ├── application/
│       │   ├── agent_orchestrator.py         # 单模型 Agent 编排（含 RAG 注入）
│       │   ├── collaboration_orchestrator.py # 多模型协作编排
│       │   └── rag_pipeline.py               # 文档摄取（ingest）与向量检索（query）
│       └── api/routers/
│           ├── chat.py          # 对话接口（普通 / 协作 / 流式）
│           ├── sessions.py      # 会话 CRUD
│           ├── llm_configs.py   # 模型配置 CRUD
│           ├── knowledge.py     # 知识库文档上传 / 列表 / 删除
│           ├── system_prompts.py
│           └── tools.py
```
