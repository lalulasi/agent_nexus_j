import json
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.config import get_settings
from api.app.core.logger import logger
from api.app.domain.schemas import ChatResponse, MessageOut
from api.app.infrastructure.database.models import AgentSession, LLMConfig, Message
from api.app.infrastructure.llm.adapters import StreamTurn, make_adapter
from api.app.infrastructure.tools.registry import get_tool, list_tools

settings = get_settings()


class AgentOrchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.tools = [t.to_anthropic_tool() for t in list_tools()]

    # ── 普通调用 ──────────────────────────────────────────────────────────────

    async def run(self, session: AgentSession, user_message: str) -> ChatResponse:
        config = await self._get_active_config()
        adapter = make_adapter(config, self.tools)

        await self._save_message(session.id, "user", user_message)
        messages = adapter.format_history(self._build_history(session, user_message))
        system = session.system_prompt_ref.content if session.system_prompt_ref else None

        final_text, usage = await self._loop(adapter, messages, system)

        saved = await self._save_message(
            session.id, "assistant", final_text, token_count=usage.get("output_tokens")
        )
        return ChatResponse(
            session_id=session.id,
            message=MessageOut.model_validate(saved),
            usage=usage,
        )

    # ── 流式调用 ──────────────────────────────────────────────────────────────

    async def stream_run(
        self,
        session: AgentSession,
        user_message: str,
        config: LLMConfig,
    ) -> AsyncGenerator[str, None]:
        adapter = make_adapter(config, self.tools)

        await self._save_message(session.id, "user", user_message)
        messages = adapter.format_history(self._build_history(session, user_message))
        system = session.system_prompt_ref.content if session.system_prompt_ref else None

        final_text = ""
        last_usage: dict = {}

        for iteration in range(1, settings.agent_max_iterations + 1):
            logger.debug(f"流式迭代 {iteration} | 模型: {config.model}")
            iter_text = ""
            turn: StreamTurn | None = None

            try:
                async for item in adapter.stream(messages, system, settings.agent_max_tokens):
                    if isinstance(item, str):
                        iter_text += item
                        yield json.dumps({"type": "text", "content": item})
                    elif isinstance(item, StreamTurn):
                        turn = item
            except Exception as e:
                logger.exception("流式 LLM 调用异常")
                yield json.dumps({"type": "error", "message": str(e)})
                return

            if turn is None:
                break

            last_usage = turn.usage

            if turn.stop_reason == "end_turn":
                final_text = iter_text
                break

            if turn.stop_reason == "tool_use":
                tool_names = [tc.name for tc in turn.tool_calls]
                yield json.dumps({"type": "tool_start", "tools": tool_names})
                logger.info(f"调用工具: {tool_names}")

                tool_outputs: dict[str, str] = {}
                results: list[str] = []
                for tc in turn.tool_calls:
                    tool = get_tool(tc.name)
                    if tool:
                        try:
                            result = await tool.run(**tc.input)
                        except Exception as e:
                            result = f"工具执行错误: {e}"
                    else:
                        result = f"未知工具: {tc.name}"
                    tool_outputs[tc.id] = str(result)
                    results.append(str(result))
                    logger.info(f"工具 '{tc.name}' → {str(result)[:120]}")

                yield json.dumps({"type": "tool_end", "results": results})
                messages = adapter.add_tool_turn(messages, turn, tool_outputs)
                final_text = iter_text
                continue

            final_text = iter_text
            break
        else:
            final_text += "\n\n（已达最大迭代次数）"

        await self._save_message(
            session.id, "assistant", final_text,
            token_count=last_usage.get("output_tokens"),
        )
        yield json.dumps({"type": "done", "usage": last_usage})

    # ── 内部：非流式循环 ──────────────────────────────────────────────────────

    async def _loop(self, adapter, messages, system) -> tuple[str, dict]:
        usage_total: dict = {}
        for iteration in range(1, settings.agent_max_iterations + 1):
            logger.debug(f"非流式迭代 {iteration}")
            try:
                turn = await adapter.complete(messages, system, settings.agent_max_tokens)
            except Exception as e:
                logger.exception("非流式 LLM 调用异常")
                return f"模型调用失败: {e}", {}

            for k in ("input_tokens", "output_tokens"):
                usage_total[k] = usage_total.get(k, 0) + turn.usage.get(k, 0)

            if turn.stop_reason == "end_turn":
                return turn.text, usage_total

            if turn.stop_reason == "tool_use":
                tool_outputs: dict[str, str] = {}
                for tc in turn.tool_calls:
                    tool = get_tool(tc.name)
                    result = await tool.run(**tc.input) if tool else f"未知工具: {tc.name}"
                    tool_outputs[tc.id] = str(result)
                messages = adapter.add_tool_turn(messages, turn, tool_outputs)
                continue

            return turn.text, usage_total

        return "已达最大迭代次数。", usage_total

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_active_config(self) -> LLMConfig:
        result = await self.db.execute(select(LLMConfig).where(LLMConfig.is_active == True))
        config = result.scalar_one_or_none()
        if config is None:
            raise ValueError("尚未配置模型，请先在左侧面板保存模型配置。")
        return config

    def _build_history(self, session: AgentSession, new_msg: str) -> list[dict]:
        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages
            if m.role in ("user", "assistant") and m.content
        ]
        history.append({"role": "user", "content": new_msg})
        return history

    async def _save_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        tool_calls: dict | None = None,
        token_count: int | None = None,
    ) -> Message:
        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            token_count=token_count,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg
