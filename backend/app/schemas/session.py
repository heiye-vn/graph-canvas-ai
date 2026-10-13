from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.asset import AssetOut
from app.schemas.layer_doc import LayerDocument


class CreateSessionRequest(BaseModel):
    """建会话：至少带一张素材进来，否则画布上没东西可编辑。"""

    title: str | None = Field(default=None, max_length=120)
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=32)


class AddSessionAssetsRequest(BaseModel):
    asset_ids: list[uuid.UUID] = Field(min_length=1, max_length=32)


class ReplaceDocRequest(BaseModel):
    """整份替换图层文档。

    刻意不做「局部 patch」：每个工具执行后产出的都是一个完整文档
    （层级顺序会变、会插入/删除图层），用 diff 语义表达这些变化既啰嗦又容易错。
    并发保护（版本比对）留给 M4 的工具入口去做，那里才真正需要。
    """

    doc: LayerDocument


class UpdateSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    layer_count: int
    asset_count: int
    created_at: datetime
    updated_at: datetime


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    doc: LayerDocument
    # 会话里的全部素材（带预签名 URL）：前端按 asset_id 去图层文档里对得上
    assets: list[AssetOut]
    created_at: datetime
    updated_at: datetime
