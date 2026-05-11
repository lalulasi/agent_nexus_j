import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context

# 1. 导入我们的配置和模型基类
from app.core.config import settings
from app.infrastructure.database.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 2. 告诉 Alembic 去哪里找我们的表结构设计图
target_metadata = Base.metadata

def run_migrations_offline() -> None:
    """离线模式 (通常不用)"""
    url = settings.async_database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations() -> None:
    """异步迁移核心逻辑"""
    # 3. 动态将 config.py 里的数据库 URL 注入到 Alembic 的配置中
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.async_database_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()

def run_migrations_online() -> None:
    """在线模式：连接数据库执行"""
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()