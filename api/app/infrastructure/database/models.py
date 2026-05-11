import uuid
from datetime import datetime
from typing import List

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, DateTime, func, ForeignKey, Text, Column, JSON


# 1. 声明基类
class Base(DeclarativeBase):
    pass


# 2. Agent 会话模型 (更新关联关系)
class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New Conversation")
    model_provider: Mapped[str] = mapped_column(String, nullable=True, default="deepseek")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    # 【新增】ORM 关联：一个 Session 对应多条 Message。级联删除保证删会话时，记录也一并清空。
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    custom_tools = Column(JSON, default=list)

# 3. 【新增】聊天记录模型
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()), index=True)

    # 外键：关联到 agent_sessions 表的 id
    session_id: Mapped[str] = mapped_column(ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True)

    # 角色 (例如: user, assistant, system)
    role: Mapped[str] = mapped_column(String, nullable=False)

    # 消息正文 (使用 Text 应对大段对话内容)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ORM 关联：多条 Message 属于一个 Session
    session: Mapped["AgentSession"] = relationship("AgentSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, title={self.title})>"