"""MCP 协议数据类型定义。

对应 MCP 规范中的 Tool、ToolResult 等核心对象，
以及平台内部使用的 ConnectionStatus 和 CapabilityEntry。
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── 连接状态 ──────────────────────────────────────────────────────────────────

class ConnectionStatus(str, Enum):
    CONNECTED    = "connected"     # 🟢 正常
    CONNECTING   = "connecting"    # 🟡 首次连接中
    RECONNECTING = "reconnecting"  # 🟡 断线重连中
    DISCONNECTED = "disconnected"  # 🔴 已断开（将触发重连）
    DISABLED     = "disabled"      # ⚫ 手动禁用，不重连
    ERROR        = "error"         # 🔴 持续失败，需人工干预


# ── MCP 协议对象 ──────────────────────────────────────────────────────────────

class MCPTool(BaseModel):
    """对应 MCP list_tools 返回的单个工具描述。"""
    name: str
    description: str = ""
    inputSchema: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})


class MCPCallResult(BaseModel):
    """call_tool 的返回结果。"""
    content: str        # 文本内容
    is_error: bool = False


class MCPInitializeResult(BaseModel):
    """initialize 握手返回的服务端信息。"""
    protocolVersion: str = ""
    serverInfo: dict = Field(default_factory=dict)
    capabilities: dict = Field(default_factory=dict)


# ── 平台内部：能力注册表条目 ───────────────────────────────────────────────────

class CapabilityEntry(BaseModel):
    """CapabilityRegistry 中的每个条目，描述一个 MCP 工具的完整信息。"""
    server_id: str              # MCPServer.id（str 格式）
    server_name: str            # MCPServer.name，用于工具前缀
    display_name: str           # MCPServer.display_name，用于 UI 展示
    tool: MCPTool               # 原始工具描述
    mode: str                   # tool_provider | chat_agent | both
    tags: list[str] = Field(default_factory=list)   # 预留：语义路由用

    @property
    def llm_tool_name(self) -> str:
        """传给 LLM 的工具名：mcp__{server_name}__{tool_name}"""
        return f"mcp__{self.server_name}__{self.tool.name}"

    def to_llm_tool_def(self) -> dict:
        """转换为 Anthropic tool_use 格式的工具定义。"""
        return {
            "name": self.llm_tool_name,
            "description": f"[{self.display_name}] {self.tool.description}",
            "input_schema": self.tool.inputSchema,
        }


# ── Pydantic Schemas（API 层） ─────────────────────────────────────────────────

class MCPServerCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,62}$",
                      description="唯一标识符，小写字母+下划线，用作工具前缀")
    display_name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    url: str = Field(..., min_length=1, description="MCP Server 的 SSE 端点地址")
    auth_header: str | None = None
    mode: str = Field(default="tool_provider",
                      pattern=r"^(tool_provider|chat_agent|both)$")


class MCPServerUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    url: str | None = None
    auth_header: str | None = None   # 空字符串 "" 表示清除
    mode: str | None = Field(default=None, pattern=r"^(tool_provider|chat_agent|both)$")


class MCPServerOut(BaseModel):
    id: str
    name: str
    display_name: str
    description: str
    url: str
    auth_header_set: bool       # 脱敏：只告知是否设置了认证头，不返回原值
    mode: str
    is_active: bool
    discovered_tools: list[dict] | None
    status: ConnectionStatus = ConnectionStatus.DISCONNECTED   # 实时状态，来自内存
    last_seen_at: Any | None = None
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


class MCPTestResult(BaseModel):
    success: bool
    latency_ms: int | None = None
    discovered_tools: list[MCPTool] | None = None
    error: str | None = None
