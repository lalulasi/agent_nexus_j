from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.api.routers import chat, llm_configs, sessions, system_prompts, tools
from api.app.core.config import get_settings
from api.app.core.logger import logger, setup_logger
from api.app.infrastructure.database.session import AsyncSessionLocal, init_db

settings = get_settings()


async def _seed_builtin_tools() -> None:
    """将 Python 内置工具同步到 user_tools 表（不存在则新增，已有则更新描述）。"""
    from sqlalchemy import select

    from api.app.infrastructure.database.models import UserTool
    from api.app.infrastructure.tools.registry import list_tools

    async with AsyncSessionLocal() as db:
        async with db.begin():
            for tool in list_tools():
                result = await db.execute(select(UserTool).where(UserTool.name == tool.name))
                existing = result.scalar_one_or_none()
                if existing:
                    existing.description = tool.description
                    existing.parameters_schema = tool.input_schema
                else:
                    display = tool.name.replace("_", " ").title()
                    db.add(UserTool(
                        name=tool.name,
                        display_name=display,
                        description=tool.description,
                        parameters_schema=tool.input_schema,
                        tool_type="builtin",
                        is_active=True,
                    ))
    logger.info("内置工具同步完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger(debug=settings.is_development)
    logger.info(f"Starting AgentNexus-J [{settings.app_env.value}]")
    await init_db()
    await _seed_builtin_tools()
    yield
    logger.info("Shutting down AgentNexus-J")


app = FastAPI(
    title="AgentNexus-J",
    description="Enterprise Multi-Agent Collaboration System",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(llm_configs.router, prefix="/api/v1")
app.include_router(system_prompts.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env.value}
