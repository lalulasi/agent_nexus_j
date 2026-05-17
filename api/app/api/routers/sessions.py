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
from app.infrastructure.llm.provider import generate_ai_reply_stream
from app.core.logger import logger
from app.infrastructure.tools.registry import tool_registry
from app.infrastructure.tools.dynamic_api import DynamicAPITool
from openai import AsyncOpenAI  # 引入原生客户端用于标题生成

router = APIRouter(prefix="/sessions", tags=["Agent Sessions"])


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

    async def event_generator():
        target_model = chat_req.text_model
        history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
        history_records = (await db.execute(history_stmt)).scalars().all()
        llm_messages = []

        # 🌟 核心面具注入逻辑：如果前端传了设定，强行插在记忆最前方！
        if chat_req.system_prompt:
            llm_messages.append({"role": "system", "content": chat_req.system_prompt})

        for m in history_records:
            if m.role == "tool":
                llm_messages.append({"role": "user", "content": f"🔧 [历史记录-工具执行结果]:\n{m.content}"})
            else:
                llm_messages.append({"role": m.role, "content": m.content})

        for m in history_records:
            if m.role == "tool":
                llm_messages.append({"role": "user", "content": f"🔧 [历史记录-工具执行结果]:\n{m.content}"})
            else:
                llm_messages.append({"role": m.role, "content": m.content})

        if chat_req.action == "chat" and chat_req.image_base64:
            target_model = chat_req.vision_model or chat_req.text_model
            llm_messages[-1]["content"] = [
                {"type": "text", "text": chat_req.user_input},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}
            ]

        for iteration in range(3):
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