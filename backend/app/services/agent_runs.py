"""多步计划的执行引擎（M8/M9.1）—— 规划 / 确认 / 取消 / 重试 / 推进。

状态流转（整轮）：planning → awaiting_confirm → running → succeeded/failed/cancelled。
步骤状态存在 plan JSONB 里，由 agent/plan.py 的状态机函数统一裁决；
本模块只负责「把该跑的步骤跑起来」和「把跑完的状态写回去」。

三条硬规矩：
    1. 同步步走 apply_tool_calls —— 与手动执行同一条路，撤销栈才完整
    2. 每个同步步一个事务，跑完立即落库 —— 「上一步完了、下一步还没
       开始」的中间态对外永远不可见（DoD ④ 的根基）
    3. 排队步投递后本轮自然停住，等对应 ToolRun 完成后由
       continue_after_tool_run 接着推进 —— 前端刷新也能从库里恢复现场

M9.1：规划改为「占位先行 + 后台流式」——draft() 秒回 planning 占位，
_plan_and_fill 在 API 进程内跑，思考 token 经 services/cot.py 实时推送；
执行期每步前后也发 observation，同一条 cot 通道。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import llm as llm_module
from app.agent import plan as plan_mod
from app.agent.plan import PlanError
from app.models import AgentRun, EditSession, ToolRun
from app.models.agent_run import (
    AWAITING_CONFIRM,
    CANCELLED,
    PLANNING,
    RUNNING,
    TERMINAL,
)
from app.models.run import CANCELLED as RUN_CANCELLED
from app.models.run import FAILED as RUN_FAILED
from app.models.run import SUCCEEDED as RUN_SUCCEEDED
from app.schemas.events import DoneEvent
from app.services import cot as cot_service
from app.services import events, tool_exec
from app.services import history as history_service
from app.services import runs as runs_service

logger = logging.getLogger("graph-canvas-ai.agent")

# ToolRun 的终态 → 计划步骤状态（字符串一致，显式映射防漂移）
_RUN_TO_STEP = {
    RUN_SUCCEEDED: plan_mod.SUCCEEDED,
    RUN_FAILED: plan_mod.FAILED,
    RUN_CANCELLED: plan_mod.CANCELED,
}


async def draft(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, instruction: str
) -> AgentRun:
    """预创建一轮「规划中」的占位，返回后立即由后台任务流式规划。

    占位先行是 CoT 实时性的前提：前端拿到 run_id 就能订阅
    /events/agent/{id}，模型边想边推，一个 token 都不用等规划结束。
    """
    await sessions_get(session, user_id, session_id)  # 归属校验
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

    # API 进程内后台规划：请求立刻返回，token 走 Redis 推给订阅者。
    # 规划只有几秒，不值得过 ARQ；但必须用独立会话，不能复用请求级 session
    task = asyncio.create_task(_plan_and_fill(turn.id))
    turn.__dict__["_plan_task"] = task  # 仅持引用防 GC，无业务含义
    return turn


async def _plan_and_fill(run_id: uuid.UUID) -> None:
    """后台流式规划：思考 token 经 cot 通道实时推送，结束后更新占位轮。"""
    async with runs_service.session_scope() as session:
        turn = await session.get(AgentRun, run_id)
        if turn is None or turn.status != PLANNING:
            return
        emit = _emitter(turn.id)

        reply, steps, error = "", [], None
        try:
            edit_session = await sessions_get(session, turn.user_id, turn.session_id)
            doc = history_service.LayerDocument.model_validate(edit_session.doc)
            calls = await llm_module.plan_tool_calls_stream(
                turn.instruction,
                tool_exec.summarize_doc(doc),
                _function_schemas(),
                emit,
            )
            # planner 吐的是 {name, args}（function calling 惯例），归一成计划的 {tool, params}
            steps = plan_mod.validate(
                [{"tool": call.get("name"), "args": call.get("args") or {}} for call in calls]
            )
        except llm_module.PlannerError as exc:
            error = str(exc)
            steps = []
        except PlanError as exc:
            error = str(exc)
            steps = []
        except Exception:  # noqa: BLE001 - 规划层的任何意外都转成人话，绝不 500
            logger.exception("计划规划异常 run_id=%s", run_id)
            error = "规划失败，请重试"
            steps = []

        if error:
            turn.status = "failed"
            await emit("reflection", error)
        elif plan_mod.needs_confirm(steps):
            turn.status = AWAITING_CONFIRM
            reply = "将按以下步骤执行，确认后开始。"
            await emit("observation", "计划已就绪，等待确认")
        elif steps:
            turn.status = RUNNING
            await emit("observation", "单步计划，直接执行")
        else:
            turn.status = "succeeded"
            reply = "这句话没有对应到可执行的操作，换一种说法试试。"
            await emit("observation", reply)

        turn.plan = steps
        turn.reply = reply
        turn.error = error
        await session.commit()
        await events.publish(DoneEvent(run_id=turn.id, status=turn.status))

        if turn.status == RUNNING:
            turn = await _advance(session, turn)
            await events.publish(DoneEvent(run_id=turn.id, status=turn.status))


def _emitter(run_id: uuid.UUID):
    async def emit(kind: str, delta: str) -> None:
        await cot_service.emit(run_id, kind, delta)

    return emit


async def confirm(session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun:
    turn = await _get(session, user_id, run_id)
    if turn.status != AWAITING_CONFIRM:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="这轮计划不在等待确认的状态")
    turn.status = RUNNING
    turn.reply = turn.reply or "已确认，开始执行。"
    await session.commit()
    return await _advance(session, turn)


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
    """从最后一个失败步重试：只重置它自己，依赖它的后续会跟着状态机自然解锁。"""
    turn = await _get(session, user_id, run_id)
    failed = next(
        (step for step in reversed(turn.plan) if step["status"] == plan_mod.FAILED), None
    )
    if failed is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="没有可重试的失败步骤")
    failed["run_id"] = None
    failed["message"] = None
    failed["status"] = plan_mod.PENDING
    turn.plan = [dict(step) for step in turn.plan]
    turn.status = RUNNING
    turn.error = None
    await session.commit()
    return await _advance(session, turn)


async def continue_after_tool_run(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID, tool_run_id: uuid.UUID
) -> AgentRun:
    """某个排队步的 ToolRun 结束了：把结果写回步骤，然后继续推进。"""
    turn = await _get(session, user_id, run_id)
    tool_run = await runs_service.get_run(session, user_id, tool_run_id)

    steps = [dict(step) for step in turn.plan]
    target = next((step for step in steps if step.get("run_id") == str(tool_run.id)), None)
    if target is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="这个任务不属于该计划")
    target["status"] = _RUN_TO_STEP.get(tool_run.status, plan_mod.FAILED)
    if tool_run.error:
        target["message"] = tool_run.error.get("message")
    elif tool_run.status == RUN_SUCCEEDED:
        target["message"] = "完成"
    turn.plan = steps
    await session.commit()

    if turn.status == RUNNING:
        return await _advance(session, turn)
    return turn


# ------------------------------------------------------------------ 推进


async def _advance(session: AsyncSession, turn: AgentRun) -> AgentRun:
    """把当前所有 ready 的步骤跑掉；排队步投出去就停，等回调再推进。"""
    emit = _emitter(turn.id)
    steps = [dict(step) for step in turn.plan]
    progressed = True
    while progressed:
        progressed = False
        for step in plan_mod.ready(steps):
            await emit("observation", f"开始执行第 {step['id']} 步：{step['tool']}")
            updated, results = await history_service.apply_tool_calls(
                session,
                user_id=turn.user_id,
                session_id=turn.session_id,
                calls=[history_service.ToolCall(name=step["tool"], params=step["params"])],
            )
            result = results[0] if results else None
            if result is None:
                step["status"] = plan_mod.FAILED
                step["message"] = "步骤执行失败"
                await emit("observation", "失败：步骤执行失败")
                progressed = True
            elif result.run_id:
                # 排队步：run 已由 apply_tool_calls 投递，等 ToolRun 终态回调
                step["run_id"] = str(result.run_id)
                step["status"] = plan_mod.QUEUED
                step["message"] = result.message
                await emit("observation", f"已提交后台任务：{result.message}")
            elif result.ok:
                step["status"] = plan_mod.SUCCEEDED
                step["message"] = result.message
                await emit("observation", f"完成：{result.message}")
                progressed = True
            else:
                step["status"] = plan_mod.FAILED
                step["message"] = result.message
                await emit("observation", f"失败：{result.message}")
                progressed = True
            # 步骤级变更立即落库（apply_tool_calls 已提交文档/历史，这里补计划本身）
            turn.plan = [dict(item) for item in steps]
            turn.status = RUNNING
            await session.commit()
            if step["status"] == plan_mod.QUEUED:
                progressed = False  # 异步步：本轮到此为止
                break

    turn.plan = [dict(item) for item in steps]
    turn.status = plan_mod.settle(steps)
    await session.commit()
    await session.refresh(turn)
    return turn


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


def _function_schemas() -> list[dict[str, Any]]:
    from app.tools.registry import function_schemas

    return function_schemas()


async def sessions_get(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> EditSession:
    from app.services import sessions as sessions_service

    return await sessions_service.get_edit_session(session, user_id, session_id)
