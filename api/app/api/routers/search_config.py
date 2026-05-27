import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.domain.schemas import SearchConfigCreate, SearchConfigOut, SearchConfigUpdate
from api.app.infrastructure.database.models import SearchConfig
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/search-config", tags=["search-config"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[SearchConfigOut])
async def list_search_configs(db: DB):
    result = await db.execute(select(SearchConfig).order_by(SearchConfig.created_at))
    return [SearchConfigOut.from_orm_mask(r) for r in result.scalars().all()]


@router.post("/", response_model=SearchConfigOut, status_code=status.HTTP_201_CREATED)
async def create_search_config(payload: SearchConfigCreate, db: DB):
    if payload.provider in ("tavily", "serper") and not payload.api_key:
        raise HTTPException(
            status_code=422,
            detail=f"{payload.provider} 需要配置 API Key",
        )
    config = SearchConfig(
        provider=payload.provider,
        api_key=payload.api_key or None,
        max_results=payload.max_results,
        is_active=False,
    )
    db.add(config)
    await db.flush()
    await db.refresh(config)
    logger.info(f"新增搜索配置：{config.provider} (id={config.id})")
    return SearchConfigOut.from_orm_mask(config)


@router.post("/{config_id}/activate", response_model=SearchConfigOut)
async def activate_search_config(config_id: uuid.UUID, db: DB):
    config = await db.get(SearchConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="搜索配置不存在")
    # 先将其他配置设为未激活
    result = await db.execute(
        select(SearchConfig).where(SearchConfig.is_active == True, SearchConfig.id != config_id)
    )
    for other in result.scalars().all():
        other.is_active = False
    config.is_active = True
    await db.flush()
    await db.refresh(config)
    logger.info(f"激活搜索配置：{config.provider} (id={config.id})")
    return SearchConfigOut.from_orm_mask(config)


@router.patch("/{config_id}", response_model=SearchConfigOut)
async def update_search_config(config_id: uuid.UUID, payload: SearchConfigUpdate, db: DB):
    config = await db.get(SearchConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="搜索配置不存在")

    if payload.provider is not None:
        config.provider = payload.provider
    if payload.api_key is not None:
        config.api_key = payload.api_key or None
    if payload.max_results is not None:
        config.max_results = payload.max_results

    await db.flush()
    await db.refresh(config)
    logger.info(f"更新搜索配置：{config.provider} (id={config.id})")
    return SearchConfigOut.from_orm_mask(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_config(config_id: uuid.UUID, db: DB):
    config = await db.get(SearchConfig, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="搜索配置不存在")
    await db.delete(config)
    logger.info(f"删除搜索配置：{config_id}")
