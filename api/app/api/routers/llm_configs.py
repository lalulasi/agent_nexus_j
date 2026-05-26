import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.domain.schemas import LLMConfigCreate, LLMConfigOut, LLMConfigUpdate
from api.app.infrastructure.database.models import LLMConfig
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/llm-configs", tags=["llm-configs"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[LLMConfigOut])
async def list_configs(db: DB):
    result = await db.execute(
        select(LLMConfig).order_by(LLMConfig.updated_at.desc())
    )
    configs = result.scalars().all()
    return [LLMConfigOut.from_orm_mask(c) for c in configs]


@router.get("/active", response_model=LLMConfigOut)
async def get_active_config(db: DB):
    result = await db.execute(
        select(LLMConfig).where(LLMConfig.is_active == True)
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="暂无激活的模型配置")
    return LLMConfigOut.from_orm_mask(config)


@router.post("/", response_model=LLMConfigOut, status_code=status.HTTP_201_CREATED)
async def save_config(payload: LLMConfigCreate, db: DB):
    # 将所有现有配置设为非激活
    await db.execute(update(LLMConfig).values(is_active=False))

    config = LLMConfig(**payload.model_dump(), is_active=True)
    db.add(config)
    await db.flush()
    await db.refresh(config)
    logger.info(f"已保存并激活模型配置: {config.display_name} ({config.model})")
    return LLMConfigOut.from_orm_mask(config)


@router.post("/{config_id}/activate", response_model=LLMConfigOut)
async def activate_config(config_id: uuid.UUID, db: DB):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")

    await db.execute(update(LLMConfig).values(is_active=False))
    config.is_active = True
    await db.flush()
    await db.refresh(config)
    logger.info(f"已切换激活配置: {config.display_name}")
    return LLMConfigOut.from_orm_mask(config)


@router.patch("/{config_id}", response_model=LLMConfigOut)
async def update_config(config_id: uuid.UUID, payload: LLMConfigUpdate, db: DB):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    if payload.display_name is not None:
        config.display_name = payload.display_name
    if payload.model is not None:
        config.model = payload.model
    if payload.api_key is not None and payload.api_key.strip():
        config.api_key = payload.api_key
    if payload.base_url is not None:
        config.base_url = payload.base_url or None      # 空字符串清除
    if payload.embedding_model is not None:
        config.embedding_model = payload.embedding_model or None
    if payload.embedding_dimensions is not None:
        config.embedding_dimensions = payload.embedding_dimensions or None  # 0 清除
    await db.flush()
    await db.refresh(config)
    logger.info(f"已更新模型配置: {config.display_name}")
    return LLMConfigOut.from_orm_mask(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(config_id: uuid.UUID, db: DB):
    config = await db.get(LLMConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="配置不存在")
    if config.is_active:
        raise HTTPException(status_code=400, detail="不能删除当前激活的配置，请先切换到其他配置")
    await db.delete(config)
    logger.info(f"已删除模型配置: {config_id}")
