"""Agent 单步入口。

响应刻意把每一步都列出来（`steps`）：用户点了「把图调亮一点」之后，
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
