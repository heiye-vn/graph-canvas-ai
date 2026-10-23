"""Agent 对话轮服务（M9.2）—— LangGraph 图驱动，REST 契约与 M8 完全一致。

职责只剩三件：
    1. draft：占位先行（planning），前端拿到 run_id 就能订阅 CoT
    2. 图驱动：astream 逐节点把 plan 增量写回 agent_runs（刷新现场永远干净）
    3. resume 入口：确认 / 排队步回调 / 重试 —— 全部是同一个
       Command(resume) 机制，状态由 PostgresSaver 落库（DoD ② 的根基）

状态来源分两层：步骤状态机仍在 plan JSONB（agent/plan.py 的纯函数），
图的推进/中断/恢复由 checkpointer 负责 —— 双写但单一真相源是 plan JSONB
（前端契约），checkpointer 是图的执行现场。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from weakref import WeakValueDictionary

from fastapi import HTTPException, status
from langgraph.types import Command
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import plan as plan_mod
from app.agent.checkpointer import get_checkpointer
from app.agent.graph import CONFIRM, build_graph
from app.db import get_engine
from app.models import AgentRun, ToolRun
from app.models.agent_run import (
    AWAITING_CONFIRM,
    CANCELLED,
    PLANNING,
    RUNNING,
    TERMINAL,
)
from app.schemas.events import DoneEvent
from app.services import events
from app.services import queue as queue_service
from app.services import runs as runs_service
from app.services import traces as traces_service
from app.tools.registry import get_tool

logger = logging.getLogger("graph-canvas-ai.agent")

# 本地锁减少同进程争用；真正的轮级互斥由数据库事务 advisory lock 提供。
_drive_locks: WeakValueDictionary[uuid.UUID, asyncio.Lock] = WeakValueDictionary()

# 事件循环持有强引用：不自己存的话，后台图可能在执行中被 GC 掉
_background_tasks: set[asyncio.Task[Any]] = set()

# 子任务超过这个时长仍未结束即视为丢失：worker 崩溃不会留下任何回调，
# 不主动收尸的话父轮次会永远停在 running（job_timeout 是 5 分钟）。
STALE_TASK_SECONDS = 15 * 60

_OPEN_STEPS = frozenset({plan_mod.PENDING, plan_mod.WAITING, plan_mod.QUEUED})


def _background_done(task: asyncio.Task[Any]) -> None:
    _background_tasks.discard(task)
    if task.cancelled():
        return
    exc = task.exception()  # 主动取走，避免 asyncio 只在 GC 时打一条无上下文的告警
    if exc is not None:
        logger.error("后台图任务异常退出", exc_info=exc)


def _spawn_background(coro: Any) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_done)
    return task


async def shutdown_background_tasks() -> None:
    """停机前取消在途图任务：连接池关闭后它们不可能再安全推进。"""
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        _, pending = await asyncio.wait(tasks, timeout=10)
        if pending:
            logger.warning("停机时仍有 %d 个图任务未退出（放弃等待）", len(pending))


def _drive_lock(run_id: uuid.UUID) -> asyncio.Lock:
    return _drive_locks.setdefault(run_id, asyncio.Lock())


async def draft(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, instruction: str
) -> AgentRun:
    """预创建一轮「规划中」的占位，返回后立即由后台任务驱动图。

    占位先行是 CoT 实时性的前提：前端拿到 run_id 就能订阅
    /events/agent/{id}，模型边想边推，一个 token 都不用等规划结束。
    """
    from app.services import sessions as sessions_service

    await sessions_service.get_edit_session(session, user_id, session_id)  # 归属校验
    turn = AgentRun(
        user_id=user_id,
        session_id=session_id,
        instruction=instruction,
        plan=[],
        status=PLANNING,
    )
    session.add(turn)
    await session.commit()
    await session.refresh(turn)

    # API 进程内后台驱动图：请求立刻返回，token 走 Redis 推给订阅者。
    # 必须用独立会话（请求级 session 会随响应关闭）
    _spawn_background(_drive(turn.id))
    return turn


async def confirm(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id, lock=True)
    if turn.status != AWAITING_CONFIRM:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="这轮计划不在等待确认的状态")
    turn.status = RUNNING
    turn.reply = turn.reply or "已确认，开始执行。"
    await session.commit()
    await _drive(run_id, resume={"action": CONFIRM})
    await session.refresh(turn)
    return turn


async def cancel(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id, lock=True)
    if turn.is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="这轮计划已经结束，无需取消")

    steps = plan_mod.cancel_remaining([dict(step) for step in turn.plan])
    # 级联取消：已投递还没跑的任务一并停掉（worker 见终态即跳过）
    cancelled_runs: list[ToolRun] = []
    for step in steps:
        if step["status"] == plan_mod.CANCELED and step.get("run_id"):
            tool_run = await session.get(ToolRun, uuid.UUID(step["run_id"]))
            if tool_run is not None and await runs_service.cancel(tool_run):
                cancelled_runs.append(tool_run)
    turn.plan = steps
    turn.status = CANCELLED
    await session.commit()
    await session.refresh(turn)
    for tool_run in cancelled_runs:
        await runs_service.publish_terminal(tool_run)
    await events.publish(DoneEvent(run_id=turn.id, status=turn.status))
    return turn


async def retry_step(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    """从失败处续跑：重置失败步，以新输入重启同一线程（用户已确认过，不再设卡）。

    反思重规划（reflect）是图内的**自动**行为；这个端点是**人工**重试 ——
    自动重试到上限（MAX_REPLANS）降级为 failed 后，就轮到它接手。
    """
    turn = await _get(session, user_id, run_id, lock=True)
    failed = next(
        (step for step in reversed(turn.plan) if step["status"] == plan_mod.FAILED), None
    )
    if turn.status != "failed" or failed is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="没有可重试的失败步骤")
    failed["run_id"] = None
    failed["message"] = None
    failed["status"] = plan_mod.PENDING
    patched_plan = [dict(step) for step in turn.plan]
    turn.plan = patched_plan
    turn.status = RUNNING
    turn.error = None
    await session.commit()

    await _drive(
        run_id,
        input_state={
            "plan": patched_plan,
            "approved": True,  # 人工重试本身就是明确指令，不再设确认卡
            "replans": 0,
        },
    )
    await session.refresh(turn)
    return turn


async def continue_after_tool_run(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID, tool_run_id: uuid.UUID
) -> AgentRun:
    """某个排队步的 ToolRun 结束了：resume 图，observe 节点核对终态后继续推进。"""
    turn = await _get(session, user_id, run_id)
    if turn.is_terminal:
        return turn
    tool_run = await runs_service.get_run(session, user_id, tool_run_id)
    if not any(step.get("run_id") == str(tool_run.id) for step in turn.plan):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="这个任务不属于该计划"
        )

    if not tool_run.is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="后台任务尚未结束")
    if not any(
        step.get("run_id") == str(tool_run.id) and step["status"] == plan_mod.QUEUED
        for step in turn.plan
    ):
        return turn
    await _drive(run_id, resume={"action": "tool_done", "run_id": str(tool_run.id)})
    await session.refresh(turn)
    return turn


# ------------------------------------------------------------------ 图驱动


async def _drive(
    run_id: uuid.UUID,
    *,
    resume: dict[str, Any] | None = None,
    input_state: dict[str, Any] | None = None,
    continue_existing: bool = False,
) -> None:
    async with _drive_lock(run_id):
        # 专用连接上的事务锁跨越图内各事务，异常/连接断开自动释放，无租约过期窗口。
        # 不锁 AgentRun 行：取消仍能独立提交；锁失败时绝不读取 checkpoint 或执行工具。
        key = int.from_bytes(
            hashlib.blake2b(f"agent-drive:{run_id}".encode(), digest_size=8).digest(),
            "big", signed=True,
        )
        async with get_engine().connect() as connection, connection.begin():
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key},
            )
            if not acquired:
                return
            await _drive_once(
                run_id,
                resume=resume,
                input_state=input_state,
                continue_existing=continue_existing,
            )


async def _drive_once(
    run_id: uuid.UUID,
    *,
    resume: dict[str, Any] | None = None,
    input_state: dict[str, Any] | None = None,
    continue_existing: bool = False,
) -> None:
    """驱动一次图执行（新起 / resume / 带输入重启），plan 增量实时落回 agent_runs。

    astream(stream_mode="updates") 逐节点产出增量：plan 一变就落库 ——
    「上一步已完成、下一步未开始」的中间现场对外永远可见（DoD ④ 延续）。

    恢复时不能盲目 astream(None)：图可能已经停在 END（confirm/retry 的驱动请求
    丢在 advisory lock 竞争或崩溃里），对结束的图传 None 不会执行任何节点。
    """
    async with runs_service.session_scope() as session:
        turn = await session.get(AgentRun, run_id)
        if turn is None or turn.status in TERMINAL:
            return
        if resume and resume.get("action") == "tool_done" and not any(
            step.get("run_id") == resume.get("run_id")
            and step["status"] == plan_mod.QUEUED for step in turn.plan
        ):
            return
        started = time.monotonic()
        interrupted_kind: str | None = None
        state_acc: dict[str, Any] = {}
        try:
            checkpointer = await get_checkpointer()
            graph = build_graph().compile(checkpointer=checkpointer)
            config = {"configurable": {"thread_id": str(run_id)}}

            checkpoint_tuple = None
            if hasattr(checkpointer, "aget_tuple"):
                checkpoint_tuple = await checkpointer.aget_tuple(config)
            elif hasattr(checkpointer, "get_tuple"):
                checkpoint_tuple = checkpointer.get_tuple(config)

            snapshot = await _snapshot_of(graph, config) if checkpoint_tuple else None
            completed = snapshot is not None and not snapshot.next

            restart = dict(input_state) if input_state is not None else None
            if (
                restart is None
                and completed
                and turn.status in (PLANNING, RUNNING)
                and _has_unfinished(turn.plan)
            ):
                # retry_step / confirm 已提交 DB，但图还停在上一轮的 END：
                # 用 DB 计划（以及已确认的事实）重新开局，否则这一轮永远不动。
                restart = {
                    "plan": [dict(step) for step in turn.plan],
                    "approved": True,
                    "replans": 0,
                }

            if restart is not None:
                stream = graph.astream(
                    _seed_state(turn, restart, approved=bool(restart.get("approved", True))),
                    config,
                    stream_mode="updates",
                )
            elif completed:
                # 图已收尾，只差把最终现场写回 DB：用 checkpoint 的 plan/errors 结算。
                # checkpoint 先于 DB 落盘，崩溃恢复时它才是更新的那一份。
                values = _snapshot_values(snapshot)
                plan = values.get("plan")
                state_acc = {
                    **values,
                    "plan": (
                        [dict(step) for step in plan]
                        if isinstance(plan, list) and plan
                        else [dict(step) for step in (turn.plan or [])]
                    ),
                }
                stream = None
            elif resume is not None and checkpoint_tuple is not None:
                # checkpoint 可能领先于 DB（plan 已落盘、增量还没写回）：先带上现场，
                # 否则 resume 若只重新挂起中断，最终写回会把计划覆盖成空
                state_acc.update(_snapshot_plan(snapshot))
                stream = graph.astream(Command(resume=resume), config, stream_mode="updates")
            elif continue_existing and checkpoint_tuple is not None:
                # 断点继续：只差没跑完的节点；pending interrupt 会重新挂起。
                if turn.status not in (PLANNING, RUNNING):
                    return
                state_acc.update(_snapshot_plan(snapshot))
                stream = graph.astream(None, config, stream_mode="updates")
            else:
                approved = bool(resume and resume.get("action") == CONFIRM) or any(
                    step.get("status") in (plan_mod.RUNNING, plan_mod.QUEUED, plan_mod.SUCCEEDED)
                    for step in (turn.plan or [])
                )
                stream = graph.astream(
                    _seed_state(turn, {}, approved=approved),
                    config,
                    stream_mode="updates",
                )

            # ⚠️ stream_mode="updates" 的增量是 {节点名: {channel: 值}}，
            # 不是扁平的 channel 字典 —— 拍平前先剥节点名。
            if stream is not None:
                async for update in stream:
                    if not update:
                        continue
                    for key, delta in update.items():
                        if key == "__interrupt__":
                            for one in delta or ():
                                value = getattr(one, "value", None) or {}
                                interrupted_kind = value.get("kind")
                            continue
                        if not isinstance(delta, dict):
                            continue
                        state_acc.update(delta)
                        if isinstance(delta.get("plan"), list):
                            if not await _persist_active(
                                session, turn, plan=delta["plan"], status=RUNNING,
                            ):
                                return
        except Exception as exc:  # noqa: BLE001 - 图内任何异常都转成失败轮，绝不把占位挂死
            logger.exception("图执行异常 run_id=%s", run_id)
            await session.rollback()
            await session.refresh(turn)
            if not await _persist_active(
                session, turn, status="failed", error=str(exc) or "执行失败，可重试或取消",
            ):
                return
            await events.publish(DoneEvent(run_id=turn.id, status=turn.status))
            return

        final_plan = state_acc.get("plan", list(turn.plan or []))
        final_values: dict[str, Any] = {"plan": final_plan}
        if interrupted_kind == CONFIRM:
            final_values["status"] = AWAITING_CONFIRM
            final_values["reply"] = turn.reply or "将按以下步骤执行，确认后开始。"
        elif interrupted_kind is not None:
            final_values["status"] = RUNNING  # wait_run：排队步在飞，不算结束
        else:
            status, error = _final_status(final_plan, state_acc.get("errors"))
            final_values["status"] = status
            if error is not None:
                final_values["error"] = error
        if not await _persist_active(session, turn, **final_values):
            return

        # 轮级 span：整轮状态 / 重规划次数（M9.3 trace）
        await traces_service.record_detached(
            turn.id,
            turn.session_id,
            kind="turn",
            name="agent_turn",
            status="ok" if turn.status in {"succeeded", "awaiting_confirm"} else "failed",
            started=started,
            detail={
                "status": turn.status,
                "steps": len(final_plan),
                "interrupted": interrupted_kind,
                "errors": state_acc.get("errors") or [],
            },
        )
        await events.publish(DoneEvent(run_id=turn.id, status=turn.status))


async def _snapshot_of(graph: Any, config: dict[str, Any]) -> Any | None:
    """读图的最新现场；旧桩/旧版没有 aget_state 时返回 None（按原逻辑继续）。"""
    getter = getattr(graph, "aget_state", None)
    if getter is None:
        return None
    return await getter(config)


def _snapshot_values(snapshot: Any) -> dict[str, Any]:
    values = getattr(snapshot, "values", None)
    return dict(values) if isinstance(values, dict) else {}


def _snapshot_plan(snapshot: Any) -> dict[str, Any]:
    plan = _snapshot_values(snapshot).get("plan")
    return {"plan": [dict(step) for step in plan]} if isinstance(plan, list) and plan else {}


def _has_unfinished(plan: list[dict[str, Any]]) -> bool:
    return any(step.get("status") in _OPEN_STEPS for step in plan)


def _seed_state(turn: AgentRun, extra: dict[str, Any], *, approved: bool) -> dict[str, Any]:
    """新起图时的完整输入；显式传入的字段（重试计划等）优先。"""
    base = dict(extra)
    base.setdefault("run_id", str(turn.id))
    base.setdefault("user_id", str(turn.user_id))
    base.setdefault("session_id", str(turn.session_id))
    base.setdefault("instruction", turn.instruction)
    base.setdefault("plan", [dict(step) for step in (turn.plan or [])])
    base.setdefault("errors", [])
    base.setdefault("replans", 0)
    base.setdefault("approved", approved)
    return base


async def _persist_active(session: AsyncSession, turn: AgentRun, **values: Any) -> bool:
    """增量与最终写回均不允许覆盖已提交的取消/其他终态。"""
    with session.no_autoflush:
        result = await session.execute(
            update(AgentRun)
            .where(AgentRun.id == turn.id, AgentRun.status.not_in(TERMINAL))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
    await session.commit()
    await session.refresh(turn)
    return result.rowcount == 1


def _last_error(state_acc: dict[str, Any]) -> str | None:
    errors = state_acc.get("errors") or []
    return str(errors[-1]) if errors else None


def _final_status(
    plan: list[dict[str, Any]], errors: list[str] | None
) -> tuple[str, str | None]:
    """收尾状态。空计划有两种：规划失败（有 errors）或模型判断无需工具（闲聊）。"""
    if not plan:
        return ("failed", str(errors[-1])) if errors else ("succeeded", None)
    status = plan_mod.settle(plan)
    if status != "failed":
        return status, None
    return status, str(errors[-1]) if errors else "执行失败，可重试或取消"


async def _get(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False,
) -> AgentRun:
    stmt = select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    turn = await session.scalar(stmt)
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="对话轮不存在")
    return turn


def _is_stale(tool_run: ToolRun) -> bool:
    anchor = tool_run.started_at or tool_run.created_at
    if anchor is None:
        return False
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return (datetime.now(UTC) - anchor).total_seconds() >= STALE_TASK_SECONDS


async def _fail_stale(session: AsyncSession, tool_run: ToolRun) -> None:
    """把长时间没有结论的任务切成可重试失败；提交后再发终态事件。"""
    changed = await runs_service.fail(
        tool_run,
        code="task_lost",
        message="任务长时间没有结束，已自动终止；请重试",
        recoverable=True,
    )
    if changed:
        await session.commit()
    await runs_service.publish_terminal(tool_run)


async def _recover_waiting(session: AsyncSession, turn: AgentRun) -> None:
    """刷新/轮询时补偿丢失的 continue；同时给失联的 worker 收尸。

    · 子任务已终态 → resume 图，observe 核对后继续
    · 子任务超时未结束 → 切成可重试失败，再 resume（否则父轮次永远 running）
    · 没有任何子任务在等却仍是 running → 驱动请求丢在锁竞争里，重驱一次
    """
    if turn.status != RUNNING or _drive_lock(turn.id).locked():
        return
    waiting = [
        step
        for step in (turn.plan or [])
        if step.get("status") == plan_mod.QUEUED and step.get("run_id")
    ]
    if not waiting:
        await _drive(turn.id, continue_existing=True)
        await session.refresh(turn)
        return
    for step in waiting:
        tool_run = await runs_service.get_run(session, turn.user_id, uuid.UUID(step["run_id"]))
        if tool_run.is_terminal:
            await _drive(turn.id, resume={"action": "tool_done", "run_id": str(tool_run.id)})
            await session.refresh(turn)
            return
        if _is_stale(tool_run):
            await _fail_stale(session, tool_run)
            await _drive(turn.id, resume={"action": "tool_done", "run_id": str(tool_run.id)})
            await session.refresh(turn)
            return


async def recover_pending() -> None:
    """API 启动后接续未完成的轮次；多实例由 _drive 的 advisory lock 去重。"""
    async with runs_service.session_scope() as session:
        run_ids = (
            await session.scalars(
                select(AgentRun.id).where(AgentRun.status.in_((PLANNING, RUNNING)))
            )
        ).all()
    for run_id in run_ids:
        try:
            await _recover_one(run_id)
        except Exception:  # noqa: BLE001 - 单轮恢复失败不能挡住其他轮次
            logger.exception("恢复 Agent 轮次失败 run_id=%s", run_id)


async def _redeliver(tool_run: ToolRun) -> None:
    """补投可能没到达 ARQ 的排队任务；_job_id=run_id 让重复补投天然幂等。

    ARQ 在任务执行期间仍保留 job key，运行中的任务重复投递会被去重；
    只有 job/result 都不存在（worker 崩溃或投递丢失）时才会真正重新入队。
    """
    spec = get_tool(tool_run.tool)
    task = spec.queue_task if spec is not None and spec.queue_task else tool_run.tool
    if spec is None:
        logger.warning("补偿投递：工具 %s 未注册，按同名任务投递", tool_run.tool)
    try:
        await queue_service.enqueue(task, tool_run.id)
    except queue_service.EnqueueFailed:
        logger.warning(
            "补偿投递失败 tool_run=%s tool=%s", tool_run.id, tool_run.tool, exc_info=True
        )


async def _recover_one(run_id: uuid.UUID) -> None:
    resume: dict[str, Any] | None = None
    should_drive = False
    async with runs_service.session_scope() as session:
        turn = await session.get(AgentRun, run_id)
        if turn is None or turn.status not in (PLANNING, RUNNING):
            return
        waiting = [
            step
            for step in (turn.plan or [])
            if step.get("status") == plan_mod.QUEUED and step.get("run_id")
        ]
        for step in waiting:
            tool_run = await runs_service.get_run(
                session, turn.user_id, uuid.UUID(str(step["run_id"]))
            )
            if tool_run.is_terminal:
                resume = {"action": "tool_done", "run_id": str(tool_run.id)}
                should_drive = True
                break
            # 进程可能崩在「run 已提交、ARQ 尚未投递」之间；
            # 运行中的任务也补投一次，由 ARQ 的 job id 去重兜底。
            await _redeliver(tool_run)
        if not waiting:
            # 规划中/执行中但没在等子任务：从 checkpoint / DB 现场继续
            should_drive = True
    if should_drive:
        await _drive(run_id, resume=resume, continue_existing=True)


async def get(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id)
    await _recover_waiting(session, turn)
    return turn


async def list_for_session(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, limit: int = 30
) -> list[AgentRun]:
    result = await session.scalars(
        select(AgentRun)
        .where(AgentRun.session_id == session_id, AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    turns = list(reversed(result.all()))
    for turn in turns:
        await _recover_waiting(session, turn)
    return turns
