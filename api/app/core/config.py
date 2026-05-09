import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

# 使用 pathlib 优雅地定位到项目的最外层根目录 (agent_nexus_j)
# config.py 的路径是: agent_nexus_j/api/app/core/config.py
# parents[0] = core, parents[1] = app, parents[2] = api, parents[3] = agent_nexus_j
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"

class Settings(BaseSettings):
    PROJECT_NAME: str = "agent_nexus_j"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # PostgreSQL
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # 预留 LLM 配置
    OPENAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),      # 转换为字符串传入
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @property
    def async_database_url(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()