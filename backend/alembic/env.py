"""Alembic 迁移环境（异步版）。

数据库地址统一来自 app.config，避免 alembic.ini 与 .env 两处配置漂移。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.config import get_settings

# 注册全部模型元数据：必须从 app.models 导入（它会连带导入所有 ORM 类），
# 只导入 Base 的话 metadata 是空的，autogenerate 会误判成「没有任何变更」
from app.models import Base  # noqa: F401

config = context.config
target_metadata = Base.metadata

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def run_migrations_offline() -> None:
    """生成 SQL 脚本而不连库：`alembic upgrade head --sql`。"""
    url = get_settings().database_url.replace("+asyncpg", "+psycopg2")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    from app.db import dispose_engine, get_engine

    connectable = get_engine()
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await dispose_engine()


def main() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        asyncio.run(run_async_migrations())


# 必须是模块级调用：alembic 用 exec 加载本文件，__name__ 不是 "__main__"，
# 套一层 `if __name__ == "__main__"` 会让所有迁移命令静默变成空操作。
main()
