import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LLMConfig(Base):
    """用户保存的大语言模型接入配置，is_active=True 为当前默认配置。"""

    __tablename__ = "llm_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    thinking_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8000)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SystemPrompt(Base):
    """可复用的 System Prompt 库，与模型无关，按需分配给会话。"""

    __tablename__ = "system_prompts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="新会话")
    system_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("system_prompts.id", ondelete="SET NULL"),
        nullable=True,
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    collab_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)   # None | "master_slave" | "round_table"
    collab_config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    rag_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    system_prompt_ref: Mapped["SystemPrompt | None"] = relationship("SystemPrompt", lazy="selectin")


class UserTool(Base):
    """用户管理的工具表：内置工具（builtin）和自定义 HTTP 工具（http）。"""

    __tablename__ = "user_tools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_schema: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tool_type: Mapped[str] = mapped_column(String(20), nullable=False, default="http")  # builtin | http
    http_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    http_method: Mapped[str] = mapped_column(String(10), nullable=False, default="POST")
    http_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tool_results: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AgentSession"] = relationship("AgentSession", back_populates="messages")


class MCPServer(Base):
    """用户注册的 MCP Agent Server，可提供工具或作为对话 Agent 参与协作。"""

    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False)
    auth_header: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="tool_provider")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    discovered_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SearchConfig(Base):
    """搜索引擎配置，支持 DuckDuckGo（免费无 Key）、Tavily、Serper.dev。全局仅保留一条激活配置。"""

    __tablename__ = "search_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="ddgs")  # ddgs | tavily | serper
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_results: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeDocument(Base):
    """全局知识库文档，与会话无关。"""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="document", cascade="all, delete-orphan", lazy="selectin"
    )


class KnowledgeChunk(Base):
    """文档切片，存储原文及向量嵌入。"""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["KnowledgeDocument"] = relationship("KnowledgeDocument", back_populates="chunks")
