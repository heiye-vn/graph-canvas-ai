"""集成测试夹具。

三条硬约束：
    1. 测试用**独立数据库** retouch_test（自动创建），绝不碰开发库
    2. 测试用**独占 Redis DB 1**，开发 worker 只听默认库，不会把测试任务抢走
    3. 测试用户统一 `test_` 前缀，收尾定向删除，不会误清真实数据

为什么表结构准备写成**同步** fixture：
    TestClient 在自己的事件循环里跑 app，如果 DDL 跑在另一个 loop 上，
    asyncpg 连接池会跨 loop 复用连接而报错。这里每次都用**独立 engine** 跑完 DDL 立刻 dispose，
    app.db 的连接池则留给 TestClient 那个 loop 自己创建，两者互不干扰。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

# 必须在导入 app.* 之前铺好环境变量，否则 Settings 校验会直接失败
_TEST_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://retouch:retouch_dev@127.0.0.1:7311/retouch_test",
    ),
    "REDIS_URL": os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:7312/1"),
    "S3_ENDPOINT": os.getenv("TEST_S3_ENDPOINT", "http://127.0.0.1:7313"),
    "S3_ACCESS_KEY": "retouch",
    "S3_SECRET_KEY": "retouch_dev",
    "S3_BUCKET": "retouch-test",
    # pyjwt 会对 <32 字节的 HS256 密钥告警；测试用也按正规长度来
    "JWT_SECRET": os.getenv("TEST_JWT_SECRET", "test-only-secret-please-do-not-use-in-prod"),
    "JWT_TTL_HOURS": "1",
    "IMAGE_PROVIDER": "mock",
    "ASSET_UPLOAD_MODE": "backend",
}


@pytest.fixture(scope="session", autouse=True)
def _test_env():
    for key, value in _TEST_ENV.items():
        os.environ.setdefault(key, value)

    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _ensure_test_database() -> None:
    """不存在则建 retouch_test（CREATE DATABASE 不能在事务里跑）。"""
    from sqlalchemy import text

    admin_url = _TEST_ENV["DATABASE_URL"].rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = 'retouch_test'")
            )
            if exists.scalar_one_or_none() is None:
                await conn.execute(text("CREATE DATABASE retouch_test"))
    finally:
        await engine.dispose()


async def _create_tables() -> None:
    """直接在测试库建表：不依赖迁移历史，迁移脚本由 `alembic upgrade head` 单独验证。"""
    await _ensure_test_database()
    from app.models import Base  # 导入即注册全部表

    engine = create_async_engine(_TEST_ENV["DATABASE_URL"])
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database_schema(_test_env):
    pytest.importorskip("asyncpg")
    asyncio.run(_create_tables())
    yield
