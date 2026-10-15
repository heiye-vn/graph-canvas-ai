"""Agent 的 LangGraph checkpointer 生命周期（M9.2）。

AsyncPostgresSaver 持有一条 psycopg 连接，随 API 进程存活；
thread_id = agent_run_id，服务重启后未完成的轮次靠它断点续跑（DoD ②）。

坑位记录：langgraph-checkpoint-postgres 依赖 psycopg3（不是 asyncpg），
连接串要把 `+asyncpg` 剥掉。
"""

from __future__ import annotations

import logging

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import get_settings

logger = logging.getLogger("graph-canvas-ai.agent")

_saver = None
_conn = None


def _psycopg_url() -> str:
    return get_settings().database_url.replace("+asyncpg", "")


async def get_checkpointer():
    """懒加载全局 checkpointer；首次调用会执行 setup() 建检查点表（幂等 DDL）。"""
    global _saver, _conn
    if _saver is not None:
        return _saver
    _conn = await AsyncConnection.connect(
        _psycopg_url(), autocommit=True, row_factory=dict_row
    )
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    _saver = AsyncPostgresSaver(_conn)
    await _saver.setup()
    logger.info("LangGraph checkpointer 就绪（postgres）")
    return _saver


async def close_checkpointer() -> None:
    global _saver, _conn
    _saver = None
    if _conn is not None:
        await _conn.close()
        _conn = None
