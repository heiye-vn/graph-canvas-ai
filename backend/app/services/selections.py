"""选区服务（M6）。

选区的生命周期刻意**不进数据库**：它是画布的临时伴随状态（画完就用于
一次局部编辑，改完图就作废），存 Redis 带 24h TTL 足够 ——
「服务重启后选区还在」不是需求，「改图后旧选区必须失效」才是。

失效的唯一裁判是 `EditSession.revision`：
    · 选区创建时把当时的 revision 写进 payload
    · 之后每次读取都比对当前 revision，对不上 = 画布已变 = 选区作废（返回 None）
    · 「改图后旧选区自动失效」（DoD ③）不需要任何主动清理 —— 比对天然覆盖
      工具、撤销、重做、整份替换所有改文档的路径
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.edits.mask import overlay_png, rasterize_strokes, to_luma, union
from app.edits.segment import segment_points
from app.models import EditSession
from app.services import assets as asset_service
from app.services import flatten as flatten_service
from app.services import storage
from app.services.events import get_redis

TTL = 24 * 3600


class StaleSelection(Exception):
    """请求带的 revision 与会话当前 revision 不一致 —— 画布已变。"""


class EmptySelection(Exception):
    """会话里没有可用选区。"""


def _key(session_id: uuid.UUID) -> str:
    return f"selection:{session_id}"


async def get(session_id: uuid.UUID, revision: int) -> dict | None:
    """取当前选区；revision 对不上返回 None（静默失效，不抛错）。"""
    raw = await get_redis().get(_key(session_id))
    if not raw:
        return None
    payload = json.loads(raw)
    if payload.get("revision") != revision:
        return None
    return payload


async def clear(session_id: uuid.UUID) -> None:
    await get_redis().delete(_key(session_id))


async def save(session_id: uuid.UUID, payload: dict) -> None:
    await get_redis().set(_key(session_id), json.dumps(payload), ex=TTL)


async def select_points(
    session: AsyncSession,
    record: EditSession,
    revision: int,
    points: list[tuple[float, float]],
    *,
    append: bool,
) -> dict:
    """点选：把点击交给分割器得到物体遮罩。append 时在已有选区上追加提示点。"""
    _guard(record, revision)
    if not points:
        raise EmptySelection
    source = await flatten_service.flatten_session(session, record)
    current = await get(record.id, revision) if append else None
    markers = list((current or {}).get("markers") or [])
    if not append:
        markers = []
    for i, (x, y) in enumerate(points):
        markers.append({"index": len(markers) + 1 + i, "x": x, "y": y})
    coords = [(item["x"], item["y"]) for item in markers]
    # 分割是 CPU 密集（SAM encoder 秒级），丢线程池避免卡住事件循环
    import asyncio

    overlay = await asyncio.to_thread(segment_points, source, coords)
    return await _store(session, record, revision, overlay, markers)


async def select_strokes(
    session: AsyncSession,
    record: EditSession,
    revision: int,
    strokes: list[list[tuple[float, float]]],
    radius: float,
) -> dict:
    """笔刷：归一化笔迹栅格化成遮罩， append 时与已有遮罩取并集。"""
    _guard(record, revision)
    if not any(strokes):
        raise EmptySelection
    size = (record.doc["canvas"]["width"], record.doc["canvas"]["height"])
    current = await get(record.id, revision)
    base = None
    markers = list((current or {}).get("markers") or [])
    if current:
        asset = await asset_service.get_asset(
            session, record.user_id, uuid.UUID(current["mask_asset_id"])
        )
        base = to_luma(storage.get_object(asset.s3_key), size)
    mask = rasterize_strokes(size, strokes, radius=radius, base=base)
    if base is not None:
        mask = union(base, mask)
    return await _store(session, record, revision, overlay_png(mask), markers)


async def _store(
    session: AsyncSession,
    record: EditSession,
    revision: int,
    overlay: bytes,
    markers: list[dict],
) -> dict:
    asset = await asset_service.create_from_bytes(
        session, user_id=record.user_id, data=overlay, kind="mask"
    )
    payload = {
        "revision": revision,
        "mask_asset_id": str(asset.id),
        "markers": markers,
    }
    await save(record.id, payload)
    return payload


async def mask_bytes(
    session: AsyncSession, record: EditSession, mask_asset_id: str | None = None
) -> bytes:
    """取出要用的遮罩字节：优先用调用方指定的，否则用会话当前选区。"""
    stored = await get(record.id, record.revision)
    asset_id = mask_asset_id or (stored or {}).get("mask_asset_id")
    if not asset_id:
        raise EmptySelection
    try:
        asset = await asset_service.get_asset(session, record.user_id, uuid.UUID(asset_id))
    except Exception as exc:  # 404/403 都归到「选区不可用」
        raise EmptySelection from exc
    return storage.get_object(asset.s3_key)


def _guard(record: EditSession, revision: int) -> None:
    if revision != record.revision:
        raise StaleSelection
