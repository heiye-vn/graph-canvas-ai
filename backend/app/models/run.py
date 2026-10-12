"""任务运行记录。

M2 起出现真正的异步任务（生图、抠图这类耗时的），
状态要有地方落库——SSE 只负责实时推送，刷新页面后靠这里恢复现场。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL_STATUSES = frozenset({SUCCEEDED, FAILED, CANCELLED})


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # M3 引入编辑会话后才有值；生图类任务暂时独立存在
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(String(16), default=QUEUED, index=True, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str | None] = mapped_column(String(64))

    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES
