"""编辑历史的响应结构。

刻意**不下发文档快照**：`before` / `after` 每份都是整份 LayerDocument，
十几条历史就够把响应体撑到几百 KB，而前端真正要的只是「刚才做了什么、还能不能退」。
要看某一步的效果，退到那一步就行 —— 完整文档只有 session 那一份才需要传。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    tool: str | None
    label: str
    changed: bool
    created_at: datetime


class HistoryOut(BaseModel):
    """撤销栈的当前状态。

    `seq` 是**指针位置**（0 = 初始状态），`items` 是全部留存记录（从新到旧）。
    前端据此判断「哪几步已经退过去了」—— 指针之后的条目就是可重做的那一截。
    """

    seq: int
    can_undo: bool
    can_redo: bool
    items: list[HistoryEntry]


class TimeTravelOut(BaseModel):
    """撤销 / 重做的结果：新文档 + 这一步的名字（用于提示「已撤销：调色」）。"""

    session: dict
    label: str | None = None
    seq: int
    can_undo: bool
    can_redo: bool
