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


class EnqueueFailed(RuntimeError):
    """任务没能投递进 ARQ。调用方必须补偿，否则已提交的 run 会永远停在 queued。"""


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def enqueue(task: str, run_id: UUID | str) -> None:
    global _pool
    try:
        pool = await get_pool()
        await pool.enqueue_job(task, str(run_id), _job_id=str(run_id))
    except Exception as exc:  # noqa: BLE001 - 任何投递失败都要转成可补偿的错误
        _pool = None  # 坏连接不复用，下一次调用重建
        raise EnqueueFailed("任务队列不可用") from exc


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
    _pool = None
