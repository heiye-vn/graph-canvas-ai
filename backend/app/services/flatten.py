"""服务端拍平入口。

`edits/render.flatten` 是纯函数（bytes in / out）；这里负责它需要的
**数据准备工作**：按文档引用的 asset_id 查素材、从对象存储取字节。
缺失的素材跳过而不是报错 —— 拍平服务于预览/分割，一张被删素材不该
让整个局部编辑链路挂掉。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.edits.render import flatten
from app.models import EditSession
from app.services import storage


async def flatten_session(session: AsyncSession, record: EditSession) -> bytes:
    """把当前文档拍平为 PNG bytes，供分割与局部编辑使用。"""
    from app.schemas.layer_doc import LayerDocument
    from app.services import assets as asset_service

    doc = LayerDocument.model_validate(record.doc)
    images: dict[uuid.UUID, bytes] = {}
    for layer in doc.layers:
        if layer.source is None:
            continue
        asset_id = layer.source.asset_id
        if asset_id in images:
            continue
        try:
            asset = await asset_service.get_asset(session, record.user_id, asset_id)
            raw = await storage.get_object(asset.s3_key)
        except Exception:  # noqa: BLE001 - 素材缺失/无权/对象没了都跳过该层
            continue
        images[asset_id] = raw
    return flatten(doc, images)
