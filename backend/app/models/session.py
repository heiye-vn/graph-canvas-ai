"""编辑会话与会话素材。

一次「编辑会话」= 一份图层文档 + 参与其中的素材。

为什么 session 与 run 要分开：
    ToolRun 是**单次任务**（几秒钟，有明确终态），EditSession 是**工作现场**
    （可能开几天，状态一直在变）。把画布状态塞进 tool_runs 会让「任务列表」里
    混进一堆永远不结束的东西，也会让「每次任务的输入快照」变得没法复盘。
    两者用 tool_runs.session_id 关联即可。

为什么资产要单独一张关联表而不是在 doc 里记 asset_id：
    图层文档是**给渲染层看的结构**（层级顺序、透明度和变换都在这里），
    session_assets 是**给数据完整性看的**（这个会话用到了哪几张素材）。
    只靠解析 JSON 提取 asset_id 的话，删除素材时的级联保护、按素材反查会话
    都得先全表扫 JSONB，而且容易漏。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DEFAULT_TITLE = "未命名编辑会话"


class EditSession(Base):
    __tablename__ = "edit_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), default=DEFAULT_TITLE, nullable=False)

    # 图层文档：唯一真相源，结构由 app/schemas/layer_doc.py 的 LayerDocument 定义。
    # 读写一律经过那个 pydantic 模型校验，这里只当普通 JSONB 存。
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # 当前所处的历史位置：0 = 初始状态（还没任何操作），N = 已应用第 N 条记录。
    # 文档本身永远表示「当前状态」，这一列表示「站在历史的哪一格」，redo 靠它往前走。
    history_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SessionAsset(Base):
    """会话与素材的关联。同一张素材重复加入只记一条（下面的唯一约束）。"""

    __tablename__ = "session_assets"
    __table_args__ = (UniqueConstraint("session_id", "asset_id", name="uq_session_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("edit_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), index=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
