"""Agent 计划相关 schema（M8）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tool: str
    params: dict[str, Any]
    depends_on: list[str]
    status: str
    run_id: str | None = None
    message: str | None = None


class AgentRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    instruction: str
    plan: list[PlanStepOut]
    reply: str | None
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime


class PlanRequest(BaseModel):
    session_id: uuid.UUID
    instruction: str = Field(min_length=1, max_length=1000)


class ContinueRequest(BaseModel):
    """排队步对应的 ToolRun id —— 它结束后驱动计划继续。"""

    run_id: uuid.UUID
