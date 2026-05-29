import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.domain.schemas import SessionCreate, SessionOut, SessionUpdate
from api.app.infrastructure.database.models import AgentSession
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/sessions", tags=["sessions"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[SessionOut])
async def list_sessions(db: DB, limit: int = 50, offset: int = 0):
    result = await db.execute(
        select(AgentSession).order_by(AgentSession.updated_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.post("/", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(payload: SessionCreate, db: DB):
    # "auto" = 创新点2占位：智能路由，当前 fallback 到普通模式
    if payload.collab_mode and payload.collab_mode not in ("round_table", "master_slave", "auto"):
        raise HTTPException(status_code=400, detail="collab_mode 必须是 round_table 或 master_slave")

    session = AgentSession(
        title=payload.title,
        system_prompt_id=payload.system_prompt_id,
        meta=payload.meta,
        collab_mode=payload.collab_mode,
        collab_config=payload.collab_config,
        rag_enabled=payload.rag_enabled,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    logger.info(
        f"创建会话 {session.id}，collab_mode={session.collab_mode}，SP={session.system_prompt_id}"
    )
    return session


@router.get("/{session_id}", response_model=SessionOut)
async def get_session(session_id: uuid.UUID, db: DB):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


@router.patch("/{session_id}", response_model=SessionOut)
async def update_session(session_id: uuid.UUID, payload: SessionUpdate, db: DB):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    if payload.title is not None:
        session.title = payload.title
    if payload.status is not None:
        session.status = payload.status
    if payload.meta is not None:
        session.meta = payload.meta
    if payload.clear_system_prompt:
        session.system_prompt_id = None
    elif payload.system_prompt_id is not None:
        session.system_prompt_id = payload.system_prompt_id
    if payload.collab_config is not None:
        session.collab_config = payload.collab_config

    await db.flush()
    await db.refresh(session)
    return session


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: uuid.UUID, db: DB):
    session = await db.get(AgentSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    await db.delete(session)
    logger.info(f"删除会话 {session_id}")
