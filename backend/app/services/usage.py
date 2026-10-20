"""使用概览统计（用户视角）。

三条口径必须先说清楚，否则数字会对不上用户的心理预期：

1. **任务**取 `tool_runs`：一次「去背景 / 拆层 / 导出物料」都算一次。
   它回答的是「我发起的操作成没成」，不是「模型调用了几次」。
2. **对话**取 `agent_runs`：一轮自然语言指令算一轮。
3. **图片**只数 `kind="image"`：投放尺寸（export）和选区遮罩（mask）是中间产物，
   算进去会让「生成了几张图」这个数字虚高。

平均耗时只统计**成功且有起止时间**的任务；失败任务往往瞬间结束，
把它们混进来会让耗时看起来好得不真实。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, AgentTrace, Asset, ToolRun
from app.models.run import CANCELLED, FAILED, SUCCEEDED
from app.schemas.usage import (
    DailyTokens,
    DailyUsage,
    FailureItem,
    TokenSummary,
    ToolUsage,
    UsageCounts,
    UsageSummaryOut,
)
from app.tools.registry import get_tool


def _label_of(tool: str) -> str:
    """工具的中文名；注册表里没有就退回原始名，不编造。"""
    spec = get_tool(tool)
    return spec.label if spec is not None else tool


def _error_text(error: Any) -> str | None:
    if not error:
        return None
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        value = error.get("message") or error.get("code")
        return str(value) if value else None
    return str(error)


async def summary(
    session: AsyncSession, user_id: uuid.UUID, *, days: int = 7
) -> UsageSummaryOut:
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    runs = (
        await session.scalars(
            select(ToolRun).where(
                ToolRun.user_id == user_id, ToolRun.created_at >= since
            )
        )
    ).all()
    chats = (
        await session.scalars(
            select(AgentRun).where(
                AgentRun.user_id == user_id, AgentRun.created_at >= since
            )
        )
    ).all()
    images = await session.scalar(
        select(func.count(Asset.id)).where(
            Asset.user_id == user_id,
            Asset.kind == "image",
            Asset.created_at >= since,
        )
    )

    tasks = {"total": len(runs), "succeeded": 0, "failed": 0, "cancelled": 0}
    chat_counts = {"total": len(chats), "succeeded": 0, "failed": 0, "cancelled": 0}
    durations: list[float] = []
    by_day: dict[str, dict[str, int]] = {}
    by_tool: dict[str, int] = {}
    failures: list[FailureItem] = []

    for run in runs:
        if run.status == SUCCEEDED:
            tasks["succeeded"] += 1
        elif run.status == FAILED:
            tasks["failed"] += 1
        elif run.status == CANCELLED:
            tasks["cancelled"] += 1

        day = run.created_at.date().isoformat()
        bucket = by_day.setdefault(day, {"succeeded": 0, "failed": 0})
        if run.status == SUCCEEDED:
            bucket["succeeded"] += 1
        elif run.status == FAILED:
            bucket["failed"] += 1

        if run.status == SUCCEEDED:
            start = run.started_at or run.created_at
            end = run.finished_at or run.updated_at
            if start and end:
                durations.append(max(0.0, (end - start).total_seconds()))
            by_tool[run.tool] = by_tool.get(run.tool, 0) + 1

        if run.status == FAILED:
            failures.append(
                FailureItem(
                    id=str(run.id),
                    kind="task",
                    label=_label_of(run.tool),
                    error=_error_text(run.error),
                    created_at=run.created_at,
                )
            )

    for chat in chats:
        if chat.status == SUCCEEDED:
            chat_counts["succeeded"] += 1
        elif chat.status == FAILED:
            chat_counts["failed"] += 1
        elif chat.status == CANCELLED:
            chat_counts["cancelled"] += 1

        if chat.status == FAILED:
            failures.append(
                FailureItem(
                    id=str(chat.id),
                    kind="chat",
                    label=(chat.instruction or "对话").strip()[:40],
                    error=_error_text(chat.error),
                    created_at=chat.created_at,
                )
            )

    failures.sort(key=lambda item: item.created_at, reverse=True)

    # ---- token 用量：只认 agent_traces 里服务商真实返回的 usage ----
    # 一次 LLM 调用一条 span（planner / reflect），validate / tool 没有 token。
    # join agent_runs 是为了按用户过滤（trace 表本身没有 user_id）。
    token_rows = (
        await session.execute(
            select(
                AgentTrace.tokens_in, AgentTrace.tokens_out, AgentTrace.created_at
            )
            .join(AgentRun, AgentTrace.agent_run_id == AgentRun.id)
            .where(
                AgentRun.user_id == user_id,
                AgentTrace.created_at >= since,
                AgentTrace.kind.in_(("planner", "reflect")),
            )
        )
    ).all()

    token_in = 0
    token_out = 0
    token_calls = 0
    token_missing = 0
    tokens_by_day: dict[str, dict[str, int]] = {}
    for row_in, row_out, created_at in token_rows:
        if row_in is None and row_out is None:
            # 服务商没返回 usage：记一笔「缺失」，绝不按字数估算
            token_missing += 1
            continue
        value_in = int(row_in or 0)
        value_out = int(row_out or 0)
        token_calls += 1
        token_in += value_in
        token_out += value_out
        day = created_at.date().isoformat()
        bucket = tokens_by_day.setdefault(day, {"input": 0, "output": 0})
        bucket["input"] += value_in
        bucket["output"] += value_out

    daily_tokens = [
        DailyTokens(
            day=(now.date() - timedelta(days=offset)).isoformat(),
            **tokens_by_day.get(
                (now.date() - timedelta(days=offset)).isoformat(),
                {"input": 0, "output": 0},
            ),
        )
        for offset in range(days - 1, -1, -1)
    ]

    # 补齐没有记录的日期：图表上要看到「那天是 0」，而不是整根柱子消失
    daily: list[DailyUsage] = []
    for offset in range(days - 1, -1, -1):
        day = (now.date() - timedelta(days=offset)).isoformat()
        bucket = by_day.get(day, {"succeeded": 0, "failed": 0})
        daily.append(DailyUsage(day=day, **bucket))

    ordered_tools = sorted(by_tool.items(), key=lambda item: item[1], reverse=True)

    return UsageSummaryOut(
        days=days,
        tasks=UsageCounts(**tasks),
        chats=UsageCounts(**chat_counts),
        avg_seconds=round(sum(durations) / len(durations), 1) if durations else 0.0,
        images=int(images or 0),
        daily=daily,
        by_tool=[
            ToolUsage(tool=tool, label=_label_of(tool), count=count)
            for tool, count in ordered_tools
        ],
        tokens=TokenSummary(
            input=token_in,
            output=token_out,
            total=token_in + token_out,
            calls=token_calls,
            missing_calls=token_missing,
            by_day=daily_tokens,
        ),
        failures=failures[:20],
    )
