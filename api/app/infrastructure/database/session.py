from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# ==========================================
# 1. 建立非同步引擎 (Async Engine)
# ==========================================
engine = create_async_engine(
    settings.async_database_url,
    echo=False,                # 打印底层执行的SQL语句
    pool_size=10,              # 连接池大小（针对Agent高并发调节）
    max_overflow=20,           # 允许额外建立的最大连接数
    pool_pre_ping=True,        # 每次从连接池取出连线前，先ping一下确保连线未断开
)

# ==========================================
# 2. 建立session工厂
# ==========================================
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,    # 非同步环境下设为False，防止commit后存储属性后报错
)

# ==========================================
# 3. 依赖注入产生器 (Dependency Injection)
# ==========================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 的依赖注入函数
    确保每个 HTTP 请求或后台任务都拥有独立的资料库会话
    只用完毕后，自动回收链接
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()