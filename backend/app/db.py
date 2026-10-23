"""SQLAlchemy 异步会话。

只提供最小骨架：M1 建 users / assets 表时在此处 import 模型元数据。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类；Alembic 的 target_metadata 指向它的 metadata。"""


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,  # 连接池里的死连接自动重连
            # 不开 echo：图像编辑链路一次会话会产生大量 SQL，刷屏后反而看不到有效日志。
            # 需要排查 SQL 时临时打开，或用 sqlalchemy 的 event 监听单独打点。
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,   # 异步下避免提交后属性被失效触发隐式 IO
            autoflush=False,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：`Depends(get_session)`。"""
    # 必须再调用一次拿到 AsyncSession 实例：SQLAlchemy 2.1 起 factory 本身不再支持 async with
    async with get_session_factory()() as session:
        yield session


async def check_database() -> bool:
    """/ready 探针用：能跑通 SELECT 1 才算就绪。"""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - 探针只关心通不通，具体异常由 /ready 统一记录
        return False


async def dispose_engine() -> None:
    """应用关闭与测试切换数据库时调用。"""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
