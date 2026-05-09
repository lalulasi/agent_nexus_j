from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "database_configured": settings.POSTGRES_DB
    }

if __name__ == "__main__":
    import uvicorn
    # 本地測試啟動
    uvicorn.run(app, host="0.0.0.0", port=8000)