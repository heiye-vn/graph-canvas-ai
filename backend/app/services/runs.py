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


async def succeed(run: ToolRun, result: dict[str, Any]) -> bool:
    """返回 True 表示本次调用完成了终态迁移，调用方负责提交后发事件。"""
    return await _update_active(run, {
        "status": SUCCEEDED, "progress": 100, "result": result,
        "error": None, "finished_at": datetime.now(UTC),
    })


async def fail(run: ToolRun, *, code: str, message: str, recoverable: bool = True) -> bool:
    """只落状态，不发事件：失败帧必须等事务提交后再推。"""
    return await _update_active(run, {
        "status": FAILED,
        "error": {"code": code, "message": message, "recoverable": recoverable},
        "finished_at": datetime.now(UTC),
    })


async def mark_enqueue_failed(run: ToolRun) -> bool:
    """队列投递失败：把已提交的 queued 任务切成可重试的 failed。

    只改状态不提交；调用方提交后再 publish_terminal。
    """
    return await fail(
        run,
        code="enqueue_failed",
        message="任务队列不可用，请稍后重试",
        recoverable=True,
    )


async def cancel(run: ToolRun) -> bool:
    """只落状态，不发事件；调用方提交后调用 publish_terminal。"""
    return await _update_active(run, {
        "status": CANCELLED, "finished_at": datetime.now(UTC),
    })


async def publish_terminal(run: ToolRun) -> None:
    """在事务提交后发布终态事件。

    必须先 commit：前端收到 error 会立刻 continue 计划，此刻数据库里
    仍然是 running 的话 continue 会 409，整轮计划就停住了。
    """
    if not run.is_terminal:
        return
    if run.status == FAILED:
        error = run.error or {}
        await events.publish(
            ErrorEvent(
                run_id=run.id,
                code=str(error.get("code") or "task_failed"),
                message=str(error.get("message") or "任务失败"),
                recoverable=bool(error.get("recoverable", True)),
            )
        )
    await events.publish(DoneEvent(run_id=run.id, status=run.status))
