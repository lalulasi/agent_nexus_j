"""MCPConnection — 单个 MCP Server 的 SSE 连接封装。

职责：
- 维护与一个 MCP Server 的 HTTP+SSE 长连接
- 实现状态机：CONNECTING → CONNECTED → RECONNECTING（指数退避）
- 对上层暴露 call_tool / chat / list_tools 三个方法
- 所有异常在此层处理，不向上传播连接级错误

MCP 通信流程：
  客户端 GET /sse      → 建立 SSE 连接，服务端推送 endpoint URL
  客户端 POST {url}    → 发送 JSON-RPC 请求
  服务端通过 SSE 推送  → JSON-RPC 响应
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx

from api.app.core.logger import logger, outbound_logger
from api.app.infrastructure.mcp.protocol import (
    ConnectionStatus,
    MCPCallResult,
    MCPTool,
)

# 重连参数
_BACKOFF_BASE    = 1.0    # 初始等待秒数
_BACKOFF_MAX     = 60.0   # 最大等待秒数
_BACKOFF_FACTOR  = 2.0    # 每次失败乘以该系数
_CALL_TIMEOUT    = 30.0   # 单次工具调用超时（秒）
_CONNECT_TIMEOUT = 10.0   # 握手超时（秒）


class MCPConnection:
    """
    管理与单个 MCP Server 的连接生命周期。

    使用方法::

        conn = MCPConnection(server_id, server_name, url, auth_header, on_status_change)
        await conn.start()          # 启动后台连接任务
        result = await conn.call_tool("search_docs", {"query": "xxx"})
        tools  = await conn.list_tools()
        await conn.stop()           # 关闭连接
    """

    def __init__(
        self,
        server_id: str,
        server_name: str,
        url: str,
        auth_header: str | None,
        on_status_change: Any | None = None,   # callable(server_name, status)
    ) -> None:
        self.server_id      = server_id
        self.server_name    = server_name
        self.url            = url.rstrip("/")
        self.auth_header    = auth_header
        self._on_status_change = on_status_change

        self._status        = ConnectionStatus.DISCONNECTED
        self._post_endpoint: str | None = None   # 握手后拿到的 POST 地址
        self._pending: dict[str, asyncio.Future] = {}   # request_id → Future
        self._task: asyncio.Task | None = None
        self._stop_event    = asyncio.Event()
        self._backoff       = _BACKOFF_BASE

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    @property
    def status(self) -> ConnectionStatus:
        return self._status

    async def start(self) -> None:
        """启动后台连接循环（非阻塞）。"""
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=f"mcp-{self.server_name}")

    async def stop(self) -> None:
        """停止连接循环并清理资源。"""
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._set_status(ConnectionStatus.DISABLED)
        self._reject_pending("连接已关闭")

    async def list_tools(self) -> list[MCPTool]:
        """调用 MCP list_tools，返回工具列表。连接未就绪时抛出 RuntimeError。"""
        raw = await self._rpc("tools/list", {})
        tools_data = raw.get("tools", [])
        return [MCPTool(**t) for t in tools_data]

    async def call_tool(self, tool_name: str, arguments: dict) -> MCPCallResult:
        """调用指定工具，返回文本结果。"""
        raw = await self._rpc("tools/call", {"name": tool_name, "arguments": arguments})
        content_list = raw.get("content", [])
        texts = [c.get("text", "") for c in content_list if c.get("type") == "text"]
        is_error = raw.get("isError", False)
        return MCPCallResult(content="\n".join(texts), is_error=is_error)

    async def chat(self, messages: list[dict]) -> str:
        """调用 chat 工具（Chat Agent 模式专用）。"""
        result = await self.call_tool("chat", {"messages": messages})
        if result.is_error:
            raise RuntimeError(f"MCP chat 工具返回错误: {result.content}")
        return result.content

    # ── 内部：连接循环 ────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._set_status(ConnectionStatus.CONNECTING)
                await self._connect_and_listen()
                # 正常退出（stop_event 触发）
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    f"MCP [{self.server_name}] 连接失败: {e}，"
                    f"{self._backoff:.0f}s 后重试"
                )
                self._set_status(ConnectionStatus.RECONNECTING)
                self._reject_pending(str(e))
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._backoff
                    )
                    break  # stop_event 触发，退出
                except asyncio.TimeoutError:
                    pass
                self._backoff = min(self._backoff * _BACKOFF_FACTOR, _BACKOFF_MAX)

    async def _connect_and_listen(self) -> None:
        """建立 SSE 连接，完成 MCP 握手，持续监听服务端消息。"""
        headers = {"Accept": "text/event-stream"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        # read=None：SSE 是持久长连接，不设读超时；connect 保留握手超时
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=None, write=30.0, pool=None)
        ) as client:
            sse_url = f"{self.url}/sse"
            async with client.stream("GET", sse_url, headers=headers) as resp:
                resp.raise_for_status()

                async for line in resp.aiter_lines():
                    if self._stop_event.is_set():
                        return

                    line = line.strip()
                    if not line or line.startswith(":"):
                        # 空行或 SSE 保活注释，跳过
                        continue

                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            # 纯文本 → POST endpoint URL（握手第一步）
                            if self._post_endpoint is None:
                                self._post_endpoint = (
                                    data_str
                                    if data_str.startswith("http")
                                    else f"{self.url}{data_str}"
                                )
                                # 在独立 task 中发 initialize，让本循环继续读 SSE 响应
                                asyncio.create_task(
                                    self._do_initialize(),
                                    name=f"mcp-init-{self.server_name}",
                                )
                            continue

                        # JSON-RPC 响应 → 匹配 pending future
                        req_id = str(data.get("id", ""))
                        if req_id in self._pending:
                            fut = self._pending.pop(req_id)
                            if not fut.done():
                                error = data.get("error")
                                if error:
                                    fut.set_exception(
                                        RuntimeError(error.get("message", "RPC error"))
                                    )
                                else:
                                    fut.set_result(data.get("result", {}))

    async def _do_initialize(self) -> None:
        """独立 task：发 initialize，等 SSE 循环回送响应后置为 CONNECTED。

        必须在独立 task 中运行，否则会和 SSE 循环互相等待（死锁）：
        SSE 循环需要运行才能 resolve future，而 future 的等待会阻塞 SSE 循环。
        """
        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "0.1.0",
                "clientInfo": {"name": "AgentNexus-J", "version": "1.0"},
                "capabilities": {},
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(_CALL_TIMEOUT)) as c:
                await c.post(self._post_endpoint, json=payload, headers=headers)
            # SSE 循环（另一个 task）读到响应后会 resolve fut
            await asyncio.wait_for(fut, timeout=_CALL_TIMEOUT)
            self._set_status(ConnectionStatus.CONNECTED)
            self._backoff = _BACKOFF_BASE
            logger.info(f"MCP [{self.server_name}] 连接已建立")
        except Exception as e:
            self._pending.pop(req_id, None)
            logger.warning(f"MCP [{self.server_name}] initialize 失败: {e}")

    # ── 内部：RPC 调用 ────────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict) -> dict:
        if self._status != ConnectionStatus.CONNECTED or self._post_endpoint is None:
            raise RuntimeError(f"MCP [{self.server_name}] 未连接，当前状态: {self._status}")

        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        async with httpx.AsyncClient(timeout=httpx.Timeout(_CALL_TIMEOUT)) as client:
            return await self._send_rpc(client, method, params)

    async def _send_rpc(self, client: httpx.AsyncClient, method: str, params: dict) -> dict:
        req_id = str(uuid.uuid4())
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut

        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        endpoint = self._post_endpoint or f"{self.url}/messages"

        # 截断 params 避免日志过长（工具调用参数可能包含大量文本）
        _params_preview = json.dumps(params, ensure_ascii=False)
        if len(_params_preview) > 500:
            _params_preview = _params_preview[:500] + "…"
        outbound_logger.info(
            f"MCP ▶ {self.server_name}  method={method}  endpoint={endpoint}\n"
            f"  params: {_params_preview}"
        )
        _t0 = time.monotonic()

        try:
            await client.post(endpoint, json=payload, headers=headers)
            result = await asyncio.wait_for(fut, timeout=_CALL_TIMEOUT)
            _dur = time.monotonic() - _t0
            _result_preview = json.dumps(result, ensure_ascii=False)
            if len(_result_preview) > 500:
                _result_preview = _result_preview[:500] + "…"
            outbound_logger.info(
                f"MCP ◀ {self.server_name}  method={method}  duration={_dur:.2f}s\n"
                f"  result: {_result_preview}"
            )
            return result
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            outbound_logger.warning(
                f"MCP ✗ {self.server_name}  method={method}  TIMEOUT after {_CALL_TIMEOUT}s"
            )
            raise RuntimeError(f"MCP [{self.server_name}].{method} 调用超时")
        except Exception as e:
            self._pending.pop(req_id, None)
            outbound_logger.warning(
                f"MCP ✗ {self.server_name}  method={method}  ERROR: {e}"
            )
            raise

    # ── 内部：状态管理 ────────────────────────────────────────────────────────

    def _set_status(self, status: ConnectionStatus) -> None:
        if self._status != status:
            self._status = status
            if self._on_status_change:
                try:
                    self._on_status_change(self.server_name, status)
                except Exception:
                    pass

    def _reject_pending(self, reason: str) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(reason))
        self._pending.clear()
