from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    development = "development"
    production = "production"
    testing = "testing"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: AppEnv = AppEnv.development
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/agent_nexus"
    )

    # Anthropic
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = "claude-opus-4-7"

    # Agent
    agent_max_tokens: int = 8192
    agent_max_iterations: int = 20

    @property
    def is_development(self) -> bool:
        return self.app_env == AppEnv.development


@lru_cache
def get_settings() -> Settings:
    return Settings()
