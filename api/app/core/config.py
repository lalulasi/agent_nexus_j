from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel
from typing import Dict, Optional

# ==========================================
# 1. 定义单个大模型的配置结构 (Schema)
# ==========================================
class LLMProviderConfig(BaseModel):
    base_url: str
    api_key: Optional[str] = None
    default_model: str            # 默认文本模型
    vision_model: Optional[str] = None  # 多模态模型（如果有的话）

# ==========================================
# 2. 更新主配置类 Settings
# ==========================================
class Settings(BaseSettings):
    PROJECT_NAME: str = "AgentNexus-J"
    VERSION: str = "1.0.0"

    # Database
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: str

    # API Keys
    DEEPSEEK_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def async_database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # ==========================================
    # 3. 【核心新增】基于注册表模式的提供商配置
    # ==========================================
    @property
    def LLM_PROVIDERS(self) -> Dict[str, LLMProviderConfig]:
        return {
            "deepseek": LLMProviderConfig(
                base_url="https://api.deepseek.com/v1",
                api_key=self.DEEPSEEK_API_KEY,
                default_model="deepseek-chat",
                vision_model=None  # 明确标记当前 DeepSeek API 暂不支持视觉
            ),
            "qwen": LLMProviderConfig(
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                api_key=self.QWEN_API_KEY,
                default_model="qwen-plus",
                vision_model="qwen-vl-max" # Qwen 的多模态大将
            )
            # 未来想加智谱？只需要在这里无脑加一行 "zhipu": LLMProviderConfig(...) 即可！
        }

settings = Settings()