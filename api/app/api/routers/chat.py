import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.application.agent_orchestrator import AgentOrchestrator
from api.app.domain.schemas import ChatRequest, ChatResponse
from api.app.infrastructure.database.models import AgentSession, LLMConfig
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/chat", tags=["chat"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/", response_model=ChatResponse)
async def chat(payload: ChatRequest, db: DB):
    session = await db.get(AgentSession, payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    orchestrator = AgentOrchestrator(db)
    return await orchestrator.run(session, payload.message)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: DB):
    session = await db.get(AgentSession, payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 提前加载激活配置，失败时返回明确的 HTTP 错误（而非在流中途报错）
    result = await db.execute(select(LLMConfig).where(LLMConfig.is_active == True))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=400, detail="尚未配置模型，请先在左侧面板保存模型配置。")

    orchestrator = AgentOrchestrator(db)

    async def event_stream():
        try:
            async for chunk in orchestrator.stream_run(session, payload.message, config):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁止 Nginx 缓冲，确保实时推送
        },
    )
