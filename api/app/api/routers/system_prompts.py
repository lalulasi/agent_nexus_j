import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.domain.schemas import SystemPromptCreate, SystemPromptOut, SystemPromptUpdate
from api.app.infrastructure.database.models import SystemPrompt
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/system-prompts", tags=["system-prompts"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[SystemPromptOut])
async def list_prompts(db: DB):
    result = await db.execute(select(SystemPrompt).order_by(SystemPrompt.updated_at.desc()))
    return result.scalars().all()


@router.post("/", response_model=SystemPromptOut, status_code=status.HTTP_201_CREATED)
async def create_prompt(payload: SystemPromptCreate, db: DB):
    prompt = SystemPrompt(**payload.model_dump())
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)
    logger.info(f"创建 System Prompt：{prompt.name}")
    return prompt


@router.patch("/{prompt_id}", response_model=SystemPromptOut)
async def update_prompt(prompt_id: uuid.UUID, payload: SystemPromptUpdate, db: DB):
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="System Prompt 不存在")
    if payload.name is not None:
        prompt.name = payload.name
    if payload.content is not None:
        prompt.content = payload.content
    await db.flush()
    await db.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt(prompt_id: uuid.UUID, db: DB):
    prompt = await db.get(SystemPrompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="System Prompt 不存在")
    await db.delete(prompt)
    logger.info(f"删除 System Prompt：{prompt.name}")
