"""SSE 流。

路由刻意**不挂业务前缀**：/events 而不是 /api/events，
便于反向代理单独为它关掉响应缓冲（Nginx 的 X-Accel-Buffering）。

鉴权走 query 参数：浏览器原生 EventSource 发不了自定义请求头，
令牌只能拼在 URL 上（代价是会进访问日志，可接受）。
"""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import user_from_token
from app.models import User
from app.schemas.events import (
    CotEvent,
    DoneEvent,
    SnapshotEvent,
    frame,
    ping_frame,
)
from app.services import cot as cot_service
from app.services import events
from app.services import runs as runs_service

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
MAX_STREAM_SECONDS = 600  # 主动断开让客户端重连，避免连接无限期挂着


@router.get("/events/agent/{run_id}")
async def stream_agent_run(
    run_id: uuid.UUID,
    token: str | None = Query(default=None),
    cot_after: int = Query(default=0, description="重连恢复：只回放 seq 大于该值的 CoT 增量"),
    session: AsyncSession = Depends(get_session),
):
    """Agent 对话轮的 CoT 流（M9.1）：回放缓冲 → 实时订阅 → done 收束。

    与 /events/runs 的差异：载体是 agent_runs（规划期没有 ToolRun），
    建流时先按 cot_after 回放 Redis 缓冲 —— 断线重连不丢 token，
    前端再按 seq 去重，双保险（DoD ③）。
    """
    from app.models.agent_run import AWAITING_CONFIRM
    from app.services import agent_runs as agent_runs_service

    user: User = await user_from_token(token, session)
    turn = await agent_runs_service.get(session, user_id=user.id, run_id=run_id)
    status_at_open = turn.status
    # 规划阶段结束标志：终态（succeeded/failed/cancelled）或等待用户确认（awaiting_confirm）
    planning_done_at_open = turn.is_terminal or status_at_open == AWAITING_CONFIRM

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _agent_event_stream(run_id, status_at_open, planning_done_at_open, cot_after),
        media_type="text/event-stream",
        status_code=status.HTTP_200_OK,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _agent_event_stream(
    run_id: uuid.UUID, status_at_open: str, done_at_open: bool, cot_after: int
):
    started = time.monotonic()

    async with events.subscription(run_id) as stream:
        yield frame(SnapshotEvent(run_id=run_id, status=status_at_open))

        # 回放断线期间错过的 CoT（前端按 seq 去重，与实时帧重叠也幂等）
        for item in await cot_service.replay(run_id, after_seq=cot_after):
            yield frame(CotEvent.model_validate(item))

        if done_at_open:
            yield frame(DoneEvent(run_id=run_id, status=status_at_open))
            return

        iterator = stream.__aiter__()
        while True:
            if time.monotonic() - started > MAX_STREAM_SECONDS:
                return
            try:
                event = await asyncio.wait_for(iterator.__anext__(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ping_frame(run_id)
                continue
            except StopAsyncIteration:
                return

            yield frame(event)
            if event.type in {"done", "error"}:
                return


@router.get("/events/runs/{run_id}")
async def stream_run(
    run_id: uuid.UUID,
    token: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    user: User = await user_from_token(token, session)
    run = await runs_service.get_run(session, user.id, run_id)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        _event_stream(run_id, run),
        media_type="text/event-stream",
        # 状态码必须是 200：部分反向代理对非 200 会缓冲整段响应，流就卡住不动了
        status_code=status.HTTP_200_OK,
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(run_id: uuid.UUID, run):
    """先订阅 → 再发快照 → 循环推送（无消息时发心跳）。

    顺序不能反：订阅先建立，才不会漏掉「订阅之后、快照之前」到达的事件。
    """
    started = time.monotonic()

    async with events.subscription(run_id) as stream:
        yield frame(runs_service.snapshot_of(run))

        if run.is_terminal:
            yield frame(DoneEvent(run_id=run_id, status=run.status))
            return

        iterator = stream.__aiter__()
        while True:
            if time.monotonic() - started > MAX_STREAM_SECONDS:
                return  # 让客户端重连，顺便重新做一次鉴权
            try:
                event = await asyncio.wait_for(iterator.__anext__(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ping_frame(run_id)
                continue
            except StopAsyncIteration:
                return

            yield frame(event)
            if event.type in {"done", "error"}:
                return
