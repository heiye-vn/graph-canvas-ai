"""任务投递（ARQ）。

去重的关键是这一行：把 run id 直接当作 job id。
同一个 run 被重复投递（前端重试、网络重放）不会产生第二次执行，
成本为零，收益是彻底消灭「同一张图生成两遍」。
"""

from __future__ import annotations

from uuid import UUID

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import get_settings

_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue(task: str, run_id: UUID | str) -> None:
    pool = await get_pool()
    await pool.enqueue_job(task, str(run_id), _job_id=str(run_id))


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
