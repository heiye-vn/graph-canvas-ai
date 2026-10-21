"""任务运行的服务层：状态流转 + 进度上报。

约定：本模块的函数一律**接收 session**，不自己开事务。
API 进程用请求级 session；worker 进程用 session_scope() 自建。
同一套逻辑两边复用，避免「API 里一套状态、worker 里另一套」。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session

from app.db import get_session_factory
from app.models import ToolRun
from app.models.run import CANCELLED, FAILED, RUNNING, SUCCEEDED, TERMINAL_STATUSES
from app.schemas.events import DoneEvent, ErrorEvent, ProgressEvent, SnapshotEvent
from app.services import events


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """worker 进程用：一次任务一个短事务。"""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_run(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tool: str,
    params: dict[str, Any] | None = None,
    session_id: uuid.UUID | None = None,
) -> ToolRun:
    run = ToolRun(
        user_id=user_id,
        tool=tool,
        params=params or {},
        session_id=session_id,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> ToolRun:
    run = await session.get(ToolRun, run_id)
    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return run


async def list_runs(
    session: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
    tool: str | None = None,
    status: str | None = None,
) -> list[ToolRun]:
    stmt = select(ToolRun).where(ToolRun.user_id == user_id)
    if tool is not None:
        stmt = stmt.where(ToolRun.tool == tool)
    if status is not None:
        stmt = stmt.where(ToolRun.status == status)
    result = await session.execute(stmt.order_by(ToolRun.created_at.desc()).limit(limit))
    return list(result.scalars().all())


def snapshot_of(run: ToolRun) -> SnapshotEvent:
    """连接建立时补发的状态，客户端据此决定要不要继续等。"""
    return SnapshotEvent(
        run_id=run.id,
        status=run.status,
        progress=run.progress,
        stage=run.stage,
        result=run.result,
        error=(run.error or {}).get("message"),
    )


async def report(
    run: ToolRun,
    *,
    progress: int | None = None,
    stage: str | None = None,
    to_running: bool = False,
) -> None:
    """更新进度并推送事件。

    只改内存里的对象，提交交给调用方（worker 里通常是下一步一并提交），
    避免一次任务写十几次库。事件是即时发的——这才是用户能看到的东西。
    """
    values: dict[str, Any] = {}
    if to_running and run.status == "queued":
        values.update(status=RUNNING, started_at=datetime.now(UTC))
    if progress is not None:
        values["progress"] = max(0, min(100, progress))
    if stage is not None:
        values["stage"] = stage
    if to_running:
        if not await _update_active(run, values):
            return
    else:
        session = async_object_session(run)
        if session is not None:
            with session.no_autoflush:
                await session.refresh(run)
        if run.is_terminal:
            return
        # 普通进度不执行 UPDATE，避免在 Provider await 期间持有任务行锁、阻塞取消。
        for key, value in values.items():
            setattr(run, key, value)

    await events.publish(
        ProgressEvent(
            run_id=run.id,
            progress=run.progress,
            stage=run.stage or "",
        )
    )


async def lock_active(session: AsyncSession, run: ToolRun) -> bool:
    """采用文档前锁住任务，取消与成功以先拿锁并提交的一方为准。"""
    current = await session.get(ToolRun, run.id, populate_existing=True, with_for_update=True)
    return current is not None and not current.is_terminal


async def _update_active(run: ToolRun, values: dict[str, Any]) -> bool:
    if run.is_terminal:
        return False
    session = async_object_session(run)
    if session is None:
        for key, value in values.items():
            setattr(run, key, value)
        return True
    # 不相信 worker 的 identity map；条件更新防止另一个请求已提交的取消被覆盖。
    with session.no_autoflush:
        result = await session.execute(
            update(ToolRun)
            .where(ToolRun.id == run.id, ToolRun.status.not_in(TERMINAL_STATUSES))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
    await session.refresh(run)
    return result.rowcount == 1


async def succeed(run: ToolRun, result: dict[str, Any]) -> None:
    await _update_active(run, {
        "status": SUCCEEDED, "progress": 100, "result": result,
        "error": None, "finished_at": datetime.now(UTC),
    })


async def fail(run: ToolRun, *, code: str, message: str, recoverable: bool = True) -> None:
    if not await _update_active(run, {
        "status": FAILED,
        "error": {"code": code, "message": message, "recoverable": recoverable},
        "finished_at": datetime.now(UTC),
    }):
        return
    await events.publish(
        ErrorEvent(run_id=run.id, code=code, message=message, recoverable=recoverable)
    )


async def cancel(run: ToolRun) -> None:
    if not await _update_active(run, {
        "status": CANCELLED, "finished_at": datetime.now(UTC),
    }):
        return
    # 必须推一帧 done：取消是用户在另一个请求里触发的，worker 侧不会产生任何事件。
    # 少了这一帧，前端的进度条要一直转到超时才知道任务没了。
    await events.publish(DoneEvent(run_id=run.id, status=CANCELLED))
