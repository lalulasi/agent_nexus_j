"""网络搜索工具，支持三个提供商：
- ddgs:   DuckDuckGo（免费，无需 API Key，通过 duckduckgo-search 库调用）
- tavily: Tavily Search API（AI 原生，每月 1000 次免费）
- serper: Serper.dev（Google 结果，2500 次一次性免费额度）
"""
from __future__ import annotations

import asyncio
import warnings
from typing import Any

# duckduckgo_search 8.x 已改名为 ddgs，但仍可用；全局屏蔽迁移 RuntimeWarning
warnings.filterwarnings("ignore", category=RuntimeWarning, module=".*duckduckgo.*")
warnings.filterwarnings("ignore", message=".*renamed.*ddgs.*")

import httpx

from api.app.core.logger import logger, outbound_logger
from api.app.infrastructure.tools.base import BaseTool

_TAVILY_URL = "https://api.tavily.com/search"
_SERPER_URL = "https://google.serper.dev/search"
_TIMEOUT = 20
# (backend, region) 尝试顺序；html 经常被封不使用
_DDGS_ATTEMPTS = [
    ("lite", "wt-wt"),
    ("auto", "wt-wt"),
    ("lite", "us-en"),
]


class SearchTool(BaseTool):
    """将用户查询发送到配置的搜索引擎，返回摘要结果供 LLM 参考。"""

    name = "web_search"
    description = (
        "搜索互联网获取实时信息。当用户询问近期事件、新闻、最新数据、"
        "价格行情或任何超出训练知识范围的内容时调用此工具。"
        "重要：query 参数必须使用简短关键词（2-5个词），避免使用'今日''最新''当前'等冗余词，"
        "也不要带完整疑问句。例如：询问美国新闻用'美国 新闻'，询问苹果股价用'Apple stock price'。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "搜索关键词，2-5个词为宜。"
                    "✓ 好的示例：'美国 新闻'、'Apple earnings 2025'、'Python 教程'。"
                    "✗ 避免：'请帮我查一下今天美国有什么新闻'、'最新消息'等冗长句子。"
                ),
            },
            "search_type": {
                "type": "string",
                "enum": ["general", "news"],
                "description": (
                    "general：通用网页搜索；news：新闻搜索（优先返回近一周内容）。"
                    "用户明确询问新闻/时事/近期事件时选 news，其他情况选 general。"
                ),
            },
        },
        "required": ["query"],
    }

    def __init__(self, config_record: Any) -> None:
        self._provider: str = config_record.provider
        self._api_key: str | None = config_record.api_key
        self._max_results: int = config_record.max_results

    async def run(self, **kwargs: Any) -> str:
        query: str = kwargs.get("query", "").strip()
        search_type: str = kwargs.get("search_type", "general")
        if not query:
            return "❌ 搜索关键词不能为空。"

        outbound_logger.info(
            f"SEARCH ▶ provider={self._provider}  type={search_type}  "
            f"query={query!r}  max={self._max_results}"
        )

        try:
            if self._provider == "ddgs":
                result = await self._search_ddgs(query, search_type)
            elif self._provider == "tavily":
                result = await self._search_tavily(query, search_type)
            elif self._provider == "serper":
                result = await self._search_serper(query, search_type)
            else:
                return f"❌ 未知搜索提供商：{self._provider}"

            outbound_logger.info(
                f"SEARCH ◀ provider={self._provider}  results={len(result)} chars"
            )
            return result
        except Exception as e:
            outbound_logger.warning(f"SEARCH ✗ provider={self._provider}  error={e}")
            logger.warning(f"搜索工具调用失败 [{self._provider}]: {e}")
            return f"❌ 搜索失败：{e}"

    # ── DuckDuckGo ─────────────────────────────────────────────────────────────

    async def _search_ddgs(self, query: str, search_type: str) -> str:
        def _try_text(backend: str, region: str) -> list[dict]:
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                timelimit = "w" if search_type == "news" else None
                return list(ddgs.text(
                    query,
                    region=region,
                    safesearch="moderate",
                    timelimit=timelimit,
                    max_results=self._max_results,
                    backend=backend,
                ))

        def _try_news() -> list[dict]:
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                return list(ddgs.news(
                    query,
                    region="wt-wt",
                    safesearch="off",
                    timelimit="w",
                    max_results=self._max_results,
                ))

        def _get_exceptions():
            warnings.filterwarnings("ignore", category=RuntimeWarning)
            from duckduckgo_search.exceptions import DuckDuckGoSearchException, RatelimitException
            return DuckDuckGoSearchException, RatelimitException

        SearchExceptions = await asyncio.to_thread(_get_exceptions)
        results: list[dict] = []
        result_type = "text"

        # 新闻模式：优先尝试 news() 接口
        if search_type == "news":
            try:
                results = await asyncio.to_thread(_try_news)
                if results:
                    result_type = "news"
            except Exception:
                pass

        # 通用模式或新闻接口失败：按 backend+region 组合顺序尝试 text()
        if not results:
            last_exc: Exception | None = None
            for backend, region in _DDGS_ATTEMPTS:
                try:
                    results = await asyncio.to_thread(_try_text, backend, region)
                    if results:
                        break
                except SearchExceptions as e:
                    last_exc = e
                    await asyncio.sleep(0.5)
                except Exception as e:
                    return f"❌ 搜索出错：{e}"
            if not results and last_exc is not None:
                return (
                    "DuckDuckGo 暂时触发访问限制，请稍后重试，"
                    "或在工具配置中切换为 Tavily / Serper.dev 搜索引擎。"
                )

        if not results:
            return (
                f"未找到 '{query}' 的相关结果，建议换用更简洁的关键词，"
                "或将中文查询改为英文后重试。"
            )

        lines: list[str] = []
        if result_type == "news":
            lines.append(f"新闻搜索结果（最近一周，共 {len(results)} 条）：\n")
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                url = r.get("url", "")
                date = r.get("date", "")
                date_str = f" [{date}]" if date else ""
                lines.append(f"[{i}] {title}{date_str}\n{body}\n来源：{url}")
        else:
            if search_type == "news":
                lines.append(f"网页搜索结果（新闻接口不可用，回退到网页搜索，共 {len(results)} 条）：\n")
            else:
                lines.append(f"网页搜索结果，共 {len(results)} 条：\n")
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                href = r.get("href", "")
                lines.append(f"[{i}] {title}\n{body}\n来源：{href}")

        return "\n\n".join(lines)

    # ── Tavily ─────────────────────────────────────────────────────────────────

    async def _search_tavily(self, query: str, search_type: str) -> str:
        if not self._api_key:
            return "❌ Tavily 未配置 API Key。"
        payload: dict = {
            "api_key": self._api_key,
            "query": query,
            "max_results": self._max_results,
            "search_depth": "basic",
            "include_answer": True,
            "topic": "news" if search_type == "news" else "general",
        }
        if search_type == "news":
            payload["days"] = 7
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_TAVILY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()

        lines: list[str] = []
        if answer := data.get("answer"):
            lines.append(f"综合摘要：\n{answer}\n")
        for i, r in enumerate(data.get("results", []), 1):
            title = r.get("title", "")
            content = r.get("content", "")
            url = r.get("url", "")
            pub = r.get("published_date", "")
            date_str = f" [{pub}]" if pub else ""
            lines.append(f"[{i}] {title}{date_str}\n{content}\n来源：{url}")
        return "\n\n".join(lines) or "未找到相关结果。"

    # ── Serper.dev ─────────────────────────────────────────────────────────────

    async def _search_serper(self, query: str, search_type: str) -> str:
        if not self._api_key:
            return "❌ Serper.dev 未配置 API Key。"
        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }
        url = "https://google.serper.dev/news" if search_type == "news" else _SERPER_URL
        payload = {"q": query, "num": self._max_results}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        lines: list[str] = []
        if search_type != "news":
            if answer_box := data.get("answerBox", {}).get("answer"):
                lines.append(f"精选答案：\n{answer_box}\n")
        key = "news" if search_type == "news" else "organic"
        for i, r in enumerate(data.get(key, []), 1):
            title = r.get("title", "")
            snippet = r.get("snippet", "")
            link = r.get("link", "")
            date = r.get("date", "")
            date_str = f" [{date}]" if date else ""
            lines.append(f"[{i}] {title}{date_str}\n{snippet}\n来源：{link}")
        return "\n\n".join(lines) or "未找到相关结果。"
