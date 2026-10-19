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
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException, status
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import plan as plan_mod
from app.agent.checkpointer import get_checkpointer
from app.agent.graph import CONFIRM, build_graph
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
from app.services import runs as runs_service
from app.services import traces as traces_service

logger = logging.getLogger("graph-canvas-ai.agent")


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
    task = asyncio.create_task(_drive(turn.id))
    turn.__dict__["_graph_task"] = task  # 仅持引用防 GC，无业务含义
    return turn


async def confirm(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id)
    if turn.status != AWAITING_CONFIRM:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="这轮计划不在等待确认的状态")
    turn.status = RUNNING
    turn.reply = turn.reply or "已确认，开始执行。"
    await session.commit()
    await _drive(run_id, resume={"action": CONFIRM})
    await session.refresh(turn)
    return turn


async def cancel(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id)
    if turn.is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="这轮计划已经结束，无需取消")

    steps = plan_mod.cancel_remaining([dict(step) for step in turn.plan])
    # 级联取消：已投递还没跑的任务一并停掉（worker 见终态即跳过）
    for step in steps:
        if step["status"] == plan_mod.CANCELED and step.get("run_id"):
            tool_run = await session.get(ToolRun, uuid.UUID(step["run_id"]))
            if tool_run is not None and tool_run.status == "queued":
                await runs_service.cancel(tool_run)
    turn.plan = steps
    turn.status = plan_mod.settle(steps) or CANCELLED
    if turn.status not in TERMINAL:
        turn.status = CANCELLED
    await session.commit()
    await session.refresh(turn)
    return turn


async def retry_step(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    """从失败处续跑：重置失败步，以新输入重启同一线程（用户已确认过，不再设卡）。

    反思重规划（reflect）是图内的**自动**行为；这个端点是**人工**重试 ——
    自动重试到上限（MAX_REPLANS）降级为 failed 后，就轮到它接手。
    """
    turn = await _get(session, user_id, run_id)
    failed = next(
        (step for step in reversed(turn.plan) if step["status"] == plan_mod.FAILED), None
    )
    if failed is None:
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
    tool_run = await runs_service.get_run(session, user_id, tool_run_id)
    if not any(step.get("run_id") == str(tool_run.id) for step in turn.plan):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="这个任务不属于该计划"
        )

    await _drive(run_id, resume={"action": "tool_done", "run_id": str(tool_run.id)})
    await session.refresh(turn)
    return turn


# ------------------------------------------------------------------ 图驱动


async def _drive(
    run_id: uuid.UUID,
    *,
    resume: dict[str, Any] | None = None,
    input_state: dict[str, Any] | None = None,
) -> None:
    """驱动一次图执行（新起 / resume / 带输入重启），plan 增量实时落回 agent_runs。

    astream(stream_mode="updates") 逐节点产出增量：plan 一变就落库 ——
    「上一步已完成、下一步未开始」的中间现场对外永远可见（DoD ④ 延续）。
    """
    async with runs_service.session_scope() as session:
        turn = await session.get(AgentRun, run_id)
        if turn is None or turn.status in TERMINAL:
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

            if resume is not None and checkpoint_tuple is not None:
                stream = graph.astream(Command(resume=resume), config, stream_mode="updates")
            else:
                base = dict(input_state or {})
                base.setdefault("run_id", str(run_id))
                base.setdefault("user_id", str(turn.user_id))
                base.setdefault("session_id", str(turn.session_id))
                base.setdefault("instruction", turn.instruction)
                base.setdefault("plan", list(turn.plan or []))
                base.setdefault("errors", [])
                base.setdefault("replans", 0)
                is_approved = (resume.get("action") == CONFIRM) if resume else False
                # 计划已经在跑/跑过（页面刷新后点确认）→ 视为已批准，别卡在确认门
                if any(
                    step.get("status") in ("running", "queued", "succeeded")
                    for step in (turn.plan or [])
                ):
                    is_approved = True
                base.setdefault("approved", is_approved)
                stream = graph.astream(base, config, stream_mode="updates")

            # ⚠️ stream_mode="updates" 的增量是 {节点名: {channel: 值}}，
            # 不是扁平的 channel 字典 —— 拍平前先剥节点名。
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
                        turn.plan = delta["plan"]
                        turn.status = RUNNING
                        await session.commit()
        except Exception as exc:  # noqa: BLE001 - 图内任何异常都转成失败轮，绝不把占位挂死
            logger.exception("图执行异常 run_id=%s", run_id)
            turn.status = "failed"
            turn.error = str(exc) or "执行失败，可重试或取消"
            await session.commit()
            await events.publish(DoneEvent(run_id=turn.id, status=turn.status))
            return

        final_plan = state_acc.get("plan", list(turn.plan or []))
        if interrupted_kind == CONFIRM:
            turn.status = AWAITING_CONFIRM
            turn.reply = turn.reply or "将按以下步骤执行，确认后开始。"
        elif interrupted_kind is not None:
            turn.status = RUNNING  # wait_run：排队步在飞，不算结束
        else:
            turn.status = plan_mod.settle(final_plan)
            # 规划被六道关卡拦下（空计划 + errors）：必须落到 failed，
            # settle 对空计划只能给 succeeded —— 人话在 errors 里
            if not final_plan and state_acc.get("errors"):
                turn.status = "failed"
            if turn.status == "failed":
                turn.error = _last_error(state_acc) or "执行失败，可重试或取消"
        turn.plan = final_plan
        await session.commit()

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


def _last_error(state_acc: dict[str, Any]) -> str | None:
    errors = state_acc.get("errors") or []
    return str(errors[-1]) if errors else None


async def _get(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await session.scalar(
        select(AgentRun).where(AgentRun.id == run_id, AgentRun.user_id == user_id)
    )
    if turn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="对话轮不存在")
    return turn


async def get(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    return await _get(session, user_id, run_id)


async def list_for_session(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, limit: int = 30
) -> list[AgentRun]:
    result = await session.scalars(
        select(AgentRun)
        .where(AgentRun.session_id == session_id, AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.all()))
