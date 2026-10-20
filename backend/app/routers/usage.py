"""使用概览接口（用户视角）。

与 `/agent/metrics` 的分工：
    /agent/metrics —— 研发看板：拒绝率、计划步数、prompt 版本对比
    /usage/summary —— 用户看板：成功几次、失败几次、平均多久、生成几张图
两个都留着，但左侧导航只暴露后者。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.usage import UsageSummaryOut
from app.services import usage as usage_service

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary", response_model=UsageSummaryOut)
async def usage_summary(
    days: int = Query(default=7, ge=1, le=90),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsageSummaryOut:
    return await usage_service.summary(session, user.id, days=days)
