"""思维链（CoT）事件的缓冲与发布（M9.1）。

设计取舍：CoT token 走「Redis 缓冲 + Pub/Sub」双通道 ——
    缓冲（list, cap 500, TTL 1h）→ 断线重连时按 seq 回放，不丢也不重
    Pub/Sub → 在线订阅者实时收
seq 由 Redis INCR 保证单调；前端只追加 seq 更大的增量，天然幂等（DoD ③）。

kind 语义（协议 M2 定死，这里只是填充）：
    thought     模型思考（reasoning_content / content 增量）
    tool_call   模型决定调用某工具
    observation 工具执行前后的客观事实
    reflection  对结果的自我评估（M9.2 反思循环启用）
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.schemas.events import CotEvent
from app.services.events import get_redis, publish

logger = logging.getLogger("graph-canvas-ai.cot")

CAP = 500
TTL_SECONDS = 3600

_seq_key = "cotseq:{run_id}"
_buf_key = "cot:{run_id}"


async def emit(
    run_id: UUID, kind: str, delta: str, *, node: str | None = None
) -> int:
    """追加一条 CoT 增量：缓冲 + 广播，返回 seq。delta 为空时跳过。

    CoT 是旁路观测：Redis 抖动不能打断已经跑起来的图（否则工具成功、轮次失败）。
    失败只记日志并返回 0，前端最多丢一段实时思考，刷新后仍以 DB 状态为准。
    """
    if not delta:
        return 0
    try:
        redis = get_redis()
        seq = await redis.incr(_seq_key.format(run_id=run_id))
        await redis.expire(_seq_key.format(run_id=run_id), TTL_SECONDS)
        event = CotEvent(run_id=run_id, seq=seq, kind=kind, delta=delta, node=node)  # type: ignore[arg-type]
        payload = event.model_dump_json()
        await redis.rpush(_buf_key.format(run_id=run_id), payload)
        await redis.ltrim(_buf_key.format(run_id=run_id), -CAP, -1)
        await redis.expire(_buf_key.format(run_id=run_id), TTL_SECONDS)
        await publish(event)
        return seq
    except Exception:  # noqa: BLE001 - CoT 只是实时补强，绝不能拖垮图执行
        logger.warning("CoT 事件发送失败 run_id=%s kind=%s", run_id, kind, exc_info=True)
        return 0


async def replay(run_id: UUID, after_seq: int = 0) -> list[dict[str, Any]]:
    """回放缓冲里 seq > after_seq 的增量（重连恢复用）。"""
    raw = await get_redis().lrange(_buf_key.format(run_id=run_id), 0, -1)
    items: list[dict[str, Any]] = []
    for line in raw:
        try:
            data = json.loads(line)
        except Exception:  # noqa: BLE001 - 坏帧跳过
            continue
        if int(data.get("seq", 0)) > after_seq:
            items.append(data)
    return items
