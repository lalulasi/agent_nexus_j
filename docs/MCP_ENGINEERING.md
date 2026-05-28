# MCP Agent 接入 — 工程师手册

> 面向产品经理与新接手工程师的完整设计文档。
> 覆盖：为什么这么设计、选了什么技术、每一层做什么、怎么一步步实现。

---

## 目录

1. [背景：我们在解决什么问题](#1-背景我们在解决什么问题)
2. [核心概念：MCP 是什么](#2-核心概念mcp-是什么)
3. [整体设计思路](#3-整体设计思路)
4. [架构分层详解](#4-架构分层详解)
5. [工具选型与原因](#5-工具选型与原因)
6. [数据模型设计](#6-数据模型设计)
7. [核心组件详解](#7-核心组件详解)
8. [API 接口设计](#8-api-接口设计)
9. [前端交互设计](#9-前端交互设计)
10. [命名规范与约定](#10-命名规范与约定)
11. [三个创新点的预留设计](#11-三个创新点的预留设计)
12. [开发路线图](#12-开发路线图)
13. [风险与注意事项](#13-风险与注意事项)
14. [用户侧：如何开发一个 MCP Agent](#14-用户侧如何开发一个-mcp-agent)

---

## 1. 背景：我们在解决什么问题

### 现状

AgentNexus-J 已经支持：
- 接入多家 LLM（Claude、DeepSeek、Qwen 等）
- 多模型协作（圆桌辩论、主从评审）
- RAG 知识库（上传文档，对话时自动检索）
- 工具调用（内置终端、HTTP 工具）

### 痛点

所有能力都由**平台本身**提供，用户无法把自己已有的 AI 能力接进来。

举个例子：一家公司已经有一个内部的「合同审查 Agent」，它能理解本公司的合规规则。现在用 AgentNexus-J 做多模型协作时，这个合同 Agent 没法参与进来，只能用平台提供的通用 LLM。

### 目标

让用户能把**自己开发的 Agent**接入平台，作为：
- **A. 工具**：LLM 在对话中自动调用用户 Agent 提供的能力
- **B. 协作参与者**：用户 Agent 和平台 LLM 一起参与圆桌讨论或主从评审

---

## 2. 核心概念：MCP 是什么

### MCP 的本质

MCP（Model Context Protocol）是 Anthropic 发布的**开放协议**，解决一个问题：

> 如何让 AI 系统和外部工具/服务稳定地互相通信？

类比：如果说 HTTP 是网页通信的标准，那 MCP 就是 AI 与工具通信的标准。

### MCP 的三个角色

```
Host（宿主）         Client（客户端）       Server（服务端）
AgentNexus-J 后端   平台内部组件           用户的 Agent
发起请求             管理连接               提供能力
```

在我们的设计里，AgentNexus-J 后端同时充当 Host 和 Client，用户开发的 Agent 是 Server。

### MCP Server 能提供什么

一个 MCP Server 可以暴露三类东西：

| 类型 | 说明 | 类比 |
|------|------|------|
| **Tools（工具）** | 可被 AI 调用的函数 | 就像手机 App 的 API |
| **Resources（资源）** | 可读取的数据 | 就像数据库表 |
| **Prompts（提示词）** | 预设的提示词模板 | 就像代码模板 |

**第一期我们只用 Tools**，这是最核心、最直接的能力。

### 传输协议

MCP 支持两种通信方式：

| 方式 | 原理 | 适用场景 |
|------|------|---------|
| **HTTP + SSE** | 用 HTTP 发请求，服务端通过 SSE 推送响应 | 远程部署的 Agent，推荐 |
| **stdio** | 通过命令行标准输入输出通信 | 本地进程，复杂度高 |

第一期只做 HTTP + SSE，原因见第 5 章。

---

## 3. 整体设计思路

### 设计哲学：最小侵入

现有系统（工具调用、协作编排）已经稳定运行。MCP 功能应该像**插件**一样接进来，不改变现有逻辑的核心路径。

具体策略：
- 工具调度层：通过**前缀识别**区分 MCP 工具和原有工具，走不同分支
- 协作编排层：槽位支持新的类型 `mcp`，原有 `llm` 类型逻辑完全不动
- 数据库：新增 `mcp_servers` 表，不改现有表结构

### 设计哲学：单一职责

整个 MCP 功能拆成四层，每层只负责一件事：

```
连接管理层   → 只管「连没连上」
协议层       → 只管「消息格式」
能力注册层   → 只管「有哪些工具」
调度层       → 只管「调用谁」
```

好处：某层出问题，不影响其他层。比如网络抖动导致连接断了，调度层根本感知不到，由连接管理层自动重连。

### 设计哲学：为未来预留空间

三个创新点（双身份 MCP Server、智能路由、托管记忆）暂时不实现，但在架构里预留好接口和扩展点。等到时机成熟，只需填充实现，不需要重构框架。

---

## 4. 架构分层详解

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 4：前端 / API 层                                       │
│                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐  │
│  │ MCP Server 管理  │  │  工具列表展示    │  │ 协作表单扩展 │  │
│  │ (注册/编辑/删除) │  │ (含 MCP 工具)   │  │(MCP Agent槽)│  │
│  └─────────────────┘  └─────────────────┘  └─────────────┘  │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP API
┌──────────────────────────────▼───────────────────────────────┐
│  Layer 3：应用编排层                                          │
│                                                              │
│  ┌────────────────────────┐  ┌────────────────────────────┐  │
│  │   AgentOrchestrator    │  │  CollaborationOrchestrator │  │
│  │   (工具调度)            │  │  (协作编排)                │  │
│  │   识别 mcp__ 前缀       │  │  支持 MCPAgent 槽位         │  │
│  └──────────┬─────────────┘  └────────────┬───────────────┘  │
│             │                             │                  │
│  ┌──────────▼─────────────────────────────▼───────────────┐  │
│  │              MCPClientManager（单例）                   │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│  Layer 2：连接管理层                                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ConnectionPool                                      │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │  MCPConnection (server_A)  状态: 🟢 CONNECTED  │  │   │
│  │  │  MCPConnection (server_B)  状态: 🟡 RECONNECTING│  │   │
│  │  │  MCPConnection (server_C)  状态: 🔴 DISABLED   │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  CapabilityRegistry（内存缓存）                       │   │
│  │  "mcp__rag_agent__search" → { schema, tags, mode }  │   │
│  │  "mcp__code_bot__chat"   → { schema, tags, mode }   │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTP + SSE
┌──────────────────────────────▼───────────────────────────────┐
│  Layer 1：外部 MCP Servers（用户开发）                        │
│                                                              │
│  ┌──────────────────┐    ┌──────────────────┐               │
│  │  合同审查 Agent   │    │  代码助手 Agent   │  ...         │
│  │  (Tool Provider) │    │  (Chat Agent)    │               │
│  └──────────────────┘    └──────────────────┘               │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. 工具选型与原因

### 为什么选 HTTP + SSE，不选 stdio？

| 对比维度 | HTTP + SSE | stdio |
|---------|------------|-------|
| 部署方式 | 用户 Agent 独立部署，提供 URL | 需要在平台服务器上启动进程 |
| 安全性 | 天然隔离，用户 Agent 在用户自己机器上 | 进程运行在平台服务器，风险高 |
| 实现复杂度 | 低，用 httpx 库直接支持 | 高，需要进程生命周期管理 |
| 适用范围 | 远程/云端部署的 Agent | 本地开发调试 |
| 横向扩展 | 用户 Agent 可以独立扩容 | 受限于平台服务器资源 |

**结论**：HTTP + SSE 更安全、更简单、更符合企业使用场景。stdio 作为进阶功能后期再考虑。

### 为什么选 SSE，不用普通 HTTP 请求？

普通 HTTP 是「一问一答」：客户端问，服务端立刻回答，连接关闭。

SSE（Server-Sent Events）是「问一次，持续回答」：客户端建立一条长连接，服务端可以随时推送消息，连接保持。

对 MCP 协议来说，SSE 有两个好处：
1. **减少握手开销**：不用每次工具调用都重新建立连接
2. **支持流式响应**：服务端可以边计算边推送结果，不必等全部完成

### 为什么用 httpx，不用 requests？

| 对比 | httpx | requests |
|------|-------|---------|
| 异步支持 | ✅ 原生支持 `async/await` | ❌ 不支持，需要线程池 |
| SSE 支持 | ✅ `aconnect_sse` | ❌ 需要手动解析流 |
| 与 FastAPI 兼容性 | ✅ 同一异步生态 | ⚠️ 需要额外处理 |

我们的后端是 FastAPI（全异步），httpx 是它的标配 HTTP 客户端。

### 为什么用 官方 mcp Python SDK？

Anthropic 官方提供了 `mcp` Python 库，内置了：
- MCP 协议的消息序列化/反序列化
- SSE 传输层封装
- `initialize`、`list_tools`、`call_tool` 等标准方法

自己实现等于重造轮子，且容易和协议规范产生偏差。用官方 SDK 保证兼容性。

### 连接重试策略：为什么用指数退避？

当连接断开后，重试策略有两种常见方案：

| 方案 | 行为 | 问题 |
|------|------|------|
| 固定间隔重试 | 每 5 秒重试一次 | 服务宕机时产生大量无效请求（惊群效应）|
| 指数退避 | 1s → 2s → 4s → 8s → ... 上限 60s | 逐渐降低频率，给服务恢复时间 |

指数退避是业界标准做法，AWS、Google 等所有大厂都用这个策略。

---

## 6. 数据模型设计

### mcp_servers 表

```
字段名              类型              说明
─────────────────────────────────────────────────────────────
id                 UUID              主键，自动生成
name               VARCHAR(64)       唯一标识符，用作工具前缀
                                     规则：小写字母+下划线，如 rag_agent
display_name       VARCHAR(255)      界面显示名称，如「合同审查助手」
description        TEXT              描述这个 Agent 的用途
                                     会被传给 LLM 帮助它理解何时调用
url                TEXT              MCP Server 地址
                                     如 http://your-server.com/mcp
auth_header        TEXT (可空)        认证头，如 Bearer sk-xxx
                                     注意：存储时建议加密
mode               VARCHAR(32)       tool_provider | chat_agent | both
is_active          BOOLEAN           是否启用（禁用时不建立连接）
discovered_tools   JSONB             list_tools 的缓存结果
                                     服务器重启后不需要重新发现
last_seen_at       TIMESTAMPTZ       最后一次心跳成功时间
created_at         TIMESTAMPTZ       创建时间
updated_at         TIMESTAMPTZ       最后更新时间
```

### discovered_tools 字段的 JSON 结构

```json
[
  {
    "name": "search_docs",
    "description": "在知识库中搜索相关文档",
    "inputSchema": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "搜索关键词"
        },
        "top_k": {
          "type": "integer",
          "description": "返回结果数量",
          "default": 5
        }
      },
      "required": ["query"]
    }
  }
]
```

这个结构直接对应 MCP 协议规范，也是传给 LLM 的格式。

### 为什么不把工具拆成单独的表？

工具列表是 MCP Server 的附属数据，随 Server 的存亡而变化。每次刷新都是全量替换，不存在「更新某个工具」的操作。用 JSONB 存储比单独建表更简单，查询时直接取整个列表传给 LLM，没有 JOIN 开销。

---

## 7. 核心组件详解

### 7.1 MCPConnection — 单个连接的状态机

**职责**：管理与一个 MCP Server 的连接生命周期。

**状态机**：

```
          ┌─────────────────────────────────────────┐
          │                                         │
  ┌───────▼──────┐                                  │
  │   DISABLED   │ ◄── is_active=False              │
  └───────┬──────┘                                  │
          │ activate()                              │
  ┌───────▼──────┐     成功     ┌──────────────┐   │
  │  CONNECTING  │ ─────────► │  CONNECTED   │   │
  └───────┬──────┘             └──────┬───────┘   │
          │ 失败                      │ 网络断开   │
  ┌───────▼──────┐             ┌──────▼───────┐   │
  │ RECONNECTING │ ◄────────── │   ERROR      │   │
  │ (指数退避)   │             └──────────────┘   │
  └───────┬──────┘                                │
          │ 退避时间到，重试                        │
          └─────────────────────────────────────────┘
```

**对外接口**：
```
call_tool(tool_name, arguments)  →  调用工具，返回结果
chat(messages)                   →  发送对话消息，返回回复
list_tools()                     →  获取工具列表
status                           →  当前连接状态
```

**关键实现细节**：
- 底层使用 `httpx` 的 `aconnect_sse()` 建立 SSE 长连接
- 每次 `call_tool` 通过 HTTP POST 发送请求，响应通过 SSE 推送回来
- 重连逻辑：`asyncio.create_task()` 创建后台任务，不阻塞主线程

### 7.2 MCPClientManager — 连接池管理器

**职责**：管理所有 MCP Server 的连接，提供统一的调度入口。

**生命周期**：
```
应用启动（lifespan）
  → 从数据库加载所有 is_active=True 的 Server
  → 为每个 Server 创建 MCPConnection
  → 触发连接，更新 CapabilityRegistry
  → 后台维护心跳

应用关闭
  → 关闭所有 SSE 连接
  → 清空 CapabilityRegistry
```

**CapabilityRegistry 的更新时机**：
- Server 首次连接成功（`list_tools` 拿到结果）
- 手动调用 `/refresh` 接口
- Server 断线重连后

**对编排层暴露的接口**：
```
call_tool(server_name, tool_name, args)  →  工具调用结果
chat(server_name, messages)              →  对话回复
get_all_tools()                          →  所有已发现工具（用于传给 LLM）
get_chat_agents()                        →  所有 chat_agent 模式的 Server 列表
get_status(server_name)                  →  连接状态
```

### 7.3 CapabilityRegistry — 能力注册表

**职责**：维护一份内存中的「平台当前拥有哪些 MCP 工具」索引。

**为什么放内存，不放数据库？**

工具列表是**高频读、低频写**的数据：
- 每次 LLM 对话开始，都要读取当前工具列表
- 只有在 Server 连接/断开/刷新时才需要更新

数据库读取每次需要网络 I/O，内存读取是纳秒级。把这份数据缓存在内存里，读取速度提升 1000 倍以上。

`discovered_tools` 字段在数据库里保存了一份副本，用于服务重启后的快速恢复，不需要等重新连接。

**数据结构**：
```
key:   "mcp__rag_agent__search_docs"    （传给 LLM 的工具名）
value: {
  server_id:   "uuid",
  server_name: "rag_agent",
  tool_name:   "search_docs",
  schema:      { ... },               （直接传给 LLM 的描述）
  mode:        "tool_provider",
  tags:        ["search", "docs"],    （预留，供未来语义路由使用）
}
```

### 7.4 修改后的工具调度逻辑

**当前逻辑（简化）**：
```
接收工具调用请求（tool_name, args）
  → 查找工具
  → 调用工具
  → 返回结果
```

**修改后**：
```
接收工具调用请求（tool_name, args）
  → 判断工具类型：
      if tool_name 以 "mcp__" 开头:
          解析 server_name 和 actual_tool_name
          → mcp_manager.call_tool(server_name, actual_tool_name, args)
      elif tool_name 是内置工具:
          → 原有内置工具逻辑（不动）
      else:
          → 原有 HTTP 工具逻辑（不动）
  → 返回结果
```

修改点极小，现有工具完全不受影响。

### 7.5 修改后的协作编排逻辑

**当前协作槽位结构**：
```
slot = {
  "config_id": "uuid",    # LLMConfig 的 ID
  "role": "proposer"
}
```

**修改后（扩展，不破坏）**：
```
slot = {
  # 方案 A：LLM 槽位（现有）
  "type": "llm",
  "config_id": "uuid",
  "role": "proposer"

  # 方案 B：MCP Agent 槽位（新增）
  "type": "mcp",
  "server_name": "code_bot",
  "role": "validator"
}
```

编排层处理：
```
for slot in collab_config.slots:
    if slot.type == "llm":
        response = await call_llm(slot.config_id, messages)    # 原有逻辑
    elif slot.type == "mcp":
        response = await mcp_manager.chat(slot.server_name, messages)  # 新增
    results.append(response)
```

---

## 8. API 接口设计

### 端点一览

```
基础路径：/api/v1/mcp-servers

GET    /                    列出所有注册的 MCP Server（含实时状态）
POST   /                    注册新 Server（注册后自动尝试连接）
PATCH  /{id}                修改配置（URL、认证头等）
DELETE /{id}                删除并断开连接
POST   /{id}/activate       启用 / 禁用切换
POST   /{id}/refresh        重新发现工具（不断开连接，直接 list_tools）
POST   /{id}/test           临时测试连通性（不写数据库，只返回结果）
GET    /{id}/status         实时状态查询（连接状态 + 最后心跳时间）
```

### 关键请求/响应示例

**注册 Server（POST /）**

请求体：
```json
{
  "name": "rag_agent",
  "display_name": "合同审查助手",
  "description": "专门处理合同合规性检查，了解公司内部合规规则",
  "url": "http://internal.company.com:8080/mcp",
  "auth_header": "Bearer sk-internal-xxx",
  "mode": "both"
}
```

响应：
```json
{
  "id": "uuid",
  "name": "rag_agent",
  "display_name": "合同审查助手",
  "mode": "both",
  "is_active": true,
  "status": "connecting",
  "discovered_tools": null,
  "last_seen_at": null,
  "created_at": "2026-05-26T10:00:00Z"
}
```

注意：注册时连接还未建立，`status` 是 `connecting`，`discovered_tools` 是 null。前端应轮询 `/status` 等待连接完成。

**测试连通性（POST /{id}/test）**

这个接口不改数据库，纯粹临时连接测试，给用户确认 URL 和认证配置是否正确：

响应：
```json
{
  "success": true,
  "latency_ms": 142,
  "discovered_tools": [
    {
      "name": "review_contract",
      "description": "检查合同条款的合规性"
    }
  ],
  "error": null
}
```

失败时：
```json
{
  "success": false,
  "latency_ms": null,
  "discovered_tools": null,
  "error": "连接超时：无法访问 http://internal.company.com:8080/mcp"
}
```

**获取列表（GET /）**

响应中的状态字段来自 MCPClientManager 内存（实时），不来自数据库：
```json
[
  {
    "id": "uuid",
    "name": "rag_agent",
    "display_name": "合同审查助手",
    "mode": "both",
    "is_active": true,
    "status": "connected",
    "discovered_tools_count": 3,
    "last_seen_at": "2026-05-26T10:05:23Z"
  }
]
```

---

## 9. 前端交互设计

### 9.1 侧边栏 🛠 工具 Tab 新增区块

在现有工具列表下方添加「MCP Agent」区块：

```
──── MCP Agent ─────────────────────────────
＋ 接入 MCP Server
  ┌─────────────────────────────────────────┐
  │ 名称 *        [rag_agent              ] │
  │ 显示名称 *    [合同审查助手            ] │
  │ 描述          [专门处理合同...         ] │
  │ URL *         [http://server.com/mcp   ] │
  │ 认证头        [Bearer sk-xxx           ] │
  │ 模式          [工具+Agent ▼           ] │
  │                                         │
  │ [测试连接]   [确认注册]                  │
  └─────────────────────────────────────────┘

已接入：
┌─────────────────────────────────────────────┐
│ 🟢 合同审查助手   · 工具+Agent · 3 工具      │
│    └─ review_contract / search_clauses / ... │
│    [刷新] [编辑] [禁用] [删除]               │
├─────────────────────────────────────────────┤
│ 🟡 代码助手      · 仅 Agent · 重连中...      │
│    [编辑] [禁用] [删除]                      │
└─────────────────────────────────────────────┘
```

状态指示：
- 🟢 `connected` — 正常
- 🟡 `connecting` / `reconnecting` — 等待/重连
- 🔴 `error` — 持续失败，需要人工介入
- ⚫ `disabled` — 已禁用

「测试连接」按钮：点击后实时展示发现的工具列表，让用户确认后再正式注册。

### 9.2 工具列表中的 MCP 工具

MCP 工具和内置工具、HTTP 工具在同一列表，用徽标区分：

```
🔵 内置  · system_time     · [启用 ●]
🔵 内置  · execute_command · [启用 ●]
🟠 HTTP  · web_search      · [启用 ●] [✏️][🗑]
🔌 MCP   · rag_agent / review_contract · [启用 ●]
🔌 MCP   · rag_agent / search_clauses  · [启用 ●]
```

MCP 工具不支持单独编辑（工具由 Server 定义），只能整体启用/禁用该 Server。

### 9.3 协作会话创建表单的扩展

模型槽位的下拉列表增加 MCP Agent 分组：

```
选择槽位 2 的模型：
  ── LLM 模型 ──────────────────────
  ✅ Claude 3.5 Sonnet
     DeepSeek-V3
     通义 Qwen-Max
  ── MCP Agent ─────────────────────
  🔌 合同审查助手  (工具+Agent) 🟢
  🔌 代码助手      (仅 Agent)   🟡
```

灰色/禁用：状态不是 `connected` 的 MCP Agent（避免用户选了一个断线的 Agent 参与协作）。

---

## 10. 命名规范与约定

### 工具名的三层表示

| 层级 | 格式 | 示例 | 用途 |
|------|------|------|------|
| 数据库存储 | `{tool_name}` | `search_docs` | 原始工具名 |
| 内部索引键 | `{server_name}.{tool_name}` | `rag_agent.search_docs` | CapabilityRegistry key |
| 传给 LLM | `mcp__{server_name}__{tool_name}` | `mcp__rag_agent__search_docs` | function calling 名称 |
| 前端显示 | `{server_display} / {tool_name}` | `合同审查助手 / search_docs` | UI 展示 |

**为什么用双下划线 `__`？**

LLM 的工具名只允许字母、数字、下划线、连字符（`[a-zA-Z0-9_-]`）。需要一个「分隔符」来区分命名空间（server）和工具名，但不能用 `.` 或 `:`。双下划线是 Python 世界的惯例，既合法又直观。

### MCP Server name 约束

- 只允许小写字母、数字、下划线
- 长度 1-32 字符
- 注册后不可修改（因为工具名前缀依赖它）
- 推荐：描述性名词，如 `contract_agent`、`code_reviewer`

---

## 11. 三个创新点的预留设计

### 创新点 1：双身份 MCP Server

**目标**：AgentNexus-J 平台自己也作为一个 MCP Server，让外部客户端（Claude Desktop、用户自己的应用）通过 MCP 协议调用平台能力。

**预留方式**：
- 新建文件 `api/app/infrastructure/mcp/host.py`，暂时为空
- 在应用启动时保留 `/mcp` 路由占位，返回 501 Not Implemented
- MCPClientManager 内设计为可以接收「反向连接」请求的接口存根

**未来暴露的工具**：
```
collaborate(messages, mode)    → 触发多模型协作
query_knowledge(question)      → RAG 检索
run_tool(tool_name, args)      → 调用平台工具
```

### 创新点 2：智能能力路由

**目标**：用户无需手动选择「圆桌/主从/普通」，平台自动分析 Query 选择最优组合。

**预留方式**：
- CapabilityRegistry 的每个工具条目预留 `tags` 字段（现在留空）
- 会话创建接口预留 `mode: "auto"` 枚举值（现在直接 pass 到普通模式）
- 新建文件 `api/app/application/routing_agent.py`，暂时只有注释

**未来逻辑**：
```
接收用户 Query
  → RoutingAgent 分析：
      "这个问题需要代码执行 + 文档检索"
  → 自动选择：
      code_reviewer (MCP) + Claude (LLM) · 主从模式
  → 执行并展示「为您自动选择...」
```

### 创新点 3：托管记忆层

**目标**：用户的 MCP Agent 可以通过平台提供的接口读写 RAG 知识库，无需自己实现向量数据库。

**预留方式**：
- RAGPipeline 所有方法增加 `namespace: str = "global"` 参数
- 现有功能默认使用 `"global"` 命名空间，行为完全不变
- MCP Server 注册时自动分配命名空间 `"mcp::{server_name}"`

**未来平台暴露给 MCP Agent 的工具**：
```
memory.write(content, key?)         → 写入该 Agent 专属知识库
memory.search(query, top_k?)        → 向量检索
memory.read(key)                    → 精确读取
memory.delete(key)                  → 删除条目
```

---

## 12. 开发路线图

### 第一阶段：工具接入（核心功能）

```
Sprint 1（约 2-3 天）
  ① 数据库模型 + Alembic migration
     文件：api/migrations/versions/xxxx_add_mcp_servers.py

  ② 协议类型定义
     文件：api/app/infrastructure/mcp/protocol.py
     内容：MCPTool, MCPCallResult, ConnectionStatus 等 Pydantic 模型

  ③ 单连接封装
     文件：api/app/infrastructure/mcp/connection.py
     内容：MCPConnection 状态机 + SSE 通信

Sprint 2（约 2-3 天）
  ④ 连接池管理器
     文件：api/app/infrastructure/mcp/manager.py
     内容：MCPClientManager + CapabilityRegistry

  ⑤ CRUD 路由
     文件：api/app/api/routers/mcp_servers.py
     内容：注册/编辑/删除/test/refresh/status

  ⑥ 工具调度接入
     文件：api/app/application/agent_orchestrator.py（修改）
     内容：识别 mcp__ 前缀，转发调用

Sprint 3（约 1-2 天）
  ⑦ 前端 MCP 管理区块
     文件：app.py（修改 🛠 工具 Tab）
     内容：注册表单 + 状态展示 + 工具列表徽标
```

### 第二阶段：Chat Agent 接入

```
Sprint 4（约 2-3 天）
  ⑧ CollaborationOrchestrator 扩展
     文件：api/app/application/collaboration_orchestrator.py（修改）
     内容：MCPAgent 槽位支持

  ⑨ 会话创建接口扩展
     文件：api/app/api/routers/sessions.py（修改）
     内容：collab_config 支持 mcp 类型槽位

  ⑩ 前端协作表单扩展
     文件：app.py（修改协作会话创建区块）
     内容：模型选择器增加 MCP Agent 分组
```

### 第三阶段：创新点（待排期）

```
  ⑪ 托管记忆层（RAGPipeline namespace 化）
  ⑫ 智能路由 Agent
  ⑬ 平台双身份 MCP Server
```

---

## 13. 风险与注意事项

### 安全风险

**认证头明文存储**

`auth_header` 字段（如 `Bearer sk-xxx`）存在数据库里。如果数据库泄露，这些密钥会暴露。

建议处理：
- MVP 阶段：存明文，接受这个风险（内部使用）
- 生产阶段：用 AES 或 KMS 加密存储，读取时解密

**用户 Agent 的恶意输出**

用户自己的 MCP Agent 可能返回恶意内容，被注入 LLM 上下文。

建议处理：
- 对 MCP Agent 返回的内容做长度限制（防 prompt 注入）
- 日志记录所有 MCP 调用的输入输出

### 稳定性风险

**级联超时**

用户 Agent 响应慢，导致整个对话请求超时。

处理：每个 `call_tool` 调用设置独立超时（默认 30 秒），超时后返回错误信息给 LLM，而不是挂起整个请求。

**SSE 连接泄漏**

MCPConnection 的后台重连任务如果没有正确取消，会在内存中积累。

处理：应用关闭时（lifespan cleanup）遍历所有连接，显式调用 `disconnect()` 并 cancel 所有 asyncio task。

### 兼容性风险

**MCP 协议版本**

MCP 协议还在演进（目前是 0.x 版本），可能有破坏性变更。

处理：在 `protocol.py` 里封装协议交互，当协议升级时只改这一个文件。使用官方 SDK 而非自己实现，SDK 会跟进协议变化。

---

## 14. 用户侧：如何开发一个 MCP Agent

详见 [MCP_DEVELOPER_GUIDE.md](MCP_DEVELOPER_GUIDE.md)。

---

*文档版本：v1.0 · 2026-05-26*
*作者：AgentNexus-J 工程团队*
