import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── LLMConfig ─────────────────────────────────────────────────────────────────

class LLMConfigCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=1)
    base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


class LLMConfigUpdate(BaseModel):
    display_name: str | None = None
    model: str | None = None
    api_key: str | None = None   # None 表示不修改；空字符串无效
    base_url: str | None = None  # 空字符串清除
    embedding_model: str | None = None
    embedding_dimensions: int | None = None


class LLMConfigOut(BaseModel):
    id: uuid.UUID
    display_name: str
    model: str
    api_key_masked: str
    base_url: str | None
    is_active: bool
    embedding_model: str | None
    embedding_dimensions: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_mask(cls, obj) -> "LLMConfigOut":
        key = obj.api_key
        masked = key[:6] + "****" + key[-4:] if len(key) > 10 else "****"
        return cls(
            id=obj.id,
            display_name=obj.display_name,
            model=obj.model,
            api_key_masked=masked,
            base_url=obj.base_url,
            is_active=obj.is_active,
            embedding_model=obj.embedding_model,
            embedding_dimensions=obj.embedding_dimensions,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )


# ── SystemPrompt ──────────────────────────────────────────────────────────────

class SystemPromptCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)


class SystemPromptUpdate(BaseModel):
    name: str | None = None
    content: str | None = None


class SystemPromptOut(BaseModel):
    id: uuid.UUID
    name: str
    content: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Message ───────────────────────────────────────────────────────────────────

class MessageBase(BaseModel):
    role: str
    content: str | None = None
    tool_calls: dict | None = None
    tool_results: dict | None = None


class MessageCreate(MessageBase):
    session_id: uuid.UUID


class MessageOut(MessageBase):
    id: uuid.UUID
    session_id: uuid.UUID
    token_count: int | None = None
    attachments: list | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    title: str = "新会话"
    system_prompt_id: uuid.UUID | None = None
    meta: dict | None = None
    collab_mode: str | None = None
    collab_config: dict | None = None
    rag_enabled: bool = False


class SessionUpdate(BaseModel):
    title: str | None = None
    system_prompt_id: uuid.UUID | None = None  # 传 None 表示不修改，传 "" 语义上用特殊值
    clear_system_prompt: bool = False           # 显式清除关联
    status: str | None = None
    meta: dict | None = None


class SystemPromptBrief(BaseModel):
    id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: uuid.UUID
    title: str
    system_prompt_id: uuid.UUID | None
    system_prompt_ref: SystemPromptBrief | None = None
    model: str
    status: str
    meta: dict | None
    collab_mode: str | None = None
    collab_config: dict | None = None
    rag_enabled: bool = False
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ── UserTool ──────────────────────────────────────────────────────────────────

class UserToolCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{1,98}$",
                      description="snake_case 函数名，供 LLM 调用")
    display_name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1)
    parameters_schema: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})
    http_url: str = Field(..., min_length=1)
    http_method: str = Field(default="POST", pattern=r"^(GET|POST)$")
    http_headers: dict | None = None


class UserToolUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    parameters_schema: dict | None = None
    http_url: str | None = None
    http_method: str | None = None
    http_headers: dict | None = None
    is_active: bool | None = None


class UserToolOut(BaseModel):
    id: uuid.UUID
    name: str
    display_name: str
    description: str
    parameters_schema: dict
    tool_type: str
    http_url: str | None
    http_method: str
    http_headers: dict | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Collaboration ─────────────────────────────────────────────────────────────

class CollabModelSlot(BaseModel):
    """圆桌模式的模型槽位：指定模型配置 ID 和角色。"""
    config_id: uuid.UUID
    role: str  # proposer | critic | creative | validator | synthesizer


class CollabConfigIn(BaseModel):
    """创建协作会话时传入的配置。"""
    mode: str  # "round_table" | "master_slave"
    rounds: int = Field(default=2, ge=1, le=3)
    # 圆桌模式：按顺序列出所有槽位（最后一个必须是 synthesizer）
    models: list[CollabModelSlot] = Field(default_factory=list)
    # 主从模式
    master_config_id: uuid.UUID | None = None
    reviewer_config_ids: list[uuid.UUID] = Field(default_factory=list)


# ── Chat ──────────────────────────────────────────────────────────────────────

class AttachmentIn(BaseModel):
    filename: str
    mime_type: str
    data: str  # base64 encoded bytes


class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str = Field(..., min_length=1)
    stream: bool = False
    attachments: list[AttachmentIn] = Field(default_factory=list)
    is_retry: bool = False


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    message: MessageOut
    usage: dict | None = None


# ── Knowledge ─────────────────────────────────────────────────────────────────

class KnowledgeDocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeQueryResult(BaseModel):
    filename: str
    content: str
    score: float
