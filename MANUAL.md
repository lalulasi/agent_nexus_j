# AgentNexus-J 操作手册

## 目录

1. [环境要求](#1-环境要求)
2. [安装依赖](#2-安装依赖)
3. [配置环境变量](#3-配置环境变量)
4. [启动系统](#4-启动系统) — 一键启动 · 手动分步
8. [首次使用：配置模型](#8-首次使用配置模型)
9. [普通对话](#9-普通对话)（含深度思考 · 网络搜索）
10. [RAG 知识库](#10-rag-知识库)
11. [多模型协作](#11-多模型协作)
12. [MCP Agent 接入](#12-mcp-agent-接入)
13. [多模态附件](#13-多模态附件)
14. [工具管理](#14-工具管理)（HTTP 工具 · 网络搜索配置）
15. [System Prompt 库](#15-system-prompt-库)
16. [日常操作](#16-日常操作)
17. [日志说明](#17-日志说明)
18. [常见问题](#18-常见问题)
19. [附录：目录结构](#19-附录目录结构)

---

## 1. 环境要求

| 工具 | 版本要求 | 安装方式 |
|------|---------|---------|
| Python | 3.12+ | [python.org](https://www.python.org/downloads/) |
| uv | 最新版 | 见下方说明 |
| Docker Desktop | 最新版 | [docker.com](https://www.docker.com/products/docker-desktop/) |

**安装 uv**

macOS / Linux：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows（PowerShell）：
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

验证安装：

```bash
python --version    # Python 3.12.x
uv --version        # uv x.x.x
docker --version    # Docker version xx.x.x
```

---

## 2. 安装依赖

macOS / Linux：
```bash
cd /path/to/agent_nexus_j
uv sync
```

Windows（PowerShell）：
```powershell
cd C:\path\to\agent_nexus_j
uv sync
```

安装完成后生成 `.venv/` 目录。后续所有命令均需在此目录下执行，或以 `uv run` 前缀调用。

> 依赖更新后重新执行 `uv sync` 即可。

---

## 3. 配置环境变量

macOS / Linux：
```bash
cp .env.example .env
```

Windows（PowerShell）：
```powershell
Copy-Item .env.example .env
```

> 使用一键启动脚本时会自动完成此步骤，无需手动执行。

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

## 4. 启动系统

### 4.1 一键启动（推荐）

**macOS / Linux**

```bash
chmod +x start.sh   # 仅需一次
./start.sh
```

**Windows CMD**

```cmd
start.bat
```

**Windows PowerShell**

```powershell
.\start.ps1
```

> 若提示执行策略受限，先在 PowerShell 中运行：
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

两个脚本逻辑相同，自动完成以下步骤：

1. 检查 Docker 和 uv 是否已安装并运行
2. 若 `.env` 不存在，自动从 `.env.example` 复制
3. 启动 PostgreSQL 容器，等待健康检查通过
4. 执行数据库迁移（`alembic upgrade head`）
5. 在后台启动 FastAPI 后端，日志写入 `logs/backend_stdout.log`
6. 在前台启动 Streamlit 前端

启动完成后：

| 服务 | 地址 |
|------|------|
| 前端控制台 | http://localhost:8501 |
| 后端 API | http://localhost:8000 |
| API 文档（开发模式） | http://localhost:8000/docs |

按 **Ctrl+C** 退出：前端和后端同时停止，数据库保持运行（数据不丢失）。再次启动直接重新运行脚本即可。

> **首次启动**时后端会自动下载本地嵌入模型（约 90 MB），脚本最多等待 2 分钟，请保持网络畅通。

### 4.2 手动启动（分步）

如需单独控制各组件（以下命令在 macOS / Linux / Windows 均相同，除非特别注明）：

**启动数据库**

项目使用 **pgvector/pgvector:pg16** 镜像，内含 pgvector 向量扩展（RAG 功能依赖）。

```bash
docker compose up -d
docker compose ps   # 看到 (healthy) 即成功
```

**数据库迁移**（首次或拉取新代码后执行，现有数据不会丢失）

```bash
uv run alembic -c api/alembic.ini upgrade head
```

**启动后端**

```bash
uv run python main.py
```

API 文档（开发模式）：http://localhost:8000/docs

**启动前端**（新开终端窗口）

```bash
uv run streamlit run app.py
```

访问：http://localhost:8501

**停止所有服务**

macOS / Linux：
```bash
# Streamlit / FastAPI：Ctrl+C
# 停止数据库（可选）：
docker compose down
```

Windows（PowerShell）：
```powershell
# Streamlit / FastAPI：Ctrl+C
# 手动终止后端进程（如有残留）：
taskkill /IM python.exe /F
# 停止数据库（可选）：
docker compose down
```

---

## 8. 首次使用：配置模型

### 8.1 接入 LLM

在左侧侧边栏切换到 **「⚙️ 模型」** tab，展开 **「＋ 接入新模型」**，填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| 配置名称 | 自定义标识 | `DeepSeek 生产` |
| 模型名称 | 模型 ID | `deepseek-chat` |
| API Key | 平台密钥 | `sk-...` |
| API URL（可选） | 非 Anthropic 官方时必填 | `https://api.deepseek.com` |
| 嵌入模型（可选） | 用于 RAG，从下拉列表选择 | 默认：bge-small-zh-v1.5 |
| 思考 Token 预算 | 仅对 Anthropic Claude 扩展思考生效 | 默认 8000 |

常见 API URL：

| 平台 | API URL |
|------|---------|
| Anthropic（Claude） | 留空 |
| DeepSeek | `https://api.deepseek.com` |
| 阿里云通义 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 硅基流动 | `https://api.siliconflow.cn/v1` |
| 本地 Ollama | `http://localhost:11434/v1` |

点击 **「💾 保存并激活」** 完成配置。

### 8.2 快速切换当前模型

已配置多个模型后，在侧边栏 **「💬 会话」** tab 顶部的 **「🤖 使用模型」** 下拉框即可直接切换，无需进入模型配置页。切换后立即生效，后续新建会话和发送消息均使用选中的模型。

### 8.3 删除模型配置

在 **「⚙️ 模型」** tab 选中目标配置后，点击右侧 **「🗑」** 按钮，确认删除。

> 当前激活中的模型无法删除。请先在「🤖 使用模型」下拉框切换到其他模型，再执行删除。

### 8.4 嵌入模型说明

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

### 9.3 深度思考

在输入框上方有 **「🧠 深度思考」** toggle 开关，**每次对话独立控制**：

- **关闭（默认）**：模型直接作答，速度更快
- **开启**：模型先进行内部推理再作答，适合复杂分析、数学推导、多步骤规划

开启后，思考过程以 **「🧠 深度思考中...」** 状态区展示，作答完成后自动折叠为「🧠 思考完毕（N 字符）」，点击可展开查看完整推理过程。

支持的模型：

| 模型系列 | 说明 |
|---------|------|
| DeepSeek-R1 / deepseek-reasoner | OpenAI 兼容接口，模型自动输出推理链 |
| QwQ 系列 | 同上 |
| Claude 3.7 Sonnet+ | 需要设置思考 Token 预算（在模型配置中调整） |

> 深度思考开启时，Anthropic Claude 会消耗额外的 thinking tokens，计入总费用。

### 9.4 网络搜索

在输入框上方有 **「🔍 网络搜索」** toggle 开关，**每次对话独立控制**，默认关闭：

- **关闭（默认）**：LLM 仅使用训练知识作答
- **开启**：将 `web_search` 工具注入本次请求的 LLM 上下文，LLM 可根据需要主动调用搜索引擎获取实时信息

> 需先在 **「🛠 工具 → 🔍 网络搜索」** 中配置并激活至少一个搜索引擎，否则 toggle 呈禁用状态。

搜索结果会以工具调用结果的形式内联显示在对话中：

```
🔧 web_search
网页搜索结果，共 5 条：
[1] 标题...
来源：https://...
```

支持的搜索引擎（在「🛠 工具」tab 配置）：

| 提供商 | API Key | 特点 |
|--------|---------|------|
| DuckDuckGo（ddgs） | 不需要 | 免费，开箱即用；稳定性一般 |
| Tavily | 需要（每月 1000 次免费） | AI 原生，结果质量最佳，推荐用于新闻/时事 |
| Serper.dev | 需要（2500 次一次性免费） | 真实 Google 结果，价格低廉 |

> 系统已自动在 System Prompt 中注入当前日期，帮助模型正确判断"实时"与"历史"信息。

### 9.5 重试与复制

最后一条 AI 回复下方有两个图标按钮：

| 按钮 | 功能 |
|------|------|
| ↺（重播图标） | 重新生成上一条回答 |
| ⬜（复制图标） | 复制回答文本到剪贴板 |

### 9.6 长对话自动压缩

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

> 需要至少配置 **2 个模型**（或 1 个模型 + 1 个 MCP Chat Agent）。在侧边栏点击 **「⚡ 协作会话」** 展开创建表单。

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
3. 为每个槽位指定模型配置或 MCP Chat Agent（标记 `[MCP]`）
4. 点击 **「✅ 创建圆桌会话」**

### 11.2 主从模式（主答 + 评委评分）

主模型先给出完整答案，评委模型从四个维度评分并提出改进版本，系统采用得分最高的改进版本作为最终答案。

评分维度：准确性 · 完整性 · 清晰度 · 逻辑性（满分各 2.5 分，共 10 分）

配置：
1. 选择 **「👑 主从模式」**
2. 指定主模型（仅限 LLM，负责流式作答）
3. 设置评委数量（1-4 个），评委可混合 LLM 和 MCP Chat Agent
4. 点击 **「✅ 创建主从会话」**

### 11.3 查看协作过程

回答生成后，点击 **「🔄 协作决策过程」** 可折叠查看各模型的完整推理内容。

---

## 12. MCP Agent 接入

MCP（Model Context Protocol）允许将外部 Agent 服务接入 AgentNexus-J，作为工具提供者或协作参与者。

### 12.1 MCP Server 的三种模式

| 模式 | 说明 | 使用场景 |
|------|------|---------|
| `tool_provider` | 仅提供工具，工具自动注入所有普通会话的 LLM 上下文 | 搜索、计算器、数据库查询等工具型服务 |
| `chat_agent` | 提供 `chat` 接口，可作为协作会话的槽位参与讨论 | 专域 Agent（数学推理、代码审查等） |
| `both` | 同时提供工具和 Chat Agent 接口 | 综合型 Agent |

### 12.2 注册 MCP Server

在侧边栏 **「🛠 工具」** tab → **「🔌 MCP Agents」** 区域，点击 **「＋ 注册 MCP Server」**：

| 字段 | 说明 | 示例 |
|------|------|------|
| 服务名称 | 内部标识符（snake_case） | `math_agent` |
| 显示名称 | 界面展示用 | `数学推理专家` |
| 服务地址 | MCP Server 的根 URL | `http://localhost:8503` |
| 连接模式 | tool_provider / chat_agent / both | `both` |
| 认证头（可选） | `Bearer <token>` 格式 | `Bearer sk-xxx` |

注册成功后，状态指示灯变为 🟢（连接中会显示 🟡，失败显示 🔴）。

### 12.3 在普通会话中使用 MCP 工具

MCP 工具**自动注入**已激活的普通会话，无需额外配置。当 LLM 调用 MCP 工具时，对话中会显示：

```
🔌 MCP [server_name] · `tool_name`
> 参数预览
```

### 12.4 在协作会话中使用 MCP Chat Agent

创建协作会话时，槽位选择下拉框中会显示已注册且激活的 `chat_agent` / `both` 模式 MCP Server，标记为 `[MCP] 显示名称`。

### 12.5 管理 MCP Server

每个 MCP Server 卡片提供三个操作：

| 按钮 | 功能 |
|------|------|
| 🔄 | 重新连接（状态异常时使用） |
| ⏸ / ▶ | 禁用 / 启用此 MCP Server |
| 🗑 | 删除注册（不影响远端服务） |

### 12.6 本地测试 MCP Server

项目根目录提供测试服务器 `mock_mcp_server.py`：

```bash
uv run python mock_mcp_server.py
# 服务地址：http://localhost:8503
# 工具：echo · get_time · calculator · chat
```

注册时填写：
- 服务地址：`http://localhost:8503`
- 连接模式：`both`

开发者文档：[docs/MCP_DEVELOPER_GUIDE.md](./docs/MCP_DEVELOPER_GUIDE.md)

---

## 13. 多模态附件

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

## 14. 工具管理

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

### 14.2 网络搜索配置

在侧边栏 **「🛠 工具」** tab → **「🔍 网络搜索」** 区块中管理搜索引擎。

#### 添加搜索引擎

点击 **「＋ 添加搜索配置」**，填写：

| 字段 | 说明 |
|------|------|
| 搜索提供商 | DuckDuckGo（免费无 Key）/ Tavily / Serper.dev |
| API Key | DuckDuckGo 留空；Tavily 和 Serper.dev 必填 |
| 最多返回结果数 | 1–10 条，默认 5 |

#### 选择当前使用的搜索引擎

已添加多个配置时，顶部 **「当前使用的搜索引擎」** 下拉框直接切换，立即生效，无需额外激活步骤。

#### 使用搜索

配置激活后，在普通对话输入框上方开启 **「🔍 网络搜索」** toggle，发送消息时 LLM 即可调用搜索工具。

#### 删除配置

点击对应配置右侧的 **「🗑」** 按钮删除。当前正在使用的唯一一条配置不可删除，需先添加另一条并切换后再删除。

---

## 15. System Prompt 库

可复用的 System Prompt 库，可跨会话复用。

1. 在侧边栏 **「📋 System Prompt 库」** → **「＋ 新建提示词」**
2. 填写名称和内容，保存
3. 从下拉列表选中后点击 **「✅ 应用到当前会话」**

---

## 16. 日常操作

### 管理模型配置

| 操作 | 步骤 |
|------|------|
| 快速切换模型 | 会话 tab 顶部「🤖 使用模型」下拉框直接选择，立即生效 |
| 切换模型（详细页）| 模型 tab 选中配置 → 点击「⚡ 激活」 |
| 修改配置 | 选中配置 → 点击「✏️ 编辑」→ 修改后保存 |
| 更换 API Key | 编辑表单中填写新 Key（留空保持不变） |
| 切换嵌入模型 | 编辑表单中从下拉框选择（切换后建议清空知识库） |
| 删除配置 | 选中配置 → 点击「🗑」→ 确认删除（激活中的模型需先切换才能删除） |

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

## 17. 日志说明

系统日志存储于项目根目录 `logs/` 文件夹，按天轮转，保留 30 天。

| 文件名 | 内容 | 查看场景 |
|--------|------|---------|
| `agent_nexus_YYYY-MM-DD.log` | 主日志：会话处理、工具调用、错误信息 | 排查系统异常 |
| `outbound_YYYY-MM-DD.log` | **对外请求专用日志**：所有发出的 LLM API 调用、MCP RPC 调用、HTTP 工具调用的完整参数与响应摘要 | 调试模型行为、审计 API 调用 |

**对外请求日志格式示例：**

```
# LLM 请求
LLM ▶ STREAM  provider=anthropic  model=claude-sonnet-4-6  messages=3  tools=[]  thinking=false  max_tokens=4096
  system: 'You are a helpful assistant'
    [user] '请分析这段代码'
LLM ◀ STREAM  provider=anthropic  model=claude-sonnet-4-6  stop=end_turn  in=512  out=234  duration=1.85s

# MCP 工具调用
MCP ▶ math_agent  method=tools/call  endpoint=http://localhost:8503/messages/xxx
  params: {"name": "calculator", "arguments": {"expression": "2**10"}}
MCP ◀ math_agent  method=tools/call  duration=0.05s
  result: {"content": [{"type": "text", "text": "1024"}], "isError": false}

# HTTP 工具调用
HTTP_TOOL ▶ 'my_api'  POST https://api.example.com/query
  params: {'q': 'test'}
HTTP_TOOL ◀ 'my_api'  status=200  duration=0.12s
  response: '{"result": "ok"}'

# 网络搜索调用
SEARCH ▶ provider=ddgs  type=news  query='美国 新闻'  max=5
SEARCH ◀ provider=ddgs  results=432 chars
```

---

## 18. 常见问题

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

### 🔍 网络搜索 toggle 呈灰色无法开启

尚未配置搜索引擎，在 **「🛠 工具 → 🔍 网络搜索」** 中添加一条配置即可。DuckDuckGo 无需 API Key，直接添加并通过下拉框选中即可使用。

### 搜索工具被调用但返回"未找到结果"

- **DuckDuckGo** 为非官方 API，稳定性有限。建议 LLM 使用 2-5 个简短关键词（如"美国 新闻"），避免冗长句子
- 可在 **「🛠 工具 → 🔍 网络搜索」** 切换为 **Tavily**（每月 1000 次免费），新闻类查询效果更好
- 对外请求日志 `logs/outbound_*.log` 中可查看具体的搜索查询参数和原始响应

### 深度思考没有效果 / 没有出现思考过程面板

- 确认开启了输入框上方的「🧠 深度思考」toggle
- DeepSeek-R1 需使用 `deepseek-reasoner` 模型名（不是 `deepseek-chat`）
- Anthropic Claude 需要模型版本支持扩展思考（claude-3-7-sonnet-20250219 及以上）

### MCP Server 状态一直是 🟡 连接中

- 确认 MCP Server 正在运行，地址填写正确
- 检查对外请求日志 `logs/outbound_*.log`，查看 MCP 握手请求的具体错误
- 手动验证（macOS/Linux）：`curl http://<server>/health`
- 手动验证（Windows PowerShell）：`Invoke-WebRequest http://<server>/health -UseBasicParsing`

### MCP Server 注册了但工具没有出现

- 确认 Server 已启用（状态为 🟢）
- MCP Server 的连接模式须包含 `tool_provider` 或 `both`
- 新建一个会话后重试（工具在每次请求时动态加载）

### 无法连接后台服务

macOS / Linux：
```bash
curl http://localhost:8000/health
# 预期：{"status":"ok","env":"development"}
```

Windows（PowerShell）：
```powershell
Invoke-WebRequest -Uri http://localhost:8000/health -UseBasicParsing
# 预期：StatusCode 200，Content 含 "status":"ok"
```

### 数据库连接失败

```bash
docker compose ps       # 确认容器运行
docker compose up -d    # 如未运行则启动
```

---

## 19. 附录：目录结构

```
agent_nexus_j/
├── start.sh                     # 一键启动脚本 — macOS / Linux
├── start.bat                    # 一键启动脚本 — Windows（主脚本，CMD / 双击均可）
├── start.ps1                    # 一键启动脚本 — Windows PowerShell 入口（调用 start.bat）
├── main.py                      # 后端启动入口
├── app.py                       # Streamlit 前端控制台
├── mock_mcp_server.py           # 本地测试用 MCP Server（echo / get_time / calculator / chat）
├── pyproject.toml               # 依赖配置（uv）
├── docker-compose.yml           # PostgreSQL + pgvector 容器
├── .env.example                 # 环境变量模板
├── logs/                        # 运行日志（agent_nexus_*.log + outbound_*.log）
├── docs/
│   ├── MCP_DEVELOPER_GUIDE.md   # MCP Agent 开发者接入文档
│   ├── MCP_ENGINEERING.md       # MCP 工程设计文档
│   └── multi_model_collaboration.md
├── api/
│   ├── alembic.ini              # 数据库迁移配置
│   ├── migrations/              # Alembic 迁移文件
│   └── app/
│       ├── core/
│       │   ├── config.py        # 应用配置（pydantic-settings）
│       │   └── logger.py        # 日志配置（主日志 + outbound 日志双轨）
│       ├── domain/schemas.py    # 全局 Pydantic 数据模型
│       ├── infrastructure/
│       │   ├── database/        # SQLAlchemy 模型（models.py）与会话管理
│       │   ├── llm/adapters.py  # LLM 适配层（Anthropic / OpenAI 兼容，含深度思考流式）
│       │   ├── embedding/       # 本地嵌入服务（fastembed + ONNX）
│       │   ├── files/           # 多模态文件文本提取（processor.py）
│       │   ├── mcp/             # MCP 协议层
│       │   │   ├── connection.py  # 单连接生命周期管理（SSE + 指数退避重连）
│       │   │   ├── manager.py     # 多 Server 注册与工具聚合
│       │   │   └── protocol.py    # 协议数据结构
│       │   └── tools/           # 内置工具注册 + HTTP 工具 + 网络搜索工具
│       │       └── builtins/search_tool.py  # 搜索工具（DuckDuckGo / Tavily / Serper）
│       ├── application/
│       │   ├── agent_orchestrator.py         # 单模型 Agent 编排（RAG 注入 / MCP 工具 / 深度思考）
│       │   ├── collaboration_orchestrator.py # 多模型协作编排（支持 MCP Agent 槽位）
│       │   └── rag_pipeline.py               # 文档摄取（ingest）与向量检索（query）
│       └── api/routers/
│           ├── chat.py          # 对话接口（普通 / 协作 / 流式，含 thinking 参数）
│           ├── sessions.py      # 会话 CRUD
│           ├── llm_configs.py   # 模型配置 CRUD（含删除接口）
│           ├── mcp_servers.py   # MCP Server 注册 / 激活 / 删除
│           ├── knowledge.py     # 知识库文档上传 / 列表 / 删除
│           ├── search_config.py # 搜索引擎配置 CRUD
│           ├── system_prompts.py
│           └── tools.py
```
