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
from app.models import Asset
from app.schemas.asset import AssetOut, ConfirmUploadRequest, UploadTicket, UploadTicketRequest
from app.services import storage

# 允许用户上传的图片类型白名单
ALLOWED_FORMATS: dict[str, str] = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}
_EXT_OF_MIME = {v: k for k, v in ALLOWED_FORMATS.items()}
_TICKET_TTL = 900

# 缩略图：素材库卡片只有 ~160px 高，直接喂原图（动辄 3000px+ / 数 MB）
# 首屏要下载+解码一整列大图 —— 列表卡顿的来源就是这个。
_THUMB_MAX_SIDE = 480
_THUMB_SUFFIX = ".thumb.jpg"


def thumb_key_of(s3_key: str) -> str:
    return f"{s3_key}{_THUMB_SUFFIX}"


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
        # 缩略图按需生成（首访生成落桶，之后命中缓存），这里只拼入口地址，零存储开销
        thumb_url=f"{get_settings().api_prefix}/assets/{asset.id}/thumb",
    )


def ensure_thumb(asset: Asset) -> str:
    """缩略图写穿缓存：首次请求从原图生成 480px 小图落桶，之后直接命中。

    返回桶内 key；调用方自行 presign。
    """
    thumb_key = thumb_key_of(asset.s3_key)
    if storage.object_exists(thumb_key):
        return thumb_key

    data = storage.get_object(asset.s3_key)
    img = Image.open(io.BytesIO(data))
    img.thumbnail((_THUMB_MAX_SIDE, _THUMB_MAX_SIDE), Image.LANCZOS)
    if img.mode in ("RGBA", "LA", "P"):
        # JPEG 没有 alpha：透明底按白底压平，别发黑
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    storage.put_object(thumb_key, buf.getvalue(), content_type="image/jpeg")
    return thumb_key


async def list_assets(session: AsyncSession, user_id: uuid.UUID) -> list[Asset]:
    result = await session.execute(
        select(Asset).where(Asset.user_id == user_id).order_by(Asset.created_at.desc())
    )
    return list(result.scalars().all())


async def list_assets_by_ids(
    session: AsyncSession, user_id: uuid.UUID, asset_ids: list[uuid.UUID]
) -> list[Asset]:
    """按 id 取本人素材，**并保持传入顺序**。

    候选图页刷新后要靠这里恢复现场：顺序是有语义的（第 1 张 / 第 2 张），
    按 created_at 重排会让用户以为图变了。
    越权的 id 直接忽略——同一次取多个资源时不该因为一个不属于我就整体 404。
    """
    if not asset_ids:
        return []
    result = await session.execute(
        select(Asset).where(Asset.user_id == user_id, Asset.id.in_(asset_ids))
    )
    by_id = {asset.id: asset for asset in result.scalars().all()}
    return [by_id[asset_id] for asset_id in asset_ids if asset_id in by_id]


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
    try:
        storage.delete_object(thumb_key_of(asset.s3_key))
    except Exception:  # noqa: BLE001 - 同上，缩略图是派生物，清理失败无碍
        pass


async def create_from_bytes(
    session: AsyncSession, user_id: uuid.UUID, data: bytes, *, kind: str = "image"
) -> Asset:
    """把一段图片字节落成素材记录（不入对象存储之外的地方）。

    选区遮罩、局部编辑结果这类**服务端产出**共用这一个入口 ——
    与 tasks/image.py 里手写的那份组装逻辑同构；那处是任务语境，这里是通用语境，
    两处将来该收敛到这一份。

    flush 是契约的一部分：调用方马上要拿 `asset.id` 组装下游结构
    （选区 payload、ResultEvent），等外层 commit 再拿就晚了。
    """
    mime, width, height = probe_image(data)
    key = build_key(user_id, mime)
    storage.put_object(key, data, content_type=mime)
    asset = Asset(
        user_id=user_id,
        kind=kind,
        s3_key=key,
        mime=mime,
        width=width,
        height=height,
        size=len(data),
    )
    session.add(asset)
    await session.flush()
    return asset
