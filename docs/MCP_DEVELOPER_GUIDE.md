# AgentNexus-J · MCP Agent 接入开发者手册

> 本文档面向想要将自己的 Agent 接入 AgentNexus-J 平台的开发者。
> 阅读完本文你将能够：独立实现一个兼容平台的 MCP Server，并完成注册、联调与上线。

---

## 目录

1. [概述](#1-概述)
2. [接入模式](#2-接入模式)
3. [通信协议规范](#3-通信协议规范)
4. [握手流程详解](#4-握手流程详解)
5. [工具定义规范](#5-工具定义规范)
6. [Chat Agent 接口规范](#6-chat-agent-接口规范)
7. [完整实现示例（Python）](#7-完整实现示例python)
8. [注册与配置](#8-注册与配置)
9. [调试指南](#9-调试指南)
10. [常见错误与解决方案](#10-常见错误与解决方案)
11. [安全建议](#11-安全建议)
12. [限制与注意事项](#12-限制与注意事项)

---

## 1. 概述

AgentNexus-J 使用 **MCP（Model Context Protocol）** 协议与外部 Agent 通信。你开发的 Agent 作为 **MCP Server** 运行，平台作为 **MCP Client** 主动连接并调用你的能力。

```
AgentNexus-J（MCP Client）          你的 Agent（MCP Server）
        │                                      │
        │── GET /sse ──────────────────────────▶ 建立 SSE 长连接
        │◀─ data: /messages/{sid} ──────────── 返回 POST 端点
        │── POST /messages/{sid} ────────────▶ 发送 JSON-RPC 请求
        │◀─ data: {"jsonrpc":"2.0",...} ─────── 通过 SSE 推送响应
```

**传输层**：HTTP + Server-Sent Events（SSE），无需 WebSocket 或 gRPC。

---

## 2. 接入模式

注册时选择以下三种模式之一：

| 模式 | 标识符 | 用途 |
|------|--------|------|
| 工具提供者 | `tool_provider` | 仅提供工具，LLM 在对话中自动调用 |
| 对话 Agent | `chat_agent` | 以独立 AI 身份参与圆桌/主从协作 |
| 工具 + Agent | `both` | 同时具备以上两种能力（推荐） |

选择 `chat_agent` 或 `both` 时，必须实现 [`chat` 工具](#6-chat-agent-接口规范)。

---

## 3. 通信协议规范

### 3.1 必须实现的端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/sse` | GET | SSE 长连接入口，平台主动发起 |
| `/messages/{session_id}` | POST | 接收 JSON-RPC 请求（endpoint 由你决定，通过 SSE 告知） |

> POST 端点路径由你自由定义，只需在 SSE 首行将其推送给平台即可。

### 3.2 SSE 格式

每条 SSE 消息格式（遵循 W3C EventSource 规范）：

```
data: {内容}\n
\n
```

- **首条消息**：POST 端点路径（**纯文本**，非 JSON）
- **后续消息**：JSON-RPC 2.0 响应（JSON 字符串）
- **保活注释**：以 `:` 开头的行，平台会自动忽略

```
# 示例 SSE 流
data: /messages/550e8400-e29b-41d4-a716-446655440000

data: {"jsonrpc":"2.0","id":"abc","result":{...}}

: keepalive

data: {"jsonrpc":"2.0","id":"def","result":{...}}
```

### 3.3 JSON-RPC 2.0 格式

**请求（平台 → 你的 Server）**：
```json
{
  "jsonrpc": "2.0",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "method": "tools/call",
  "params": {
    "name": "your_tool",
    "arguments": {"key": "value"}
  }
}
```

**成功响应（你的 Server → 平台，经 SSE 推送）**：
```json
{
  "jsonrpc": "2.0",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "result": { ... }
}
```

**错误响应**：
```json
{
  "jsonrpc": "2.0",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "error": {
    "code": -32601,
    "message": "Method not found"
  }
}
```

> **重要**：响应必须通过 **SSE** 返回，而非 POST 请求的 HTTP 响应体。
> POST 接口只需返回 `{"ok": true}` 表示已收到即可。

---

## 4. 握手流程详解

平台连接你的 Server 时，按以下顺序进行：

```
1. 平台  GET /sse          → 建立 SSE 连接
2. 你    data: /messages/{sid}\n\n   → 告知 POST 端点（纯文本）
3. 平台  POST /messages/{sid}        → 发送 initialize 请求
4. 你    data: {jsonrpc 响应}\n\n    → 通过 SSE 返回 initialize 结果
5. 状态变为 CONNECTED，开始正常工作
```

### initialize 请求内容

```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "method": "initialize",
  "params": {
    "protocolVersion": "0.1.0",
    "clientInfo": {
      "name": "AgentNexus-J",
      "version": "1.0"
    },
    "capabilities": {}
  }
}
```

### initialize 响应内容

```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "result": {
    "protocolVersion": "0.1.0",
    "serverInfo": {
      "name": "your-server-name",
      "version": "1.0"
    },
    "capabilities": {
      "tools": {}
    }
  }
}
```

---

## 5. 工具定义规范

### 5.1 tools/list

平台在连接成功后会自动调用 `tools/list` 发现你的工具。

**请求**：
```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "method": "tools/list",
  "params": {}
}
```

**响应**：
```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "result": {
    "tools": [
      {
        "name": "search_docs",
        "description": "在知识库中搜索相关文档，返回最相关的段落。当用户询问公司政策或产品细节时使用。",
        "inputSchema": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "搜索关键词或自然语言问题"
            },
            "top_k": {
              "type": "integer",
              "description": "返回结果数量，默认 3",
              "default": 3
            }
          },
          "required": ["query"]
        }
      }
    ]
  }
}
```

### 5.2 工具命名规范

| 要求 | 说明 |
|------|------|
| 字符集 | 只允许 `[a-zA-Z0-9_-]` |
| 长度 | 建议不超过 40 字符 |
| 风格 | 小写字母 + 下划线，如 `search_docs`、`get_weather` |
| 禁止 | 不能以数字开头，不能包含空格或特殊符号 |

> 工具名到达 LLM 时会被自动加上前缀：`mcp__{server_name}__{tool_name}`。
> 例如：你的 `search_docs` → LLM 看到 `mcp__contract_agent__search_docs`。

### 5.3 description 写作建议

`description` 直接决定 LLM 是否以及何时调用你的工具，**写好描述是最关键的一步**：

✅ **好的描述**：
```
在公司合规知识库中搜索相关条款。当用户询问合同审查、法律条款、
合规要求时使用此工具。返回最相关的 3 条文档段落。
```

❌ **差的描述**：
```
搜索文档
```

建议包含：
- **是什么**：工具的核心能力
- **什么时候用**：触发场景（LLM 靠这个决策）
- **返回什么**：输出格式说明

### 5.4 tools/call

**请求**：
```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "method": "tools/call",
  "params": {
    "name": "search_docs",
    "arguments": {
      "query": "合同违约责任条款",
      "top_k": 3
    }
  }
}
```

**成功响应**：
```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "第十二条：违约责任。若甲方未按约定时间交付，..."
      }
    ],
    "isError": false
  }
}
```

**工具执行失败响应**（逻辑错误，非协议错误）：
```json
{
  "jsonrpc": "2.0",
  "id": "uuid",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "搜索失败：数据库连接超时"
      }
    ],
    "isError": true
  }
}
```

> `isError: true` 会在平台 UI 中显示为 `[工具错误]` 前缀，LLM 会感知到工具失败并作出相应处理。

---

## 6. Chat Agent 接口规范

选择 `chat_agent` 或 `both` 模式时，**必须**在工具列表中暴露名为 `chat` 的工具。

### 工具定义

```json
{
  "name": "chat",
  "description": "接收对话历史，以[你的角色定位]身份参与回答。",
  "inputSchema": {
    "type": "object",
    "properties": {
      "messages": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "role":    {"type": "string", "enum": ["user", "assistant"]},
            "content": {"type": "string"}
          }
        },
        "description": "对话历史，最后一条为当前问题"
      }
    },
    "required": ["messages"]
  }
}
```

### 调用示例

平台在协作模式中会这样调用你的 `chat` 工具：

```json
{
  "method": "tools/call",
  "params": {
    "name": "chat",
    "arguments": {
      "messages": [
        {
          "role": "user",
          "content": "[系统指令] 你是批判者（Critic）。专门审视答案中的漏洞和不完整之处。\n\n请分析：AI 大模型的涌现能力是否可以用传统神经网络理论解释？"
        }
      ]
    }
  }
}
```

### 响应要求

- 返回纯文本，内容将直接展示在协作结果中
- 建议在回复开头标注角色，例如 `【合同审查助手】`，方便用户区分
- 响应时间建议 < 30 秒（平台超时设置为 30s）
- 不需要流式输出，返回完整文本即可

---

## 7. 完整实现示例（Python）

以下是可直接运行的最小实现，基于 `fastapi` + `uvicorn`：

```python
"""
my_mcp_server.py — 最小 MCP Server 实现模板

依赖：pip install fastapi uvicorn httpx
启动：python my_mcp_server.py
"""
import asyncio
import json
import uuid
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# session_id → asyncio.Queue（每个 SSE 连接一个队列）
_sessions: dict[str, asyncio.Queue] = {}

# ── 1. 定义你的工具 ──────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_docs",
        "description": (
            "在合同知识库中搜索相关条款。当用户询问合规、违约、"
            "赔偿等法律问题时调用此工具。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "chat",
        "description": "以合同审查专家身份参与多模型协作对话。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "对话历史",
                }
            },
            "required": ["messages"],
        },
    },
]

# ── 2. 工具执行逻辑 ──────────────────────────────────────────────────────────

def run_tool(name: str, arguments: dict) -> str:
    if name == "search_docs":
        query = arguments.get("query", "")
        # 替换为你的真实检索逻辑
        return f"关于「{query}」的检索结果：第十二条违约责任……（示例）"

    if name == "chat":
        messages = arguments.get("messages", [])
        last = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            ""
        )
        # 替换为你的真实 AI 调用逻辑
        return f"【合同审查专家】针对问题「{last[:100]}」的专业意见：……"

    raise ValueError(f"未知工具: {name}")

# ── 3. JSON-RPC 路由 ─────────────────────────────────────────────────────────

def handle_rpc(method: str, params: dict) -> tuple[dict, dict | None]:
    """返回 (result, error)"""
    if method == "initialize":
        return {
            "protocolVersion": "0.1.0",
            "serverInfo": {"name": "my-mcp-server", "version": "1.0"},
            "capabilities": {"tools": {}},
        }, None

    if method == "tools/list":
        return {"tools": TOOLS}, None

    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            text = run_tool(name, arguments)
            return {"content": [{"type": "text", "text": text}], "isError": False}, None
        except Exception as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}, None

    return {}, {"code": -32601, "message": f"Method not found: {method}"}

# ── 4. SSE 端点 ──────────────────────────────────────────────────────────────

@app.get("/sse")
async def sse(request: Request):
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sessions[session_id] = queue

    async def stream():
        try:
            # 必须先发 POST 端点路径（纯文本，非 JSON）
            yield f"data: /messages/{session_id}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if msg is None:
                        break
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"   # 保活，客户端会忽略
        finally:
            _sessions.pop(session_id, None)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── 5. JSON-RPC POST 端点 ────────────────────────────────────────────────────

@app.post("/messages/{session_id}")
async def messages(session_id: str, request: Request):
    queue = _sessions.get(session_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Session not found")

    body = await request.json()
    result, error = handle_rpc(body.get("method", ""), body.get("params", {}))

    response = (
        {"jsonrpc": "2.0", "id": body.get("id"), "error": error}
        if error else
        {"jsonrpc": "2.0", "id": body.get("id"), "result": result}
    )
    await queue.put(response)
    return {"ok": True}   # POST 响应体无关紧要，真正的结果走 SSE

# ── 6. 健康检查（可选，推荐） ─────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "tools": [t["name"] for t in TOOLS]}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8504)
```

---

## 8. 注册与配置

### 8.1 在平台注册你的 Server

1. 打开 AgentNexus-J → 侧边栏 → **🛠 工具** Tab → **🔌 MCP Agent**
2. 展开「＋ 接入 MCP Server」，填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| **名称** | 小写字母+下划线，作为工具前缀，注册后不可修改 | `contract_agent` |
| **显示名称** | 在 UI 和协作流中展示 | `合同审查助手` |
| **描述** | 告知 LLM 该 Agent 的整体用途 | `专注合同法律条款的审查助手` |
| **URL** | 你的 SSE 端点基础地址 | `http://192.168.1.100:8504` |
| **认证头** | 可选，Bearer Token | `Bearer sk-your-key` |
| **接入模式** | 按需选择 | `工具+Agent` |

> URL 填写 **基础地址**（不含 `/sse`），平台会自动追加 `/sse` 和 `/messages/{sid}`。

### 8.2 认证

如果你的 Server 需要认证，在注册时填入「认证头」字段（如 `Bearer sk-xxx`）。平台在每次请求（SSE GET 和 JSON-RPC POST）时都会在 `Authorization` 请求头中携带该值。

你的 Server 验证方式：

```python
from fastapi import Header, HTTPException

@app.get("/sse")
async def sse(authorization: str | None = Header(default=None)):
    if authorization != "Bearer sk-your-secret-key":
        raise HTTPException(status_code=401, detail="Unauthorized")
    ...
```

### 8.3 连接状态说明

| 图标 | 状态 | 说明 |
|------|------|------|
| 🟢 | 已连接 | 工具可用，协作可参与 |
| 🟡 | 连接中/重连中 | 正在握手或断线重试，最多等 10s |
| 🔴 | 连接错误 | 握手失败，检查 URL 和服务状态 |
| ⚫ | 已禁用 | 手动禁用，工具不可用 |

连接后平台会自动发现工具（`tools/list`）。如果工具列表更新，点击 **🔄** 按钮手动刷新。

---

## 9. 调试指南

### 9.1 用 curl 验证 SSE 端点

```bash
# 确认 SSE 连接是否正常
curl -N -H "Accept: text/event-stream" http://localhost:8504/sse

# 预期输出（前两行）
# data: /messages/550e8400-e29b-41d4-a716-446655440000
#
```

### 9.2 手动发送 JSON-RPC 请求

```bash
# 替换 {sid} 为上面 curl 输出中的 session_id
SID="550e8400-e29b-41d4-a716-446655440000"

# 测试 tools/list
curl -X POST http://localhost:8504/messages/$SID \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"test-1","method":"tools/list","params":{}}'

# 测试工具调用
curl -X POST http://localhost:8504/messages/$SID \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"test-2","method":"tools/call","params":{"name":"search_docs","arguments":{"query":"违约责任"}}}'
```

> 响应不会出现在 curl POST 的返回里，而是出现在第一个 `curl -N` 的 SSE 流中。

### 9.3 平台侧日志确认

平台后端日志中搜索以下关键字：

```
MCP [your_server_name] 连接已建立         ← 握手成功
MCP 工具已注入 LLM 上下文: ['mcp__...']   ← 工具已进入 LLM context
调用工具: ['mcp__your_server__tool_name']  ← LLM 正在调用你的工具
工具 'mcp__...' → ...                     ← 工具返回结果
```

---

## 10. 常见错误与解决方案

### SSE 连接建立后状态一直是 🟡

**原因**：`initialize` 握手超时（10 秒内未收到响应）。

**排查**：
1. 确认 POST 端点可以被正常访问
2. 确认 `initialize` 响应通过 **SSE** 返回，而非 POST 的 HTTP 响应体
3. 用 curl 手动测试 SSE 流

### 工具不被 LLM 调用

**原因**：工具 `description` 不够清晰，或 LLM 判断不需要工具。

**解决**：
1. 优化 description，明确写出"何时调用"
2. 用明确的 prompt 强制触发，例如：`请调用 mcp__{server_name}__{tool_name} 工具……`
3. 点击 🔄 确认工具已刷新

### tools/call 调用后 LLM 报告"工具执行错误"

**原因**：`result.content` 格式不符合规范，或 `isError: true`。

**检查**：确认返回格式严格符合：
```json
{
  "content": [{"type": "text", "text": "你的结果"}],
  "isError": false
}
```

### 工具调用超时

平台等待工具响应的超时时间为 **30 秒**。如果你的工具（例如大模型调用）耗时较长：
- 考虑异步处理 + 流式输出
- 或拆分为多个轻量工具

### 平台无法连接到你的 Server

常见原因：
- Server 运行在本机，但平台部署在远端 → 需要内网穿透或公网 IP
- 防火墙未放行端口
- URL 多了尾部 `/sse`（平台会自动追加，不要重复）

---

## 11. 安全建议

1. **始终启用认证**：生产环境必须在注册时设置 Bearer Token，防止未授权访问
2. **验证 arguments**：不要直接 `eval` 或 `exec` 来自工具调用的 `arguments` 内容
3. **限制返回内容大小**：工具返回的 `text` 字段建议不超过 4000 字符，避免撑爆 LLM context
4. **不要在工具返回中暴露内部错误堆栈**：捕获异常，返回用户友好的错误消息
5. **认证头在 DB 中明文存储**：平台当前 MVP 阶段不加密存储，生产部署时建议将平台也做私有化

---

## 12. 限制与注意事项

| 项目 | 当前限制 |
|------|---------|
| Server 名称 | 注册后不可修改（工具名前缀依赖它） |
| 单次工具调用超时 | 30 秒 |
| 连接超时 | 握手 10 秒内完成 |
| 工具数量 | 无硬限制，建议 ≤ 20 个 |
| 工具返回文本 | 建议 ≤ 4000 字符 |
| Chat 工具响应 | 不支持流式，返回完整文本 |
| 传输协议 | 仅支持 HTTP + SSE，暂不支持 stdio 模式 |
| 并发连接 | 每个注册 Server 维护一条长连接 |

---

## 附录：完整 JSON-RPC 方法列表

| 方法 | 调用时机 | 必须实现 |
|------|---------|---------|
| `initialize` | 每次握手时 | ✅ |
| `tools/list` | 连接成功后自动调用，及手动刷新时 | ✅ |
| `tools/call` | LLM 调用工具 / 协作模式触发 chat 时 | ✅ |

---

*文档版本：v1.0 · 对应 AgentNexus-J MCP 功能第一、二阶段*
