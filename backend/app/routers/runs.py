from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import ToolRun, User
from app.models.run import TERMINAL_STATUSES
from app.services import queue
from app.services import runs as runs_service

router = APIRouter(prefix="/runs", tags=["runs"])

TOOL_TEXT_TO_IMAGE = "text_to_image"


class TextToImageRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    size: str = Field(default="1024x1024", pattern=r"^\d{2,4}x\d{2,4}$")
    n: int = Field(default=1, ge=1, le=4)

    @field_validator("prompt")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """只校验长度是不够的：一串空格照样能过 min_length=1。

        顺便 trim 一下——前后空白对模型没有意义，留着只会让「看起来一样」的
        prompt 生成出不同的图（mock provider 的种子是按字符算的）。
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("prompt 不能为空")
        return stripped


class RunOut(BaseModel):
    id: uuid.UUID
    tool: str
    status: str
    progress: int
    stage: str | None
    params: dict
    result: dict | None = None
    error: dict | None = None

    model_config = {"from_attributes": True}


@router.post("/text-to-image", status_code=status.HTTP_202_ACCEPTED)
async def create_text_to_image(
    payload: TextToImageRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> RunOut:
    """建任务并入队。

    返回 202：任务只是被接受，结果通过 /events/runs/{id} 或轮询 /runs/{id} 获取。
    """
    _check_size(payload.size, settings)

    run = await runs_service.create_run(
        session,
        user_id=user.id,
        tool=TOOL_TEXT_TO_IMAGE,
        params={"prompt": payload.prompt, "size": payload.size, "n": payload.n},
    )
    await queue.enqueue(TOOL_TEXT_TO_IMAGE, run.id)
    return RunOut.model_validate(run)


@router.get("", response_model=list[RunOut])
async def list_runs(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ToolRun]:
    return await runs_service.list_runs(session, user.id)


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ToolRun:
    return await runs_service.get_run(session, user.id, run_id)


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ToolRun:
    run = await runs_service.get_run(session, user.id, run_id)
    if run.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已结束，无法取消")
    await runs_service.cancel(run)
    await session.commit()
    # 队列里的任务无法跨进程召回，只能靠 worker 执行时看到 cancelled 自行跳过
    return RunOut.model_validate(run)


def _check_size(size: str, settings: Settings) -> None:
    width, height = (int(x) for x in size.split("x"))
    if not (256 <= width <= 2048 and 256 <= height <= 2048):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="尺寸需在 256~2048 之间",
        )
