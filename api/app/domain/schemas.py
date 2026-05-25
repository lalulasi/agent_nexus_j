import uuid
from datetime import datetime

from pydantic import BaseModel, Field


# ── LLMConfig ─────────────────────────────────────────────────────────────────

class LLMConfigCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    model: str = Field(..., min_length=1, max_length=100)
    api_key: str = Field(..., min_length=1)
    base_url: str | None = None


class LLMConfigUpdate(BaseModel):
    display_name: str | None = None
    model: str | None = None
    api_key: str | None = None   # None 表示不修改；空字符串无效
    base_url: str | None = None  # 空字符串清除


class LLMConfigOut(BaseModel):
    id: uuid.UUID
    display_name: str
    model: str
    api_key_masked: str
    base_url: str | None
    is_active: bool
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
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Session ───────────────────────────────────────────────────────────────────

class SessionCreate(BaseModel):
    title: str = "新会话"
    system_prompt_id: uuid.UUID | None = None
    meta: dict | None = None


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
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: uuid.UUID
    message: str = Field(..., min_length=1)
    stream: bool = False


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    message: MessageOut
    usage: dict | None = None
