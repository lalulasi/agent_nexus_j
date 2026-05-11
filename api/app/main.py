from fastapi import FastAPI
from app.core.config import settings
from app.core.logger import logger

# === 引入我们刚刚写的路由模块 ===
from app.api.routers import sessions
# 初始化系统工具
import app.infrastructure.tools.builtins.system_time

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)
logger.info("🌟 AgentNexus-J FastAPI host server initialized...")
# === 将路由挂载到主程序，并加上 /api/v1 前缀 ===
app.include_router(sessions.router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    logger.info("健康检查接口被调用")
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)