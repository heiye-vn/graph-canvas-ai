"""编辑会话 API（M3）。

路由前缀 `/edit-sessions`，全部需要登录，且**只认本人会话**。

设计上刻意只有「整份替换文档」而没有「改单个图层」：
每个操作之后文档的状态是由多个图层共同决定的（层级顺序、可见性互相影响），
逐个暴露 PATCH 端点等于把渲染层的逻辑搬进服务端。工具执行完后给一份完整文档，
服务端只负责校验结构 + 落库。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.history import HistoryEntry, HistoryOut, TimeTravelOut
from app.schemas.session import (
    AddSessionAssetsRequest,
    CreateSessionRequest,
    ReplaceDocRequest,
    SessionOut,
    SessionSummary,
    UpdateSessionRequest,
)
from app.services import history as history_service
from app.services import sessions as sessions_service

router = APIRouter(prefix="/edit-sessions", tags=["edit-sessions"])


async def _to_out(session: AsyncSession, edit_session) -> SessionOut:
    """把 ORM 对象组装成响应：文档按 LayerDocument 解析，素材补预签名 URL。

    注意 edit_sessions 与 tools 两个路由里各有一份 `to_out`：服务端那份在
    `services/sessions.py`，两边都调它 —— 「会话长什么样」的答案必须只有一处。
    """
    return await sessions_service.to_out(session, edit_session)


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: CreateSessionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    """新建会话。至少带一张素材进来 —— 空会话没有可编辑的东西。"""
    edit_session = await sessions_service.create_session(
        session, user_id=user.id, asset_ids=payload.asset_ids, title=payload.title
    )
    return await _to_out(session, edit_session)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[SessionSummary]:
    items = await sessions_service.list_sessions(session, user.id)
    summaries: list[SessionSummary] = []
    for item in items:
        doc = item.doc or {}
        summaries.append(
            SessionSummary(
                id=item.id,
                title=item.title,
                layer_count=len(doc.get("layers", [])),
                asset_count=await sessions_service.count_assets(session, item.id),
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return summaries


@router.get("/{session_id}", response_model=SessionOut)
async def get_edit_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    """恢复现场用的端点。

    前端刷新 / 直接分享 `/editor/{session_id}` 时靠它把画布重建出来，
    不依赖任何内存状态 —— 与候选页 `GET /runs/{id}/assets` 是同一个道理。
    """
    edit_session = await sessions_service.get_edit_session(session, user.id, session_id)
    return await _to_out(session, edit_session)


@router.post("/{session_id}/assets", response_model=SessionOut)
async def add_assets(
    session_id: uuid.UUID,
    payload: AddSessionAssetsRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    edit_session = await sessions_service.add_assets(
        session, user_id=user.id, session_id=session_id, asset_ids=payload.asset_ids
    )
    return await _to_out(session, edit_session)


@router.put("/{session_id}/doc", response_model=SessionOut)
async def replace_doc(
    session_id: uuid.UUID,
    payload: ReplaceDocRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    """整份替换图层文档。

    423 的那种乐观并发保护等到 M4 工具入口真正并发调用时再加；
    现在一次只有一个编辑者在改，加了反而让前端每次都得处理冲突。
    """
    edit_session = await sessions_service.replace_doc(
        session, user_id=user.id, session_id=session_id, doc=payload.doc
    )
    return await _to_out(session, edit_session)


@router.patch("/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: uuid.UUID,
    payload: UpdateSessionRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> SessionOut:
    edit_session = await sessions_service.rename_session(
        session, user_id=user.id, session_id=session_id, title=payload.title
    )
    return await _to_out(session, edit_session)


@router.get("/{session_id}/history", response_model=HistoryOut)
async def get_history(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HistoryOut:
    """撤销栈的当前状态：指针位置 + 留存记录。

    这里是**不下发文档快照**的（原因见 schemas/history.py），
    所以列表不能直接拿给前端做画布，只能用来回答问题：「刚才做了什么、还能退回几步」。
    """
    edit_session = await sessions_service.get_edit_session(session, user.id, session_id)
    entries = await history_service.list_history(session, user_id=user.id, session_id=session_id)

    return HistoryOut(
        seq=edit_session.history_seq,
        can_undo=await history_service.can_undo(session, edit_session.id, edit_session.history_seq),
        can_redo=await history_service.can_redo(session, edit_session.id, edit_session.history_seq),
        items=[
            HistoryEntry(
                seq=entry.seq,
                tool=entry.tool,
                label=entry.label,
                changed=entry.changed,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
    )


async def _time_travel(
    back: bool, session: AsyncSession, user: User, session_id: uuid.UUID
) -> TimeTravelOut:
    """撤销 / 重做的共同尾巴：拿新文档，顺便把新的指针位置一起回传。

    `can_undo` / `can_redo` 必须跟着返回：前端如果为了显示按钮状态再发一次 GET，
    在快速连点时会出现「按钮可点但请求 409」的窗口。

    不可操作时由服务层抛 409 直接透传 —— 「撤销到底了」是一种状态，不是异常。
    """
    travel = history_service.undo if back else history_service.redo
    result = await travel(session, user_id=user.id, session_id=session_id)

    edit_session = result.edit_session
    seq = edit_session.history_seq
    return TimeTravelOut(
        session=(await sessions_service.to_out(session, edit_session)).model_dump(mode="json"),
        label=result.label,
        seq=seq,
        can_undo=await history_service.can_undo(session, edit_session.id, seq),
        can_redo=await history_service.can_redo(session, edit_session.id, seq),
    )


@router.post("/{session_id}/history/undo", response_model=TimeTravelOut)
async def undo_step(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TimeTravelOut:
    """退一步。已经在初始状态时返回 **409** —— 这不是参数错误，是当前状态不允许。"""
    return await _time_travel(True, session, user, session_id)


@router.post("/{session_id}/history/redo", response_model=TimeTravelOut)
async def redo_step(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TimeTravelOut:
    """前进一步。指针已经在最新一步时返回 **409**。"""
    return await _time_travel(False, session, user, session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    await sessions_service.delete_session(session, user_id=user.id, session_id=session_id)
