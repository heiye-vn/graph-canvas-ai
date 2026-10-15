"""多步计划校验（M8）—— 六道关卡，全部拦在「碰画布」之前。

    ① 工具存在性   ② 参数 model_validate   ③ 补 step id + 默认串行依赖
    ④ MAX_STEPS=8  ⑤ 依赖存在性            ⑥ Kahn 拓扑环检测

任何一道不过都是一句人话的 PlanError —— 幻觉工具名、参数错型、
循环依赖、超长计划，绝不能流到执行层变成「跑了两步然后莫名失败」。
异常统一由 services 层转成「plan 清空 + 一句人话」，绝不 500。

步骤状态机（存在 plan JSONB 里）：
    pending → queued(run 已投递) → succeeded / failed / canceled
    waiting —— 预留给人机确认（M9.2 的 interrupt 会正式用上）
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.tools.base import ToolSpec
from app.tools.registry import get_tool

MAX_STEPS = 8

PENDING = "pending"
WAITING = "waiting"
QUEUED = "queued"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELED = "canceled"

_OPEN = {PENDING, WAITING, QUEUED, RUNNING}
_BLOCKED = {FAILED, CANCELED}


class PlanError(Exception):
    """计划校验失败。message 面向用户，直接展示。"""


def validate(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """六道关卡入口：LLM 吐出的裸调用列表 → 可执行的计划。"""
    checked: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        name = item.get("tool")
        spec = get_tool(name) if name else None
        if spec is None:
            known = "、".join(sorted(spec.name for spec in _all_specs())[:12])
            raise PlanError(f"第 {index} 步用了不存在的工具「{name}」。可用工具：{known}")
        try:
            spec.params_model.model_validate(item.get("args") or {})
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            raise PlanError(
                f"第 {index} 步（{spec.label}）参数不对：{where or '参数'} {first.get('msg')}"
            ) from exc
        checked.append({"tool": spec.name, "params": item.get("args") or {}})
    return assemble(checked)


def assemble(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """补全步骤 id、顺序依赖与初始状态，并拒绝超长或成环的计划。"""
    if len(raw) > MAX_STEPS:
        raise PlanError(f"计划超过 {MAX_STEPS} 步，请拆成多次说明")

    steps: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        step_id = item.get("id") or f"s{index}"
        depends = item.get("depends_on")
        if depends is None:
            # 默认串行：后一步依赖前一步（编辑类操作的天然顺序）
            depends = [steps[-1]["id"]] if steps else []
        steps.append(
            {
                "id": step_id,
                "tool": item["tool"],
                "params": item.get("params") or {},
                "depends_on": list(depends),
                "run_id": item.get("run_id"),
                "message": item.get("message"),
                "status": item.get("status") or PENDING,
            }
        )

    known = {step["id"] for step in steps}
    for step in steps:
        missing = [dep for dep in step["depends_on"] if dep not in known]
        if missing:
            raise PlanError(f"步骤 {step['id']} 依赖了不存在的步骤")
    if _cyclic(steps):
        raise PlanError("计划步骤存在循环依赖")
    return steps


def ready(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依赖全部成功、自己还没跑的步骤 —— 现在就能执行。"""
    by_id = {step["id"]: step for step in steps}
    return [step for step in steps if _is_ready(step, by_id)]


def settle(steps: list[dict[str, Any]]) -> str:
    """根据步骤状态汇总整轮。

    关键：失败步的依赖者永远 pending —— 若只看「还有开放步就 RUNNING」，
    计划会卡死在 RUNNING 且重试按钮永远不出现。所以只要没有在跑的
    步骤且存在失败，整轮就判定为 FAILED（重试从失败步续）。
    """
    statuses = [step["status"] for step in steps]
    if any(status in {QUEUED, RUNNING} for status in statuses):
        return RUNNING
    if any(status == FAILED for status in statuses):
        return FAILED
    if any(status == CANCELED for status in statuses):
        return CANCELED
    if any(status in {PENDING, WAITING} for status in statuses):
        # 理论不可达（pending 只会被失败或取消堵住）；守一眼，宁可 RUNNING 不谎报完成
        return RUNNING
    return SUCCEEDED


def needs_confirm(steps: list[dict[str, Any]]) -> bool:
    return len(steps) > 1


def cancel_remaining(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """没到终态的步骤全部取消 —— queued 也要取消（级联取消靠这个状态找 run）。"""
    return [
        {**step, "status": CANCELED}
        if step["status"] in {PENDING, WAITING, QUEUED}
        else step
        for step in steps
    ]


def _is_ready(step: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    if step["status"] not in {PENDING, WAITING} or step.get("run_id"):
        return False
    deps = [by_id[dep] for dep in step["depends_on"]]
    if any(dep["status"] in _BLOCKED for dep in deps):
        return False
    return all(dep["status"] == SUCCEEDED for dep in deps)


def _cyclic(steps: list[dict[str, Any]]) -> bool:
    """Kahn：拓扑序能走完 = 无环。"""
    ids = [step["id"] for step in steps]
    incoming = {step_id: 0 for step_id in ids}
    outgoing: dict[str, list[str]] = {step_id: [] for step_id in ids}
    for step in steps:
        for dep in step["depends_on"]:
            outgoing[dep].append(step["id"])
            incoming[step["id"]] += 1

    queue = [step_id for step_id, count in incoming.items() if count == 0]
    seen = 0
    while queue:
        node = queue.pop()
        seen += 1
        for nxt in outgoing[node]:
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    return seen != len(ids)


def _all_specs() -> list[ToolSpec]:
    from app.tools.registry import all_tools

    return all_tools()
