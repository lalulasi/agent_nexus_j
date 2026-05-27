"""MCPClientManager — 连接池 + CapabilityRegistry 单例。

职责：
- 应用启动时从 DB 加载所有激活的 MCPServer，建立连接
- 维护 CapabilityRegistry（内存中的工具能力索引）
- 对编排层提供统一调度接口：call_tool / chat / get_all_mcp_tools
- 提供 CRUD 操作后的热更新（新增/删除/激活/禁用不需重启）

使用方式：
    manager = get_mcp_manager()
    await manager.startup(db_session)        # lifespan 启动时调用
    await manager.shutdown()                 # lifespan 关闭时调用
    result = await manager.call_tool("rag_agent", "search_docs", {"query": "x"})
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.infrastructure.database.models import MCPServer
from api.app.infrastructure.mcp.connection import MCPConnection
from api.app.infrastructure.mcp.protocol import (
    CapabilityEntry,
    ConnectionStatus,
    MCPCallResult,
    MCPTool,
)


class MCPClientManager:
    """
    全局单例，管理所有 MCP Server 连接和能力注册表。

    CapabilityRegistry 结构::

        {
          "mcp__rag_agent__search_docs": CapabilityEntry,
          "mcp__code_bot__chat":          CapabilityEntry,
        }
    """

    def __init__(self) -> None:
        self._connections: dict[str, MCPConnection] = {}   # server_name → MCPConnection
        self._registry: dict[str, CapabilityEntry] = {}    # llm_tool_name → CapabilityEntry
        self._server_meta: dict[str, dict] = {}            # server_name → {id, display_name, mode}

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    async def startup(self, db: AsyncSession) -> None:
        """应用启动时调用：从 DB 加载所有激活 Server 并建立连接。"""
        result = await db.execute(
            select(MCPServer).where(MCPServer.is_active == True)
        )
        servers = result.scalars().all()
        for srv in servers:
            await self._connect_server(srv)
        logger.info(f"MCPClientManager 启动完成，已加载 {len(servers)} 个 Server")

    async def shutdown(self) -> None:
        """应用关闭时调用：断开所有连接。"""
        tasks = [conn.stop() for conn in self._connections.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._connections.clear()
        self._registry.clear()
        logger.info("MCPClientManager 已关闭所有 MCP 连接")

    # ── 热更新（CRUD 后调用） ─────────────────────────────────────────────────

    async def add_server(self, srv: MCPServer) -> None:
        """注册新 Server 并立即建立连接。"""
        await self._connect_server(srv)

    async def remove_server(self, server_name: str) -> None:
        """断开并移除指定 Server。"""
        conn = self._connections.pop(server_name, None)
        if conn:
            await conn.stop()
        self._server_meta.pop(server_name, None)
        self._remove_registry(server_name)
        logger.info(f"MCP [{server_name}] 已移除")

    async def activate_server(self, srv: MCPServer) -> None:
        """启用 Server（is_active 由调用方已写 DB）。"""
        if srv.name not in self._connections:
            await self._connect_server(srv)

    async def deactivate_server(self, server_name: str) -> None:
        """禁用 Server：断开连接但保留 DB 记录。"""
        conn = self._connections.pop(server_name, None)
        if conn:
            await conn.stop()
        self._server_meta.pop(server_name, None)
        self._remove_registry(server_name)

    async def refresh_tools(self, server_name: str) -> list[MCPTool]:
        """重新 list_tools，更新 CapabilityRegistry，返回最新工具列表。"""
        conn = self._connections.get(server_name)
        if not conn or conn.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(f"MCP [{server_name}] 未连接，无法刷新工具")
        tools = await conn.list_tools()
        meta = self._server_meta.get(server_name, {})
        self._rebuild_registry(
            server_name=server_name,
            server_id=meta.get("id", ""),
            display_name=meta.get("display_name", server_name),
            mode=meta.get("mode", "tool_provider"),
            tools=tools,
        )
        logger.info(f"MCP [{server_name}] 工具已刷新：{[t.name for t in tools]}")
        return tools

    # ── 编排层接口 ────────────────────────────────────────────────────────────

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> MCPCallResult:
        conn = self._get_conn(server_name)
        return await conn.call_tool(tool_name, arguments)

    async def chat(self, server_name: str, messages: list[dict]) -> str:
        conn = self._get_conn(server_name)
        return await conn.chat(messages)

    def get_all_mcp_tools(self) -> list[dict]:
        """返回所有已激活 MCP 工具的 LLM 工具定义列表（Anthropic 格式）。"""
        return [entry.to_llm_tool_def() for entry in self._registry.values()]

    def get_chat_agents(self) -> list[dict]:
        """返回所有 chat_agent 模式的 Server 信息列表（供协作表单使用）。"""
        seen: set[str] = set()
        agents = []
        for entry in self._registry.values():
            if entry.mode in ("chat_agent", "both") and entry.server_name not in seen:
                seen.add(entry.server_name)
                agents.append({
                    "server_name":  entry.server_name,
                    "display_name": entry.display_name,
                    "status":       self.get_status(entry.server_name),
                })
        return agents

    def get_status(self, server_name: str) -> ConnectionStatus:
        conn = self._connections.get(server_name)
        if conn is None:
            return ConnectionStatus.DISABLED
        return conn.status

    def get_all_statuses(self) -> dict[str, ConnectionStatus]:
        return {name: conn.status for name, conn in self._connections.items()}

    def is_mcp_tool(self, llm_tool_name: str) -> bool:
        return llm_tool_name.startswith("mcp__")

    def parse_mcp_tool_name(self, llm_tool_name: str) -> tuple[str, str]:
        """'mcp__rag_agent__search_docs' → ('rag_agent', 'search_docs')"""
        parts = llm_tool_name.split("__", 2)
        if len(parts) != 3:
            raise ValueError(f"无法解析 MCP 工具名: {llm_tool_name}")
        return parts[1], parts[2]

    # ── 内部 ──────────────────────────────────────────────────────────────────

    async def _connect_server(self, srv: MCPServer) -> None:
        server_name = srv.name
        self._server_meta[server_name] = {
            "id": str(srv.id),
            "display_name": srv.display_name,
            "mode": srv.mode,
        }

        # 若已有连接先清理
        old = self._connections.pop(server_name, None)
        if old:
            await old.stop()

        conn = MCPConnection(
            server_id=str(srv.id),
            server_name=server_name,
            url=srv.url,
            auth_header=srv.auth_header,
            on_status_change=self._on_status_change,
        )
        self._connections[server_name] = conn
        await conn.start()

        # 若 DB 已有缓存工具，先写入 Registry（保证连接中也能看到工具定义）
        if srv.discovered_tools:
            tools = [MCPTool(**t) for t in srv.discovered_tools]
            self._rebuild_registry(
                server_name=server_name,
                server_id=str(srv.id),
                display_name=srv.display_name,
                mode=srv.mode,
                tools=tools,
            )

        # 后台任务：连接成功后刷新工具
        asyncio.create_task(
            self._post_connect_refresh(server_name),
            name=f"mcp-refresh-{server_name}",
        )

    async def _post_connect_refresh(self, server_name: str) -> None:
        """等待连接就绪后，自动刷新工具列表。"""
        conn = self._connections.get(server_name)
        if not conn:
            return
        for _ in range(30):
            if conn.status == ConnectionStatus.CONNECTED:
                try:
                    await self.refresh_tools(server_name)
                except Exception as e:
                    logger.warning(f"MCP [{server_name}] 连接后刷新工具失败: {e}")
                return
            await asyncio.sleep(1)

    def _on_status_change(self, server_name: str, status: ConnectionStatus) -> None:
        logger.debug(f"MCP [{server_name}] 状态变更: {status}")
        if status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.ERROR):
            self._remove_registry(server_name)

    def _rebuild_registry(
        self,
        server_name: str,
        server_id: str,
        display_name: str,
        mode: str,
        tools: list[MCPTool],
    ) -> None:
        self._remove_registry(server_name)
        for tool in tools:
            entry = CapabilityEntry(
                server_id=server_id,
                server_name=server_name,
                display_name=display_name,
                tool=tool,
                mode=mode,
            )
            self._registry[entry.llm_tool_name] = entry

    def _remove_registry(self, server_name: str) -> None:
        keys = [k for k, v in self._registry.items() if v.server_name == server_name]
        for k in keys:
            del self._registry[k]

    def _get_conn(self, server_name: str) -> MCPConnection:
        conn = self._connections.get(server_name)
        if not conn:
            raise RuntimeError(f"MCP Server '{server_name}' 未注册")
        if conn.status != ConnectionStatus.CONNECTED:
            raise RuntimeError(
                f"MCP Server '{server_name}' 未就绪，当前状态: {conn.status}"
            )
        return conn


# ── 全局单例 ──────────────────────────────────────────────────────────────────

_manager: MCPClientManager | None = None


def get_mcp_manager() -> MCPClientManager:
    global _manager
    if _manager is None:
        _manager = MCPClientManager()
    return _manager
