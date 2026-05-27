"""MCP Server 管理路由。

端点：
    GET    /mcp-servers/           列出所有 Server（含实时状态）
    POST   /mcp-servers/           注册新 Server
    PATCH  /mcp-servers/{id}       更新配置
    DELETE /mcp-servers/{id}       删除
    POST   /mcp-servers/{id}/activate   启用 / 禁用切换
    POST   /mcp-servers/{id}/refresh    重新发现工具
    POST   /mcp-servers/{id}/test       临时连通性测试（不写 DB）
    GET    /mcp-servers/{id}/status     实时状态
"""
from __future__ import annotations

import time
import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.infrastructure.database.models import MCPServer
from api.app.infrastructure.database.session import get_db
from api.app.infrastructure.mcp.manager import get_mcp_manager
from api.app.infrastructure.mcp.protocol import (
    ConnectionStatus,
    MCPServerCreate,
    MCPServerOut,
    MCPServerUpdate,
    MCPTestResult,
    MCPTool,
)

router = APIRouter(prefix="/mcp-servers", tags=["mcp-servers"])
DB = Annotated[AsyncSession, Depends(get_db)]


def _to_out(srv: MCPServer) -> MCPServerOut:
    manager = get_mcp_manager()
    return MCPServerOut(
        id=str(srv.id),
        name=srv.name,
        display_name=srv.display_name,
        description=srv.description,
        url=srv.url,
        auth_header_set=bool(srv.auth_header),
        mode=srv.mode,
        is_active=srv.is_active,
        discovered_tools=srv.discovered_tools,
        status=manager.get_status(srv.name) if srv.is_active else ConnectionStatus.DISABLED,
        last_seen_at=srv.last_seen_at,
        created_at=srv.created_at,
        updated_at=srv.updated_at,
    )


@router.get("/", response_model=list[MCPServerOut])
async def list_servers(db: DB):
    result = await db.execute(select(MCPServer).order_by(MCPServer.created_at.desc()))
    servers = result.scalars().all()
    return [_to_out(s) for s in servers]


@router.post("/", response_model=MCPServerOut, status_code=status.HTTP_201_CREATED)
async def create_server(payload: MCPServerCreate, db: DB):
    # 名称唯一检查
    existing = await db.execute(select(MCPServer).where(MCPServer.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"名称 '{payload.name}' 已存在")

    srv = MCPServer(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        url=payload.url,
        auth_header=payload.auth_header or None,
        mode=payload.mode,
        is_active=True,
    )
    db.add(srv)
    await db.flush()
    await db.refresh(srv)

    # 触发连接
    await get_mcp_manager().add_server(srv)
    logger.info(f"MCP Server 已注册: {srv.name}")
    return _to_out(srv)


@router.patch("/{server_id}", response_model=MCPServerOut)
async def update_server(server_id: uuid.UUID, payload: MCPServerUpdate, db: DB):
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")

    if payload.display_name is not None:
        srv.display_name = payload.display_name
    if payload.description is not None:
        srv.description = payload.description
    if payload.url is not None:
        srv.url = payload.url
    if payload.auth_header is not None:
        srv.auth_header = payload.auth_header.strip() or None  # "" 清除
    if payload.mode is not None:
        srv.mode = payload.mode

    await db.flush()
    await db.refresh(srv)

    # URL 或认证变更后重新连接
    if srv.is_active and (payload.url or payload.auth_header is not None):
        await get_mcp_manager().add_server(srv)

    return _to_out(srv)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: uuid.UUID, db: DB):
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")
    await get_mcp_manager().remove_server(srv.name)
    await db.delete(srv)
    logger.info(f"MCP Server 已删除: {srv.name}")


@router.post("/{server_id}/activate", response_model=MCPServerOut)
async def toggle_activate(server_id: uuid.UUID, db: DB):
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")

    srv.is_active = not srv.is_active
    await db.flush()
    await db.refresh(srv)

    if srv.is_active:
        await get_mcp_manager().activate_server(srv)
    else:
        await get_mcp_manager().deactivate_server(srv.name)

    return _to_out(srv)


@router.post("/{server_id}/refresh", response_model=MCPServerOut)
async def refresh_tools(server_id: uuid.UUID, db: DB):
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")

    try:
        tools = await get_mcp_manager().refresh_tools(srv.name)
        srv.discovered_tools = [t.model_dump() for t in tools]
        await db.flush()
        await db.refresh(srv)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _to_out(srv)


@router.post("/{server_id}/test", response_model=MCPTestResult)
async def test_connection(server_id: uuid.UUID, db: DB):
    """临时测试连通性：不写 DB，直接尝试连接并返回发现的工具列表。"""
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")

    start = time.monotonic()
    try:
        tools = await _probe_server(srv.url, srv.auth_header)
        latency = int((time.monotonic() - start) * 1000)
        return MCPTestResult(success=True, latency_ms=latency, discovered_tools=tools)
    except Exception as e:
        return MCPTestResult(success=False, error=str(e))


@router.get("/{server_id}/status")
async def get_status(server_id: uuid.UUID, db: DB):
    srv = await db.get(MCPServer, server_id)
    if not srv:
        raise HTTPException(status_code=404, detail="Server 不存在")
    manager = get_mcp_manager()
    return {
        "server_name": srv.name,
        "status": manager.get_status(srv.name) if srv.is_active else ConnectionStatus.DISABLED,
        "last_seen_at": srv.last_seen_at,
    }


# ── 内部：轻量探测（不走 MCPConnection 状态机） ────────────────────────────────

async def _probe_server(url: str, auth_header: str | None) -> list[MCPTool]:
    """
    发起一次性 SSE 连接探测，拿到 endpoint 后调用 list_tools。
    用于 /test 接口，不影响正式连接池。
    """
    from api.app.infrastructure.mcp.connection import MCPConnection, _CONNECT_TIMEOUT
    import asyncio

    tools_result: list[MCPTool] = []
    done_event = asyncio.Event()
    error_holder: list[Exception] = []

    async def _run():
        try:
            conn = MCPConnection(
                server_id="test",
                server_name="__probe__",
                url=url,
                auth_header=auth_header,
            )
            await conn.start()
            # 等待连接就绪
            for _ in range(int(_CONNECT_TIMEOUT)):
                from api.app.infrastructure.mcp.protocol import ConnectionStatus
                if conn.status == ConnectionStatus.CONNECTED:
                    tools = await conn.list_tools()
                    tools_result.extend(tools)
                    break
                await asyncio.sleep(1)
            await conn.stop()
        except Exception as e:
            error_holder.append(e)
        finally:
            done_event.set()

    task = asyncio.create_task(_run())
    try:
        await asyncio.wait_for(done_event.wait(), timeout=_CONNECT_TIMEOUT + 5)
    except asyncio.TimeoutError:
        task.cancel()
        raise RuntimeError(f"连接超时：无法在 {_CONNECT_TIMEOUT}s 内访问 {url}")

    if error_holder:
        raise error_holder[0]

    return tools_result
