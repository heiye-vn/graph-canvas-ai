"""工具元数据与直接调用。

`GET /api/tools` 是前端表单的**唯一来源**：加一个工具，前端不改一行代码就能
显示标签和参数表单（DoD ②）。所以这份元数据必须包含渲染表单需要的全部信息
（标签、说明、类型、取值范围、默认值），而不是只给个名字让前端去猜。

`POST /api/tools/{name}/invoke` 是给「确定性操作」用的：模型不参与，
参数由界面给出。它的存在也让工具链路在没有配置模型 Key 的情况下可以被验证。
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
from app.schemas.layer_doc import LayerDocument
from app.schemas.session import SessionOut
from app.services import sessions as sessions_service
from app.services import tool_exec
from app.tools.base import ToolContext, ToolError
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

    edit_session = await sessions_service.get_edit_session(
        session, user.id, payload.session_id
    )
    ctx = ToolContext(
        session_id=edit_session.id,
        user_id=user.id,
        doc=LayerDocument.model_validate(edit_session.doc),
        # UI 给的参数全部作为「服务端回填」的来源：asset_id 这类隐藏字段由界面传，
        # 不走模型那条路
        pinned=payload.params,
    )

    try:
        result = await tool_exec.invoke(name, payload.params, ctx)
    except ToolError as exc:
        # 工具自己的业务失败对用户是可解释的，给 422 而不是 500
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message)

    updated = await sessions_service.replace_doc(
        session, user_id=user.id, session_id=edit_session.id, doc=result.doc
    )
    return InvokeResponse(
        tool=name,
        message=result.message,
        session=await sessions_service.to_out(session, updated),
    )
