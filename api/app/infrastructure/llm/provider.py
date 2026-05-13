from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function
from typing import List, Dict, Any, Optional, AsyncGenerator
from app.core.logger import logger
from app.infrastructure.tools.registry import tool_registry


async def generate_ai_reply_stream(
        messages_history: List[Dict[str, Any]],
        api_key: str,
        base_url: str,
        model_name: str,
        enable_tools: bool = True,
        extra_tool_schemas: Optional[List[Dict[str, Any]]] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    支持流式输出 (Streaming) 的增强版 LLM 引擎。
    智能分离普通文本流与工具调用流。
    """
    if not all([api_key, base_url, model_name]):
        logger.error("Incomplete LLM configuration.")
        raise ValueError("Missing LLM configuration.")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    final_tools = []
    if enable_tools:
        final_tools.extend(tool_registry.get_all_openai_schemas())
        if extra_tool_schemas:
            final_tools.extend(extra_tool_schemas)

    logger.debug(f"Calling LLM Stream | Model: {model_name} | Tools: {len(final_tools)}")

    try:
        request_params = {
            "model": model_name,
            "messages": messages_history,
            "temperature": 0.7,
            "max_tokens": 2000,
            "stream": True  # 🌟 开启底层流式传输
        }

        if final_tools:
            request_params["tools"] = final_tools
            request_params["tool_choice"] = "auto"

        response = await client.chat.completions.create(**request_params)

        # 🌟 工具调用的碎片缓冲池
        tool_calls_buffer = {}
        content_buffer = []

        async for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # 1. 如果是人类可读的文本碎片，直接抛出给前端渲染！
            if delta.content:
                content_buffer.append(delta.content)
                yield {"type": "text_chunk", "data": delta.content}

            # 2. 如果是工具调用的 JSON 碎片，拦截并放入缓冲池拼接，不让前端看到
            if delta.tool_calls:
                for tc_chunk in delta.tool_calls:
                    idx = tc_chunk.index
                    if idx not in tool_calls_buffer:
                        tool_calls_buffer[idx] = {
                            "id": tc_chunk.id,
                            "type": "function",
                            "function": {"name": tc_chunk.function.name or "", "arguments": ""}
                        }
                    if tc_chunk.function.arguments:
                        tool_calls_buffer[idx]["function"]["arguments"] += tc_chunk.function.arguments

        # 3. 流式传输结束。如果有拼装好的工具调用，还原成原生对象抛出
        final_tool_calls = []
        if tool_calls_buffer:
            for idx, tc in sorted(tool_calls_buffer.items()):
                final_tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=tc["id"],
                        type="function",
                        function=Function(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                    )
                )

        # 构造最终的完整 Message 对象，为了兼容我们现有的 Agent 循环架构
        final_message = ChatCompletionMessage(
            role="assistant",
            content="".join(content_buffer) if content_buffer else None,
            tool_calls=final_tool_calls if final_tool_calls else None
        )

        # 抛出最终的完整消息对象，供后端存数据库和执行工具
        yield {"type": "final_message", "data": final_message}

    except Exception as e:
        logger.error(f"LLM Stream Error: {str(e)}")
        yield {"type": "error", "data": f"Provider Error: {str(e)}"}