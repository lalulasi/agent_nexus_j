from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
# 导入数据库依赖和模型
from app.infrastructure.database.session import get_db
from app.infrastructure.database.models import AgentSession
# 导入 Pydantic 校验模型
from app.domain.schemas import SessionCreate, SessionResponse, ChatRequest
from app.infrastructure.database.models import AgentSession, Message
from app.domain.schemas import SessionCreate, SessionResponse, MessageCreate, MessageResponse
from app.infrastructure.llm.provider import generate_ai_reply
from app.core.logger import logger # 引入 logger

router = APIRouter(prefix="/sessions", tags=["Agent Sessions"])

@router.post("/", response_model=SessionResponse)
async def create_session(
        session_in: SessionCreate,
        db: AsyncSession = Depends(get_db)
):
    """
    创建一个新的 Agent 会话
    """
    # 1. 实例化数据库模型
    new_session = AgentSession(
        title=session_in.title,
        model_provider=session_in.model_provider
    )

    # 2. 写入数据库
    db.add(new_session)
    await db.commit()  # 提交事务
    await db.refresh(new_session)  # 刷新对象，获取数据库自动生成的 id 和 created_at

    # 3. 返回数据（FastAPI 会自动将其转换为 SessionResponse 格式）
    return new_session

@router.get("/", response_model=list[SessionResponse])
async def list_sessions(
        limit: int = 10,
        db: AsyncSession = Depends(get_db)
):
    """
    获取最近的会话列表
    """
    # 异步查询所有会话，按时间倒序排列
    stmt = select(AgentSession).order_by(AgentSession.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return sessions

@router.post("/{session_id}/messages", response_model=MessageResponse)
async def create_message(
        session_id: str,
        message_in: MessageCreate,
        db: AsyncSession = Depends(get_db)
):
    """
    向指定的会话中发送一条新消息
    """
    # 1. 先校验会话存不存在
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    result = await db.execute(stmt)
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. 创建并保存消息
    new_message = Message(
        session_id=session_id,
        role=message_in.role,
        content=message_in.content
    )
    db.add(new_message)
    await db.commit()
    await db.refresh(new_message)

    return new_message

@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
        session_id: str,
        db: AsyncSession = Depends(get_db)
):
    """
    获取某个会话下的所有历史聊天记录（按时间正序）
    """
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    result = await db.execute(stmt)
    messages = result.scalars().all()

    return messages


@router.post("/{session_id}/chat", response_model=MessageResponse)
async def chat_with_agent(
        session_id: str,
        chat_req: ChatRequest,
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"📥 收到新的 Chat 请求 | Session ID: {session_id}")
    logger.debug(f"用户输入: {chat_req.user_input}")
    # 1. 获取会话与保存用户消息
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = Message(session_id=session_id, role="user", content=chat_req.user_input)
    db.add(user_msg)
    await db.flush()

    # 2. 提取历史记录
    history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    history_records = (await db.execute(history_stmt)).scalars().all()
    llm_messages = [{"role": m.role, "content": m.content} for m in history_records]

    # 3. 核心大招：智能多模态路由判断！
    if chat_req.image_base64:
        logger.warning("👁️ 侦测到图片 Payload，准备进行多模态视觉路由拦截！")
        if not chat_req.vision_model:
            logger.error("❌ 路由失败：用户未配置视觉模型")
            raise HTTPException(status_code=400, detail="您上传了图片，但未配置多模态视觉模型！")

        target_model = chat_req.vision_model  # 触发图片，自动切换到视觉模型
        logger.info(f"🔄 模型路由已切换至视觉模型: {target_model}")
        llm_messages[-1]["content"] = [
            {"type": "text", "text": chat_req.user_input},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}
        ]
    else:
        target_model = chat_req.text_model  # 纯文字，使用基础模型
        logger.info(f"💬 纯文本模式，使用基础模型: {target_model}")
    # 4. 调用极简 BYOK 引擎
    try:
        logger.info("🧠 正在呼叫大模型引擎...")
        ai_content = await generate_ai_reply(
            messages_history=llm_messages,
            api_key=chat_req.api_key,
            base_url=chat_req.base_url,
            model_name=target_model
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

    # 5. 保存并返回
    ai_msg = Message(session_id=session_id, role="assistant", content=ai_content)
    db.add(ai_msg)
    await db.commit()
    await db.refresh(ai_msg)
    logger.success("✅ AI 回复已成功入库并返回！")
    return ai_msg