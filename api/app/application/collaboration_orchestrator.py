"""
多模型协作调度器

支持两种模式：
  - round_table : B+C 算法（迭代辩论 + 角色圆桌），最多 5 个模型，N 轮独立作答后
                  综合者汇总输出最终答案。
  - master_slave: 主模型作答，N 个评委并行评审打分，取最优改进版作为最终答案。

流式事件类型（JSON 字符串，供 SSE 传输）：
  collab_phase         — 进入新阶段（round_1 / round_2 / review / synthesis）
  collab_model_result  — 圆桌某模型在某轮次的完整回答
  collab_model_text    — 主模型流式文本块（主从模式专用）
  collab_model_end     — 主模型流式结束（主从模式专用）
  collab_reviewer_result — 评委评审结果（评分 + 点评 + 改进答案）
  collab_synthesis_start — 综合者开始输出
  text                 — 最终答案的流式文本块（复用普通 chat 格式）
  done                 — 全部结束
  error                — 错误
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncGenerator

from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.config import get_settings
from api.app.core.logger import logger
from api.app.infrastructure.database.models import AgentSession, LLMConfig, Message, UserTool
from api.app.infrastructure.llm.adapters import StreamTurn, make_adapter
from api.app.infrastructure.tools.base import BaseTool
from api.app.infrastructure.tools.http_tool import HttpTool
from api.app.infrastructure.tools.registry import get_tool

settings = get_settings()

# ── 角色定义 ──────────────────────────────────────────────────────────────────

ROLE_LABELS: dict[str, str] = {
    "proposer":   "提案者",
    "critic":     "批判者",
    "creative":   "创意者",
    "validator":  "验证者",
    "synthesizer":"综合者",
}

ROLE_PROMPTS: dict[str, str] = {
    "proposer": (
        "你是提案者（Proposer）。直接给出最清晰、最优化的答案，聚焦解决方案，避免冗余。"
    ),
    "critic": (
        "你是批判者（Critic）。专门审视答案中的漏洞、逻辑错误、边界情况和不完整之处。"
        "不必给出完整答案，只需精准指出问题所在。"
    ),
    "creative": (
        "你是创意思考者（Creative Thinker）。提出非传统的、跳出框架的创新思路和角度，"
        "探索主流方案之外的可能性。"
    ),
    "validator": (
        "你是事实验证者（Validator）。用具体数据、逻辑推理来验证或推翻各方观点，"
        "指出哪些说法有据可查，哪些缺乏支撑。"
    ),
    "synthesizer": (
        "你是综合者（Synthesizer）。你将看到多个模型在多轮讨论中输出的观点。"
        "请提炼各方共识，客观呈现分歧，给出经过多角度验证的最终最优答案。"
        "直接输出最终答案，不要描述讨论过程本身。"
    ),
}

_REVIEWER_INSTRUCTION = """\
你是专业评审员。请评估主模型的回答，以 JSON 格式输出，格式严格如下（只输出 JSON，无任何额外说明）：
{
  "scores": {
    "accuracy":     8,
    "completeness": 7,
    "clarity":      9,
    "reasoning":    8
  },
  "critique": "（具体指出2-3个优缺点）",
  "improved_answer": "（基于原答案改进后的完整版本）"
}
各项满分 10 分。权重：accuracy 30%、completeness 25%、clarity 25%、reasoning 20%。"""

_SCORE_WEIGHTS = {"accuracy": 0.30, "completeness": 0.25, "clarity": 0.25, "reasoning": 0.20}


def _weighted_score(scores: dict) -> float:
    return sum(scores.get(k, 5) * w for k, w in _SCORE_WEIGHTS.items())


# ── 协作调度器 ────────────────────────────────────────────────────────────────

class CollaborationOrchestrator:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._tool_defs: list[dict] = []
        self._executors: dict[str, BaseTool] = {}

    # ── 工具加载（复用普通 orchestrator 的逻辑）────────────────────────────────

    async def _load_tools(self) -> None:
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
        self._tool_defs = defs
        self._executors = executors

    # ── 入口：流式调用 ────────────────────────────────────────────────────────

    async def stream_run(
        self,
        session: AgentSession,
        user_message: str,
    ) -> AsyncGenerator[str, None]:
        await self._load_tools()
        mode = session.collab_mode
        cfg = session.collab_config or {}

        await self._save_message(session.id, "user", user_message)

        if mode == "round_table":
            async for ev in self._stream_round_table(session, user_message, cfg):
                yield ev
        elif mode == "master_slave":
            async for ev in self._stream_master_slave(session, user_message, cfg):
                yield ev
        else:
            yield json.dumps({"type": "error", "message": f"未知协作模式: {mode}"})

    # ── 圆桌模式（B+C：迭代辩论 + 角色圆桌）──────────────────────────────────

    async def _stream_round_table(
        self,
        session: AgentSession,
        user_message: str,
        cfg: dict,
    ) -> AsyncGenerator[str, None]:
        models_cfg: list[dict] = cfg.get("models", [])
        rounds: int = cfg.get("rounds", 2)

        if len(models_cfg) < 2:
            yield json.dumps({"type": "error", "message": "圆桌模式至少需要 2 个模型槽位"})
            return

        # 加载所有 LLMConfig
        config_map: dict[str, LLMConfig] = {}
        for slot in models_cfg:
            cid = str(slot["config_id"])
            if cid not in config_map:
                llm_cfg = await self.db.get(LLMConfig, uuid.UUID(cid))
                if llm_cfg is None:
                    yield json.dumps({"type": "error", "message": f"模型配置不存在: {cid}"})
                    return
                config_map[cid] = llm_cfg

        synthesizer_slot = next(
            (s for s in reversed(models_cfg) if s["role"] == "synthesizer"),
            models_cfg[-1],
        )
        panel_slots = [s for s in models_cfg if s["role"] != "synthesizer"]

        base_system = session.system_prompt_ref.content if session.system_prompt_ref else ""

        # ── 多轮讨论 ──────────────────────────────────────────────────────────
        all_round_results: dict[int, list[dict]] = {}   # {round: [{role, model_name, text}]}

        for rnd in range(1, rounds + 1):
            phase_label = f"Round {rnd} · {'独立作答' if rnd == 1 else '交叉审视'}"
            yield json.dumps({"type": "collab_phase", "phase": f"round_{rnd}", "label": phase_label})
            logger.info(f"[圆桌] {phase_label}")

            # 构建本轮的追加上下文（R2 起才有）
            context_suffix = ""
            if rnd > 1:
                parts = []
                for prev_rnd in range(1, rnd):
                    for entry in all_round_results.get(prev_rnd, []):
                        label = ROLE_LABELS.get(entry["role"], entry["role"])
                        parts.append(f"【{label} · {entry['model_name']}】\n{entry['text']}")
                context_suffix = (
                    "\n\n---\n以下是其他模型在上一轮的观点，请从你的角色视角进行评述或补充：\n\n"
                    + "\n\n".join(parts)
                )

            # 并行运行本轮所有面板模型
            async def _call_one(slot: dict, suffix: str) -> dict:
                cid = str(slot["config_id"])
                llm_cfg = config_map[cid]
                role = slot["role"]
                role_prompt = ROLE_PROMPTS.get(role, "")
                system = (base_system + "\n\n" if base_system else "") + role_prompt

                adapter = make_adapter(llm_cfg, [])
                question = user_message + suffix
                messages = adapter.format_history([{"role": "user", "content": question}])
                try:
                    turn = await adapter.complete(messages, system, settings.agent_max_tokens)
                    text = turn.text
                except Exception as exc:
                    text = f"[调用失败: {exc}]"
                    logger.warning(f"[圆桌] {role} ({llm_cfg.display_name}) 调用失败: {exc}")
                return {"role": role, "model_name": llm_cfg.display_name, "text": text}

            tasks = [_call_one(slot, context_suffix) for slot in panel_slots]
            round_results: list[dict] = await asyncio.gather(*tasks)

            all_round_results[rnd] = round_results
            for entry in round_results:
                yield json.dumps({
                    "type": "collab_model_result",
                    "round": rnd,
                    "role": entry["role"],
                    "role_label": ROLE_LABELS.get(entry["role"], entry["role"]),
                    "model_name": entry["model_name"],
                    "content": entry["text"],
                })

        # ── 综合阶段 ──────────────────────────────────────────────────────────
        synth_cfg = config_map[str(synthesizer_slot["config_id"])]
        yield json.dumps({
            "type": "collab_synthesis_start",
            "model_name": synth_cfg.display_name,
        })

        # 构建综合者的完整输入
        summary_parts = [f"**用户问题：**\n{user_message}\n"]
        for rnd in range(1, rounds + 1):
            summary_parts.append(
                f"=== Round {rnd} ({'独立作答' if rnd == 1 else '交叉审视'}) ==="
            )
            for entry in all_round_results.get(rnd, []):
                label = ROLE_LABELS.get(entry["role"], entry["role"])
                summary_parts.append(f"【{label} · {entry['model_name']}】\n{entry['text']}")
        synthesis_input = "\n\n".join(summary_parts)

        synth_system = (base_system + "\n\n" if base_system else "") + ROLE_PROMPTS["synthesizer"]
        synth_adapter = make_adapter(synth_cfg, [])
        synth_messages = synth_adapter.format_history([
            {"role": "user", "content": synthesis_input}
        ])

        final_text = ""
        last_usage: dict = {}
        try:
            async for item in synth_adapter.stream(synth_messages, synth_system, settings.agent_max_tokens):
                if isinstance(item, str):
                    final_text += item
                    yield json.dumps({"type": "text", "content": item})
                elif isinstance(item, StreamTurn):
                    last_usage = item.usage
        except Exception as exc:
            logger.exception("[圆桌] 综合者调用失败")
            yield json.dumps({"type": "error", "message": str(exc)})
            return

        await self._save_message(session.id, "assistant", final_text)
        await self._auto_title(session, user_message, synth_adapter)
        yield json.dumps({"type": "done", "usage": last_usage})

    # ── 主从模式 ──────────────────────────────────────────────────────────────

    async def _stream_master_slave(
        self,
        session: AgentSession,
        user_message: str,
        cfg: dict,
    ) -> AsyncGenerator[str, None]:
        master_cid = cfg.get("master_config_id")
        reviewer_cids: list[str] = cfg.get("reviewer_config_ids", [])

        if not master_cid:
            yield json.dumps({"type": "error", "message": "主从模式缺少 master_config_id"})
            return

        master_cfg = await self.db.get(LLMConfig, uuid.UUID(str(master_cid)))
        if master_cfg is None:
            yield json.dumps({"type": "error", "message": "主模型配置不存在"})
            return

        reviewer_cfgs: list[LLMConfig] = []
        for cid in reviewer_cids:
            rc = await self.db.get(LLMConfig, uuid.UUID(str(cid)))
            if rc:
                reviewer_cfgs.append(rc)

        base_system = session.system_prompt_ref.content if session.system_prompt_ref else None

        # ── Step 1: 主模型作答（流式） ────────────────────────────────────────
        yield json.dumps({
            "type": "collab_phase",
            "phase": "master",
            "label": f"主模型作答 · {master_cfg.display_name}",
        })
        yield json.dumps({
            "type": "collab_model_text",
            "role": "master",
            "model_name": master_cfg.display_name,
            "content": "",   # start signal
        })

        master_adapter = make_adapter(master_cfg, self._tool_defs)
        history = [
            {"role": m.role, "content": m.content}
            for m in session.messages
            if m.role in ("user", "assistant") and m.content
        ]
        history.append({"role": "user", "content": user_message})
        master_messages = master_adapter.format_history(history)

        master_text = ""
        master_usage: dict = {}
        try:
            async for item in master_adapter.stream(master_messages, base_system, settings.agent_max_tokens):
                if isinstance(item, str):
                    master_text += item
                    yield json.dumps({"type": "collab_model_text", "role": "master",
                                      "model_name": master_cfg.display_name, "content": item})
                elif isinstance(item, StreamTurn):
                    master_usage = item.usage
        except Exception as exc:
            logger.exception("[主从] 主模型调用失败")
            yield json.dumps({"type": "error", "message": str(exc)})
            return

        yield json.dumps({"type": "collab_model_end", "role": "master", "usage": master_usage})

        if not reviewer_cfgs:
            # 无评委，主模型答案即最终答案
            await self._save_message(session.id, "assistant", master_text, token_count=master_usage.get("output_tokens"))
            await self._auto_title(session, user_message, master_adapter)
            yield json.dumps({"type": "done", "usage": master_usage})
            return

        # ── Step 2: 评委并行评审 ──────────────────────────────────────────────
        yield json.dumps({
            "type": "collab_phase",
            "phase": "review",
            "label": f"评委评审中（{len(reviewer_cfgs)} 位）",
        })

        review_prompt = (
            f"原始问题：{user_message}\n\n"
            f"主模型答案：\n{master_text}\n\n"
            f"{_REVIEWER_INSTRUCTION}"
        )

        async def _review_one(rc: LLMConfig) -> dict:
            raw_text = ""
            try:
                adapter = make_adapter(rc, [])
                msgs = adapter.format_history([{"role": "user", "content": review_prompt}])
                turn = await adapter.complete(msgs, None, 1500)
                raw_text = turn.text.strip()
                # 提取 JSON：去掉 markdown 围栏，再用正则定位 {} 块
                cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()
                m = re.search(r"\{[\s\S]*\}", cleaned)
                raw_json = m.group() if m else cleaned
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                data = {"scores": {}, "critique": raw_text[:400], "improved_answer": master_text}
            except Exception as exc:
                logger.warning(f"[主从] 评委 {rc.display_name} 调用失败: {exc}")
                data = {"scores": {}, "critique": f"评审失败: {exc}", "improved_answer": master_text}

            scores = data.get("scores", {})
            weighted = _weighted_score(scores)
            return {
                "model_name": rc.display_name,
                "scores": scores,
                "weighted_total": round(weighted, 1),
                "critique": data.get("critique", ""),
                "improved_answer": data.get("improved_answer", master_text),
            }

        reviewer_results: list[dict] = await asyncio.gather(*[_review_one(rc) for rc in reviewer_cfgs])

        for res in reviewer_results:
            yield json.dumps({"type": "collab_reviewer_result", **res})

        # ── Step 3: 取最高分改进版作为最终答案 ────────────────────────────────
        best = max(reviewer_results, key=lambda r: r["weighted_total"])
        final_text = best["improved_answer"] or master_text

        yield json.dumps({
            "type": "collab_synthesis_start",
            "model_name": best["model_name"],
            "score": best["weighted_total"],
        })

        # 分块 yield 最终文本，模拟流式输出
        chunk_size = 60
        for i in range(0, len(final_text), chunk_size):
            yield json.dumps({"type": "text", "content": final_text[i:i + chunk_size]})

        await self._save_message(session.id, "assistant", final_text)
        await self._auto_title(session, user_message, master_adapter)
        yield json.dumps({"type": "done", "usage": master_usage})

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _save_message(
        self,
        session_id: uuid.UUID,
        role: str,
        content: str,
        token_count: int | None = None,
    ) -> Message:
        msg = Message(
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
        )
        self.db.add(msg)
        await self.db.flush()
        await self.db.refresh(msg)
        return msg

    async def _auto_title(self, session: AgentSession, user_message: str, adapter) -> None:
        if session.title != "新会话":
            return
        try:
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
        except Exception:
            logger.warning("[协作] 自动命名失败")
