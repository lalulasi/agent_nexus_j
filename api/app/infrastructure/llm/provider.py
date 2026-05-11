from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional
from app.core.logger import logger
from app.infrastructure.tools.registry import tool_registry


async def generate_ai_reply(
        messages_history: List[Dict[str, Any]],
        api_key: str,
        base_url: str,
        model_name: str,
        enable_tools: bool = True,
        # 新增：接收前端傳入的自定義工具 Schema
        extra_tool_schemas: Optional[List[Dict[str, Any]]] = None
) -> Any:
    """
    Engine with support for both System Tools and Custom Dynamic Tools.
    """
    if not all([api_key, base_url, model_name]):
        logger.error("Incomplete LLM configuration.")
        raise ValueError("Missing LLM configuration.")

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    # 1. 組合工具清單 (System Tools + User Custom Tools)
    final_tools = []
    if enable_tools:
        # 獲取系統內建工具
        final_tools.extend(tool_registry.get_all_openai_schemas())
        # 加入動態傳入的工具
        if extra_tool_schemas:
            final_tools.extend(extra_tool_schemas)
            logger.info(f"Injected {len(extra_tool_schemas)} custom tools into the prompt.")

    logger.debug(f"Calling LLM | Model: {model_name} | Total Tools: {len(final_tools)}")

    try:
        request_params = {
            "model": model_name,
            "messages": messages_history,
            "temperature": 0.7,
            "max_tokens": 2000,
        }

        if final_tools:
            request_params["tools"] = final_tools
            request_params["tool_choice"] = "auto"

        response = await client.chat.completions.create(**request_params)
        logger.info(f"LLM Response received | Tokens: {response.usage.total_tokens}")

        return response.choices[0].message

    except Exception as e:
        logger.error(f"LLM Engine Error: {str(e)}")
        raise Exception(f"Provider Error: {str(e)}")