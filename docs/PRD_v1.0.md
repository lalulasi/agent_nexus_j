# 📝 AgentNexus-J 产品需求与架构设计文档 (v1.0)

## 一、 项目概述 (Project Overview)

**项目名称**：AgentNexus-J (企业级多智能体协作枢纽)
**项目愿景**：构建一个高度可扩展、支持多模型无缝切换、具备多模态感知与物理执行（Function Calling）能力的现代 AI Agent 基础设施平台。
**核心价值**：告别写死逻辑（Hardcoding），采用“配置驱动”与“插件化工具”理念，打造一个真正为“多智能体协作”和“复杂任务自动执行”而生的后端引擎与极客交互界面。

---

## 二、 技术栈与底层架构 (Tech Stack & Architecture)

系统采用严格的**前后端分离**与**领域驱动设计 (DDD)** 规范。

### 1. 核心技术栈

* **后端服务**：FastAPI (全异步、高性能)
* **数据持久化**：PostgreSQL 15+ (主业务数据)
* **ORM 与迁移**：SQLAlchemy (Async) + asyncpg + Alembic
* **前端 UI**：Streamlit (极速构建的大模型交互界面)
* **容器化基建**：Docker + Docker Compose (一键部署隔离环境)

### 2. 架构设计原则 (Architecture Guidelines)

* **面向配置编程 (Registry Pattern)**：大模型提供商（Provider）与执行工具（Tools）均采用注册表模式接入。彻底消除 `if-else` 路由判断，确保系统符合“开闭原则”。
* **状态解耦**：FastAPI 作为纯无状态服务，所有对话记忆交由 PostgreSQL 持久化，支持高并发多实例部署。
* **前端纯渲染 (Dumb Frontend)**：Streamlit 仅负责数据展示与用户意图收集，所有复杂的上下文组装、工具路由决策均在 FastAPI 核心业务层完成。

---

## 三、 核心功能需求拆解 (Functional Requirements)

### 阶段一：基础会话与极客模型调度 (Phase 1: Core & BYOK) - *[进行中]*

* **F1.1 多会话管理 (Session Management)**
* 用户可新建、查看多个独立的对话会话（AgentSession）。
* 后端基于 `UUID` 自动隔离会话，实现对话记忆的独立回溯。


* **F1.2 UI 端内置模型热切换**
* 用户可在前端侧边栏实时选择底层 LLM（如 `deepseek-chat`, `qwen-plus`）。
* 后端依据选择自动从 `LLM_PROVIDERS` 配置中加载对应的请求策略。


* **F1.3 极客自定义模式 (BYOK - Bring Your Own Key)**
* **描述**：允许高级用户在 UI 上展开“极客模式”，手动输入任意兼容 OpenAI 标准的 `模型名称`、`Base URL` 和 `API Key`。
* **安全规范**：自定义信息仅在当前前端 Session 及单次请求的内存中存活，**绝对禁止**落盘写入数据库，确保用户资产绝对安全。



### 阶段二：多模态感知赋予 (Phase 2: Multimodal Vision) - *[待开发]*

* **F2.1 图像分析与视觉路由**
* 前端提供文件/图片上传组件。
* **智能降级与路由**：当后端接收到图文混合请求时，自动检测当前模型是否支持视觉。若不支持，精准抛出异常；若支持（如配置了 `qwen-vl-max`），则自动切换引擎进行视觉推理。


* **F2.2 S3 兼容的云存储整合 (后续演进)**
* 废弃早期的 Base64 内存直传方案，引入本地 MinIO 或云端 OSS。
* 实现大文件的异步上传、持久化存储与时效链接生成。



### 阶段三：物理双手与智能体执行 (Phase 3: Agentic Execution) - *[核心攻坚]*

* **F3.1 插件化工具系统 (Tool Registry)**
* 后端实现抽象基类 `BaseTool`，支持开发者极速编写独立功能的 Python 脚本（如查天气、搜索网络）。


* **F3.2 宿主机指令执行 (Local Execution)**
* **目标**：赋予 Agent 在授权环境下，通过 Bash 执行诸如 `brew install xxx`、文件读写等跨沙箱操作的能力。
* **机制**：基于 OpenAI 标准的 Function Calling / Tools 规范，系统将用户意图转化为标准的工具调用 JSON，并由后端的执行引擎完成最终动作。


* **F3.3 护栏机制 (Human-in-the-loop) [安全必须]**
* Agent 触发高危操作（安装软件、删除文件）前，必须通过前端页面向用户弹出二次确认阻断，用户点击“同意”后方可下发执行。



### 阶段四：国际化与体验升级 (Phase 4: i18n & UX) - *[待排期]*

* **F4.1 多国语言无缝切换**
* 界面支持 英语 (EN)、中文 (ZH)、日语 (JA) 实时动态切换。
* 通过前端的 `locales` 字典实现硬编码文本的隔离提取。



---

## 四、 数据库实体模型设计 (ER Design)

1. **AgentSession (会话表)**
* `id`: UUID (主键)
* `title`: String (会话标题)
* `model_provider`: String (模型标识，如 deepseek)
* `created_at` / `updated_at`: DateTime (时间戳)


2. **Message (消息记录表)**
* `id`: UUID (主键)
* `session_id`: UUID (外键，级联删除)
* `role`: String (user / assistant / system / tool)
* `content`: Text (消息正文，未来可存 JSON 以支持多模态或工具返回)
* `created_at`: DateTime



---

## 五、 数据安全与合规 (Security & Compliance)

1. **API 密钥管理**：系统级 API Key 强制通过根目录 `.env` 文件注入，杜绝代码库硬编码。BYOK 用户级 Key 实现“阅后即焚”机制。
2. **跨域与网络防护**：FastAPI 配置严格的 CORS 策略，Docker Compose 配置独立虚拟网络 `nexus-network`，数据库不对外直接暴露物理机端口。