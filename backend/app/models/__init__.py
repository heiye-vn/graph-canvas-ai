"""ORM 模型。

Alembic 的 target_metadata 指向这里导出的 Base.metadata，
因此**每新增一个模型都必须在本文件的 __all__ 里导出**，否则 autogenerate 扫不到。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.history import EditHistory
from app.models.run import ToolRun
from app.models.session import EditSession, SessionAsset

__all__ = ["Base", "User", "Asset", "ToolRun", "EditSession", "SessionAsset", "EditHistory"]


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Asset(Base):
    """素材：一张上传到对象存储的图片/遮罩。

    注意存的是 s3_key 而不是 URL —— 对外访问一律临时生成预签名 URL，
    桶保持私有，读写 URL 永不落库（否则换域名/换存储就得洗数据）。
    """

    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(String(16), default="image", nullable=False)
    s3_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    mime: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    size: Mapped[int] = mapped_column(default=0, nullable=False)
    checksum: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
