from fastapi import FastAPI
from app.core.config import settings
from app.core.logger import setup_logging, logger  # 引入我们刚写的日志配置

# 在实例化 FastAPI 之前，先初始化日志
setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)


@app.get("/health")
async def health_check():
    # 我们可以这样记录一条信息到文件里
    logger.info("健康检查接口被调用了一次")

    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)