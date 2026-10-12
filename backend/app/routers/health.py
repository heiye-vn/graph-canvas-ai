"""健康检查。

两条探针刻意分开（与 liveness / readiness 的语义一致）：
    /health  liveness  —— 只证明进程活着，**不探任何依赖**，依赖抖动不会导致容器被重启
    /ready   readiness —— 探 PG / Redis / 对象存储，不就绪才从负载均衡摘除

SSE 后续会挂在 /events（不挂 /api 前缀），便于反向代理单独关掉缓冲。
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.config import get_settings
from app.db import check_database
from app.services import storage

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__, "env": get_settings().app_env}


@router.get("/ready")
async def ready(response: Response) -> dict:
    settings = get_settings()

    db_ok = await check_database()
    redis_ok = await _check_redis()
    # boto3 是同步客户端，必须丢到线程池，否则会阻塞事件循环
    storage_ok = await run_in_threadpool(storage.check_storage)

    checks = {"database": db_ok, "redis": redis_ok, "storage": storage_ok}
    all_ok = all(checks.values())

    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
        "provider": settings.image_provider,
    }


async def _check_redis() -> bool:
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(get_settings().redis_url, socket_connect_timeout=2)
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 - 探针只关心通不通
        return False
