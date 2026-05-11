from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from typing import Optional, List, Dict, Any

# 1. 新增：用户自定义工具的数据模型
class CustomAPIToolConfig(BaseModel):
    name: str = Field(..., description="工具名称 (英文，如 get_weather)")
    description: str = Field(..., description="工具描述，告诉 AI 何时使用")
    url: str = Field(..., description="API 目标地址 (POST请求)")
    parameters: Dict[str, Any] = Field(..., description="OpenAI 格式的 JSON Schema")

# ==========================================
# 1. 接收用户请求的模型 (Request Schema)
# ==========================================
class SessionCreate(BaseModel):
    """创建新会话时，用户允许传入的字段"""
    title: str = Field(default="New Conversation", description="会话的初始标题")
    model_provider: Optional[str] = Field(default="deepseek", description="选用的 AI 模型")

# ==========================================
# 2. 返回给用户的模型 (Response Schema)
# ==========================================
class SessionResponse(BaseModel):
    """接口返回给前端的完整会话信息"""
    id: str
    title: str
    model_provider: Optional[str]
    created_at: datetime
    updated_at: datetime

    # 关键配置：允许 Pydantic 直接读取 SQLAlchemy 模型对象
    model_config = ConfigDict(from_attributes=True)

# ==========================================
# 3. 创建消息时的请求模型
# ==========================================
class MessageCreate(BaseModel):
    role: str = Field(..., description="角色：user, assistant, system")
    content: str = Field(..., description="消息文本内容")


class ChatRequest(BaseModel):
    user_input: str
    image_base64: Optional[str] = None

    # 用户必须提供的纯净版 BYOK 配置
    api_key: str
    base_url: str
    text_model: str  # 用于纯文本对话的模型
    vision_model: Optional[str] = None  # 用于图片的模型
    # 允许用户随本次对话带上自定义 API 工具
    custom_tools: Optional[List[CustomAPIToolConfig]] = Field(default_factory=list)
# ==========================================
# 4. 返回给用户的消息模型
# ==========================================
class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)