"""
LLM 适配层：统一 Anthropic 和 OpenAI 兼容接口。

检测逻辑：
  - base_url 为空 或 包含 "anthropic.com" → AnthropicAdapter
  - 其他（DeepSeek、Qwen、本地模型等 OpenAI 兼容接口）→ OpenAIAdapter
"""
from __future__ import annotations

import base64
import json
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Union
from urllib.parse import parse_qs, urlparse

import anthropic
import httpx
from openai import AsyncAzureOpenAI, AsyncOpenAI

from api.app.core.logger import outbound_logger
from api.app.infrastructure.database.models import LLMConfig

_CONTENT_PREVIEW = 400   # 每条消息内容最大预览字符数


def _preview_messages(messages: list[dict]) -> str:
    """将消息列表压缩为可读摘要，用于对外请求日志。"""
    lines = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            text = content[:_CONTENT_PREVIEW] + ("…" if len(content) > _CONTENT_PREVIEW else "")
        elif isinstance(content, list):
            parts = []
            for b in content:
                if not isinstance(b, dict):
                    continue
                btype = b.get("type", "?")
                if btype == "text":
                    t = b.get("text", "")
                    parts.append(t[:100] + ("…" if len(t) > 100 else ""))
                elif btype in ("image", "image_url"):
                    parts.append("[image]")
                elif btype == "tool_use":
                    parts.append(f"[tool_use: {b.get('name')}]")
                elif btype == "tool_result":
                    parts.append(f"[tool_result: {str(b.get('content',''))[:80]}]")
                else:
                    parts.append(f"[{btype}]")
            text = " | ".join(parts)
        else:
            text = str(content)[:_CONTENT_PREVIEW]
        lines.append(f"    [{role}] {text!r}")
    return "\n".join(lines)


# ── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class StreamTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict = field(default_factory=dict)
    reasoning_content: str = ""  # DeepSeek thinking 模式，必须原样传回 API


@dataclass
class ThinkingChunk:
    """深度思考增量片段，在 text 内容之前流式 yield。"""
    content: str


StreamItem = Union[str, StreamTurn, ThinkingChunk]


# ── 基类 ──────────────────────────────────────────────────────────────────────

class BaseLLMAdapter(ABC):
    """每次对话时按需实例化，不缓存。"""

    def __init__(self, config: LLMConfig, anthropic_tools: list[dict]) -> None:
        self.config = config
        self.anthropic_tools = anthropic_tools  # Anthropic 原始格式，子类按需转换

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int,
        thinking: bool = False,
    ) -> AsyncGenerator[StreamItem, None]:
        """
        流式生成。依次 yield str（文本块），最后 yield StreamTurn（终止标志）。
        """
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        system: str,
        max_tokens: int,
    ) -> StreamTurn:
        """非流式，一次性返回完整结果。"""
        ...

    @abstractmethod
    def format_history(self, history: list[dict]) -> list[dict]:
        """将内部 [{role, content}] 历史转换为提供商格式。"""
        ...

    @abstractmethod
    def add_tool_turn(
        self,
        messages: list[dict],
        turn: StreamTurn,
        tool_outputs: dict[str, str],
    ) -> list[dict]:
        """将工具调用结果追加到消息列表，用于下一轮对话。"""
        ...


# ── Anthropic 适配器 ──────────────────────────────────────────────────────────

class AnthropicAdapter(BaseLLMAdapter):
    def __init__(self, config: LLMConfig, anthropic_tools: list[dict]) -> None:
        super().__init__(config, anthropic_tools)
        kwargs: dict = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)

    async def stream(self, messages, system, max_tokens, thinking: bool = False):
        text = ""
        thinking_text = ""
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": self.anthropic_tools,
        }
        if system:
            kwargs["system"] = system
        if thinking:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.config.thinking_budget,
            }
            # 开启 thinking 时工具调用不可用，清除 tools 避免 API 报错
            kwargs.pop("tools", None)

        _tool_names = [t["name"] for t in self.anthropic_tools]
        outbound_logger.info(
            f"LLM ▶ STREAM  provider=anthropic  model={self.config.model}  "
            f"messages={len(messages)}  tools={_tool_names}  "
            f"thinking={thinking}  max_tokens={max_tokens}\n"
            + (f"  system: {system[:200]!r}{'…' if system and len(system) > 200 else ''}\n" if system else "")
            + _preview_messages(messages)
        )
        _t0 = time.monotonic()

        async with self.client.messages.stream(**kwargs) as s:
            async for event in s:
                etype = getattr(event, "type", None)
                if etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", None)
                    if dtype == "thinking_delta":
                        chunk = getattr(delta, "thinking", "")
                        thinking_text += chunk
                        yield ThinkingChunk(content=chunk)
                    elif dtype == "text_delta":
                        chunk = getattr(delta, "text", "")
                        text += chunk
                        yield chunk
            final = await s.get_final_message()

        _dur = time.monotonic() - _t0
        _in  = getattr(final.usage, "input_tokens", 0)
        _out = getattr(final.usage, "output_tokens", 0)
        outbound_logger.info(
            f"LLM ◀ STREAM  provider=anthropic  model={self.config.model}  "
            f"stop={final.stop_reason}  in={_in}  out={_out}  duration={_dur:.2f}s"
        )

        yield StreamTurn(
            text=text,
            tool_calls=[
                ToolCall(id=b.id, name=b.name, input=dict(b.input))
                for b in final.content
                if b.type == "tool_use"
            ],
            stop_reason=final.stop_reason or "end_turn",
            usage={"input_tokens": _in, "output_tokens": _out},
            reasoning_content=thinking_text,
        )

    async def complete(self, messages, system, max_tokens):
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": self.anthropic_tools,
        }
        if system:
            kwargs["system"] = system

        _tool_names = [t["name"] for t in self.anthropic_tools]
        outbound_logger.info(
            f"LLM ▶ COMPLETE  provider=anthropic  model={self.config.model}  "
            f"messages={len(messages)}  tools={_tool_names}  max_tokens={max_tokens}\n"
            + (f"  system: {system[:200]!r}{'…' if system and len(system) > 200 else ''}\n" if system else "")
            + _preview_messages(messages)
        )
        _t0 = time.monotonic()

        resp = await self.client.messages.create(**kwargs)

        _dur = time.monotonic() - _t0
        _in  = getattr(resp.usage, "input_tokens", 0)
        _out = getattr(resp.usage, "output_tokens", 0)
        outbound_logger.info(
            f"LLM ◀ COMPLETE  provider=anthropic  model={self.config.model}  "
            f"stop={resp.stop_reason}  in={_in}  out={_out}  duration={_dur:.2f}s"
        )

        text = "\n".join(b.text for b in resp.content if hasattr(b, "text"))
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input))
            for b in resp.content
            if b.type == "tool_use"
        ]
        return StreamTurn(
            text=text,
            tool_calls=tool_calls,
            stop_reason=resp.stop_reason or "end_turn",
            usage={"input_tokens": _in, "output_tokens": _out},
        )

    def format_history(self, history: list[dict]) -> list[dict]:
        result = []
        for msg in history:
            atts = msg.get("attachments") or []
            if not atts:
                result.append({"role": msg["role"], "content": msg.get("content") or ""})
                continue
            blocks: list[dict] = []
            for att in atts:
                if att.get("type") == "image":
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att["mime_type"],
                            "data": att["data"],
                        },
                    })
                else:
                    blocks.append({
                        "type": "text",
                        "text": f"[文件: {att['filename']}]\n{att.get('extracted_text', '')}",
                    })
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            result.append({"role": msg["role"], "content": blocks})
        return result

    def add_tool_turn(self, messages, turn, tool_outputs):
        assistant_content = []
        if turn.text:
            assistant_content.append({"type": "text", "text": turn.text})
        for tc in turn.tool_calls:
            assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})

        user_content = [
            {"type": "tool_result", "tool_use_id": tc.id, "content": tool_outputs.get(tc.id, "")}
            for tc in turn.tool_calls
        ]
        return messages + [
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": user_content},
        ]


# ── 模型类型检测 ──────────────────────────────────────────────────────────────

_IMAGE_MODEL_KEYWORDS = ("dall-e", "gpt-image", "image-generation")

# 仅在模型名开头为 o+数字时识别为 o-series（排除 gpt-4o 等）
def _is_image_model(model_name: str) -> bool:
    name = model_name.lower()
    return any(kw in name for kw in _IMAGE_MODEL_KEYWORDS)

def _is_reasoning_model(model_name: str) -> bool:
    """o1 / o3 / o4 系列：需要 max_completion_tokens。"""
    name = model_name.lower()
    return len(name) >= 2 and name[0] == "o" and name[1].isdigit()

def _no_system_role(model_name: str) -> bool:
    """o1-mini / o1-preview 不接受 system 角色。"""
    name = model_name.lower()
    return name.startswith(("o1-mini", "o1-preview"))

def _no_tools_support(model_name: str) -> bool:
    """o1-mini / o1-preview 不支持 function calling。"""
    name = model_name.lower()
    return name.startswith(("o1-mini", "o1-preview"))

def _no_streaming(model_name: str) -> bool:
    """o1-preview 不支持流式输出。"""
    return model_name.lower().startswith("o1-preview")

# 不能用于文本对话的模型类型，给出明确错误而非 404
_UNSUPPORTED_PREFIXES = (
    "tts-", "whisper-",
    "text-embedding-", "text-similarity-", "text-search-",
    "omni-moderation-", "text-moderation-",
)

def _is_azure_endpoint(url: str) -> bool:
    return ".openai.azure.com" in url or ".azure.com" in url

def _parse_azure_endpoint(url: str) -> tuple[str, str]:
    """从 Azure URL 中提取 (endpoint, api_version)。

    用户可能填完整路径（含 deployment 和 api-version），也可能只填 endpoint。
    始终返回纯 endpoint（scheme+host）和 api-version。
    """
    parsed = urlparse(url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}"
    qs = parse_qs(parsed.query)
    api_version = qs.get("api-version", ["2024-12-01-preview"])[0]
    return endpoint, api_version


def _unsupported_model_type(model_name: str) -> str | None:
    """返回不兼容原因字符串，兼容则返回 None。"""
    name = model_name.lower()
    if any(name.startswith(p) for p in ("tts-",)):
        return "TTS 语音合成模型，不支持文本对话"
    if name.startswith("whisper-"):
        return "Whisper 语音转文字模型，不支持文本对话"
    if any(name.startswith(p) for p in ("text-embedding-", "text-similarity-", "text-search-")):
        return "Embedding 向量模型，不支持文本对话"
    if any(name.startswith(p) for p in ("omni-moderation-", "text-moderation-")):
        return "内容审核模型，不支持文本对话"
    return None


# ── OpenAI 兼容适配器 ─────────────────────────────────────────────────────────

class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, config: LLMConfig, anthropic_tools: list[dict]) -> None:
        super().__init__(config, anthropic_tools)
        if _is_azure_endpoint(config.base_url or ""):
            endpoint, api_version = _parse_azure_endpoint(config.base_url)
            self.client = AsyncAzureOpenAI(
                api_key=config.api_key,
                azure_endpoint=endpoint,
                api_version=api_version,
            )
        else:
            self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self._image_model    = _is_image_model(config.model)
        self._reasoning      = _is_reasoning_model(config.model)
        self._no_system      = _no_system_role(config.model)
        self._no_tools       = _no_tools_support(config.model)
        self._no_stream      = _no_streaming(config.model)
        self._unsupported    = _unsupported_model_type(config.model)
        # 转换工具格式
        self.openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in anthropic_tools
        ]

    def _extract_prompt(self, messages: list[dict]) -> str:
        """从消息列表中提取最后一条用户消息作为图像生成 prompt。"""
        for msg in reversed(messages):
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
        return ""

    async def _generate_image(self, messages: list[dict]) -> StreamTurn:
        prompt = self._extract_prompt(messages)
        _base = self.config.base_url or "openai"
        outbound_logger.info(f"LLM ▶ IMAGE  provider={_base}  model={self.config.model}  prompt={prompt[:200]!r}")
        _t0 = time.monotonic()

        result = await self.client.images.generate(
            model=self.config.model,
            prompt=prompt,
            n=1,
            size="1024x1024",
        )

        _dur = time.monotonic() - _t0
        outbound_logger.info(f"LLM ◀ IMAGE  provider={_base}  model={self.config.model}  duration={_dur:.2f}s")

        item = result.data[0]
        if getattr(item, "b64_json", None):
            text = f"![生成图片](data:image/png;base64,{item.b64_json})"
        elif getattr(item, "url", None):
            # 下载图片转为 base64，避免临时 URL 过期后图片丢失
            try:
                async with httpx.AsyncClient(timeout=30) as hc:
                    img_resp = await hc.get(item.url)
                    img_resp.raise_for_status()
                    mime = img_resp.headers.get("content-type", "image/png").split(";")[0]
                    b64 = base64.b64encode(img_resp.content).decode()
                    text = f"![生成图片](data:{mime};base64,{b64})"
            except Exception:
                # 下载失败时降级保留 URL
                text = f"![生成图片]({item.url})"
        else:
            text = "图片生成完成，但未返回图片数据。"
        return StreamTurn(text=text, stop_reason="end_turn", usage={})

    def _build_messages(self, messages: list[dict], system: str) -> list[dict]:
        """构造最终消息列表，处理不支持 system 角色的模型。"""
        if not system:
            return list(messages)
        if self._no_system:
            # 将 system 内容合并到第一条 user 消息，避免 400 错误
            result = list(messages)
            for i, msg in enumerate(result):
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        result[i] = {"role": "user", "content": f"{system}\n\n{content}"}
                    return result
            # 没有 user 消息时插入一条
            return [{"role": "user", "content": system}] + result
        return [{"role": "system", "content": system}] + list(messages)

    async def stream(self, messages, system, max_tokens, thinking: bool = False):
        if self._unsupported:
            raise ValueError(f"模型 '{self.config.model}' 是{self._unsupported}，无法在对话中使用。")

        if self._image_model:
            turn = await self._generate_image(messages)
            yield turn.text
            yield turn
            return

        # o1-preview 不支持流式，降级为 complete
        if self._no_stream:
            turn = await self.complete(messages, system, max_tokens)
            yield turn.text
            yield turn
            return

        full_messages = self._build_messages(messages, system)
        kwargs: dict = {
            "model": self.config.model,
            "messages": full_messages,
            "stream": True,
        }
        # o-series 用 max_completion_tokens，其他用 max_tokens
        if self._reasoning:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        if self.openai_tools and not self._no_tools:
            kwargs["tools"] = self.openai_tools

        _base = self.config.base_url or "openai"
        _tool_names = [t["function"]["name"] for t in self.openai_tools]
        outbound_logger.info(
            f"LLM ▶ STREAM  provider={_base}  model={self.config.model}  "
            f"messages={len(full_messages)}  tools={_tool_names}  "
            f"thinking={thinking}  max_tokens={max_tokens}\n"
            + (f"  system: {system[:200]!r}{'…' if system and len(system) > 200 else ''}\n" if system else "")
            + _preview_messages(messages)
        )
        _t0 = time.monotonic()

        text = ""
        reasoning_text = ""
        pending: dict[int, dict] = {}
        usage: dict = {}
        finish_reason: str | None = None

        response = await self.client.chat.completions.create(**kwargs)
        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None
            if choice:
                delta = choice.delta
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_text += rc
                    if thinking:
                        yield ThinkingChunk(content=rc)
                if delta.content:
                    text += delta.content
                    yield delta.content
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in pending:
                            pending[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            pending[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                pending[idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                pending[idx]["arguments"] += tc.function.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "input_tokens": chunk.usage.prompt_tokens or 0,
                    "output_tokens": chunk.usage.completion_tokens or 0,
                }

        tool_calls = []
        for tc in pending.values():
            try:
                input_data = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except json.JSONDecodeError:
                input_data = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], input=input_data))

        _dur = time.monotonic() - _t0
        _stop = "tool_use" if finish_reason == "tool_calls" else "end_turn"
        outbound_logger.info(
            f"LLM ◀ STREAM  provider={_base}  model={self.config.model}  "
            f"stop={_stop}  in={usage.get('input_tokens', 0)}  "
            f"out={usage.get('output_tokens', 0)}  duration={_dur:.2f}s"
            + (f"  reasoning={len(reasoning_text)}chars" if reasoning_text else "")
        )

        yield StreamTurn(
            text=text,
            tool_calls=tool_calls,
            stop_reason=_stop,
            usage=usage,
            reasoning_content=reasoning_text,
        )

    async def complete(self, messages, system, max_tokens):
        if self._unsupported:
            raise ValueError(f"模型 '{self.config.model}' 是{self._unsupported}，无法在对话中使用。")

        if self._image_model:
            return await self._generate_image(messages)

        full_messages = self._build_messages(messages, system)
        kwargs: dict = {
            "model": self.config.model,
            "messages": full_messages,
        }
        if self._reasoning:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

        if self.openai_tools and not self._no_tools:
            kwargs["tools"] = self.openai_tools

        _base = self.config.base_url or "openai"
        _tool_names = [t["function"]["name"] for t in self.openai_tools]
        outbound_logger.info(
            f"LLM ▶ COMPLETE  provider={_base}  model={self.config.model}  "
            f"messages={len(full_messages)}  tools={_tool_names}  max_tokens={max_tokens}\n"
            + (f"  system: {system[:200]!r}{'…' if system and len(system) > 200 else ''}\n" if system else "")
            + _preview_messages(messages)
        )
        _t0 = time.monotonic()

        resp = await self.client.chat.completions.create(**kwargs)

        _dur = time.monotonic() - _t0
        _in  = resp.usage.prompt_tokens if resp.usage else 0
        _out = resp.usage.completion_tokens if resp.usage else 0
        choice = resp.choices[0]
        _stop = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"
        outbound_logger.info(
            f"LLM ◀ COMPLETE  provider={_base}  model={self.config.model}  "
            f"stop={_stop}  in={_in}  out={_out}  duration={_dur:.2f}s"
        )

        text = choice.message.content or ""
        rc = getattr(choice.message, "reasoning_content", None) or ""
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    input_data = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    input_data = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=input_data))

        return StreamTurn(
            text=text or rc,  # reasoning-only 模型 content 为空时用 thinking 兜底
            tool_calls=tool_calls,
            stop_reason=_stop,
            usage={"input_tokens": _in, "output_tokens": _out},
            reasoning_content=rc,
        )

    def format_history(self, history: list[dict]) -> list[dict]:
        result = []
        for msg in history:
            atts = msg.get("attachments") or []
            if not atts:
                result.append({"role": msg["role"], "content": msg.get("content") or ""})
                continue
            parts: list[dict] = []
            for att in atts:
                if att.get("type") == "image":
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{att['mime_type']};base64,{att['data']}"},
                    })
                else:
                    parts.append({
                        "type": "text",
                        "text": f"[文件: {att['filename']}]\n{att.get('extracted_text', '')}",
                    })
            if msg.get("content"):
                parts.append({"type": "text", "text": msg["content"]})
            result.append({"role": msg["role"], "content": parts})
        return result

    def add_tool_turn(self, messages, turn, tool_outputs):
        assistant_msg: dict = {"role": "assistant", "content": turn.text or None}
        if turn.reasoning_content:
            assistant_msg["reasoning_content"] = turn.reasoning_content
        if turn.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input, ensure_ascii=False),
                    },
                }
                for tc in turn.tool_calls
            ]
        tool_msgs = [
            {"role": "tool", "tool_call_id": tc.id, "content": tool_outputs.get(tc.id, "")}
            for tc in turn.tool_calls
        ]
        return messages + [assistant_msg] + tool_msgs


# ── 工厂函数 ──────────────────────────────────────────────────────────────────

def make_adapter(config: LLMConfig, anthropic_tools: list[dict]) -> BaseLLMAdapter:
    base_url = config.base_url or ""
    if not base_url or "anthropic.com" in base_url:
        return AnthropicAdapter(config, anthropic_tools)
    return OpenAIAdapter(config, anthropic_tools)
