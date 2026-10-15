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


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    session_id: uuid.UUID
    kind: str
    name: str
    status: str
    duration_ms: int | None
    prompt_version: str | None
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    detail: dict[str, Any] | None
    created_at: datetime


class VersionMetrics(BaseModel):
    prompt_version: str
    plannings: int
    validate_failed: int
    reject_rate: float
    avg_duration_ms: float
    tokens_out: int


class DailyMetrics(BaseModel):
    day: str
    rounds: int
    failed: int
    steps: int


class MetricsOut(BaseModel):
    days: int
    rounds_total: int
    rejected_total: int
    reject_rate: float
    avg_steps_per_round: float
    tool_fail_rate: float
    daily: list[DailyMetrics]
    by_prompt_version: list[VersionMetrics]
