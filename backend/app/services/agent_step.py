"""Agent 单步执行（M4）。

一次「单步」= 一句自然语言 → 若干工具调用 → 新文档落库 → 回传每一步的结果。

刻意只做**单步**而不是循环规划：多步计划（含计划校验与人机确认）是 M8 的活。
先把「一句指令真的能改动画布」打通，再往上加编排 —— 否则出问题时分不清
是模型的问题还是执行层的问题。

两个不变量：
  1. 给模型的上下文里**没有 id**（`tool_exec.summarize_doc` 保证），
     模型的输出里就不该出现 id
  2. 工具执行失败要当成正常结果返回给调用方（带 ok=False），
     而不是让整个请求 500 —— 一句指令里有一个工具失败，其余的仍然有效

M5 起这里与 `/api/tools/{name}/invoke` 共用 `history.apply_tool_calls`：
手动调用与模型调用写进同一条撤销栈。否则用户会发现「自动帮我做的那些操作撤销不了」，
而那恰恰是最需要撤回的一部分。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.layer_doc import LayerDocument
from app.services import history as history_service
from app.services import sessions as sessions_service
from app.services import tool_exec
from app.services.history import StepResult, ToolCall  # noqa: F401 - 兼容既有导入
from app.tools.registry import function_schemas


class StepOutcome(BaseModel):
    steps: list[StepResult]
    session: dict
    """模型没给出任何工具调用时给用户的说明（比如用户说的是一句闲聊）。"""
    note: str | None = None


async def run_step(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    instruction: str,
) -> StepOutcome:
    # 延迟导入：langchain 只在这一条链路上需要，不该因为没装 agent extra
    # 就让整个应用起不来（其余功能与模型无关）
    from app.agent.llm import plan_tool_calls

    edit_session = await sessions_service.get_edit_session(session, user_id, session_id)
    doc = LayerDocument.model_validate(edit_session.doc)

    calls = await plan_tool_calls(instruction, tool_exec.summarize_doc(doc), function_schemas())
    if not calls:
        out = await sessions_service.to_out(session, edit_session)
        return StepOutcome(
            steps=[],
            session=out.model_dump(mode="json"),
            note="这句话没有对应到可执行的操作，换一种说法试试（例如「把图调亮一点」）。",
        )

    updated, steps = await history_service.apply_tool_calls(
        session,
        user_id=user_id,
        session_id=session_id,
        calls=[ToolCall(name=call["name"], params=call.get("args") or {}) for call in calls],
    )

    out = await sessions_service.to_out(session, updated)
    return StepOutcome(steps=steps, session=out.model_dump(mode="json"))
