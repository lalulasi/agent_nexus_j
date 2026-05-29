import json
import uuid
from collections.abc import AsyncGenerator
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select as sa_select

from api.app.application.rag_pipeline import RAGPipeline
from api.app.core.config import get_settings
from api.app.core.logger import logger
from api.app.domain.schemas import ChatResponse, MessageOut
from api.app.infrastructure.database.models import AgentSession, LLMConfig, Message, SearchConfig, UserTool
from api.app.infrastructure.llm.adapters import StreamTurn, ThinkingChunk, _is_image_model, make_adapter
from api.app.infrastructure.tools.base import BaseTool
from api.app.infrastructure.tools.http_tool import HttpTool
from api.app.infrastructure.mcp.manager import get_mcp_manager
from api.app.infrastructure.tools.registry import get_tool
from api.app.infrastructure.tools.builtins.search_tool import SearchTool

settings = get_settings()


class AgentOrchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._tool_defs: list[dict] = []       # LLM 用的工具定义（Anthropic 格式）
        self._executors: dict[str, BaseTool] = {}  # name → 可执行实例

    # ── 工具加载（每次请求从 DB 读取激活工具） ────────────────────────────────

    async def _load_tools(self, search: bool = False) -> None:
        result = await self.db.execute(
            sa_select(UserTool).where(UserTool.is_active == True)
        )
        records = result.scalars().all()
        defs, executors = [], {}
        for r in records:
            defs.append({
                "name": r.name,
                "description": r.description,
                "input_schema": r.parameters_schema or {"type": "object", "properties": {}},
            })
            if r.tool_type == "builtin":
                builtin = get_tool(r.name)
                if builtin:
                    executors[r.name] = builtin
            elif r.tool_type == "http" and r.http_url:
                executors[r.name] = HttpTool(r)
        # 仅在前端请求开启搜索时注入搜索工具
        if search:
            search_result = await self.db.execute(
                sa_select(SearchConfig).where(SearchConfig.is_active == True)
            )
            search_cfg = search_result.scalar_one_or_none()
            if search_cfg:
                search_tool = SearchTool(search_cfg)
                defs.append({
                    "name": search_tool.name,
                    "description": search_tool.description,
                    "input_schema": search_tool.input_schema,
                })
                executors[search_tool.name] = search_tool
                logger.debug(f"搜索工具已注入 LLM 上下文: {search_cfg.provider}")

        # 追加 MCP 工具定义（MCP 工具通过 manager 执行，不放 executors）
        mcp_defs = get_mcp_manager().get_all_mcp_tools()
        defs.extend(mcp_defs)

        self._tool_defs = defs
        self._executors = executors
        if mcp_defs:
            logger.info(f"MCP 工具已注入 LLM 上下文: {[d['name'] for d in mcp_defs]}")
        else:
            logger.debug(f"已加载工具: {list(executors.keys())} (无 MCP 工具)")

    # ── RAG 检索 ──────────────────────────────────────────────────────────────

    async def _retrieve_rag(self, user_message: str, config: LLMConfig) -> list[dict]:
        """当 session.rag_enabled 时检索知识库，返回 top-k 切片列表。"""
        try:
            pipeline = RAGPipeline(self.db, config)
            return await pipeline.query(user_message)
        except Exception as e:
            logger.warning(f"RAG 检索失败，跳过: {e}")
            return []

    # ── 普通调用 ──────────────────────────────────────────────────────────────

    async def run(self, session: AgentSession, user_message: str) -> ChatResponse:
        await self._load_tools()
        config = await self._get_active_config()
        adapter = make_adapter(config, self._tool_defs)

        await self._save_message(session.id, "user", user_message)
        messages = adapter.format_history(self._build_history(session, user_message))
        system = self._get_effective_system(session)  # run() 不含搜索，has_search=False
        final_text, usage = await self._loop(adapter, messages, system)

        saved = await self._save_message(
            session.id, "assistant", final_text, token_count=usage.get("output_tokens")
        )
        await self._auto_title(session, user_message, adapter)
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
        attachments: list[dict] | None = None,
        is_retry: bool = False,
        thinking: bool = False,
        search: bool = False,
    ) -> AsyncGenerator[str, None]:
        await self._load_tools(search=search)
        adapter = make_adapter(config, self._tool_defs)

        if not is_retry:
            await self._save_message(
                session.id, "user", user_message, attachments=attachments or []
            )

        compressed = await self._maybe_compress(session, config)
        if compressed:
            await self.db.refresh(session, ["messages"])
            yield json.dumps({"type": "compression"})

        messages = adapter.format_history(
            self._build_history(
                session,
                user_message,
                already_in_messages=is_retry or compressed,
                new_attachments=attachments or [],
            )
        )
        has_search = "web_search" in {d["name"] for d in self._tool_defs}
        system = self._get_effective_system(session, has_search=has_search)

        # RAG：检索相关切片并注入 system prompt
        if session.rag_enabled:
            rag_chunks = await self._retrieve_rag(user_message, config)
            if rag_chunks:
                rag_block = "\n\n---\n以下是从知识库中检索到的相关内容，请参考：\n" + "\n\n".join(
                    f"[来源: {c['filename']}]\n{c['content']}" for c in rag_chunks
                )
                system = (system or "") + rag_block
                yield json.dumps({"type": "rag_context", "chunks": rag_chunks})

        final_text = ""
        last_usage: dict = {}

        for iteration in range(1, settings.agent_max_iterations + 1):
            logger.debug(f"流式迭代 {iteration} | 模型: {config.model}")
            iter_text = ""
            turn: StreamTurn | None = None

            try:
                async for item in adapter.stream(messages, system, settings.agent_max_tokens, thinking=thinking):
                    if isinstance(item, ThinkingChunk):
                        yield json.dumps({"type": "thinking", "content": item.content})
                    elif isinstance(item, str):
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
                tool_info = [{"name": tc.name, "input": tc.input} for tc in turn.tool_calls]
                yield json.dumps({"type": "tool_start", "tools": tool_names, "tool_info": tool_info})
                logger.info(f"调用工具: {tool_names}")

                tool_outputs: dict[str, str] = {}
                results: list[str] = []
                mcp_mgr = get_mcp_manager()
                for tc in turn.tool_calls:
                    try:
                        if mcp_mgr.is_mcp_tool(tc.name):
                            # MCP 工具：解析前缀，通过 manager 调用
                            srv_name, tool_name = mcp_mgr.parse_mcp_tool_name(tc.name)
                            mcp_result = await mcp_mgr.call_tool(srv_name, tool_name, tc.input)
                            result = mcp_result.content
                            if mcp_result.is_error:
                                result = f"[工具错误] {result}"
                        else:
                            executor = self._executors.get(tc.name)
                            if executor:
                                result = await executor.run(**tc.input)
                            else:
                                result = f"未知工具: {tc.name}"
                    except Exception as e:
                        result = f"工具执行错误: {e}"
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
        await self._auto_title(session, user_message, adapter)

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
                    executor = self._executors.get(tc.name)
                    try:
                        result = await executor.run(**tc.input) if executor else f"未知工具: {tc.name}"
                    except Exception as e:
                        result = f"工具执行错误: {e}"
                    tool_outputs[tc.id] = str(result)
                messages = adapter.add_tool_turn(messages, turn, tool_outputs)
                continue

            return turn.text, usage_total

        return "已达最大迭代次数。", usage_total

    # ── 自动命名 ──────────────────────────────────────────────────────────────

    async def _auto_title(self, session: AgentSession, user_message: str, adapter) -> None:
        if session.title != "新会话":
            return
        try:
            # 图像模型无法生成文本标题，直接用消息前缀
            if _is_image_model(adapter.config.model):
                title = user_message.strip()[:20]
                if title:
                    session.title = title
                    await self.db.flush()
                return

            # 使用无工具 adapter，避免模型对命名 prompt 发起工具调用
            naming_adapter = make_adapter(adapter.config, [])
            msgs = naming_adapter.format_history([{
                "role": "user",
                "content": "为以下对话内容生成一个中文标题，10字以内：\n\n" + user_message[:300],
            }])
            _naming_system = "只输出标题本身，不超过10个字，不加任何解释或前缀。"
            title_text = ""
            async for item in naming_adapter.stream(msgs, _naming_system, 100):
                if isinstance(item, str):
                    title_text += item
            title = title_text.strip().strip("\"'《》「」【】<>、。，").strip()[:20]
            # 兜底：模型未输出有效内容时取用户消息前10字
            if not title:
                title = user_message.strip()[:10]
            if title:
                session.title = title
                await self.db.flush()
                logger.info(f"自动命名会话 {session.id}：{title}")
        except Exception:
            logger.warning("自动命名失败，保持默认标题")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_active_config(self) -> LLMConfig:
        result = await self.db.execute(select(LLMConfig).where(LLMConfig.is_active == True))
        config = result.scalar_one_or_none()
        if config is None:
            raise ValueError("尚未配置模型，请先在左侧面板保存模型配置。")
        return config

    def _build_history(
        self,
        session: AgentSession,
        new_msg: str,
        already_in_messages: bool = False,
        new_attachments: list[dict] | None = None,
    ) -> list[dict]:
        last_summary_idx = -1
        for i, m in enumerate(session.messages):
            if m.role == "summary":
                last_summary_idx = i
        msgs_to_use = session.messages[last_summary_idx + 1:]
        history = [
            {
                "role": m.role,
                "content": m.content,
                "attachments": m.attachments or [],
            }
            for m in msgs_to_use
            if m.role in ("user", "assistant") and (m.content or m.attachments)
        ]
        if not already_in_messages:
            history.append({
                "role": "user",
                "content": new_msg,
                "attachments": new_attachments or [],
            })
        return history

    def _get_effective_system(self, session: AgentSession, has_search: bool = False) -> str | None:
        base = session.system_prompt_ref.content if session.system_prompt_ref else None

        # 始终注入当前日期，让模型知道"今天"是哪天，避免把当前日期误判为未来
        today_str = date.today().strftime("%Y年%m月%d日")
        date_block = f"当前日期：{today_str}。"

        # 搜索工具提示：有 web_search 工具时，提示模型主动使用
        search_hint = (
            "你拥有 web_search 工具，可以搜索互联网获取实时信息。"
            "遇到近期事件、新闻、最新数据等超出训练知识范围的问题时，"
            "务必主动调用 web_search 工具获取最新内容，而不是拒绝回答或说不知道。"
        ) if has_search else ""

        prefix_parts = [p for p in [date_block, search_hint] if p]
        prefix = " ".join(prefix_parts)

        base_with_prefix = (prefix + "\n\n" + base) if base else prefix

        summary_msg = next(
            (m for m in reversed(session.messages) if m.role == "summary"), None
        )
        if summary_msg:
            block = (
                f"\n\n---\n以下是本次会话早期对话的摘要，请参考以保持上下文连贯：\n"
                f"{summary_msg.content}"
            )
            return base_with_prefix + block
        return base_with_prefix

    @staticmethod
    def _estimate_tokens(messages: list) -> int:
        total = 0
        for m in messages:
            if m.role in ("user", "assistant") and m.content:
                total += m.token_count if m.token_count else len(m.content) // 2
        return total

    async def _maybe_compress(self, session: AgentSession, config: LLMConfig) -> bool:
        # Find the last summary boundary so we only measure/compress new content
        last_summary_idx = -1
        last_summary_content: str | None = None
        for i, m in enumerate(session.messages):
            if m.role == "summary":
                last_summary_idx = i
                last_summary_content = m.content

        effective_msgs = [
            m for m in session.messages[last_summary_idx + 1:]
            if m.role in ("user", "assistant") and m.content
        ]
        if self._estimate_tokens(effective_msgs) <= settings.agent_compress_threshold:
            return False

        keep = settings.agent_compress_keep_recent
        to_compress = effective_msgs[:-keep] if len(effective_msgs) > keep else []
        if not to_compress:
            return False

        # Build cumulative compression input: prior summary + new messages to compress
        parts: list[str] = []
        if last_summary_content:
            parts.append(f"[之前的对话摘要]:\n{last_summary_content}")
        parts.append("\n".join(f"[{m.role}]: {m.content[:800]}" for m in to_compress))

        adapter = make_adapter(config, [])
        msgs = adapter.format_history([{
            "role": "user",
            "content": (
                "请将以下对话内容（含历史摘要）压缩成一份简洁的累积摘要，"
                "保留关键信息、重要决策和结论，用中文输出：\n\n"
                + "\n\n".join(parts)
            ),
        }])
        summary_text = ""
        try:
            async for item in adapter.stream(
                msgs,
                "你是对话摘要助手，请将对话内容压缩为简洁的累积摘要，保留关键信息。",
                1000,
            ):
                if isinstance(item, str):
                    summary_text += item
        except Exception:
            logger.warning("对话压缩失败，跳过本次压缩")
            return False
        if not summary_text.strip():
            return False

        await self._save_message(session.id, "summary", summary_text.strip())
        logger.info(f"已压缩会话 {session.id} 的 {len(to_compress)} 条历史消息")
        return True

    async def _save_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        tool_calls: dict | None = None,
        token_count: int | None = None,
        attachments: list[dict] | None = None,
    ) -> Message:
        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            token_count=token_count,
            attachments=attachments or None,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg
