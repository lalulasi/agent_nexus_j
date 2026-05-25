import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.app.core.logger import logger
from api.app.domain.schemas import UserToolCreate, UserToolOut, UserToolUpdate
from api.app.infrastructure.database.models import UserTool
from api.app.infrastructure.database.session import get_db

router = APIRouter(prefix="/tools", tags=["tools"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("/", response_model=list[UserToolOut])
async def list_tools(db: DB):
    result = await db.execute(
        select(UserTool).order_by(UserTool.tool_type, UserTool.display_name)
    )
    return result.scalars().all()


@router.post("/", response_model=UserToolOut, status_code=status.HTTP_201_CREATED)
async def create_tool(payload: UserToolCreate, db: DB):
    existing = await db.execute(select(UserTool).where(UserTool.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"工具名 '{payload.name}' 已存在")
    tool = UserTool(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        parameters_schema=payload.parameters_schema,
        tool_type="http",
        http_url=payload.http_url,
        http_method=payload.http_method,
        http_headers=payload.http_headers,
        is_active=True,
    )
    db.add(tool)
    await db.flush()
    await db.refresh(tool)
    logger.info(f"新增 HTTP 工具：{tool.name} → {tool.http_url}")
    return tool


@router.patch("/{tool_id}", response_model=UserToolOut)
async def update_tool(tool_id: uuid.UUID, payload: UserToolUpdate, db: DB):
    tool = await db.get(UserTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")

    for field in ("display_name", "description", "parameters_schema",
                  "http_url", "http_method", "http_headers", "is_active"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(tool, field, val)

    await db.flush()
    await db.refresh(tool)
    logger.info(f"更新工具：{tool.name}")
    return tool


@router.patch("/{tool_id}/toggle", response_model=UserToolOut)
async def toggle_tool(tool_id: uuid.UUID, db: DB):
    tool = await db.get(UserTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    tool.is_active = not tool.is_active
    await db.flush()
    await db.refresh(tool)
    logger.info(f"工具 '{tool.name}' 已{'启用' if tool.is_active else '禁用'}")
    return tool


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(tool_id: uuid.UUID, db: DB):
    tool = await db.get(UserTool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="工具不存在")
    if tool.tool_type == "builtin":
        raise HTTPException(status_code=400, detail="内置工具不可删除，只能禁用。")
    await db.delete(tool)
    logger.info(f"删除工具：{tool_id}")
