"""ARQ worker 配置。

必须与 API 同时启动，否则任务会一直停在 queued——本地开发要开两个终端。
"""

from __future__ import annotations

import logging

from arq.connections import RedisSettings

from app.config import get_settings
from app.tasks.image import text_to_image
from app.tasks.region import inpaint_region

logger = logging.getLogger("graph-canvas-ai.worker")


async def startup(ctx) -> None:
    settings = get_settings()
    logger.info("worker 启动：provider=%s", settings.image_provider)
    # 预热 provider，避免第一个任务承担建连开销
    from app.providers import get_image_provider

    get_image_provider()


async def shutdown(ctx) -> None:
    from app.db import dispose_engine
    from app.services.events import close_redis
    from app.services.queue import close_pool

    await close_pool()
    await close_redis()
    await dispose_engine()
    logger.info("worker 已关闭")


class WorkerSettings:
    functions = [text_to_image, inpaint_region]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 4
    job_timeout = 300
    max_tries = 1  # 失败交给上层决策（重试/改参数），不在队列里盲目重跑
    on_startup = startup
    on_shutdown = shutdown
