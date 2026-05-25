from typing import Any

import httpx

from api.app.core.logger import logger
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
        logger.info(f"HTTP 工具 '{self.name}' → {self._method} {self._url} params={kwargs}")
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                if self._method == "GET":
                    resp = await client.get(self._url, params=kwargs, headers=self._headers)
                else:
                    resp = await client.post(self._url, json=kwargs, headers=self._headers)
                resp.raise_for_status()
                return resp.text[:4000] or "（响应为空）"
        except httpx.HTTPStatusError as e:
            return f"❌ HTTP {e.response.status_code}：{e.response.text[:500]}"
        except Exception as e:
            return f"❌ 工具调用失败：{e}"
