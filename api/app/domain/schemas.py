from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any

class CustomAPIToolConfig(BaseModel):
    name: str = Field(..., description="工具名称 (英文，如 get_weather)")
    description: str = Field(..., description="工具描述，告诉 AI 何时使用")
    url: str = Field(..., description="API 目标地址 (POST请求)")
    parameters: Dict[str, Any] = Field(..., description="OpenAI 格式的 JSON Schema")

class SessionCreate(BaseModel):
    title: str = Field(default="New Conversation", description="会话的初始标题")
    model_provider: Optional[str] = Field(default="deepseek", description="选用的 AI 模型")

class SessionResponse(BaseModel):
    id: str
    title: str
    model_provider: Optional[str]
    created_at: datetime
    updated_at: datetime
    custom_tools: Optional[List[Any]] = []
    model_config = ConfigDict(from_attributes=True)

class MessageCreate(BaseModel):
    role: str = Field(..., description="角色：user, assistant, system")
    content: str = Field(..., description="消息文本内容")

class ChatRequest(BaseModel):
    # 🌟 核心修复 2：将 user_input 改为可选字段，默认值为 None！
    user_input: Optional[str] = None
    image_base64: Optional[str] = None

    api_key: str
    base_url: str
    text_model: str
    vision_model: Optional[str] = None
    custom_tools: Optional[List[CustomAPIToolConfig]] = Field(default_factory=list)

    action: str = "chat"
    pending_tool_name: Optional[str] = None
    pending_tool_args: Optional[str] = None

class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime
    status: str = "completed"
    pending_action: Optional[Dict[str, Any]] = None
    model_config = ConfigDict(from_attributes=True)