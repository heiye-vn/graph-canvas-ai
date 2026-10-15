"""快照式撤销 —— M5 的核心。

两条不变量，其余都是它们的推论：

    1. **文档与历史在同一个事务里写**。先写文档再补历史（或反过来），
       一旦中间失败就得到「画布变了但撤销栈里没有它」——用户按撤销没反应，
       而这时最能给人信心的功能恰好失灵了。
    2. **一次工具调用 = 一条历史**。不合并、不按 Explore 的连贯动作分组：
       一句自然语言可能命中三个工具，把三个效果揉成一条历史，
       undo 一次就丢掉了三步中的后两步。

「历史为真」的几条边界情况，这里显式处理：

    · 参数与现状相同（把已经是 50% 的图层再设成 50%）→ 照样留一条记录，
      但 changed=False。用户在编辑记录里要看得见自己刚才那一下；
      撤销时会自动跳过它，不会出现「按了没反应」。
    · undo 之后再来新操作 → 先把指针之后的记录删掉（截断 redo 分支）。
      分支一旦留着，redo 会跳进一条从来没人验证过的路径。
    · 历史超过上限 → 丢最老的，且**不重排 seq**。撤到边界就停住。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EditHistory, EditSession
from app.models.history import HISTORY_LIMIT
from app.schemas.layer_doc import LayerDocument
from app.services import sessions as sessions_service
from app.services import tool_exec
from app.tools.base import QueuedOutcome, ToolContext, ToolError

__all__ = [
    "HISTORY_LIMIT",
    "ToolCall",
    "StepResult",
    "TimeTravelResult",
    "apply_tool_calls",
    "undo",
    "redo",
    "list_history",
    "can_undo",
    "can_redo",
]


class StepResult(BaseModel):
    """一次工具调用的结果。工具失败不是异常 —— 它是**给用户看的**结果。"""

    tool: str
    args: dict
    ok: bool
    message: str
    """这一步是否真的改了文档（False = 记了历史但画布没动）。"""
    changed: bool = True
    """排队型工具提交出的任务 id —— 前端凭它订阅进度流。"""
    run_id: uuid.UUID | None = None


@dataclass
class ToolCall:
    name: str
    params: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ 写入


async def apply_tool_calls(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    calls: list[ToolCall],
    pinned: dict[str, Any] | None = None,
) -> tuple[EditSession, list[StepResult]]:
    """依次执行若干工具，**每条成功的调用留一条历史**，最后一次性提交。

    返回 (edit_session, steps)。文档与历史在同一事务里落地，中途抛错时不留下
    半截状态（调用方拿到异常 = 什么都没改）。

    注意这里**不用** `sessions_service.replace_doc`：那个函数自己会 commit，
    会把「写文档」和「写历史」劈成两个事务。
    """
    edit_session = await sessions_service.get_edit_session(session, user_id, session_id)
    doc = LayerDocument.model_validate(edit_session.doc)

    steps: list[StepResult] = []
    queued: list[tuple[str, QueuedOutcome]] = []
    for call in calls:
        ctx = ToolContext(
            session_id=edit_session.id,
            user_id=user_id,
            doc=doc,
            pinned=pinned or {},
            db=session,
        )
        try:
            result = await tool_exec.invoke(call.name, call.params, ctx)
        except ToolError as exc:
            steps.append(
                StepResult(tool=call.name, args=call.params, ok=False, message=exc.message)
            )
            continue

        if isinstance(result, QueuedOutcome):
            # 排队型工具：run 已落库，任务在**本事务提交后**才投递 ARQ ——
            # 先投递再提交会有竞态：worker 抢到任务时 run 行还不存在
            await _record(
                session,
                edit_session,
                tool=call.name,
                label=result.message,
                changed=False,
                before=doc,
                after=doc,
                params=call.params,
            )
            steps.append(
                StepResult(
                    tool=call.name,
                    args=call.params,
                    ok=True,
                    message=result.message,
                    changed=False,
                    run_id=result.run_id,
                )
            )
            queued.append((result.task, result))
            continue

        # 标签用**这一步的结果说明**而不是工具名：
        # 连续三次改名在历史里就是三条一模一样的「改名」，用户根本分不出要退到哪一步。
        # 「图层已改名为「顶层」」这种才是能认出来的东西。
        changed = _differs(doc, result.doc)
        await _record(
            session,
            edit_session,
            tool=call.name,
            label=result.message,
            changed=changed,
            before=doc,
            after=result.doc,
            params=call.params,
        )
        doc = result.doc
        steps.append(
            StepResult(
                tool=call.name,
                args=call.params,
                ok=True,
                message=result.message if changed else f"{result.message}（画布没有变化）",
                changed=changed,
            )
        )

    # ⚠️ 文档本身必须在**同一个事务**里更新：只写历史不写文档，
    # 结果就是「画布没变但撤销栈里多了一条」，用户按撤销看到的是上一步的图。
    if _differs(LayerDocument.model_validate(edit_session.doc), doc):
        edit_session.doc = doc.model_dump(mode="json")
        # revision 只在文档真的变化时自增：选区失效的裁判是它，
        # 「重复设置同一个值」这类 changed=False 的操作不该作废选区
        edit_session.revision += 1

    await session.commit()

    # 事务已落地，现在投递排队任务（顺序：先库后队列，杜绝幽灵任务）
    from app.services import queue as queue_service

    for task, outcome in queued:
        await queue_service.enqueue(task, outcome.run_id)

    await session.refresh(edit_session)
    return edit_session, steps


async def record_external(
    session: AsyncSession,
    edit_session: EditSession,
    *,
    tool: str,
    label: str,
    after: LayerDocument,
    params: dict[str, Any] | None = None,
) -> None:
    """worker 进程替排队型工具落文档 + 历史（拆层这类「执行后整份换文档」的任务）。

    与 apply_tool_calls 共用 _record：撤销栈里必须找得到 worker 干的活，
    否则用户拆完层按撤销会「没反应」。调用方负责在同一事务里 commit。
    """
    before = LayerDocument.model_validate(edit_session.doc)
    await _record(
        session,
        edit_session,
        tool=tool,
        label=label,
        changed=True,
        before=before,
        after=after,
        params=params or {},
    )
    edit_session.doc = after.model_dump(mode="json")
    edit_session.revision += 1


async def _record(
    session: AsyncSession,
    edit_session: EditSession,
    *,
    tool: str | None,
    label: str,
    changed: bool,
    before: LayerDocument,
    after: LayerDocument,
    params: dict[str, Any],
) -> EditHistory:
    """追加一条历史，并顺手截断 redo 分支 + 裁剪超量记录。"""
    # 1) 截断：站在第 k 格时又做了新动作，那么第 k 格之后的分支永远不该再到达
    await session.execute(
        delete(EditHistory).where(
            EditHistory.session_id == edit_session.id,
            EditHistory.seq > edit_session.history_seq,
        )
    )

    # 2) 追加
    seq = await _max_seq(session, edit_session.id) + 1
    entry = EditHistory(
        session_id=edit_session.id,
        seq=seq,
        tool=tool,
        label=label[:64],
        changed=changed,
        before=before.model_dump(mode="json"),
        after=after.model_dump(mode="json"),
        params=dict(params),
    )
    session.add(entry)
    edit_session.history_seq = seq
    await session.flush()

    # 3) 裁剪
    await _trim(session, edit_session.id)
    return entry


async def _max_seq(session: AsyncSession, session_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.coalesce(func.max(EditHistory.seq), 0)).where(
            EditHistory.session_id == session_id
        )
    )
    return int(result.scalar_one())


async def _trim(session: AsyncSession, session_id: uuid.UUID) -> None:
    """只留最近 HISTORY_LIMIT 条；丢的时候不重排 seq（见 models/history.py 的注释）。"""
    result = await session.execute(
        select(EditHistory.seq)
        .where(EditHistory.session_id == session_id)
        .order_by(EditHistory.seq.desc())
        .offset(HISTORY_LIMIT)
    )
    stale = list(result.scalars().all())
    if stale:
        await session.execute(
            delete(EditHistory).where(
                EditHistory.session_id == session_id,
                EditHistory.seq.in_(stale),
            )
        )


def _differs(before: LayerDocument, after: LayerDocument) -> bool:
    """文档是否真的变了。

    用 dict 比而不是 `==`：pydantic 模型的相等性是引用无关但**包含子类配置**的，
    而这里只关心「JSONB 里要写的东西是否一样」。
    """
    return before.model_dump(mode="json") != after.model_dump(mode="json")


# ------------------------------------------------------------------ 撤销 / 重做


def _nothing_to_do(direction: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"没有可{direction}的操作")


async def _entry_at(
    session: AsyncSession, session_id: uuid.UUID, seq: int
) -> EditHistory | None:
    result = await session.execute(
        select(EditHistory).where(
            EditHistory.session_id == session_id, EditHistory.seq == seq
        )
    )
    return result.scalar_one_or_none()


@dataclass
class TimeTravelResult:
    """撤销 / 重做的结果。

    `label` 是刚刚被越过那一步的名字（「调色」「删除图层」）。带上它是为了让
    调用方能提示「已撤销：调色」—— 纯 seq 数字对用户没有任何意义。
    """

    edit_session: EditSession
    label: str | None = None


async def undo(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> TimeTravelResult:
    """退一步：把当前那一步的 before 快照写回文档。

    `changed=False` 的条目会被**跳过**（一路往前找真正动过画布的那条）——
    否则用户按撤销会「没反应」，而那往往只是一条无害的重复设置。

    没有可撤销的操作时抛 409：这不是错误路径，是状态本身不允许。
    """
    edit_session = await sessions_service.get_edit_session(session, user_id, session_id)
    if edit_session.history_seq <= 0:
        raise _nothing_to_do("撤销")

    seq = edit_session.history_seq
    label: str | None = None
    while seq > 0:
        entry = await _entry_at(session, edit_session.id, seq)
        edit_session.history_seq = seq - 1
        if entry is not None and entry.changed:
            edit_session.doc = entry.before
            label = entry.label
            break
        seq -= 1

    # 撤销同样改变像素：选区必须跟着作废（revision 是唯一裁判，方向无关）
    edit_session.revision += 1
    # 即使只跳过了几条「画布没变」的记录也要提交：指针动了对用户是有意义的
    # （下一次 undo 该从新位置继续），留着不写会让读到的位置和实际不一致
    await session.commit()
    await session.refresh(edit_session)
    return TimeTravelResult(edit_session, label)


async def redo(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> TimeTravelResult:
    """前进一步：把下一格的 after 快照写回文档。跳过 changed=False 的条目，理由同 undo。"""
    edit_session = await sessions_service.get_edit_session(session, user_id, session_id)

    seq = edit_session.history_seq + 1
    label: str | None = None
    while True:
        entry = await _entry_at(session, edit_session.id, seq)
        if entry is None:
            break
        if entry.changed:
            edit_session.history_seq = seq
            edit_session.doc = entry.after
            label = entry.label
            break
        seq += 1

    if label is None:
        # 后面全是「画布没变」的记录或根本没有记录 → 指针一步也不该动，回滚掉试探
        await session.rollback()
        raise _nothing_to_do("重做")
    edit_session.revision += 1
    await session.commit()
    await session.refresh(edit_session)
    return TimeTravelResult(edit_session, label)


# ------------------------------------------------------------------ 查询


async def list_history(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> list[EditHistory]:
    edit_session = await sessions_service.get_edit_session(session, user_id, session_id)
    result = await session.execute(
        select(EditHistory)
        .where(EditHistory.session_id == edit_session.id)
        .order_by(EditHistory.seq.desc())
        .limit(HISTORY_LIMIT)
    )
    return list(result.scalars().all())


async def can_undo(session: AsyncSession, session_id: uuid.UUID, current_seq: int) -> bool:
    """指针之前还有**真正改过画布**的步骤吗。"""
    if current_seq <= 0:
        return False
    result = await session.execute(
        select(func.count(EditHistory.id)).where(
            EditHistory.session_id == session_id,
            EditHistory.seq <= current_seq,
            EditHistory.changed.is_(True),
        )
    )
    return int(result.scalar_one()) > 0


async def can_redo(session: AsyncSession, session_id: uuid.UUID, current_seq: int) -> bool:
    result = await session.execute(
        select(func.count(EditHistory.id)).where(
            EditHistory.session_id == session_id,
            EditHistory.seq > current_seq,
            EditHistory.changed.is_(True),
        )
    )
    return int(result.scalar_one()) > 0
