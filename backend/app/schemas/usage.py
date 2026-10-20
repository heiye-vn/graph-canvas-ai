"""使用概览的响应结构（用户视角，不是研发指标）。

刻意与 `MetricsOut`（拒绝率 / prompt 版本）分开：那两个回答「Agent 稳不稳」，
这里回答「我这两天用得顺不顺、花了几张、哪次没出来」。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class UsageCounts(BaseModel):
    total: int
    succeeded: int
    failed: int
    cancelled: int


class DailyUsage(BaseModel):
    day: str
    succeeded: int
    failed: int


class ToolUsage(BaseModel):
    tool: str
    label: str
    count: int


class FailureItem(BaseModel):
    id: str
    kind: Literal["task", "chat"]
    label: str
    error: str | None
    created_at: datetime


class DailyTokens(BaseModel):
    day: str
    input: int
    output: int


class TokenSummary(BaseModel):
    """LLM 的 token 用量 —— **只统计服务商真实返回的 usage**。

    没有任何估算：模型没回 usage 的调用记进 `missing_calls` 并在界面上说明，
    而不是按字数猜一个看起来完整的数字。

    口径：planner / reflect 两次 LLM 调用的 span（一次调用一条 trace），
    生图、去背景、超分这些按次计费的任务不产生 token，不在其中。
    """

    input: int
    output: int
    total: int
    calls: int
    missing_calls: int
    by_day: list[DailyTokens]


class UsageSummaryOut(BaseModel):
    days: int
    tasks: UsageCounts
    chats: UsageCounts
    avg_seconds: float
    images: int
    daily: list[DailyUsage]
    by_tool: list[ToolUsage]
    tokens: TokenSummary
    failures: list[FailureItem]
