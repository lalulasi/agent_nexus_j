import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.application.agent_orchestrator import AgentOrchestrator
from api.app.application.collaboration_orchestrator import CollaborationOrchestrator
from api.app.domain.schemas import ChatRequest, ChatResponse
from api.app.infrastructure.database.models import AgentSession, LLMConfig, Message
from api.app.infrastructure.database.session import get_db
from api.app.infrastructure.files.processor import process_attachment

router = APIRouter(prefix="/chat", tags=["chat"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: DB):
    session = await db.get(AgentSession, payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if session.collab_mode:
        raise HTTPException(status_code=400, detail="协作会话请使用流式接口 /chat/stream")

    orchestrator = AgentOrchestrator(db)
    return await orchestrator.run(session, payload.message)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: DB):
    session = await db.get(AgentSession, payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # ── 协作模式：路由到 CollaborationOrchestrator ─────────────────────────────
    if session.collab_mode:
        collab = CollaborationOrchestrator(db)

        async def collab_event_stream():
            try:
                async for chunk in collab.stream_run(session, payload.message):
                    yield f"data: {chunk}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            finally:
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            collab_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── 普通模式 ───────────────────────────────────────────────────────────────
    result = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="尚未配置模型，请先在左侧面板保存模型配置。")

    # 重试：先删除上一条 assistant 消息，并刷新 session.messages
    if payload.is_retry:
        del_result = await db.execute(
            select(Message)
            .where(Message.session_id == payload.session_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_asst = del_result.scalar_one_or_none()
        if last_asst:
            await db.delete(last_asst)
            await db.flush()
        await db.refresh(session, ["messages"])

    processed_attachments = [
        process_attachment(a.filename, a.mime_type, a.data)
        for a in payload.attachments
    ]

    orchestrator = AgentOrchestrator(db)

    async def event_stream():
        try:
            async for chunk in orchestrator.stream_run(
                session, payload.message, config, processed_attachments,
                is_retry=payload.is_retry,
            ):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
