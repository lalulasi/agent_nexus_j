import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

# 引入你的数据模型、配置和日志
from app.infrastructure.database.session import get_db
from app.infrastructure.database.models import AgentSession
# 导入 Pydantic 校验模型
from app.domain.schemas import SessionCreate, SessionResponse, ChatRequest
from app.infrastructure.database.models import AgentSession, Message
from app.domain.schemas import SessionCreate, SessionResponse, MessageCreate, MessageResponse
from app.infrastructure.llm.provider import generate_ai_reply
from app.core.logger import logger
from app.infrastructure.tools.registry import tool_registry
from app.infrastructure.tools.dynamic_api import DynamicAPITool

router = APIRouter(prefix="/sessions", tags=["Agent Sessions"])

@router.post("/", response_model=SessionResponse)
async def create_session(
        session_in: SessionCreate,
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"Creating new session | Provider: {session_in.model_provider}")
    new_session = AgentSession(
        title=session_in.title,
        model_provider=session_in.model_provider
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return new_session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session_title(
        session_id: str,
        title: str,  # 直接接收新标题
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"Updating title for session {session_id} to: {title}")
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.title = title
    await db.commit()
    await db.refresh(session)
    return session

# ==========================================
# 接口：删除会话（连同消息一起删除）
# ==========================================
@router.delete("/{session_id}")
async def delete_session(
        session_id: str,
        db: AsyncSession = Depends(get_db)
):
    logger.warning(f"Deleting session {session_id}")
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await db.delete(session)
    await db.commit()
    return {"message": "Session deleted successfully"}

# ==========================================
# 接口：获取所有历史会话列表 (用于侧边栏展示)
# ==========================================
@router.get("/", response_model=list[SessionResponse])
async def list_all_sessions(
    db: AsyncSession = Depends(get_db)
):
    logger.info("Fetching all historical sessions from database.")
    # 按更新时间倒序排列，最新的排在最前面
    stmt = select(AgentSession).order_by(AgentSession.updated_at.desc())
    records = (await db.execute(stmt)).scalars().all()
    logger.debug(f"Retrieved {len(records)} sessions.")
    return records

# ==========================================
# 接口 2：获取会话的历史消息
# ==========================================
@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_messages(
        session_id: str,
        db: AsyncSession = Depends(get_db)
):
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    records = (await db.execute(stmt)).scalars().all()
    return records


# ==========================================
# 接口 3：终极 Agent 聊天与工具执行循环
# ==========================================
@router.post("/{session_id}/chat", response_model=MessageResponse)
async def chat_with_agent(
        session_id: str,
        chat_req: ChatRequest,
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"Received new Chat request | Session: {session_id}")

    # 1. 验证会话并保存用户消息
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user_msg = Message(session_id=session_id, role="user", content=chat_req.user_input)
    db.add(user_msg)
    await db.flush()

    # 2. 提取并组装历史记录
    history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    history_records = (await db.execute(history_stmt)).scalars().all()
    llm_messages = [{"role": m.role, "content": m.content} for m in history_records]

    local_custom_tools = {}
    extra_schemas = []
    if chat_req.custom_tools:
        logger.info(f"Processing {len(chat_req.custom_tools)} dynamic tools for this session.")
        for t_cfg in chat_req.custom_tools:
            # 實例化萬能適配器
            dynamic_tool = DynamicAPITool(
                name=t_cfg.name,
                description=t_cfg.description,
                parameters=t_cfg.parameters,
                target_url=t_cfg.url
            )
            local_custom_tools[t_cfg.name] = dynamic_tool
            extra_schemas.append(dynamic_tool.to_openai_schema())
    # 3. 智能多模态路由
    if chat_req.image_base64:
        logger.info("Vision payload detected. Routing to vision model.")
        if not chat_req.vision_model:
            raise HTTPException(status_code=400, detail="您上传了图片，但未配置多模态视觉模型！")
        target_model = chat_req.vision_model
        llm_messages[-1]["content"] = [
            {"type": "text", "text": chat_req.user_input},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}
        ]
    else:
        target_model = chat_req.text_model

    # 4. 🧠 The Agent Execution Loop
    MAX_ITERATIONS = 3

    for iteration in range(MAX_ITERATIONS):
        logger.info(f"Starting Agent Loop Iteration: {iteration + 1}")

        try:
            ai_message = await generate_ai_reply(
                messages_history=llm_messages,
                api_key=chat_req.api_key,
                base_url=chat_req.base_url,
                model_name=target_model,
                enable_tools=True
            )
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

        # 【场景 A：大模型决定调用工具】
        if ai_message.tool_calls:
            logger.warning(f"LLM decided to call {len(ai_message.tool_calls)} tool(s).")

            # 记录大模型的调用意图
            llm_messages.append(ai_message.model_dump(exclude_unset=True))

            # 执行工具
            for tool_call in ai_message.tool_calls:
                t_name = tool_call.function.name
                t_args_str = tool_call.function.arguments
                t_id = tool_call.id

                logger.debug(f"Preparing to execute tool: '{t_name}' | Args: {t_args_str}")

                try:
                    t_args = json.loads(t_args_str) if t_args_str else {}
                    tool_instance = tool_registry.get_tool(t_name)

                    if not tool_instance:
                        raise ValueError(f"Tool '{t_name}' not found in local registry.")

                    t_result = await tool_instance.execute(**t_args)
                    logger.success(f"Tool '{t_name}' executed successfully.")

                except Exception as e:
                    logger.error(f"Tool execution failed: {str(e)}")
                    t_result = f"Error executing tool: {str(e)}"

                # 将工具执行结果喂回给大模型
                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": t_id,
                    "name": t_name,
                    "content": str(t_result)
                })

            logger.info("Tool results injected. Re-prompting LLM...")
            continue

        # 【场景 B：最终回复】
        else:
            final_content = ai_message.content
            logger.info("Agent loop finished. Final text generated.")

            ai_msg = Message(session_id=session_id, role="assistant", content=final_content)
            db.add(ai_msg)
            await db.commit()
            await db.refresh(ai_msg)

            return ai_msg

    logger.error("Agent reached maximum iterations.")
    raise HTTPException(status_code=500, detail="Agent thinking timeout.")