"""Agent 的 LangGraph checkpointer 生命周期（M9.2）。

AsyncPostgresSaver 持有一条 psycopg 连接，随 API 进程存活；
thread_id = agent_run_id，服务重启后未完成的轮次靠它断点续跑（DoD ②）。

坑位记录：langgraph-checkpoint-postgres 依赖 psycopg3（不是 asyncpg），
连接串要把 `+asyncpg` 剥掉。
"""

from __future__ import annotations

import asyncio
import logging

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import get_settings

logger = logging.getLogger("graph-canvas-ai.agent")

_saver = None
_conn = None
_init_lock = asyncio.Lock()

# 建连与建表都可能卡在不可达的库上；启动流程不能被无限期挂住
_INIT_TIMEOUT = 10.0


def _psycopg_url() -> str:
    return get_settings().database_url.replace("+asyncpg", "")


async def get_checkpointer():
    """懒加载全局 checkpointer；首次调用会执行 setup() 建检查点表（幂等 DDL）。

    非生产环境初始化失败时降级为 MemorySaver，保证本地单机开发不中断；
    生产环境必须失败退出 —— 内存检查点跨进程/重启即丢，确认与断点续跑会静默失效。
    """
    global _saver, _conn
    if _saver is not None:
        return _saver
    # 并发首个调用只允许一个建连 + setup：否则会漏一条连接，DDL 也可能互相踩
    async with _init_lock:
        if _saver is not None:
            return _saver
        conn = None
        try:
            conn = await asyncio.wait_for(
                AsyncConnection.connect(
                    _psycopg_url(), autocommit=True, row_factory=dict_row
                ),
                timeout=_INIT_TIMEOUT,
            )
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            saver = AsyncPostgresSaver(conn)
            await asyncio.wait_for(saver.setup(), timeout=_INIT_TIMEOUT)
        except BaseException as exc:
            if conn is not None:
                try:
                    await asyncio.wait_for(conn.close(), timeout=5)
                except BaseException:  # noqa: BLE001 - 初始化已失败，清理错误不再上抛
                    logger.warning("checkpointer 初始化失败后关闭连接失败", exc_info=True)
            # 取消/退出信号原样上抛，不能被降级逻辑吞掉
            if not isinstance(exc, Exception):
                raise
            if get_settings().is_production:
                raise RuntimeError(
                    "生产环境必须使用 Postgres checkpointer（LangGraph 断点续跑依赖它）"
                ) from exc
            logger.warning(
                "LangGraph postgres checkpointer 初始化失败（%s），降级使用 MemorySaver", exc
            )
            from langgraph.checkpoint.memory import MemorySaver

            _saver = MemorySaver()
            return _saver
        _conn, _saver = conn, saver
        logger.info("LangGraph checkpointer 就绪（postgres）")
        return _saver


async def close_checkpointer() -> None:
    global _saver, _conn
    # 与初始化串行：避免「刚判定需要新建」的 get 拿到一条正在关闭的连接
    async with _init_lock:
        _saver = None
        conn, _conn = _conn, None
        if conn is None:
            return
        # 关闭必须带超时：若还有在途的图在用这条连接，close 可能永久等待 ——
        # 测试与停机场景宁可丢弃连接也不能把进程挂死
        try:
            await asyncio.wait_for(conn.close(), timeout=5)
        except Exception:  # noqa: BLE001
            logger.warning("checkpointer 连接关闭超时/失败（已放弃）", exc_info=True)
