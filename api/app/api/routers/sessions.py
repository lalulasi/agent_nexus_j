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
from openai import AsyncOpenAI  # 引入原生客户端用于标题生成
import asyncio # 🌟 确保导入了 asyncio 用于并发
import httpx

from app.domain.schemas import SwarmNode

router = APIRouter(prefix="/sessions", tags=["Agent Sessions"])

LOCAL_BRAIN_MODEL = "qwen3.5:2b" # 🌟 我们选定的本地神经中枢

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

            # 🌟 还原功能：自动重命名逻辑
            history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
            history_records = (await db.execute(history_stmt)).scalars().all()
            if len(history_records) == 1 and (not session.title or "新会话" in session.title):
                try:
                    client = AsyncOpenAI(api_key=chat_req.api_key, base_url=chat_req.base_url)
                    resp = await client.chat.completions.create(
                        model=chat_req.text_model,
                        messages=[
                            {"role": "system", "content": "输出4到6个字标题，不要标点。"},
                            {"role": "user", "content": f"根据内容生成标题：{chat_req.user_input}"}
                        ]
                    )
                    session.title = resp.choices[0].message.content.strip(' \n\r"“”。')
                    await db.commit()
                except Exception as e:
                    logger.error(f"Auto-rename failed: {e}")

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
        # 🌟 专用流式拉取管道
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
                yield f"data: {json.dumps({'type': 'error', 'content': f'Ollama 连接失败，请确保本地 Ollama 已启动！({str(e)})'})}\n\n"

        return StreamingResponse(pull_stream(), media_type="text/event-stream")

    async def event_generator():
        target_model = chat_req.text_model

        # ==========================================
        # 🕵️ 静默探测：如果是多模型协作，检查本地大脑是否存在
        # ==========================================
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
                pass  # Ollama未启动或连接失败，交由前端处理

            if not has_local_model:
                yield f"data: {json.dumps({'type': 'requires_local_model', 'model_name': LOCAL_BRAIN_MODEL})}\n\n"
                return  # 🌟 核心：强制中断，交由前端弹窗

        history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        history_records = (await db.execute(history_stmt)).scalars().all()

        llm_messages = []
        if chat_req.system_prompt:
            llm_messages.append({"role": "system", "content": chat_req.system_prompt})

        for m in history_records:
            if m.role == "tool":
                llm_messages.append({"role": "user", "content": f"🔧 [历史记录-工具执行结果]:\n{m.content}"})
            else:
                llm_messages.append({"role": m.role, "content": m.content})

            # 🌟 追加当前用户的最新提问 (如果是带图片的，替换为多模态格式)
        current_msg = {"role": "user", "content": chat_req.user_input}
        if chat_req.action == "chat" and chat_req.image_base64:
            target_model = chat_req.vision_model or chat_req.text_model
            current_msg["content"] = [
                {"type": "text", "text": chat_req.user_input},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}
            ]
        llm_messages.append(current_msg)
        # ==========================================
        # 🗜️ 2. 本地小模型介入：无感记忆压缩器 (Context Compressor)
        # ==========================================
        # 当历史消息超过 8 条 (不包含系统提示和当前最新提问) 时，触发本地记忆压缩
        msgs_to_compress = [m for m in llm_messages[:-1] if m.get("role") != "system"]

        if len(msgs_to_compress) >= 8:
            logger.info(
                f"🗜️ [记忆压缩] 检测到历史记录过长 ({len(msgs_to_compress)}条)，正在唤醒本地模型 [{LOCAL_BRAIN_MODEL}]...")
            yield f"data: {json.dumps({'type': 'status', 'content': f'🗜️ 历史记录达到 {len(msgs_to_compress)} 条，本地小模型正在压缩上下文记忆...'})}\n\n"

            history_text = "\n".join([f"{m['role']}: {str(m['content'])[:500]}..." for m in msgs_to_compress])
            compress_prompt = "你是一个记忆压缩清道夫。请将以下冗长的多轮历史对话压缩成 300 字以内的精华摘要。必须保留用户的核心意图、关键的已知前提和代码片段。不要闲聊，直接输出摘要内容。"

            summary_res = ""
            try:
                # 调用本地小模型进行压缩 (零成本)
                async for ev in generate_ai_reply_stream(
                        [{"role": "user", "content": f"{compress_prompt}\n\n【待压缩历史记录】:\n{history_text}"}],
                        "ollama", "http://localhost:11434/v1", LOCAL_BRAIN_MODEL, False, None):
                    if ev["type"] == "text_chunk":
                        summary_res += ev["data"]

                if summary_res.strip():
                    logger.info(
                        f"✅ [记忆压缩] 本地模型压缩完成！原长度: {len(history_text)} 字符 -> 压缩后: {len(summary_res)} 字符")
                    yield f"data: {json.dumps({'type': 'status', 'content': '✅ 记忆压缩完成，正在唤醒主脑计算当前问题...'})}\n\n"

                    # 🌟 重构上下文：系统提示词 + 记忆摘要 + 最新问题
                    new_llm_messages = []
                    if chat_req.system_prompt:
                        new_llm_messages.append({"role": "system", "content": chat_req.system_prompt})
                    new_llm_messages.append(
                        {"role": "system", "content": f"【💡 此前的历史对话已被压缩为摘要】:\n{summary_res}"})
                    new_llm_messages.append(current_msg)  # 压入当前问题
                    llm_messages = new_llm_messages  # 替换掉原来极其臃肿的 messages 列表
            except Exception as e:
                logger.error(f"❌ [记忆压缩] 本地模型压缩失败: {str(e)}。已回退到完整历史记录模式。")
                yield f"data: {json.dumps({'type': 'status', 'content': '⚠️ 本地记忆压缩未响应，回退使用完整历史记录...'})}\n\n"
                # 如果失败，直接 catch 掉，不影响后续大模型的正常访问
                pass

        # ==========================================
        # 👑 智能体协作核心调度总线 (Swarm Orchestrator)
        # ==========================================
        if chat_req.swarm_mode and chat_req.swarm_nodes:
            logger.info(
                f"🚀 [Swarm] 启动协作网络 | 模式: {chat_req.swarm_mode} | 参战模型: {[n.text_model for n in chat_req.swarm_nodes]}")

            # ------------------------------------------
            # ⚔️ 分支 A：主从迭代模式
            # ------------------------------------------
            if chat_req.swarm_mode == "maker_checker" and len(chat_req.swarm_nodes) > 1:
                primary = chat_req.swarm_nodes[0]
                critics = chat_req.swarm_nodes[1:]  # 🌟 纯净的云端副脑舰队，不再混入本地模型

                yield f"data: {json.dumps({'type': 'status', 'content': f'🚀 启动主从迭代 | 主脑: {primary.provider_name}'})}\n\n"

            # ------------------------------------------
            # ⚔️ 分支 A：主从迭代模式
            # ------------------------------------------
            # ------------------------------------------
            # ⚔️ 分支 A：主从迭代模式
            # ------------------------------------------
            if chat_req.swarm_mode == "maker_checker" and len(chat_req.swarm_nodes) > 1:
                primary = chat_req.swarm_nodes[0]
                critics = chat_req.swarm_nodes[1:]  # 🌟 纯净的云端副脑舰队，不再混入本地模型

                yield f"data: {json.dumps({'type': 'status', 'content': f'🚀 启动主从迭代 | 主脑: {primary.provider_name}'})}\n\n"

                current_messages = list(llm_messages)
                final_draft = ""

                for iteration in range(1, 4):  # 最大循环 3 次
                    yield f"data: {json.dumps({'type': 'status', 'content': f'✍️ [第 {iteration} 轮] 主脑正在生成草稿...'})}\n\n"

                    draft = ""
                    async for ev in generate_ai_reply_stream(current_messages, primary.api_key, primary.base_url,
                                                                 primary.text_model, False, None):
                        if ev["type"] == "text_chunk": draft += ev["data"]

                    yield f"data: {json.dumps({'type': 'status', 'content': f'🕵️ {len(critics)} 位副脑(含本地中枢)正在并发审查中...'})}\n\n"

                    # 并发执行副模型打分
                    tasks = []
                    for c in critics:
                        sys_prompt = """你是一个冷酷无情、极其严苛的 AI 首席审查官 (Judge)。
        你的任务是评估【待审草稿】是否完美解答了【用户问题】。

        请你严格按照以下【评分量表】给出 0-100 的整数评分：
        - [90-100分]：无懈可击。事实绝对正确，逻辑严密，排版优雅，代码/方案可直接投入生产环境。
        - [80-89分]：合格但平庸。大方向正确，但缺少深度、遗漏了次要细节、或者表达不够清晰。
        - [60-79分]：必须重写。存在明显的逻辑漏洞、部分事实错误、代码存在 Bug 或严重偏题。
        - [0-59分]：灾难性错误。严重的幻觉、产生危险后果、或者完全没有回答用户的问题。

        扣分规则：
        1. 只要发现任何一处常识性错误或代码语法错误，分数不得高于 75 分。
        2. 如果草稿遗漏了用户提问中的任何一个限定条件，分数不得高于 80 分。

        在决定分数前，请先深吸一口气，一步一步地审查草稿的事实、逻辑和完整性。"""
                        tasks.append(generate_json_evaluation(sys_prompt,
                                                                  f"用户问题: {chat_req.user_input}\n\n待审草稿:\n{draft}",
                                                                  c.api_key, c.base_url, c.text_model))

                    eval_results = await asyncio.gather(*tasks, return_exceptions=True)

                    all_pass = True
                    advices = []
                    total_score = 0
                    valid_score_count = 0

                    # 🌟 专门用于收集发给前端用户的“打分卡详情”
                    critic_details = []

                    for idx, res in enumerate(eval_results):
                        c_name = critics[idx].provider_name  # 获取对应的副模型名字
                        if isinstance(res, dict):
                            is_pass = res.get("pass", True)
                            score = res.get("score", 0)
                            advice = res.get("advice", "完美解答，无修改意见。")

                            if not is_pass: all_pass = False
                            if advice and advice.strip(): advices.append(f"[{c_name} 的建议]: {advice}")
                            if "score" in res and isinstance(res["score"], (int, float)):
                                total_score += res["score"]
                                valid_score_count += 1

                            # 将每个评委的打分和评语记录下来
                            critic_details.append(f"> - **{c_name}**: 评分 `{score}/100`。*评价: {advice}*")

                    avg_score = (total_score / valid_score_count) if valid_score_count > 0 else 0

                    # 🌟 判断是否进入终局
                    if all_pass or avg_score >= 85 or iteration == 3:
                        if iteration == 3 and not all_pass and avg_score < 85:
                            yield f"data: {json.dumps({'type': 'status', 'content': f'⚠️ 达到最大重试次数 (平均分 {avg_score:.1f})'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'status', 'content': f'✅ 审查通过 (平均分 {avg_score:.1f})'})}\n\n"

                        # 🌟 构建极其优雅的 Markdown 评审报告
                        review_summary = f"> 📊 **多智能体委员会 - 最终评审报告 (综合得分: {avg_score:.1f})**\n>\n"
                        for detail in critic_details:
                            review_summary += f"{detail}\n>\n"
                        review_summary += "> ---\n\n"

                        # 🌟 核心修复：直接把报告拼接在终稿的最前面！
                        # 这样它不仅能一次性丝滑地流式渲染给前端，还会被完美保存在数据库的历史记录里！
                        final_draft = review_summary + draft
                        break

                    # 🌟 未通过：收集建议打回重做
                    else:
                        yield f"data: {json.dumps({'type': 'status', 'content': f'⚠️ 评分仅为 {avg_score:.1f}，正在根据专家意见重写...'})}\n\n"
                        advice_str = "\n".join(advices)
                        current_messages.append({"role": "assistant", "content": draft})
                        current_messages.append({"role": "user",
                                                 "content": f"你的回答未通过审查（综合得分：{avg_score:.1f}）。请严格根据以下专家的批评建议进行彻底重写：\n{advice_str}"})

                # 将最终结果以流的形式平滑展示给用户
                chunk_size = 10
                for i in range(0, len(final_draft), chunk_size):
                    yield f"data: {json.dumps({'type': 'chunk', 'content': final_draft[i:i + chunk_size]})}\n\n"
                    await asyncio.sleep(0.02)

                db.add(Message(session_id=session_id, role="assistant", content=final_draft))
                await db.commit()
                yield f"data: {json.dumps({'type': 'completed', 'content': final_draft})}\n\n"
                return

            # ------------------------------------------
            # ⚔️ 分支 B：圆桌会议模式
            # ------------------------------------------
            elif chat_req.swarm_mode == "roundtable":
                participants = list(chat_req.swarm_nodes)  # 🌟 纯净的参会者列表，不再混入本地模型

                yield f"data: {json.dumps({'type': 'status', 'content': f'🎪 启动圆桌会议 | {len(participants)} 位专家并发思考中...'})}\n\n"

                async def get_node_answer(n):
                    ans = ""
                    async for ev in generate_ai_reply_stream(llm_messages, n.api_key, n.base_url, n.text_model,
                                                                 False, None):
                        if ev["type"] == "text_chunk": ans += ev["data"]
                    return f"【{n.provider_name} 的观点】:\n{ans}"

                tasks = [get_node_answer(node) for node in participants]
                answers = await asyncio.gather(*tasks, return_exceptions=True)
                valid_answers = [a for a in answers if isinstance(a, str)]

                yield f"data: {json.dumps({'type': 'status', 'content': '⚖️ 意见收集完毕，首席主脑正在融合终极答案...'})}\n\n"

                judge = chat_req.swarm_nodes[0]
                synthesis_prompt = f"你是圆桌会议的主席。针对用户的问题，以下是各位专家的意见：\n\n{chr(10).join(valid_answers)}\n\n请你综合各方优缺点，给出一份无可挑剔的最终回答。"
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
        # 🚶 普通模式 (Single Agent)
        # ==========================================
        for iteration in range(3):
            # ... (这部分保持原有的普通单聊逻辑，调用 generate_ai_reply_stream 处理 tool calls 等) ...
            async for event in generate_ai_reply_stream(llm_messages, chat_req.api_key, chat_req.base_url, target_model,
                                                        True, extra_schemas):
                if event["type"] == "text_chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': event['data']})}\n\n"
                elif event["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': event['data']})}\n\n"
                    return
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

                            if t_name == "execute_local_terminal_command":
                                try:
                                    cmd_to_run = json.loads(t_args_str).get("command", "").strip()
                                except:
                                    cmd_to_run = ""
                                SAFE = ("ls", "cat", "pwd", "echo", "whoami", "date", "which")
                                DANGER = ("&&", ";", "|", ">", "<", "`", "$")
                                is_safe = any(cmd_to_run.startswith(p) for p in SAFE) and not any(
                                    c in cmd_to_run for c in DANGER)
                                if not is_safe:
                                    await db.commit()
                                    yield f"data: {json.dumps({'type': 'requires_action', 'name': t_name, 'args': t_args_str})}\n\n"
                                    return

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
                        ai_msg_obj = Message(session_id=session_id, role="assistant", content=ai_message.content)
                        db.add(ai_msg_obj)
                        await db.commit()
                        yield f"data: {json.dumps({'type': 'completed', 'content': ai_message.content})}\n\n"
                        return

    return StreamingResponse(event_generator(), media_type="text/event-stream")