import time
from typing import Any

import httpx

from api.app.core.logger import logger, outbound_logger
from api.app.infrastructure.tools.base import BaseTool

_TIMEOUT = 30


class HttpTool(BaseTool):
    """将 LLM 的工具调用转发到用户配置的 HTTP 端点。"""

    def __init__(self, record: Any) -> None:
        self.name = record.name
        self.description = record.description
        self.input_schema = record.parameters_schema or {"type": "object", "properties": {}}
        self._url: str = record.http_url or ""
        self._method: str = (record.http_method or "POST").upper()
        self._headers: dict = record.http_headers or {}

    async def run(self, **kwargs: Any) -> str:
        if not self._url:
            return "❌ 工具未配置 HTTP 地址。"

        outbound_logger.info(
            f"HTTP_TOOL ▶ '{self.name}'  {self._method} {self._url}\n"
            f"  params: {kwargs}"
        )
        _t0 = time.monotonic()

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                if self._method == "GET":
                    resp = await client.get(self._url, params=kwargs, headers=self._headers)
                else:
                    resp = await client.post(self._url, json=kwargs, headers=self._headers)
                resp.raise_for_status()
                _dur = time.monotonic() - _t0
                _body = resp.text[:500] + ("…" if len(resp.text) > 500 else "")
                outbound_logger.info(
                    f"HTTP_TOOL ◀ '{self.name}'  status={resp.status_code}  duration={_dur:.2f}s\n"
                    f"  response: {_body!r}"
                )
                logger.info(f"HTTP 工具 '{self.name}' → {self._method} {self._url} status={resp.status_code}")
                return resp.text[:4000] or "（响应为空）"
        except httpx.HTTPStatusError as e:
            _dur = time.monotonic() - _t0
            outbound_logger.warning(
                f"HTTP_TOOL ✗ '{self.name}'  status={e.response.status_code}  duration={_dur:.2f}s\n"
                f"  error: {e.response.text[:300]!r}"
            )
            return f"❌ HTTP {e.response.status_code}：{e.response.text[:500]}"
        except Exception as e:
            _dur = time.monotonic() - _t0
            outbound_logger.warning(
                f"HTTP_TOOL ✗ '{self.name}'  duration={_dur:.2f}s  error: {e}"
            )
            return f"❌ 工具调用失败：{e}"
