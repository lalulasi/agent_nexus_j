import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.infrastructure.database.session import get_db
from app.infrastructure.database.models import AgentSession, Message
from app.domain.schemas import SessionCreate, SessionResponse, ChatRequest, MessageResponse
from app.infrastructure.llm.provider import generate_ai_reply_stream, generate_json_evaluation
from app.core.logger import logger
from app.infrastructure.tools.registry import tool_registry
from app.infrastructure.tools.dynamic_api import DynamicAPITool
from openai import AsyncOpenAI
import asyncio
import httpx

from app.domain.schemas import SwarmNode

router = APIRouter(prefix="/sessions", tags=["Agent Sessions"])

LOCAL_BRAIN_MODEL = "qwen3.5:2b"


@router.post("/", response_model=SessionResponse)
async def create_session(session_in: SessionCreate, db: AsyncSession = Depends(get_db)):
    new_session = AgentSession(title=session_in.title, model_provider=session_in.model_provider)
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session_title(session_id: str, title: str, db: AsyncSession = Depends(get_db)):
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session: raise HTTPException(status_code=404)
    session.title = title
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session: raise HTTPException(status_code=404)
    await db.delete(session)
    await db.commit()
    return {"message": "Deleted"}


@router.get("/", response_model=list[SessionResponse])
async def list_all_sessions(db: AsyncSession = Depends(get_db)):
    stmt = select(AgentSession).order_by(AgentSession.updated_at.desc())
    return (await db.execute(stmt)).scalars().all()


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(session_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    return (await db.execute(stmt)).scalars().all()


@router.post("/{session_id}/chat")
async def chat_with_agent(session_id: str, chat_req: ChatRequest, db: AsyncSession = Depends(get_db)):
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session: raise HTTPException(status_code=404)

    if chat_req.custom_tools is not None:
        session.custom_tools = [t.model_dump() for t in chat_req.custom_tools]
        await db.commit()

    local_custom_tools = {}
    extra_schemas = []
    if chat_req.custom_tools:
        for t_cfg in chat_req.custom_tools:
            dt = DynamicAPITool(name=t_cfg.name, description=t_cfg.description, parameters=t_cfg.parameters,
                                target_url=t_cfg.url)
            local_custom_tools[t_cfg.name] = dt
            extra_schemas.append(dt.to_openai_schema())

    if chat_req.action == "chat":
        combined_text = chat_req.user_input or ""
        if chat_req.file_content:
            fname = chat_req.file_name or "document.txt"
            combined_text += f"\n\n[附带文件: {fname}]\n{chat_req.file_content}\n[文件结束]"
        if combined_text.strip():
            db.add(Message(session_id=session_id, role="user", content=combined_text))
            await db.flush()

            history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
            history_records = (await db.execute(history_stmt)).scalars().all()
            if len(history_records) == 1 and (not session.title or "新会话" in session.title):
                try:
                    client = AsyncOpenAI(api_key=chat_req.api_key, base_url=chat_req.base_url)
                    resp = await client.chat.completions.create(
                        model=chat_req.text_model,
                        messages=[{"role": "system", "content": "输出4到6个字标题，不要标点。"},
                                  {"role": "user", "content": f"根据内容生成标题：{chat_req.user_input}"}]
                    )
                    session.title = resp.choices[0].message.content.strip(' \n\r"“”。')
                    await db.commit()
                except Exception as e:
                    pass

    elif chat_req.action == "approve_tool":
        tool_instance = local_custom_tools.get(chat_req.pending_tool_name) or tool_registry.get_tool(
            chat_req.pending_tool_name)
        try:
            args_dict = json.loads(chat_req.pending_tool_args) if chat_req.pending_tool_args else {}
            result = await tool_instance.execute(**args_dict)
        except Exception as e:
            result = f"Error: {str(e)}"
        db.add(Message(session_id=session_id, role="user", content=f"👉 [系统汇报] 终端命令已执行。\n结果:\n{result}"))
        await db.flush()
    elif chat_req.action == "reject_tool":
        db.add(Message(session_id=session_id, role="user", content="🚫 [系统汇报] 用户拒绝了命令。"))
        await db.flush()
    elif chat_req.action == "pull_local_model":
        async def pull_stream():
            try:
                async with httpx.AsyncClient() as client:
                    async with client.stream("POST", "http://localhost:11434/api/pull",
                                             json={"name": LOCAL_BRAIN_MODEL}) as resp:
                        async for line in resp.aiter_lines():
                            if line:
                                data = json.loads(line)
                                yield f"data: {json.dumps({'type': 'pull_progress', 'status': data.get('status', ''), 'completed': data.get('completed', 0), 'total': data.get('total', 1)})}\n\n"
                yield f"data: {json.dumps({'type': 'pull_success'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': f'Ollama 连接失败({str(e)})'})}\n\n"

        return StreamingResponse(pull_stream(), media_type="text/event-stream")

    async def event_generator():
        target_model = chat_req.text_model

        if chat_req.swarm_mode:
            has_local_model = False
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get("http://localhost:11434/api/tags", timeout=2.0)
                    if resp.status_code == 200:
                        tags = resp.json().get("models", [])
                        has_local_model = any(
                            m.get("name") == LOCAL_BRAIN_MODEL or m.get("name") == f"{LOCAL_BRAIN_MODEL}:latest" for m
                            in tags)
            except Exception:
                pass
            if not has_local_model:
                yield f"data: {json.dumps({'type': 'requires_local_model', 'model_name': LOCAL_BRAIN_MODEL})}\n\n"
                return

        history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        history_records = (await db.execute(history_stmt)).scalars().all()

        llm_messages = []
        if chat_req.system_prompt: llm_messages.append({"role": "system", "content": chat_req.system_prompt})

        for m in history_records:
            if m.role == "tool":
                llm_messages.append({"role": "user", "content": f"🔧 [历史记录-工具执行结果]:\n{m.content}"})
            else:
                llm_messages.append({"role": m.role, "content": m.content})

        current_msg = {"role": "user", "content": chat_req.user_input}
        if chat_req.action == "chat" and chat_req.image_base64:
            target_model = chat_req.vision_model or chat_req.text_model
            current_msg["content"] = [{"type": "text", "text": chat_req.user_input}, {"type": "image_url",
                                                                                      "image_url": {
                                                                                          "url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}]
        llm_messages.append(current_msg)

        msgs_to_compress = [m for m in llm_messages[:-1] if m.get("role") != "system"]
        if len(msgs_to_compress) >= 8:
            logger.info(f"🗜️ [记忆压缩] 唤醒本地模型 [{LOCAL_BRAIN_MODEL}]...")
            yield f"data: {json.dumps({'type': 'status', 'content': f'🗜️ 历史记录达到 {len(msgs_to_compress)} 条，本地小模型正在压缩记忆...'})}\n\n"
            history_text = "\n".join([f"{m['role']}: {str(m['content'])[:500]}..." for m in msgs_to_compress])
            compress_prompt = "你是一个记忆压缩清道夫。请将以下冗长的多轮历史对话压缩成 300 字以内的精华摘要。必须保留用户的核心意图、关键的已知前提和代码片段。不要闲聊，直接输出摘要内容。"
            summary_res = ""
            try:
                async for ev in generate_ai_reply_stream(
                        [{"role": "user", "content": f"{compress_prompt}\n\n【待压缩历史记录】:\n{history_text}"}],
                        "ollama", "http://localhost:11434/v1", LOCAL_BRAIN_MODEL, False, None):
                    if ev["type"] == "text_chunk": summary_res += ev["data"]
                if summary_res.strip():
                    yield f"data: {json.dumps({'type': 'status', 'content': '✅ 记忆压缩完成，正在唤醒主脑计算当前问题...'})}\n\n"
                    new_llm_messages = []
                    if chat_req.system_prompt: new_llm_messages.append(
                        {"role": "system", "content": chat_req.system_prompt})
                    new_llm_messages.append(
                        {"role": "system", "content": f"【💡 此前的历史对话已被压缩为摘要】:\n{summary_res}"})
                    new_llm_messages.append(current_msg)
                    llm_messages = new_llm_messages
            except Exception as e:
                yield f"data: {json.dumps({'type': 'status', 'content': '⚠️ 本地记忆压缩未响应，回退使用完整历史记录...'})}\n\n"

        # ==========================================
        # 🚀 新增极客武器：使 Swarm 节点支持独立工具调用闭环！
        # ==========================================
        async def run_node_with_tools(node: SwarmNode, msgs: list) -> str:
            node_msgs = list(msgs)

            # 🌟 核心映射：将传过来的工具名称列表，映射为真正的 OpenAI JSON Schema
            node_schemas = []
            assigned_names = getattr(node, "assigned_tools", []) or []
            for t_name in assigned_names:
                for schema in extra_schemas:  # extra_schemas 是路由最顶端已经解析好的全部工具
                    if schema["function"]["name"] == t_name:
                        node_schemas.append(schema)
                        break

            if not node_schemas: node_schemas = None
            final_text = ""
            for _ in range(5):  # 最多允许连续调用 5 次工具
                current_text = ""
                tool_calls_to_exec = None

                async for ev in generate_ai_reply_stream(node_msgs, node.api_key, node.base_url, node.text_model,
                                                         bool(node_schemas), node_schemas):
                    if ev["type"] == "text_chunk":
                        current_text += ev["data"]
                    elif ev["type"] == "final_message":
                        ai_msg = ev["data"]
                        if ai_msg.tool_calls:
                            tool_calls_to_exec = ai_msg.tool_calls
                            node_msgs.append(ai_msg.model_dump(exclude_unset=True))
                        else:
                            current_text = ai_msg.content or current_text
                #
                if tool_calls_to_exec:
                    for tc in tool_calls_to_exec:
                        t_name = tc.function.name
                        t_args = tc.function.arguments
                        # 拦截测试用的虚拟时间工具
                        logger.info(f"🛠️ [Swarm 工具调用] 节点正动用工具: [{t_name}] | 参数: {t_args}")
                        if t_name == "get_system_time":
                            from datetime import datetime
                            t_res = f"系统执行成功，当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        else:
                            try:
                                tool_inst = local_custom_tools.get(t_name) or tool_registry.get_tool(t_name)
                                if tool_inst:
                                    t_res = await tool_inst.execute(**json.loads(t_args))
                                else:
                                    t_res = f"无此工具: {t_name}"
                            except Exception as e:
                                t_res = f"执行报错: {str(e)}"
                        logger.info(f"✅ [Swarm 工具返回] 结果截取: {str(t_res)[:100]}...")
                        node_msgs.append({"role": "tool", "tool_call_id": tc.id, "name": t_name, "content": str(t_res)})
                else:
                    final_text = current_text
                    break
            return final_text

        if chat_req.swarm_mode and chat_req.swarm_nodes:
            if len(chat_req.swarm_nodes) == 1:
                yield f"data: {json.dumps({'type': 'status', 'content': '⚡ 仅检测到单模型，已自动降级为极速直连模式...'})}\n\n"
                chat_req.swarm_mode = None
            else:
                yield f"data: {json.dumps({'type': 'status', 'content': '🚀 指令已接收，正在编排异构舰队...'})}\n\n"

            # ------------------------------------------
            # ⚔️ 分支 A：主从迭代模式
            # ------------------------------------------
            if chat_req.swarm_mode == "maker_checker" and len(chat_req.swarm_nodes) > 1:
                primary = chat_req.swarm_nodes[0]
                critics = chat_req.swarm_nodes[1:]

                yield f"data: {json.dumps({'type': 'status', 'content': f'🚀 启动主从迭代 | 主脑: {primary.provider_name}'})}\n\n"

                current_messages = list(llm_messages)
                final_draft = ""

                for iteration in range(1, 4):
                    yield f"data: {json.dumps({'type': 'status', 'content': f'✍️ [第 {iteration} 轮] 主脑正在动用专属能力撰写草稿...'})}\n\n"
                    # 🌟 异构革新：主脑带着它的专属工具去写草稿！
                    draft = await run_node_with_tools(primary, current_messages)

                    yield f"data: {json.dumps({'type': 'status', 'content': f'🕵️ {len(critics)} 位副脑正在并发严苛审查中...'})}\n\n"

                    tasks = []
                    for c in critics:
                        sys_prompt = """你是一个冷酷无情、极其严苛的 AI 首席审查官 (Judge)。
你的任务是评估【待审草稿】是否完美解答了【用户问题】。
请你严格按照以下【评分量表】给出 0-100 的整数评分：
- [90-100分]：无懈可击。事实绝对正确，逻辑严密。
- [80-89分]：合格但平庸。大方向正确，但缺少深度或遗漏细节。
- [60-79分]：必须重写。存在明显逻辑漏洞、事实错误。
- [0-59分]：灾难性错误。严重幻觉、完全偏题。"""
                        tasks.append(generate_json_evaluation(sys_prompt,
                                                              f"用户问题: {chat_req.user_input}\n\n待审草稿:\n{draft}",
                                                              c.api_key, c.base_url, c.text_model))

                    eval_results = await asyncio.gather(*tasks, return_exceptions=True)
                    all_pass, advices, total_score, valid_score_count, critic_details = True, [], 0, 0, []

                    for idx, res in enumerate(eval_results):
                        c_name = critics[idx].provider_name
                        if isinstance(res, dict):
                            is_pass, score, advice = res.get("pass", True), res.get("score", 0), res.get("advice",
                                                                                                         "无修改意见。")
                            if not is_pass: all_pass = False
                            if advice.strip(): advices.append(f"[{c_name}]: {advice}")
                            if "score" in res and isinstance(score, (int, float)):
                                total_score += score
                                valid_score_count += 1
                            critic_details.append(f"> - **{c_name}**: 评分 `{score}/100`。*评价: {advice}*")

                    avg_score = (total_score / valid_score_count) if valid_score_count > 0 else 0

                    if all_pass or avg_score >= 85 or iteration == 3:
                        yield f"data: {json.dumps({'type': 'status', 'content': f'✅ 审查结束 (综合得分 {avg_score:.1f})'})}\n\n"
                        review_summary = f"> 📊 **多智能体委员会 - 最终评审报告 (得分: {avg_score:.1f})**\n>\n"
                        for detail in critic_details: review_summary += f"{detail}\n>\n"
                        review_summary += "> ---\n\n"
                        final_draft = review_summary + draft
                        break
                    else:
                        yield f"data: {json.dumps({'type': 'status', 'content': f'⚠️ 评分 {avg_score:.1f}，打回重写...'})}\n\n"
                        current_messages.extend([{"role": "assistant", "content": draft}, {"role": "user",
                                                                                           "content": f"审查未通过（得分：{avg_score:.1f}）。请彻底重写：\n" + "\n".join(
                                                                                               advices)}])

                chunk_size = 10
                for i in range(0, len(final_draft), chunk_size):
                    yield f"data: {json.dumps({'type': 'chunk', 'content': final_draft[i:i + chunk_size]})}\n\n"
                    await asyncio.sleep(0.01)

                db.add(Message(session_id=session_id, role="assistant", content=final_draft))
                await db.commit()
                yield f"data: {json.dumps({'type': 'completed', 'content': final_draft})}\n\n"
                return

            # ------------------------------------------
            # ⚔️ 分支 B：圆桌会议模式 (异构 Map-Reduce)
            # ------------------------------------------
            elif chat_req.swarm_mode == "roundtable" and len(chat_req.swarm_nodes) > 0:
                participants = list(chat_req.swarm_nodes)
                judge = participants[0]

                yield f"data: {json.dumps({'type': 'status', 'content': f'🎪 启动异构圆桌会议 | {len(participants)} 位专家正在利用专属工具并发思考...'})}\n\n"

                async def get_node_answer(n):
                    # 🌟 异构革新：每个专家带着自己的专属工具独立调研！
                    ans = await run_node_with_tools(n, llm_messages)
                    return f"【{n.provider_name} 的独立见解】:\n{ans}\n"

                tasks = [get_node_answer(node) for node in participants]
                answers = await asyncio.gather(*tasks, return_exceptions=True)
                valid_answers = [a for a in answers if isinstance(a, str) and a.strip()]

                yield f"data: {json.dumps({'type': 'status', 'content': f'⚖️ 数据收集完毕，首席法官 [{judge.provider_name}] 正在进行跨模态降维融合...'})}\n\n"

                synthesis_prompt = f"""你是本次多智能体圆桌会议的首席法官(Judge)。
【业务背景】：用户期望遵循规则：“{chat_req.system_prompt}”。请纳入考量。
以下是各位专家的独立调研报告（部分专家可能调用了特定的系统 API 获取了真实数据）：
====================
{chr(10).join(valid_answers)}
====================

请运用 Map-Reduce 融合算法，严格按以下 Markdown 格式输出：
> 🎪 **多智能体圆桌会议 - 首席法官综合纪要**
> 
> **🟢 核心共识 / 确凿事实**：
> (提炼共识，若某专家通过工具获取了真实数据，请将其作为确凿事实)
> 
> **🔴 关键分歧 / 独到见解**：
> (指出冲突或信息差)
> 
> **⚖️ 法官裁决**：
> (给出最终专业判断)

---
(在此处输出融合后的最终完美解答)
"""
                judge_messages = [{"role": "system", "content": synthesis_prompt},
                                  {"role": "user", "content": chat_req.user_input}]
                full_response = ""
                async for event in generate_ai_reply_stream(judge_messages, judge.api_key, judge.base_url,
                                                            judge.text_model, False, None):
                    if event["type"] == "text_chunk":
                        full_response += event["data"]
                        yield f"data: {json.dumps({'type': 'chunk', 'content': event['data']})}\n\n"

                db.add(Message(session_id=session_id, role="assistant", content=full_response))
                await db.commit()
                yield f"data: {json.dumps({'type': 'completed', 'content': full_response})}\n\n"
                return

        # ==========================================
        # 🚶 普通单机模式
        # ==========================================
        for iteration in range(3):
            async for event in generate_ai_reply_stream(llm_messages, chat_req.api_key, chat_req.base_url, target_model,
                                                        True, extra_schemas):
                if event["type"] == "text_chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': event['data']})}\n\n"
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': event['data']})}\n\n"; return
                elif event["type"] == "final_message":
                    ai_message = event["data"]
                    if ai_message.tool_calls:
                        llm_messages.append(ai_message.model_dump(exclude_unset=True))
                        t_names = ", ".join([tc.function.name for tc in ai_message.tool_calls])
                        db.add(Message(session_id=session_id, role="assistant",
                                       content=ai_message.content or f"[调用工具: {t_names}]"))
                        await db.flush()

                        for tool_call in ai_message.tool_calls:
                            t_name = tool_call.function.name
                            t_args_str = tool_call.function.arguments

                            # 拦截测试用时间工具
                            if t_name == "get_system_time":
                                from datetime import datetime
                                t_result = f"当前系统时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                            else:
                                try:
                                    tool_instance = local_custom_tools.get(t_name) or tool_registry.get_tool(t_name)
                                    t_result = await tool_instance.execute(**json.loads(t_args_str))
                                except Exception as e:
                                    t_result = f"Error: {str(e)}"
                            db.add(Message(session_id=session_id, role="user",
                                           content=f"🔧 [系统汇报: 工具执行结果]\n{t_result}"))
                            await db.flush()
                            llm_messages.append({"role": "tool", "tool_call_id": tool_call.id, "name": t_name,
                                                 "content": str(t_result)})
                        break
                    else:
                        db.add(Message(session_id=session_id, role="assistant", content=ai_message.content))
                        await db.commit()
                        yield f"data: {json.dumps({'type': 'completed', 'content': ai_message.content})}\n\n"
                        return

    return StreamingResponse(event_generator(), media_type="text/event-stream")