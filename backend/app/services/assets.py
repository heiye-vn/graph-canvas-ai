"""素材服务：上传凭据、入库与读取。

上传被刻意做成**两段式契约**（拿 ticket → 上传 → confirm），
因为「后端直传」和「预签名直传」的唯一区别就在第一步拿到的 ticket 内容上，
其余流程完全一致——将来切 ASSET_UPLOAD_MODE=presigned 时前端零改动。
"""

from __future__ import annotations

import hashlib
import io
import uuid

from fastapi import HTTPException, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.services import storage
from app.models import Asset
from app.schemas.asset import AssetOut, ConfirmUploadRequest, UploadTicket, UploadTicketRequest

# 允许用户上传的图片类型白名单
ALLOWED_FORMATS: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_EXT_OF_MIME = {v: k for k, v in ALLOWED_FORMATS.items()}
_TICKET_TTL = 900


def probe_image(data: bytes) -> tuple[str, int, int]:
    """按**文件内容**（magic bytes）探测格式与尺寸。

    不信任请求里的 mime / 扩展名——那两者都由客户端决定，改一个后缀就能绕过。
    """
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # 校验数据完整性；verify 后不能再读像素，但尺寸仍可取
    except Exception as exc:  # noqa: BLE001 - Pillow 的异常类型很杂，统一转成人话
        raise ValueError("不是有效的图片文件，或文件已损坏") from exc

    if img.format not in ALLOWED_FORMATS:
        raise ValueError(
            f"不支持的图片格式：{img.format}，仅支持 {'/'.join(_EXT_OF_MIME.values())}"
        )
    return ALLOWED_FORMATS[img.format], img.width, img.height


def validate_size(size: int, settings: Settings) -> None:
    limit = settings.asset_max_size_mb * 1024 * 1024
    if size > limit:
        raise ValueError(f"文件超过 {settings.asset_max_size_mb}MB 上限")


def build_key(user_id: uuid.UUID, mime: str) -> str:
    ext = _EXT_OF_MIME.get(mime, "png").lower()
    return f"assets/{user_id}/{uuid.uuid4()}.{ext}"


def key_belongs_to(key: str, user_id: uuid.UUID) -> bool:
    """confirm 阶段的越权防线：只能确认自己名下的 key。"""
    return key.startswith(f"assets/{user_id}/")


def create_upload_ticket(
    user_id: uuid.UUID, payload: UploadTicketRequest, settings: Settings
) -> UploadTicket:
    validate_size(payload.size, settings)
    if payload.mime not in _EXT_OF_MIME:
        raise ValueError(f"不支持的图片类型：{payload.mime}")

    from urllib.parse import unquote

    # filename 只用于日志兜底，真实扩展名由 mime 决定
    _ = unquote(payload.filename)

    key = build_key(user_id, payload.mime)

    if settings.asset_upload_mode == "presigned":
        return UploadTicket(
            mode="presigned",
            key=key,
            upload_url=storage.presign_put(key, payload.mime, ttl=_TICKET_TTL),
            method="PUT",
            headers={"Content-Type": payload.mime},
            expires_in=_TICKET_TTL,
        )

    return UploadTicket(
        mode="backend",
        key=key,
        upload_url=f"{settings.api_prefix}/assets/upload-direct",
        method="POST",
        headers={},
        expires_in=_TICKET_TTL,
    )


def store_bytes(key: str, data: bytes, content_type: str) -> None:
    storage.put_object(key, data, content_type=content_type)


async def confirm_upload(
    session: AsyncSession,
    user_id: uuid.UUID,
    payload: ConfirmUploadRequest,
) -> Asset:
    """上传完成后落库。

    幂等：同一个 key 重复确认返回已有记录（前端重试/network 抖动时的必备容错）。
    """
    if not key_belongs_to(payload.key, user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权确认该素材")

    existing = await session.scalar(select(Asset).where(Asset.s3_key == payload.key))
    if existing is not None:
        return existing

    if not storage.object_exists(payload.key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="对象不存在或已过期")

    data = storage.get_object(payload.key)
    validate_size(len(data), get_settings())
    mime, width, height = probe_image(data)

    asset = Asset(
        user_id=user_id,
        kind=payload.kind,
        s3_key=payload.key,
        mime=mime,  # 以探测结果为准，不采信请求里的值
        width=width,
        height=height,
        size=len(data),
        checksum=hashlib.sha256(data).hexdigest(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


def asset_to_out(asset: Asset) -> AssetOut:
    return AssetOut(
        id=asset.id,
        kind=asset.kind,
        mime=asset.mime,
        width=asset.width,
        height=asset.height,
        size=asset.size,
        created_at=asset.created_at,
        url=storage.presign_get(asset.s3_key),
    )


async def list_assets(session: AsyncSession, user_id: uuid.UUID) -> list[Asset]:
    result = await session.execute(
        select(Asset).where(Asset.user_id == user_id).order_by(Asset.created_at.desc())
    )
    return list(result.scalars().all())


async def get_asset(session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID) -> Asset:
    asset = await session.get(Asset, asset_id)
    if asset is None or asset.user_id != user_id:
        # 刻意不区分「不存在」与「无权」——返回 404 不泄露资源是否存在
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在")
    return asset


async def delete_asset(session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID) -> None:
    asset = await get_asset(session, user_id, asset_id)
    await session.delete(asset)
    await session.commit()
    try:
        storage.delete_object(asset.s3_key)
    except Exception:  # noqa: BLE001 - 记录已删，对象清理失败不影响主流程，交给后台清理
        pass
