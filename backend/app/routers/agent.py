"""Agent 路由：多步计划（M8）+ 既有单步入口。

M8 起对话默认走 /agent/plan：一句指令 → 计划（>1 步先等确认）→
确认/取消/重试/继续。/agent/step 保留为「直接执行」的单步通道
（不给确认环节，适合简单指令与既有测试）。

响应刻意把每一步都列出来：用户点了「把图调亮一点」之后，
想知道的正是「它到底做了什么」—— 只回一个新文档，等于让他自己 diff。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.agent import AgentRunOut, ContinueRequest, PlanRequest
from app.services import agent_runs as agent_runs_service
from app.services.agent_step import StepOutcome, run_step

router = APIRouter(prefix="/agent", tags=["agent"])


class StepRequest(BaseModel):
    session_id: uuid.UUID
    instruction: str = Field(min_length=1, max_length=1000)


@router.post("/step", response_model=StepOutcome)
async def step(
    payload: StepRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> StepOutcome:
    return await run_step(
        session,
        user_id=user.id,
        session_id=payload.session_id,
        instruction=payload.instruction.strip(),
    )


@router.post("/plan", response_model=AgentRunOut)
async def create_plan(
    payload: PlanRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    """一句指令 → planning 占位（毫秒级返回）。

    规划在后台流式执行：前端拿 run_id 订阅 /events/agent/{id} 收 CoT，
    收到 done 帧后 GET 本轮拿最终计划（M9.1）。
    """
    return await agent_runs_service.draft(
        session,
        user_id=user.id,
        session_id=payload.session_id,
        instruction=payload.instruction.strip(),
    )


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_agent_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    return await agent_runs_service.get(session, user_id=user.id, run_id=run_id)


@router.post("/runs/{run_id}/confirm", response_model=AgentRunOut)
async def confirm_plan(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    return await agent_runs_service.confirm(session, user_id=user.id, run_id=run_id)


@router.post("/runs/{run_id}/cancel", response_model=AgentRunOut)
async def cancel_plan(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    return await agent_runs_service.cancel(session, user_id=user.id, run_id=run_id)


@router.post("/runs/{run_id}/retry", response_model=AgentRunOut)
async def retry_plan(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    return await agent_runs_service.retry_step(session, user_id=user.id, run_id=run_id)


@router.post("/runs/{run_id}/continue", response_model=AgentRunOut)
async def continue_plan(
    run_id: uuid.UUID,
    payload: ContinueRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AgentRunOut:
    """排队步的 ToolRun 结束后由前端驱动继续（刷新后凭 plan 里的 run_id 也能接上）。"""
    return await agent_runs_service.continue_after_tool_run(
        session, user_id=user.id, run_id=run_id, tool_run_id=payload.run_id
    )


@router.get("/sessions/{session_id}/runs", response_model=list[AgentRunOut])
async def list_session_runs(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AgentRunOut]:
    """恢复现场：对话轮列表（含每轮计划与步骤状态）。"""
    return await agent_runs_service.list_for_session(
        session, user_id=user.id, session_id=session_id
    )
