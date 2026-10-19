"""服务端拍平入口。

`edits/render.flatten` 是纯函数（bytes in / out）；这里负责它需要的
**数据准备工作**：按文档引用的 asset_id 查素材、从对象存储取字节。
缺失的素材跳过而不是报错 —— 拍平服务于预览/分割，一张被删素材不该
让整个局部编辑链路挂掉。
"""

from __future__ import annotations

import logging
import uuid

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.edits.render import flatten
from app.models import EditSession
from app.services import storage

logger = logging.getLogger("graph-canvas-ai.flatten")

# 只吞「这个素材取不到」这一类可预期失败（已删 / 越权 / 对象没了）。
# 绝不能连编程错误一起吞：曾把 `await` 一个同步返回的 bytes 吞成
# TypeError，于是每个图层都被静默跳过，拍平成一张纯白图交出去 ——
# 拆层/局部编辑照常「成功」，产物却是白板，比直接报错难查十倍。
_SKIPPABLE = (HTTPException, ClientError, BotoCoreError, ValueError)


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
            # get_object 是**同步**的（boto3）：多一个 await 就是 TypeError
            raw = storage.get_object(asset.s3_key)
        except _SKIPPABLE as exc:
            logger.warning("拍平跳过素材 %s：%s", asset_id, exc)
            continue
        images[asset_id] = raw

    if doc.layers and not images and any(layer.source is not None for layer in doc.layers):
        # 有引用的图层却一张都没取到：拍平结果必然是空画布，
        # 交给下游只会产出「看起来正常」的白图 —— 宁可在这里报错
        raise RuntimeError("拍平失败：文档引用的素材一张都没取到（对象存储不可用或素材已删）")
    return flatten(doc, images)
