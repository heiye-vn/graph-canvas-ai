"""工具元数据与直接调用。

`GET /api/tools` 是前端表单的**唯一来源**：加一个工具，前端不改一行代码就能
显示标签和参数表单（DoD ②）。所以这份元数据必须包含渲染表单需要的全部信息
（标签、说明、类型、取值范围、默认值），而不是只给个名字让前端去猜。

`POST /api/tools/{name}/invoke` 是给「确定性操作」用的：模型不参与，
参数由界面给出。它的存在也让工具链路在没有配置模型 Key 的情况下可以被验证。

M5 起这两个入口**都写历史**（`services/history.py`）：手动点一次和让模型做一次，
在撤销栈里必须是同一种东西 —— 否则用户会发现「自动帮我做的那些操作撤销不了」。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.session import SessionOut
from app.services import history as history_service
from app.services import sessions as sessions_service
from app.tools.builtins import install_builtin_tools  # noqa: F401 - 导入即注册
from app.tools.registry import get_tool, metadata

router = APIRouter(prefix="/tools", tags=["tools"])


class InvokeRequest(BaseModel):
    session_id: uuid.UUID
    params: dict[str, Any] = Field(default_factory=dict)


class InvokeResponse(BaseModel):
    tool: str
    message: str
    session: SessionOut


@router.get("")
async def list_tools() -> dict:
    return {"items": metadata()}


@router.post("/{name}/invoke", response_model=InvokeResponse)
async def invoke_tool(
    name: str,
    payload: InvokeRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> InvokeResponse:
    if get_tool(name) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="工具不存在")

    # UI 给的参数同时也是「服务端回填」的来源：asset_id 这类隐藏字段由界面传，
    # 不走模型那条路
    updated, steps = await history_service.apply_tool_calls(
        session,
        user_id=user.id,
        session_id=payload.session_id,
        calls=[history_service.ToolCall(name=name, params=payload.params)],
        pinned=payload.params,
    )

    # 单工具入口保持「失败就是失败」的语义：这里是确定性调用，没有别的步骤要救
    if not steps or not steps[0].ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=steps[0].message if steps else "工具执行失败",
        )

    return InvokeResponse(
        tool=name,
        message=steps[0].message,
        session=await sessions_service.to_out(session, updated),
    )
