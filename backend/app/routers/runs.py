from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import ToolRun, User
from app.models.run import SUCCEEDED, TERMINAL_STATUSES
from app.schemas.asset import AssetOut
from app.services import assets as asset_service
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


from datetime import datetime

class RunOut(BaseModel):
    id: uuid.UUID
    tool: str
    status: str
    progress: int
    stage: str | None
    params: dict
    result: dict | None = None
    error: dict | None = None
    created_at: datetime | None = None
    cover_url: str | None = None

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
    tool: str | None = Query(default=None, description="按工具名过滤，如 text_to_image"),
    status: str | None = Query(default=None, description="按任务状态过滤，如 succeeded, failed"),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[RunOut]:
    # 当指定了 tool 时，稍微多查一些，避免部分图片已被用户删除的空壳任务占用 limit 名额
    fetch_limit = limit * 2 if tool else limit
    runs = await runs_service.list_runs(session, user.id, limit=fetch_limit, tool=tool, status=status)

    # 批量收集所有任务的 asset_id，以便一次性查询数据库中真正存在的图片及其预签名 URL
    all_asset_ids: list[uuid.UUID] = []
    for r in runs:
        raw_assets = (r.result or {}).get("asset_ids") or []
        for x in raw_assets:
            try:
                all_asset_ids.append(uuid.UUID(str(x)))
            except ValueError:
                pass

    asset_map: dict[uuid.UUID, str] = {}
    if all_asset_ids:
        assets = await asset_service.list_assets_by_ids(session, user.id, all_asset_ids)
        for a in assets:
            asset_map[a.id] = asset_service.asset_to_out(a).url

    outs: list[RunOut] = []
    for r in runs:
        out = RunOut.model_validate(r)
        raw_assets = (r.result or {}).get("asset_ids") or []
        valid_ids: list[uuid.UUID] = []
        for x in raw_assets:
            try:
                uid = uuid.UUID(str(x))
                if uid in asset_map:
                    valid_ids.append(uid)
            except ValueError:
                pass

        # 方案 A：面向创作流的历史素材，只展示成功出图且产物图片在素材库依然存活有效的任务
        if tool == TOOL_TEXT_TO_IMAGE and (r.status != SUCCEEDED or not valid_ids):
            continue

        if valid_ids:
            out.cover_url = asset_map.get(valid_ids[0])
            if out.result:
                out.result["asset_ids"] = [str(x) for x in valid_ids]

        outs.append(out)
        if len(outs) >= limit:
            break
    return outs


@router.get("/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunOut:
    run = await runs_service.get_run(session, user.id, run_id)
    out = RunOut.model_validate(run)
    raw_assets = (run.result or {}).get("asset_ids") or []
    if raw_assets:
        try:
            first_id = uuid.UUID(str(raw_assets[0]))
            assets = await asset_service.list_assets_by_ids(session, user.id, [first_id])
            if assets:
                out.cover_url = asset_service.asset_to_out(assets[0]).url
        except ValueError:
            pass
    return out


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """删除历史任务记录。"""
    run = await runs_service.get_run(session, user.id, run_id)
    await session.delete(run)
    await session.commit()


@router.get("/{run_id}/assets", response_model=list[AssetOut])
async def list_run_assets(
    run_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[AssetOut]:
    """这一次运行产出了哪些图。

    有了这个端点，候选页就不再依赖**内存里的 SSE 事件** —— 刷新页面 / 直接分享链接
    都能还原现场。SSE 只负责实时增量，现场恢复一律走这里。
    """
    run = await runs_service.get_run(session, user.id, run_id)

    raw = (run.result or {}).get("asset_ids") or []
    asset_ids: list[uuid.UUID] = []
    for item in raw:
        try:
            asset_ids.append(uuid.UUID(str(item)))
        except ValueError:
            continue  # 脏数据跳过，不该让一条坏 id 让整个列表 500

    items = await asset_service.list_assets_by_ids(session, user.id, asset_ids)
    return [asset_service.asset_to_out(a) for a in items]


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
