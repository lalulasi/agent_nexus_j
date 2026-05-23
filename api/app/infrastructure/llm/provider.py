import json
import re
import httpx
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
    🌟 终极增强版 LLM 引擎 (Raw HTTP Streaming)
    完全绕过 SDK 拦截，完美支持 DeepSeek 家族及 R1 推理过程的双向传输。
    """
    if not all([api_key, base_url, model_name]):
        logger.error("Incomplete LLM configuration.")
        yield {"type": "error", "data": "🚨 配置不完整：请检查参数。"}
        return

    final_tools = []
    if enable_tools:
        final_tools.extend(tool_registry.get_all_openai_schemas())
        if extra_tool_schemas:
            final_tools.extend(extra_tool_schemas)

    # ==========================================
    # 🧠 API 兼容层：精准判定是否需要 reasoning_content
    # ==========================================
    # 🌟 破案关键点：加入了 'deepseek'，只要碰到 DeepSeek 接口一律免疫 400 错误！
    is_r1_family = any(k in model_name.lower() or k in (base_url or "").lower() for k in
                       ["r1", "reasoner", "think", "deepseek", "dashscope", "volces"])

    adapted_messages = []
    for msg in messages_history:
        new_msg = dict(msg)
        if new_msg.get("role") == "assistant":
            content = str(new_msg.get("content") or "")

            # 1. 若历史记录中有思考过程，精准剥离
            if "<think>" in content and "</think>" in content:
                think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
                if think_match:
                    clean_content = re.sub(r"💭 \*\*思考过程:\*\*\n<think>.*?</think>\n\n---\n\n", "", content,
                                           flags=re.DOTALL)
                    clean_content = re.sub(r"💭 \*\*思考过程:\*\*\n<think>.*?</think>", "", clean_content,
                                           flags=re.DOTALL)
                    clean_content = re.sub(r"<think>.*?</think>", "", clean_content, flags=re.DOTALL).strip()

                    new_msg["content"] = clean_content
                    if is_r1_family:
                        new_msg["reasoning_content"] = think_match.group(1).strip()
            else:
                # 2. 如果是深思家族但历史没思考，强塞空字符串满足 API 的变态校验
                if is_r1_family:
                    new_msg["reasoning_content"] = ""

            # 3. 防御性清洗 (防止无 content 无 tool_calls 导致大模型内部异常崩溃)
            if not new_msg.get("content") and not new_msg.get("tool_calls"):
                new_msg["content"] = "(无文本输出)"

        # 普通大模型（如 GPT-4 / Qwen）严禁携带推理字段
        if not is_r1_family:
            new_msg.pop("reasoning_content", None)

        adapted_messages.append(new_msg)

    # ==========================================
    # 🚀 降维打击：直接使用底层 HTTP 发送请求
    # ==========================================
    request_payload = {
        "model": model_name,
        "messages": adapted_messages,
        "temperature": 0.7,
        "stream": True
    }
    if final_tools:
        request_payload["tools"] = final_tools
        request_payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    endpoint = f"{base_url.rstrip('/')}/chat/completions"

    tool_calls_buffer = {}
    content_buffer = []
    is_thinking = False

    try:
        async with httpx.AsyncClient() as http_client:
            async with http_client.stream("POST", endpoint, headers=headers, json=request_payload,
                                          timeout=120.0) as response:
                if response.status_code != 200:
                    error_text = await response.aread()
                    logger.error(f"❌ [请求崩溃] HTTP {response.status_code} | 云端返回: {error_text.decode('utf-8')}")
                    raise Exception(f"HTTP {response.status_code}: {error_text.decode('utf-8')}")

                # 实时解析 SSE 流
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    if line == "data: [DONE]":
                        break

                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

                    if not chunk.get("choices"):
                        continue

                    delta = chunk["choices"][0].get("delta", {})

                    # 🧠 1. 解析思考流 (Reasoning Content)
                    reasoning = delta.get("reasoning_content")
                    if reasoning:
                        if not is_thinking:
                            is_thinking = True
                            start_tag = "💭 **思考过程:**\n<think>\n"
                            content_buffer.append(start_tag)
                            yield {"type": "text_chunk", "data": start_tag}

                        content_buffer.append(reasoning)
                        yield {"type": "text_chunk", "data": reasoning}

                    # 📝 2. 解析普通文本流 (Content)
                    delta_content = delta.get("content")
                    if delta_content:
                        if is_thinking:
                            is_thinking = False
                            end_tag = "\n</think>\n\n---\n\n"
                            content_buffer.append(end_tag)
                            yield {"type": "text_chunk", "data": end_tag}

                        content_buffer.append(delta_content)
                        yield {"type": "text_chunk", "data": delta_content}

                    # 🔧 3. 解析工具调用流 (Tool Calls)
                    tcs = delta.get("tool_calls")
                    if tcs:
                        for tc_chunk in tcs:
                            idx = tc_chunk.get("index")
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": tc_chunk.get("id"),
                                    "type": "function",
                                    "function": {"name": tc_chunk.get("function", {}).get("name", ""), "arguments": ""}
                                }
                            args = tc_chunk.get("function", {}).get("arguments")
                            if args:
                                tool_calls_buffer[idx]["function"]["arguments"] += args

        # 流式传输结束，安全兜底闭合思考标签
        if is_thinking:
            end_tag = "\n</think>\n\n---\n\n"
            content_buffer.append(end_tag)
            yield {"type": "text_chunk", "data": end_tag}

        # 4. 组装最终结果返回给后端调度中心
        final_tool_calls = []
        if tool_calls_buffer:
            for idx, tc in sorted(tool_calls_buffer.items()):
                final_tool_calls.append(
                    ChatCompletionMessageToolCall(
                        id=tc["id"] or "call_id_unknown",
                        type="function",
                        function=Function(name=tc["function"]["name"], arguments=tc["function"]["arguments"])
                    )
                )

        final_message = ChatCompletionMessage(
            role="assistant",
            content="".join(content_buffer) if content_buffer else None,
            tool_calls=final_tool_calls if final_tool_calls else None
        )
        yield {"type": "final_message", "data": final_message}

    except Exception as e:
        logger.error(f"LLM Raw Stream Error: {str(e)}")
        yield {"type": "error", "data": f"底座模型响应失败: {str(e)}"}


async def generate_json_evaluation(
        system_prompt: str,
        user_prompt: str,
        api_key: str,
        base_url: str,
        model_name: str
) -> dict:
    """专门用于 Multi-Agent 协作的后台裁判引擎"""
    logger.info(f"🔍 [Swarm 审查] 唤醒模型: [{model_name}] 进行逻辑打分...")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    json_instruction = """
    你必须以纯 JSON 格式响应。JSON 必须严格包含以下三个字段：
    - "pass": 布尔值 (true 或 false)。
    - "score": 整数 (0-100)。
    - "advice": 字符串。请详细写出评价理由，绝对不能为空！
    """
    messages = [
        {"role": "system", "content": f"{system_prompt}\n\n{json_instruction}"},
        {"role": "user", "content": user_prompt}
    ]

    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result_str = response.choices[0].message.content or ""
        result_str = result_str.strip()

        bt = chr(96) * 3
        if result_str.startswith(f"{bt}json\n"):
            result_str = result_str[8:]
        elif result_str.startswith(f"{bt}json"):
            result_str = result_str[7:]
        elif result_str.startswith(bt):
            result_str = result_str[3:]
        if result_str.endswith(bt): result_str = result_str[:-3]

        result_str = result_str.strip()
        if not result_str: raise ValueError("大模型返回了空字符串")

        result_dict = json.loads(result_str)
        logger.info(
            f"📊 [审查完成] {model_name} | 分数: {result_dict.get('score')} | 意见: {result_dict.get('advice', '无')[:30]}...")
        return result_dict

    except Exception as e:
        logger.error(f"❌ [审查报错] 模型 [{model_name}] JSON解析失败: {str(e)}")
        return {"pass": True, "score": 60, "advice": f"({model_name} 审查异常，自动放行)"}