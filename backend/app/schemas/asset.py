from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    mime: str
    width: int | None
    height: int | None
    size: int
    created_at: datetime
    # 预签名临时 URL：桶是私有的，前端一律用这个地址取图，不要把 s3_key 暴露出去
    url: str


class AssetListResponse(BaseModel):
    items: list[AssetOut]


class UploadTicketRequest(BaseModel):
    filename: str = Field(max_length=255)
    mime: str = Field(max_length=64)
    size: int = Field(gt=0)
    kind: str = Field(default="image", max_length=16)


class UploadTicket(BaseModel):
    """上传凭据 —— 前后端之间的上传契约。

    两种模式共用同一份结构，前端按 method 分支即可，**后端切换模式无需改前端**：

        mode=backend    method=POST   直传到本服务，url 是 /api/assets/upload-direct
        mode=presigned  method=PUT    直传对象存储，url 是预签名 S3 地址；
                                      headers 带 Content-Type，传完再调 /confirm 落库

    MVP 先用 backend（实现简单、便于服务端做病毒/尺寸校验），
    流量上来后把 ASSET_UPLOAD_MODE 改成 presigned，前端零改动。
    """

    mode: str
    key: str
    upload_url: str
    method: str
    headers: dict[str, str] = Field(default_factory=dict)
    expires_in: int


class ConfirmUploadRequest(BaseModel):
    key: str = Field(max_length=512)
    mime: str = Field(max_length=64)
    size: int = Field(gt=0)
    kind: str = Field(default="image", max_length=16)
