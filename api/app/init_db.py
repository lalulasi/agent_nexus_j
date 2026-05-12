import asyncio

from app.infrastructure.database.models import Base
from app.infrastructure.database.session import engine


async def reset_database():
    print("🔄 正在连接数据库...")
    async with engine.begin() as conn:
        print("🗑️ 正在强行删除旧的数据表...")
        await conn.run_sync(Base.metadata.drop_all)

        print("✨ 正在根据最新的 models.py 创建新表...")
        await conn.run_sync(Base.metadata.create_all)

    print("✅ 数据库重置成功！包含了 'name' 字段的 messages 表已准备就绪！")


if __name__ == "__main__":
    asyncio.run(reset_database())