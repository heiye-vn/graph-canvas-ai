"""trace 落库与指标聚合（M9.3）。

record() 刻意**吞掉自身异常**：trace 是观测设施，它坏了不能连累主流程 ——
宁可丢一条观测数据，也不能让用户的编辑操作跟着失败。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, AgentTrace
from app.models.agent_run import TERMINAL
from app.services import langfuse_export
from app.services import runs as runs_service

logger = logging.getLogger("graph-canvas-ai.trace")


async def record_detached(agent_run_id: uuid.UUID, session_id: uuid.UUID, **kwargs: Any) -> None:
    """图节点里用的免会话入口：自己开短会话，与节点内的业务会话解耦。"""
    try:
        async with runs_service.session_scope() as session:
            await record(session, agent_run_id=agent_run_id, session_id=session_id, **kwargs)
    except Exception:  # noqa: BLE001 - 同 record：观测设施绝不连累主流程
        logger.warning("trace（detached）落库失败（已忽略）", exc_info=True)


async def record(
    session: AsyncSession,
    *,
    agent_run_id: uuid.UUID,
    session_id: uuid.UUID,
    kind: str,
    name: str,
    status: str = "ok",
    started: float | None = None,
    prompt_version: str | None = None,
    model: str | None = None,
    tokens: dict[str, Any] | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """落一条 span。started = time.monotonic() 起点（有则自动算耗时）。"""
    try:
        trace = AgentTrace(
            agent_run_id=agent_run_id,
            session_id=session_id,
            kind=kind,
            name=name[:120],
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000) if started else None,
            prompt_version=prompt_version,
            model=model,
            tokens_in=(tokens or {}).get("input"),
            tokens_out=(tokens or {}).get("output"),
            detail=detail,
        )
        session.add(trace)
        await session.flush()

        # 旁路导出到 Langfuse（未配置 LANGFUSE_* 时完全 no-op）
        langfuse_export.export_span(
            agent_run_id=agent_run_id,
            session_id=session_id,
            kind=kind,
            name=name,
            status=status,
            duration_ms=trace.duration_ms,
            prompt_version=prompt_version,
            model=model,
            tokens_in=trace.tokens_in,
            tokens_out=trace.tokens_out,
            detail=detail,
        )
    except Exception:  # noqa: BLE001 - 观测设施绝不连累主流程
        logger.warning("trace 落库失败（已忽略）", exc_info=True)


async def trace_of(
    session: AsyncSession, *, user_id: uuid.UUID, run_id: uuid.UUID
) -> list[AgentTrace]:
    result = await session.scalars(
        select(AgentTrace)
        .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
        .where(AgentTrace.agent_run_id == run_id, AgentRun.user_id == user_id)
        .order_by(AgentTrace.created_at)
    )
    return list(result.all())


async def metrics(
    session: AsyncSession, *, user_id: uuid.UUID, days: int = 14
) -> dict[str, Any]:
    """按天聚合的可观测指标（仅当前用户）。核心是**计划校验拒绝率**（DoD ②）。

    拒绝率口径：planning 阶段 validate 失败的轮数 / 规划总轮数。
    分母取 turn 级（agent_runs），分子取 validate span 的 failed 数 ——
    两者都来自同一张 trace 表，口径天然一致。
    """
    since = datetime.now(UTC) - timedelta(days=days)

    turns = (
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.user_id == user_id, AgentRun.created_at >= since)
            .order_by(AgentRun.created_at)
        )
    ).all()

    validate_failed = (
        await session.scalars(
            select(func.count(AgentTrace.id))
            .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
            .where(
                AgentTrace.kind == "validate",
                AgentTrace.status == "failed",
                AgentTrace.created_at >= since,
                AgentRun.user_id == user_id,
            )
        )
    ).one()

    tool_spans = (
        await session.scalars(
            select(AgentTrace)
            .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
            .where(
                AgentTrace.kind == "tool",
                AgentTrace.created_at >= since,
                AgentRun.user_id == user_id,
            )
        )
    ).all()

    planner_spans = (
        await session.scalars(
            select(AgentTrace)
            .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
            .where(
                AgentTrace.kind == "planner",
                AgentTrace.created_at >= since,
                AgentRun.user_id == user_id,
            )
        )
    ).all()

    # ---- 轮级日聚合 ----
    by_day: dict[str, dict[str, Any]] = {}
    for turn in turns:
        day = turn.created_at.date().isoformat()
        bucket = by_day.setdefault(
            day, {"day": day, "rounds": 0, "failed": 0, "steps": 0}
        )
        bucket["rounds"] += 1
        if turn.status in TERMINAL and turn.status != "succeeded":
            bucket["failed"] += 1
        bucket["steps"] += len(turn.plan or [])

    rejected_total = int(validate_failed or 0)
    rounds_total = len(turns)
    planned_rounds = sum(1 for t in turns if t.plan) + rejected_total

    daily = sorted(by_day.values(), key=lambda item: item["day"])
    for bucket in daily:
        bucket["reject_rate"] = None  # 轮级日桶没有拒绝数，拒绝率只在版本组给

    # ---- prompt 版本分组（DoD ③：改版前后可对比） ----
    by_version: dict[str, dict[str, Any]] = {}
    for span in planner_spans:
        version = span.prompt_version or "unknown"
        bucket = by_version.setdefault(
            version, {"prompt_version": version, "plannings": 0, "validate_failed": 0,
                      "avg_duration_ms": 0.0, "tokens_out": 0}
        )
        bucket["plannings"] += 1
        bucket["avg_duration_ms"] += span.duration_ms or 0
        bucket["tokens_out"] += span.tokens_out or 0
    for bucket in by_version.values():
        n = bucket["plannings"]
        bucket["avg_duration_ms"] = round(bucket["avg_duration_ms"] / n, 1) if n else 0.0

    # validate 失败按版本分：靠 run 关联回 planner span 的版本
    validate_rows = (
        await session.scalars(
            select(AgentTrace)
            .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
            .where(
                AgentTrace.kind == "validate",
                AgentTrace.created_at >= since,
                AgentRun.user_id == user_id,
            )
        )
    ).all()
    for row in validate_rows:
        if row.status != "failed":
            continue
        # 精确归属：找同一 run 的 planner span
        planner = next(
            (s for s in planner_spans if s.agent_run_id == row.agent_run_id), None
        )
        version = planner.prompt_version if planner and planner.prompt_version else "unknown"
        if version in by_version:
            by_version[version]["validate_failed"] += 1

    for bucket in by_version.values():
        planned = bucket["plannings"] + bucket["validate_failed"]
        bucket["reject_rate"] = (
            round(bucket["validate_failed"] / planned, 4) if planned else 0.0
        )

    tool_failed = sum(1 for span in tool_spans if span.status == "failed")

    planned_turns = sum(1 for t in turns if t.plan)
    avg_steps = (
        round(sum(len(t.plan or []) for t in turns if t.plan) / max(1, planned_turns), 2)
    )
    # 重规划轮数 = 产生过 reflect span 的轮次；不要从 error 文案里猜（那里没有这个信息）
    replan_rounds = len(
        (
            await session.scalars(
                select(AgentTrace.agent_run_id)
                .join(AgentRun, AgentRun.id == AgentTrace.agent_run_id)
                .where(
                    AgentTrace.kind == "reflect",
                    AgentTrace.created_at >= since,
                    AgentRun.user_id == user_id,
                )
                .distinct()
            )
        ).all()
    )

    return {
        "days": days,
        "rounds_total": rounds_total,
        "rejected_total": rejected_total,
        # 核心指标：拒绝率 = 被拦下的计划 / 尝试规划的计划
        "reject_rate": round(rejected_total / planned_rounds, 4) if planned_rounds else 0.0,
        "avg_steps_per_round": avg_steps,
        "replan_rounds": replan_rounds,
        "tool_fail_rate": round(tool_failed / len(tool_spans), 4) if tool_spans else 0.0,
        "daily": daily,
        "by_prompt_version": sorted(
            by_version.values(), key=lambda item: item["prompt_version"]
        ),
    }
