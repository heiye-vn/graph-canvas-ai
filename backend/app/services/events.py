"""事件发布与订阅（Redis Pub/Sub）。

worker 与 API 是两个进程，进度必须靠一条公共通道传出去——
数据库只负责持久化最终状态，实时性交给 Pub/Sub。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.config import get_settings
from app.schemas.events import Event, StreamEvent

CHANNEL_PREFIX = "run"

logger = logging.getLogger("graph-canvas-ai.events")

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def channel_of(run_id: UUID | str) -> str:
    return f"{CHANNEL_PREFIX}:{run_id}"


async def publish(event: Event) -> None:
    """尽力推送。事件只是实时补强，数据库才是真相。

    Redis 抖动不能让**已经提交**的状态在 API 里变成 500，也不能让 worker
    在任务成功后再判一次失败 —— 前端刷新/轮询会从数据库把现场补回来。
    """
    try:
        await get_redis().publish(channel_of(event.run_id), event.model_dump_json())
    except Exception:  # noqa: BLE001
        logger.exception(
            "事件发布失败 run_id=%s type=%s", event.run_id, event.type,
        )


@asynccontextmanager
async def subscription(run_id: UUID | str) -> AsyncIterator[AsyncIterator[StreamEvent]]:
    """订阅一个 run 的事件流。

    用上下文管理器而不是裸 async generator：**进入上下文时订阅已经完成**，
    调用方才能安全地「先订阅、再发快照」——否则任务可能在订阅前就结束，
    快照之后再也等不到任何事件，连接会一直空着。
    """
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(channel_of(run_id))
    try:
        yield _iter_messages(pubsub)
    finally:
        await pubsub.close()


async def _iter_messages(pubsub: Any) -> AsyncIterator[StreamEvent]:
    from pydantic import TypeAdapter

    adapter: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        raw = message.get("data")
        if not raw:
            continue
        try:
            yield adapter.validate_python(json.loads(raw))
        except Exception:  # noqa: BLE001 - 一条坏帧不该让整个流断开
            continue


async def publish_raw(run_id: UUID, payload: dict[str, Any]) -> None:
    """兜底通道：非标准结构的事件（逐步被上面的类型化事件取代）。"""
    await get_redis().publish(channel_of(run_id), json.dumps(payload))
