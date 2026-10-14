"""编辑历史（M5 快照式撤销）。

为什么每个图层之上还要再养一张「历史」表：

    图层文档只回答「现在长什么样」，回答不了「怎么来的」。
    没有历史，用户唯一的纠错手段是手工把每一步倒着再做一遍 ——
    而 Agent 一次会调好几个工具，用户甚至不知道刚才发生了什么。

为什么是**快照**而不是「反向操作」：

    反向操作要为 13 个工具各写一份 undo 逻辑，而且必须和正向严格对称 ——
    任何一处不对称（比如 reorder 的原索引没记下来）都会让撤销悄悄改坏文档，
    且难以复现。快照式把复杂度压成一条读写语句：before 就是过去的文档。
    代价是文档翻倍存，但一份文档只有几 KB，且有 50 条上限。

为什么 session 上要挂一个 history_seq 指针：

    文档永远表示「当前状态」，指针表示「站在历史的哪一格」。
    有了它，redo 就不需要另一个方向的链表 —— 往前走一格就是 seq+1，
    而新操作只需要把指针之后的记录删掉（截断 redo 分支）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

HISTORY_LIMIT = 50
"""每个会话保留的历史条数。

超出后从最老的开始丢。**刻意不重排 seq**：seq 是绝对递增的序号，
重排会让 history_seq 指针一夜之间指向别的条目。
丢掉的结果是「撤销到底之前先停住」，这比「撤销到错误的中间态」好得多。
"""


class EditHistory(Base):
    __tablename__ = "edit_history"
    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_history_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("edit_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # 每个会话内从 1 开始绝对递增
    seq: Mapped[int] = mapped_column(Integer, nullable=False)

    tool: Mapped[str | None] = mapped_column(String(64))
    """产生这条记录的工具名。为 None 表示不是工具产生的（例如未来的生成类任务）。"""

    label: Mapped[str] = mapped_column(String(64), nullable=False)
    """给用户看的一句话标签（「调色」「删除图层」）。"""

    changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    """这一步**是否真的改变了文档**。

    为 False 的情况：① 参数与现状相同（把已经是 50% 的图层再设成 50%）；
    ② 「结果只进图片墙」这类画布没变的操作。这些照样留一条历史 ——
    用户在编辑记录里要能找到自己刚才那一下，否则会以为操作丢了。
    撤销时会自动跳过它们（见 services/history.py）。
    """

    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """操作前后的**整份文档快照**。undo 取 before，redo 取 after。"""

    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """调用参数，给「编辑记录」面板展示，也给 M6 重放留口子。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
