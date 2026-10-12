"""测试夹具。

两条硬约束（照抄参考项目里做得对的部分，并在 M10 补强）：
    1. 测试用**独占 Redis DB 1**，开发 worker 只听默认库，不会把测试任务抢走
    2. 测试用户统一 test_ 前缀并定向删除，绝不误清开发库真实数据
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest

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
    "JWT_SECRET": "test-only-secret",
    "IMAGE_PROVIDER": "mock",
}


@pytest.fixture(scope="session", autouse=True)
def _test_env() -> Iterator[None]:
    for key, value in _TEST_ENV.items():
        os.environ.setdefault(key, value)

    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
async def session() -> AsyncIterator[object]:
    """数据库会话；需要真实 Postgres，M1 建表后启用。"""
    from app.db import dispose_engine, get_session_factory

    factory = get_session_factory()
    async with factory() as s:
        yield s
    await dispose_engine()
