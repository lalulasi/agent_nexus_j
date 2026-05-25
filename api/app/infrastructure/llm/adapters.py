"""
LLM 适配层：统一 Anthropic 和 OpenAI 兼容接口。

检测逻辑：
  - base_url 为空 或 包含 "anthropic.com" → AnthropicAdapter
  - 其他（DeepSeek、Qwen、本地模型等 OpenAI 兼容接口）→ OpenAIAdapter
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Union

import anthropic
from openai import AsyncOpenAI

from api.app.infrastructure.database.models import LLMConfig


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


StreamItem = Union[str, StreamTurn]


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

    async def stream(self, messages, system, max_tokens):
        text = ""
        kwargs: dict = {
            "model": self.config.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": self.anthropic_tools,
        }
        if system:
            kwargs["system"] = system
        async with self.client.messages.stream(**kwargs) as s:
            async for chunk in s.text_stream:
                text += chunk
                yield chunk
            final = await s.get_final_message()

        yield StreamTurn(
            text=text,
            tool_calls=[
                ToolCall(id=b.id, name=b.name, input=dict(b.input))
                for b in final.content
                if b.type == "tool_use"
            ],
            stop_reason=final.stop_reason or "end_turn",
            usage={
                "input_tokens": getattr(final.usage, "input_tokens", 0),
                "output_tokens": getattr(final.usage, "output_tokens", 0),
            },
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
        resp = await self.client.messages.create(**kwargs)
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
            usage={
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
            },
        )

    def format_history(self, history: list[dict]) -> list[dict]:
        return history  # Anthropic 格式与内部格式相同

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


# ── OpenAI 兼容适配器 ─────────────────────────────────────────────────────────

class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, config: LLMConfig, anthropic_tools: list[dict]) -> None:
        super().__init__(config, anthropic_tools)
        self.client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
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

    async def stream(self, messages, system, max_tokens):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs: dict = {
            "model": self.config.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if self.openai_tools:
            kwargs["tools"] = self.openai_tools

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
                # reasoning_content：DeepSeek 推理模型思考阶段，不向用户输出
                rc = getattr(delta, "reasoning_content", None)
                if rc:
                    reasoning_text += rc
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

        yield StreamTurn(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if finish_reason == "tool_calls" else "end_turn",
            usage=usage,
            reasoning_content=reasoning_text,
        )

    async def complete(self, messages, system, max_tokens):
        full_messages = ([{"role": "system", "content": system}] if system else []) + messages
        kwargs: dict = {
            "model": self.config.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
        }
        if self.openai_tools:
            kwargs["tools"] = self.openai_tools

        resp = await self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
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
            stop_reason="tool_use" if choice.finish_reason == "tool_calls" else "end_turn",
            usage={
                "input_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "output_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
            reasoning_content=rc,
        )

    def format_history(self, history: list[dict]) -> list[dict]:
        return history  # {role, content} 格式一致

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
