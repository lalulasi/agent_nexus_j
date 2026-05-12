import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import uuid
from datetime import datetime

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
# 接口 3：终极 Agent 聊天与工具执行循环 (带 HITL 拦截)
# ==========================================
@router.post("/{session_id}/chat", response_model=MessageResponse)
async def chat_with_agent(
        session_id: str,
        chat_req: ChatRequest,
        db: AsyncSession = Depends(get_db)
):
    logger.info(f"Received new Chat request | Session: {session_id} | Action: {chat_req.action}")

    # 1. 验证会话
    stmt = select(AgentSession).where(AgentSession.id == session_id)
    session = (await db.execute(stmt)).scalars().first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 持久化挂载的自定义工具
    if chat_req.custom_tools is not None:
        session.custom_tools = [t.model_dump() for t in chat_req.custom_tools]
        await db.commit()

    # 实例化自定义工具对象
    local_custom_tools = {}
    extra_schemas = []
    if chat_req.custom_tools:
        logger.info(f"Processing {len(chat_req.custom_tools)} dynamic tools for this session.")
        for t_cfg in chat_req.custom_tools:
            dynamic_tool = DynamicAPITool(
                name=t_cfg.name,
                description=t_cfg.description,
                parameters=t_cfg.parameters,
                target_url=t_cfg.url
            )
            local_custom_tools[t_cfg.name] = dynamic_tool
            extra_schemas.append(dynamic_tool.to_openai_schema())

    # ==========================================
    # 2. 根据 Action 路由不同的处理逻辑
    # ==========================================
    if chat_req.action == "chat":
        # 只有在正常的聊天发送时，才保存用户消息
        if chat_req.user_input:
            user_msg = Message(session_id=session_id, role="user", content=chat_req.user_input)
            db.add(user_msg)
            await db.flush()

            # 自动重命名逻辑
            history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
            history_records = (await db.execute(history_stmt)).scalars().all()
            if len(history_records) == 1:
                if not session.title or "新会话" in session.title or "New Session" in session.title:
                    logger.info("侦测到新会话，准备调用大模型生成标题...")
                    try:
                        title_messages = [
                            {"role": "system",
                             "content": "你是一个只输出4到6个字标题的AI。请直接输出标题，绝对不要包含引号或任何标点符号。"},
                            {"role": "user", "content": f"根据以下内容生成一个简短标题：{chat_req.user_input}"}
                        ]
                        title_reply = await generate_ai_reply(
                            messages_history=title_messages,
                            api_key=chat_req.api_key,
                            base_url=chat_req.base_url,
                            model_name=chat_req.text_model,
                            enable_tools=False,
                            extra_tool_schemas=None
                        )
                        session.title = title_reply.content.strip(' \n\r"“”。')
                        db.add(session)
                        await db.commit()
                        await db.refresh(session)
                    except Exception as e:
                        logger.error(f"❌ 自动命名失败: {str(e)}")

    elif chat_req.action == "approve_tool":
        logger.info(f"👍 用户已授权执行高危工具: {chat_req.pending_tool_name}")
        tool_instance = local_custom_tools.get(chat_req.pending_tool_name) or tool_registry.get_tool(
            chat_req.pending_tool_name)
        try:
            args_dict = json.loads(chat_req.pending_tool_args) if chat_req.pending_tool_args else {}
            result = await tool_instance.execute(**args_dict)
        except Exception as e:
            result = f"Error executing approved tool: {str(e)}"

        # 🌟 核心修复 1：不再使用 role="tool"，伪装成 user 汇报给大模型，避开严格的 ID 校验
        msg_content = f"👉 [系统汇报] 您刚才申请的终端命令已获用户批准并执行完毕。\n执行结果:\n{result}"
        tool_msg = Message(session_id=session_id, role="user", content=msg_content)
        db.add(tool_msg)
        await db.flush()

    elif chat_req.action == "reject_tool":
        logger.warning(f"🚫 用户拒绝了高危工具的执行: {chat_req.pending_tool_name}")
        # 🌟 同理，改用 user 汇报
        msg_content = "🚫 [系统汇报] 用户出于安全原因拒绝了该终端命令。请结合现有信息直接回复，或提供其他方案。"
        reject_msg = Message(session_id=session_id, role="user", content=msg_content)
        db.add(reject_msg)
        await db.flush()

    # ==========================================
    # 3. 提取历史记录并准备 LLM 轮询
    # ==========================================
    history_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    history_records = (await db.execute(history_stmt)).scalars().all()
    llm_messages = []

    for m in history_records:
        # 🌟 核心修复 2：将历史遗留的 role="tool" 全部降维扁平化为 user 消息
        if m.role == "tool":
            llm_messages.append({"role": "user", "content": f"🔧 [历史记录-工具执行结果]:\n{m.content}"})
        else:
            llm_messages.append({"role": m.role, "content": m.content})

    # 视觉模型拦截
    target_model = chat_req.text_model
    if chat_req.action == "chat" and chat_req.image_base64:
        if not chat_req.vision_model:
            raise HTTPException(status_code=400, detail="您上传了图片，但未配置多模态视觉模型！")
        target_model = chat_req.vision_model
        llm_messages[-1]["content"] = [
            {"type": "text", "text": chat_req.user_input},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{chat_req.image_base64}"}}
        ]

    # ==========================================
    # 4. Agent 思考执行大循环
    # ==========================================
    MAX_ITERATIONS = 3
    for iteration in range(MAX_ITERATIONS):
        logger.info(f"Starting Agent Loop Iteration: {iteration + 1}")

        try:
            ai_message = await generate_ai_reply(
                messages_history=llm_messages,
                api_key=chat_req.api_key,
                base_url=chat_req.base_url,
                model_name=target_model,
                enable_tools=True,
                extra_tool_schemas=extra_schemas
            )
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

        if ai_message.tool_calls:
            logger.warning(f"LLM decided to call {len(ai_message.tool_calls)} tool(s).")

            # 将大模型的调用意图存入上下文，方便继续推演
            llm_messages.append(ai_message.model_dump(exclude_unset=True))

            # 存入数据库，防止刷新页面时丢失“思考过程”
            tool_names = ", ".join([tc.function.name for tc in ai_message.tool_calls])
            ai_msg_db = Message(session_id=session_id, role="assistant",
                                content=ai_message.content or f"[思考中... 准备调用工具: {tool_names}]")
            db.add(ai_msg_db)
            await db.flush()

            for tool_call in ai_message.tool_calls:
                t_name = tool_call.function.name
                t_args_str = tool_call.function.arguments

                # 🚨 高危预警拦截！紧急刹车返回前端
                if t_name == "execute_local_terminal_command":
                    try:
                        args_dict = json.loads(t_args_str)
                        cmd_to_run = args_dict.get("command", "").strip()
                    except Exception:
                        cmd_to_run = ""

                        # 1. 定义绝对安全的命令前缀
                    SAFE_PREFIXES = ("ls", "cat", "pwd", "echo", "whoami", "date", "which")

                    # 2. 定义危险连接符（防止命令注入，例如 ls && rm -rf /）
                    DANGEROUS_CHARS = ("&&", ";", "|", ">", "<", "`", "$")

                    # 3. 智能判断逻辑
                    is_safe = False
                    if any(cmd_to_run.startswith(prefix) for prefix in SAFE_PREFIXES):
                        if not any(char in cmd_to_run for char in DANGEROUS_CHARS):
                            is_safe = True

                    if not is_safe:
                        logger.critical(f"⚠️ 拦截到非白名单或含有危险字符的动作: {cmd_to_run}")
                        await db.commit()
                        return MessageResponse(
                            id=str(uuid.uuid4()),
                            session_id=session_id,
                            role="assistant",
                            content="Agent 申请执行敏感终端命令，等待授权。",
                            created_at=datetime.utcnow(),
                            status="requires_action",
                            pending_action={"name": t_name, "args": t_args_str}
                        )
                    else:
                        logger.success(f"🟢 触发白名单，自动放行安全命令: {cmd_to_run}")

                    logger.critical(f"⚠️ 拦截到高危动作请求: {t_args_str}")
                    await db.commit()
                    return MessageResponse(
                        id=str(uuid.uuid4()),  # 🌟 补齐所需字段
                        session_id=session_id,
                        role="assistant",  # 🌟 补齐所需字段
                        content="Agent 申请执行高危终端命令。",  # 🌟 改成了 content
                        created_at=datetime.utcnow(),  # 🌟 补齐所需字段
                        status="requires_action",
                        pending_action={"name": t_name, "args": t_args_str}
                    )

                # 普通工具，直接执行
                logger.debug(f"Preparing to execute tool: '{t_name}'")
                try:
                    t_args = json.loads(t_args_str) if t_args_str else {}
                    tool_instance = local_custom_tools.get(t_name) or tool_registry.get_tool(t_name)
                    if not tool_instance:
                        raise ValueError(f"Tool '{t_name}' not found.")
                    t_result = await tool_instance.execute(**t_args)
                except Exception as e:
                    t_result = f"Error: {str(e)}"

                    # 🌟 核心修复 3：存入数据库时用 user 扁平化存储
                tool_msg_db = Message(session_id=session_id, role="user",
                                          content=f"🔧 [系统汇报: 工具 {t_name} 执行结果]\n{t_result}")
                db.add(tool_msg_db)
                await db.flush()

                # 🌟 极其重要：当前请求的内存中，仍然保持严格的 tool 格式喂给大模型！
                llm_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,  # 这里必须有！
                    "name": t_name,
                    "content": str(t_result)
                })

            logger.info("Tool results injected. Re-prompting LLM...")
            continue

        else:
            final_content = ai_message.content
            logger.info("Agent loop finished. Final text generated.")

            ai_msg = Message(session_id=session_id, role="assistant", content=final_content)
            db.add(ai_msg)
            await db.commit()
            await db.refresh(ai_msg)  # 🌟 刷新以获取数据库自动生成的 id 和 created_at

            return MessageResponse(
                id=ai_msg.id,  # 🌟 从数据库对象提取
                session_id=session_id,
                role=ai_msg.role,  # 🌟 从数据库对象提取
                content=ai_msg.content or "Done.",  # 🌟 从数据库对象提取
                created_at=ai_msg.created_at,  # 🌟 从数据库对象提取
                status="completed"
            )

    logger.error("Agent reached maximum iterations.")
    raise HTTPException(status_code=500, detail="Agent thinking timeout.")