"""
Mock MCP Server — 用于本地测试 AgentNexus-J 的 MCP 接入功能。

运行方式：
    uv run python mock_mcp_server.py

服务地址：http://localhost:8503

暴露的能力（mode = both，工具提供者 + Chat Agent）：
  工具：
    echo(message)              → 回显输入，验证工具调用链路
    get_time()                 → 返回当前服务器时间
    calculator(expression)     → 安全计算数学表达式（+、-、*、/、**）
  Chat：
    chat(messages)             → 数学推理专家 Agent，用于协作会话

通信协议（HTTP + SSE，与 connection.py 完全对应）：
    GET  /sse                  → 建立 SSE 长连接，推送 POST endpoint
    POST /messages/{sid}       → 接收 JSON-RPC 请求，通过 SSE 推送响应
    GET  /health               → 健康检查
"""
from __future__ import annotations

import ast
import asyncio
import json
import operator
import uuid
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="Mock MCP Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# session_id → asyncio.Queue（SSE 通道）
_sessions: dict[str, asyncio.Queue] = {}

# ── 工具定义（工具清单，符合 MCPTool schema） ─────────────────────────────────

TOOLS = [
    {
        "name": "echo",
        "description": "原样返回输入的文本，用于验证工具调用链路是否正常。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "要回显的内容"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "get_time",
        "description": "返回当前服务器的系统时间（北京时间格式）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "calculator",
        "description": "安全计算数学表达式，支持 +、-、*、/、** 运算符。例：2 ** 10 + 3 * 4。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "合法的数学表达式字符串，如 '(3 + 5) * 2'",
                },
            },
            "required": ["expression"],
        },
    },
    {
        "name": "chat",
        "description": (
            "Chat Agent 接口：接收对话历史，以「数学推理专家」身份参与回答。"
            "用于圆桌/主从协作模式中作为 MCP Agent 槽位。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "对话历史，格式：[{\"role\": \"user\", \"content\": \"...\"}, ...]",
                },
            },
            "required": ["messages"],
        },
    },
]

# ── 工具执行 ──────────────────────────────────────────────────────────────────

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError(f"不支持的运算: {ast.dump(node)}")


def _run_tool(name: str, args: dict) -> str:
    if name == "echo":
        return args.get("message", "（空消息）")

    if name == "get_time":
        return f"当前时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    if name == "calculator":
        expr = args.get("expression", "").strip()
        try:
            tree = ast.parse(expr, mode="eval")
            result = _safe_eval(tree.body)
            # 整数结果不显示小数点
            result_str = str(int(result)) if isinstance(result, float) and result.is_integer() else str(result)
            return f"{expr} = {result_str}"
        except Exception as e:
            raise ValueError(f"表达式解析失败：{e}")

    if name == "chat":
        messages = args.get("messages", [])
        return _chat_response(messages)

    raise ValueError(f"未知工具：{name}")


def _chat_response(messages: list[dict]) -> str:
    """数学推理专家 Agent 的回复逻辑。"""
    last_user = next(
        (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    # 提取关键词判断回答策略
    has_math = any(kw in last_user for kw in ["+", "-", "*", "/", "计算", "数学", "公式", "等于", "多少"])
    has_logic = any(kw in last_user for kw in ["如果", "假设", "推导", "证明", "逻辑"])

    lines = [
        "【MockMCP · 数学推理专家】",
        "",
        f"收到问题：{last_user[:300]}",
        "",
    ]

    if has_math:
        lines += [
            "从数学计算角度分析：",
            "1. 首先确认运算的优先级和边界条件",
            "2. 建议将复杂表达式分解为子问题逐步求解",
            "3. 最终结果需验证数量级是否合理",
        ]
    elif has_logic:
        lines += [
            "从逻辑推理角度分析：",
            "1. 建立前提条件和约束",
            "2. 运用形式逻辑进行推导",
            "3. 检查结论是否存在反例",
        ]
    else:
        lines += [
            "作为数学推理专家，我的分析视角：",
            "1. 将问题形式化，明确输入/输出定义",
            "2. 寻找问题的数学结构（线性、概率、图论等）",
            "3. 选择最简洁的解法路径，避免冗余步骤",
            "",
            "（注：本 Agent 为 AgentNexus-J Mock MCP Server，用于测试协作模式）",
        ]

    return "\n".join(lines)


# ── JSON-RPC 请求路由 ─────────────────────────────────────────────────────────

def _handle_rpc(method: str, params: dict) -> tuple[dict, dict | None]:
    """返回 (result, error)，error 为 None 表示成功。"""
    if method == "initialize":
        return {
            "protocolVersion": "0.1.0",
            "serverInfo": {"name": "mock-mcp-server", "version": "1.0"},
            "capabilities": {"tools": {}},
        }, None

    if method == "tools/list":
        return {"tools": TOOLS}, None

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            text = _run_tool(tool_name, arguments)
            return {"content": [{"type": "text", "text": text}], "isError": False}, None
        except Exception as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}, None

    return {}, {"code": -32601, "message": f"Method not found: {method}"}


# ── SSE 端点 ──────────────────────────────────────────────────────────────────

@app.get("/sse")
async def sse_endpoint(request: Request):
    """
    MCP 握手入口。
    1. 生成会话 ID，创建响应队列
    2. 第一个 SSE 事件推送 POST 端点 URL（纯文本，非 JSON）
    3. 持续等待队列消息并推送 JSON-RPC 响应
    """
    session_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _sessions[session_id] = queue
    print(f"  ↑ 新连接: session={session_id[:8]}...")

    async def event_stream():
        try:
            # 第一条：POST 端点地址（客户端 connection.py 会解析此行确定请求地址）
            yield f"data: /messages/{session_id}\n\n"

            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if msg is None:
                        break
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    # 保活注释行，避免代理/nginx 断开空闲连接
                    yield ": keepalive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            _sessions.pop(session_id, None)
            print(f"  ↓ 连接关闭: session={session_id[:8]}...")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── JSON-RPC POST 端点 ────────────────────────────────────────────────────────

@app.post("/messages/{session_id}")
async def messages_endpoint(session_id: str, request: Request):
    """
    接收客户端的 JSON-RPC 请求，处理后将响应推入对应会话的 SSE 队列。
    """
    queue = _sessions.get(session_id)
    if queue is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id[:8]} not found")

    body = await request.json()
    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    print(f"  → RPC [{method}] id={str(req_id)[:8]}")

    result, error = _handle_rpc(method, params)

    if error:
        rpc_response = {"jsonrpc": "2.0", "id": req_id, "error": error}
    else:
        rpc_response = {"jsonrpc": "2.0", "id": req_id, "result": result}

    await queue.put(rpc_response)
    return {"ok": True}


# ── 健康检查 ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "server": "mock-mcp-server",
        "mode": "both",
        "tools": [t["name"] for t in TOOLS],
        "active_sessions": len(_sessions),
    }


# ── 启动 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  🔌 Mock MCP Server")
    print("=" * 55)
    print(f"  地址:  http://localhost:8503")
    print(f"  模式:  both（工具提供者 + Chat Agent）")
    print(f"  工具:  echo / get_time / calculator / chat")
    print(f"  SSE:   GET  http://localhost:8503/sse")
    print(f"  RPC:   POST http://localhost:8503/messages/{{sid}}")
    print(f"  健康:  GET  http://localhost:8503/health")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=8503, log_level="warning")
