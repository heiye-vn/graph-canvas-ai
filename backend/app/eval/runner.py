"""评测 runner（M10）。

plan_fn 可注入：真实模型模式传 llm.plan_tool_calls_stream 的包装，
测试/回归门禁打桩模式传查表假 planner —— 打分逻辑两种模式完全同源。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from app.agent import plan as plan_mod
from app.agent.plan import PlanError

CASES_PATH = Path(__file__).parent / "cases.json"

# 评测用的固定画布摘要：模型决策依赖「图层叫什么」，评测不依赖具体画布
EVAL_SUMMARY = "画幅 1024×1024；图层 3 个（背景、图层 2、文字层）；当前图 PNG 含透明通道"


PlanFn = Callable[[str, str, list[dict[str, Any]]], Awaitable[Any]]


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    import json

    return json.loads((path or CASES_PATH).read_text(encoding="utf-8"))["cases"]


async def eval_one(
    case: dict[str, Any], plan_fn: PlanFn, functions: list[dict[str, Any]]
) -> dict[str, Any]:
    """跑一条：规划 → 校验 → 打分。规划层的任何异常都计为「被拦下」而非崩溃。"""
    from app.eval.metrics import exact_match, slot_accuracy, tool_f1

    rejected, error = False, None
    started = time.monotonic()
    calls: list[dict[str, Any]] = []
    try:
        raw = await plan_fn(case["instruction"], EVAL_SUMMARY, functions)
        calls, _meta = raw if isinstance(raw, tuple) else (raw, {})
        plan_mod.validate(
            [{"tool": call.get("name"), "args": call.get("args") or {}} for call in calls]
        )
    except PlanError as exc:
        rejected, error = True, str(exc)
    except Exception as exc:  # noqa: BLE001 - 规划层任何异常都是一条失败样本
        rejected, error = True, f"{type(exc).__name__}: {exc}"

    elapsed = int((time.monotonic() - started) * 1000)
    pred_tools = [call.get("name") for call in calls if call.get("name")]
    expected_tools = [step["tool"] for step in case["expected"]]

    return {
        "id": case["id"],
        "instruction": case["instruction"],
        "pred_tools": pred_tools,
        "expected_tools": expected_tools,
        "pred_calls": calls,
        "rejected": rejected,
        "error": error,
        "duration_ms": elapsed,
        "f1": tool_f1(pred_tools, expected_tools),
        "em": exact_match(pred_tools, expected_tools),
        "slot": slot_accuracy(calls, case["expected"]),
    }


async def run_eval(
    plan_fn: PlanFn,
    functions: list[dict[str, Any]],
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """跑完整评测集，返回聚合报告。"""
    from app.eval.metrics import exact_match, slot_accuracy, tool_f1  # noqa: F401

    cases = cases if cases is not None else load_cases()
    details = [await eval_one(case, plan_fn, functions) for case in cases]
    n = len(details) or 1

    return {
        "total": len(details),
        "tool_f1": round(sum(d["f1"] for d in details) / n, 4),
        "em": round(sum(1 for d in details if d["em"]) / n, 4),
        "slot_accuracy": round(sum(d["slot"] for d in details) / n, 4),
        "validate_pass_rate": round(sum(1 for d in details if not d["rejected"]) / n, 4),
        "avg_duration_ms": round(sum(d["duration_ms"] for d in details) / n),
        "details": details,
    }


# ------------------------------------------------------------------ 门禁

# 指标容差：真实模型输出有随机性（temperature>0），卡死基线会造成假警报
TOLERANCE = 0.05
# 门禁只看这几个聚合指标
GATED_KEYS = ("tool_f1", "em", "slot_accuracy", "validate_pass_rate")


def compare(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """当前指标 vs 基线：返回违反项的人话清单（空 = 通过）。"""
    violations = []
    for key in GATED_KEYS:
        floor = float(baseline.get(key, 0.0)) - TOLERANCE
        if float(current.get(key, 0.0)) < floor:
            violations.append(
                f"{key}: {current.get(key)} 低于基线 {baseline.get(key)}（容差 {TOLERANCE}）"
            )
    return violations
