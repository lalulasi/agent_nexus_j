from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.app.api.routers import chat, llm_configs, sessions, system_prompts
from api.app.core.config import get_settings
from api.app.core.logger import logger, setup_logger
from api.app.infrastructure.database.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logger(debug=settings.is_development)
    logger.info(f"Starting AgentNexus-J [{settings.app_env.value}]")
    await init_db()
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
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env.value}
