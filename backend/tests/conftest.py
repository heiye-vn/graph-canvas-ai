"""集成测试夹具。

安全边界：
    1. 集成测试必须显式设置 TEST_DATABASE_URL 和 TEST_ALLOW_DATABASE_RESET=1，
       确认 retouch_test 是可重置的专用测试库后才允许建库 / 删表。
    2. 强制使用 Redis DB 1、retouch-test 桶；覆盖开发环境并禁用 .env 和真实模型凭据。
    3. 标记 unit 的离线用例不准备基础设施，其余用例默认要求上述显式授权。

为什么表结构准备写成**同步** fixture：
    TestClient 在自己的事件循环里跑 app，如果 DDL 跑在另一个 loop 上，
    asyncpg 连接池会跨 loop 复用连接而报错。这里每次都用**独立 engine** 跑完 DDL 立刻 dispose，
    app.db 的连接池则留给 TestClient 那个 loop 自己创建，两者互不干扰。
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import create_async_engine

# 必须在导入 app.* 之前铺好环境变量，否则 Settings 校验会直接失败
_TEST_ENV = {
    "APP_ENV": "test",
    "DATABASE_URL": os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://retouch:retouch_dev@127.0.0.1:7411/retouch_test",
    ),
    "REDIS_URL": os.getenv("TEST_REDIS_URL", "redis://127.0.0.1:7412/1"),
    "S3_ENDPOINT": os.getenv("TEST_S3_ENDPOINT", "http://127.0.0.1:7413"),
    "S3_ACCESS_KEY": "retouch",
    "S3_SECRET_KEY": "retouch_dev",
    "S3_BUCKET": "retouch-test",
    # pyjwt 会对 <32 字节的 HS256 密钥告警；测试用也按正规长度来
    "JWT_SECRET": os.getenv("TEST_JWT_SECRET", "test-only-secret-please-do-not-use-in-prod"),
    "JWT_TTL_HOURS": "1",
    "IMAGE_PROVIDER": "mock",
    "DASHSCOPE_API_KEY": "",
    "IMAGE_API_KEY": "",
    "IMAGE_BASE_URL": "",
    "LLM_BASE_URL": "",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "LANGFUSE_HOST": "",
    "MATTING_PROVIDER": "circle",
    # OCR 引擎加载要秒级，测试一律走 none —— detect_text 的降级分支单独测
    "OCR_PROVIDER": "none",
    "ASSET_UPLOAD_MODE": "backend",
}


# 收集测试时就可能导入 app；fixture 阶段才设环境已经太晚。
_ENV_PATCH = pytest.MonkeyPatch()
for _key, _value in _TEST_ENV.items():
    _ENV_PATCH.setenv(_key, _value)

from app.config import Settings, get_settings  # noqa: E402

_ENV_PATCH.setitem(Settings.model_config, "env_file", None)
get_settings.cache_clear()


def pytest_unconfigure(config):
    _ENV_PATCH.undo()
    get_settings.cache_clear()


def pytest_configure(config):
    config.addinivalue_line("markers", "unit: 不连接数据库、Redis 或对象存储")


@pytest.fixture(scope="session", autouse=True)
def _test_env():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _validate_test_services() -> None:
    """任何建库 / 删表之前要求显式确认专用测试服务；报错不包含连接凭据。"""
    if not os.getenv("TEST_DATABASE_URL") or os.getenv("TEST_ALLOW_DATABASE_RESET") != "1":
        raise pytest.UsageError(
            "集成测试须显式配置 TEST_DATABASE_URL 并设置 TEST_ALLOW_DATABASE_RESET=1；"
            "只运行离线测试请使用 -m unit"
        )
    try:
        database = make_url(_TEST_ENV["DATABASE_URL"])
        redis = urlsplit(_TEST_ENV["REDIS_URL"])
        safe = (
            database.drivername == "postgresql+asyncpg"
            and database.database == "retouch_test"
            and not database.query
            and redis.scheme in {"redis", "rediss"}
            and redis.path == "/1"
            and not redis.query
            and not redis.fragment
            and os.environ.get("DATABASE_URL") == _TEST_ENV["DATABASE_URL"]
            and os.environ.get("REDIS_URL") == _TEST_ENV["REDIS_URL"]
            and os.environ.get("S3_BUCKET") == "retouch-test"
            and get_settings().database_url == _TEST_ENV["DATABASE_URL"]
            and get_settings().redis_url == _TEST_ENV["REDIS_URL"]
            and get_settings().s3_bucket == "retouch-test"
        )
    except (ArgumentError, ValueError, TypeError):
        safe = False
    if not safe:
        raise pytest.UsageError(
            "拒绝操作：测试服务必须使用 retouch_test、Redis DB 1 和 retouch-test 桶"
        )


async def _ensure_test_database() -> None:
    """不存在则建 retouch_test（CREATE DATABASE 不能在事务里跑）。"""
    from sqlalchemy import text

    _validate_test_services()
    admin_url = make_url(_TEST_ENV["DATABASE_URL"]).set(database="postgres")
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


@pytest.fixture(autouse=True)
def _database_schema(request, _test_env):
    if request.node.get_closest_marker("unit") is None:
        request.getfixturevalue("_integration_schema")


@pytest.fixture(scope="session")
def _integration_schema(_test_env):
    _validate_test_services()
    pytest.importorskip("asyncpg")
    asyncio.run(_create_tables())

    from app.services import storage

    storage.ensure_bucket()  # 测试桶，与开发桶分开（S3_BUCKET=retouch-test）
    yield


def run_async(coro):
    """在独立事件循环里跑一段协程，结束后**释放连接池并清空单例**。

    TestClient 在自己的 portal 里持有另一套 loop；如果异步测试复用同一个
    asyncpg 连接池，就会跨 loop 复用连接而报错。这里的做法是：每次都开新 loop，
    用完立刻 dispose 并把 engine 单例置空，让下一个用例重新建。
    """
    from app.db import dispose_engine

    async def wrapper():
        try:
            return await coro
        finally:
            await dispose_engine()
            from app.services.events import close_redis

            await close_redis()

    return asyncio.run(wrapper())
