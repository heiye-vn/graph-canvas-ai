"""Agent 多步计划（M8）。

一次「对话轮」落成一条 agent_runs：instruction + plan（步骤数组 JSONB）+ 状态。
步骤状态存在 plan JSONB 里（pending/queued/succeeded/…），表上的 status 是
整轮的汇总 —— 这是参考项目验证过的形状：步骤级细节跟着轮次走，
刷新后从库里就能把「执行到哪一步了」完整恢复出来。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# 整轮状态（与 tool_runs 的 queued/running 同名不同义 —— 这是「一轮对话」的生命周期）
AWAITING_CONFIRM = "awaiting_confirm"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL = {SUCCEEDED, FAILED, CANCELLED}


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("edit_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    instruction: Mapped[str] = mapped_column(String(1000), nullable=False)
    # 步骤数组：[{id, tool, params, depends_on, status, run_id, message}]
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    # 给用户看的人话回应（计划说明 / 闲聊回应 / 失败原因）
    reply: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(
        String(20), default=AWAITING_CONFIRM, index=True, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL
