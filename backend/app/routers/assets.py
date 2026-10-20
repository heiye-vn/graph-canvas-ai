from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.asset import (
    AssetListResponse,
    AssetOut,
    ConfirmUploadRequest,
    UploadTicket,
    UploadTicketRequest,
)
from app.services import assets as asset_service
from app.services import storage

router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/upload-ticket", response_model=UploadTicket)
async def create_upload_ticket(
    payload: UploadTicketRequest,
    user: User = Depends(get_current_user),
) -> UploadTicket:
    # ticket 里的 size/mime 只是**预声明**，真正的校验在上传后按文件内容做
    try:
        return asset_service.create_upload_ticket(user.id, payload, get_settings())
    except ValueError as exc:
        # 体积超限 / 类型不支持：都是「客户端换个文件重试」级别的错误
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/upload-direct", status_code=status.HTTP_204_NO_CONTENT)
async def upload_direct(
    key: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> None:
    """后端直传通道（ASSET_UPLOAD_MODE=backend 时使用）。

    切到预签名模式后这个端点不再被调用，保留它是为了让两种模式可随时回退。
    """
    if not asset_service.key_belongs_to(key, user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权上传到该路径")

    data = await read_capped(file)
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件内容为空")

    asset_service.store_bytes(key, data, file.content_type or "application/octet-stream")


async def read_capped(file: UploadFile) -> bytes:
    """按上限流式读取。

    ticket 里的 size 只是客户端**声明**，不能当真：声明 1MB 却真传 1GB 的请求
    会让 file.read() 把整个 body 灌进内存。这里边读边计数，超限立即 413。
    """
    limit = get_settings().asset_max_size_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"文件超过 {get_settings().asset_max_size_mb}MB 上限",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/confirm", response_model=AssetOut)
async def confirm_upload(
    payload: ConfirmUploadRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetOut:
    try:
        asset = await asset_service.confirm_upload(session, user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return asset_service.asset_to_out(asset)


@router.get("", response_model=AssetListResponse)
async def list_assets(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetListResponse:
    items = await asset_service.list_assets(session, user.id)
    return AssetListResponse(items=[asset_service.asset_to_out(a) for a in items])


@router.get("/{asset_id}", response_model=AssetOut)
async def get_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AssetOut:
    asset = await asset_service.get_asset(session, user.id, asset_id)
    return asset_service.asset_to_out(asset)


@router.get("/{asset_id}/thumb")
async def asset_thumb(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """素材缩略图：首次请求现生成 480px 小图落桶（写穿缓存），之后 307 到预签名地址。

    生成失败（源文件损坏等）降级回原始大图 —— 缩略图是锦上添花，
    不能因为它没出来就让素材看不了。
    """
    asset = await asset_service.get_asset(session, user.id, asset_id)
    try:
        key = asset_service.ensure_thumb(asset)
    except Exception:  # noqa: BLE001
        key = asset.s3_key
    return RedirectResponse(storage.presign_get(key), status_code=307)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await asset_service.delete_asset(session, user.id, asset_id)
