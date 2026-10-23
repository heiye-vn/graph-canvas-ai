"""真 LangGraph 状态机（M9.2）—— 计划 / 确认中断 / 执行 / 观察 / 反思。

图结构：
    START → plan → confirm_gate → execute → observe →（条件边）
        confirm_gate 未确认时 interrupt() —— **人机确认就是一次图中断**，
        状态由 checkpointer 落库，用户点「确认」后 Command(resume) 从断点续跑。
        这是「转 QUEUED + 手动点」做不到的：中断恢复、断点续跑、重启接续
        全部是同一个机制（DoD ② 的根基）。
    observe 条件边：
        有失败且 replan 未超限 → reflect（错误回灌，只重规划剩余目标）
        有失败且超限           → END（优雅降级为 failed，绝不死循环）
        有排队步              → wait_run interrupt（ToolRun 完成后 resume）
        全部成功               → END
        其余                   → execute

⚠️ State 只保留 Annotation 声明过的 channel —— 未声明的 key 会被
LangGraph **静默丢弃**（踩过的坑，写在这里防再犯）。
"""

from __future__ import annotations

import operator
import time
import uuid
from typing import Annotated, Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from typing_extensions import TypedDict

from app.agent import llm as llm_module
from app.agent import plan as plan_mod
from app.agent.plan import PlanError
from app.agent.prompts import PROMPT_VERSION
from app.models import AgentRun
from app.services import cot as cot_service
from app.services import history as history_service
from app.services import runs as runs_service
from app.services import tool_exec
from app.services import traces as traces_service

MAX_REPLANS = 2  # reflect→replan 的上限，超过即优雅降级（DoD ③）

CONFIRM = "confirm"
WAIT_RUN = "wait_run"


class GraphState(TypedDict):
    # ⚠️ 这里没有声明的 key 一律不进 checkpoint
    run_id: str
    user_id: str
    session_id: str
    instruction: str
    plan: list[dict[str, Any]]
    errors: Annotated[list[str], operator.add]
    replans: int
    approved: bool


# ------------------------------------------------------------------ 节点


async def plan_node(state: GraphState) -> dict[str, Any]:
    """流式规划 + 六道关卡。已有计划（retry 续跑）时直接跳过。"""
    if state.get("plan"):
        return {}
    run_id_val = state.get("run_id")
    if not run_id_val:
        return {}
    started = time.monotonic()
    emit = _emitter(run_id_val)
    edit_session = await _session_of(state)
    doc = history_service.LayerDocument.model_validate(edit_session.doc)
    result = await llm_module.plan_tool_calls_stream(
        state["instruction"], tool_exec.summarize_doc(doc), _function_schemas(), emit
    )
    # 兼容旧桩（直接返回 list）：新签名返回 (calls, meta)
    calls, meta = result if isinstance(result, tuple) else (result, {})
    try:
        steps = plan_mod.validate(
            [{"tool": call.get("name"), "args": call.get("args") or {}} for call in calls]
        )
    except PlanError as exc:
        await emit("reflection", str(exc))
        # 校验失败必须落 trace ——「计划校验拒绝率」的分母不能少这一票
        await traces_service.record_detached(
            uuid.UUID(state["run_id"]),
            uuid.UUID(state["session_id"]),
            kind="validate",
            name="plan.validate",
            status="failed",
            started=started,
            prompt_version=PROMPT_VERSION,
            model=meta.get("model"),
            tokens=meta.get("tokens"),
            detail={"error": str(exc), "tool_calls": calls},
        )
        return {"plan": [], "errors": [str(exc)]}

    await traces_service.record_detached(
        uuid.UUID(state["run_id"]),
        uuid.UUID(state["session_id"]),
        kind="planner",
        name="plan.stream",
        status="ok",
        started=started,
        prompt_version=PROMPT_VERSION,
        model=meta.get("model"),
        tokens=meta.get("tokens"),
        detail={"steps": len(steps), "tool_calls": calls},
    )
    return {"plan": steps}


async def confirm_gate(state: GraphState) -> dict[str, Any]:
    """人机确认 = 图中断（★ M9.2 的点睛）。

    多步计划首次进入且未确认 → interrupt：整个图状态由 checkpointer 落地，
    进程重启都不丢。用户点「确认」→ Command(resume={"action": CONFIRM})。
    """
    plan = state["plan"]
    if not plan or state.get("approved"):
        return {}
    # 已有排队步（从 wait_run 恢复的续跑）不算需要确认
    if not plan_mod.needs_confirm(plan) or any(
        step["status"] in {plan_mod.SUCCEEDED, plan_mod.QUEUED} for step in plan
    ):
        return {"approved": True}

    response = interrupt({"kind": CONFIRM, "plan": plan})
    action = (response or {}).get("action")
    if action != CONFIRM:
        # resume 传的不是确认：视为取消
        canceled = plan_mod.cancel_remaining([dict(step) for step in plan])
        return {"plan": canceled, "approved": False}
    return {"approved": True}


async def execute_node(state: GraphState) -> dict[str, Any]:
    """跑**一个**就绪步骤（同步步走 apply_tool_calls，与手动执行同路径）。

    每步一事务、每步一次节点往返 —— 前端刷新拿到的 plan 永远是
    「上一步已完成、下一步未开始」的干净现场（M8 DoD ④ 的延续）。
    """
    emit = _emitter(state["run_id"])
    steps = [dict(step) for step in state["plan"]]
    ready = plan_mod.ready(steps)
    if not ready:
        return {"plan": steps}
    step = ready[0]
    started = time.monotonic()

    async with runs_service.session_scope() as session:
        turn = await session.get(
            AgentRun, uuid.UUID(state["run_id"]), populate_existing=True, with_for_update=True,
        )
        if turn is None or turn.is_terminal:
            return {"plan": plan_mod.cancel_remaining(steps)}
        # 崩溃重放保护：apply_tool_calls 已把这一步的终态与副作用同事务提交，
        # 而 checkpoint 可能仍停在执行前 —— DB 里已推进的步骤绝不重复执行。
        committed = next(
            (item for item in (turn.plan or []) if item.get("id") == step["id"]), None,
        )
        if committed is not None and (
            committed.get("status") not in (plan_mod.PENDING, plan_mod.WAITING)
            or committed.get("run_id")
        ):
            for item in steps:
                if item.get("id") == step["id"]:
                    item.update(
                        {key: committed.get(key) for key in ("status", "run_id", "message")}
                    )
                    break
            return {"plan": steps}
        await emit("observation", f"开始执行第 {step['id']} 步：{step['tool']}")
        # 工具提交时在同一事务内关联父计划；不能等图增量写回，否则取消会漏子任务。
        session.info["agent_step"] = (turn.id, step["id"])
        try:
            _, results = await history_service.apply_tool_calls(
                session,
                user_id=uuid.UUID(state["user_id"]),
                session_id=uuid.UUID(state["session_id"]),
                calls=[history_service.ToolCall(name=step["tool"], params=step["params"])],
            )
        finally:
            session.info.pop("agent_step", None)
    result = results[0] if results else None
    if result is None:
        step["status"] = plan_mod.FAILED
        step["message"] = "步骤执行失败"
    elif result.run_id:
        step["run_id"] = str(result.run_id)
        step["status"] = plan_mod.QUEUED
        step["message"] = result.message
        await emit("observation", f"已提交后台任务：{result.message}")
    elif result.ok:
        step["status"] = plan_mod.SUCCEEDED
        step["message"] = result.message
        await emit("observation", f"完成：{result.message}")
    else:
        step["status"] = plan_mod.FAILED
        step["message"] = result.message
        await emit("observation", f"失败：{result.message}")

    # 排队只代表提交成功；异步工具真正的成败由 observe 节点核对，
    # 这里记 failed 会把所有排队型工具的提交都算进工具失败率。
    ok = step["status"] in (plan_mod.SUCCEEDED, plan_mod.QUEUED)
    await traces_service.record_detached(
        uuid.UUID(state["run_id"]),
        uuid.UUID(state["session_id"]),
        kind="tool",
        name=f"execute:{step['tool']}",
        status="ok" if ok else "failed",
        started=started,
        detail={
            "step_id": step["id"],
            "message": step.get("message"),
            "run_id": step.get("run_id"),
            "async": step["status"] == plan_mod.QUEUED,
        },
    )
    return {"plan": steps}


async def observe_node(state: GraphState) -> dict[str, Any]:
    """核对排队步的真实终态；停在 wait_run 等回调恢复。

    ⚠️ interrupt() 的语义：首次执行到此处抛出中断并 checkpoint；
    resume 后**本节点从头重跑**，interrupt() 返回 resume 值 ——
    所以核对逻辑写成幂等循环，重放时不会重复发事件（状态已终态就不再 emit）。
    """
    emit = _emitter(state["run_id"])
    steps = [dict(step) for step in state["plan"]]
    while True:
        for step in steps:
            if step["status"] != plan_mod.QUEUED or not step.get("run_id"):
                continue
            async with runs_service.session_scope() as session:
                tool_run = await runs_service.get_run(
                    session, uuid.UUID(state["user_id"]), uuid.UUID(step["run_id"])
                )
            mapped = {
                "succeeded": plan_mod.SUCCEEDED,
                "failed": plan_mod.FAILED,
                "cancelled": plan_mod.CANCELED,
            }.get(tool_run.status)
            if mapped and step["status"] != mapped:
                step["status"] = mapped
                step["message"] = (tool_run.error or {}).get("message") or step["message"] or "完成"
                await emit(
                    "observation",
                    f"后台任务结束：{step['message']}"
                    if mapped == plan_mod.SUCCEEDED
                    else f"失败：{step['message']}",
                )
        waiting = [step for step in steps if step["status"] == plan_mod.QUEUED]
        if not waiting:
            return {"plan": steps}
        # 还有排队步没到终态：中断等回调；resume 后循环重跑，自然再核对
        interrupt({"kind": WAIT_RUN, "run_id": waiting[0].get("run_id")})


async def reflect_node(state: GraphState) -> dict[str, Any]:
    """错误回灌：反思失败原因，重规划**剩余**目标（DoD ①）。"""
    started = time.monotonic()
    emit = _emitter(state["run_id"])
    steps = [dict(step) for step in state["plan"]]
    failed = next(step for step in reversed(steps) if step["status"] == plan_mod.FAILED)
    done = [step["tool"] for step in steps if step["status"] == plan_mod.SUCCEEDED]

    await emit(
        "reflection",
        f"「{failed['tool']}」失败了：{failed.get('message') or '未知原因'}。重新规划剩余步骤。",
    )

    remaining_goal = (
        f"{state['instruction']}\n\n"
        f"（已成功完成：{'、'.join(done) if done else '无'}。"
        f"上一步「{failed['tool']}」失败：{failed.get('message') or '未知原因'}。"
        f"请只输出完成剩余目标所需的后续工具调用。）"
    )
    result = await llm_module.plan_tool_calls_stream(
        remaining_goal, "（反思重规划）", _function_schemas(), emit
    )
    calls, meta = result if isinstance(result, tuple) else (result, {})
    replans = state.get("replans", 0) + 1

    async def _trace_reflect(status: str, detail: dict[str, Any]) -> None:
        await traces_service.record_detached(
            uuid.UUID(state["run_id"]),
            uuid.UUID(state["session_id"]),
            kind="reflect",
            name=f"reflect#{replans}",
            status=status,
            started=started,
            prompt_version=PROMPT_VERSION,
            model=meta.get("model"),
            tokens=meta.get("tokens"),
            detail=detail,
        )

    try:
        replanned = plan_mod.validate(
            [{"tool": call.get("name"), "args": call.get("args") or {}} for call in calls]
        )
    except PlanError as exc:
        await emit("reflection", f"重规划仍失败：{exc}")
        await _trace_reflect("failed", {"error": str(exc), "failed_tool": failed["tool"]})
        return {"plan": steps, "errors": [str(exc)], "replans": replans}

    if not replanned:
        await emit("reflection", "重规划没有产出任何步骤，停下交还给人。")
        await _trace_reflect("failed", {"error": "重规划为空", "failed_tool": failed["tool"]})
        return {"plan": steps, "replans": replans}

    # 丢弃失败步与它的未完成依赖，换成新计划（已完成步保留在前）
    kept = [step for step in steps if step["status"] == plan_mod.SUCCEEDED]
    # validate 每次都从 s1 编号；必须连同依赖一起重映射，不能覆盖已完成步。
    prefix = f"r{replans}_{uuid.uuid4().hex}_"
    id_map = {step["id"]: f"{prefix}{step['id']}" for step in replanned}
    for step in replanned:
        step["id"] = id_map[step["id"]]
        step["depends_on"] = [id_map[dep] for dep in step["depends_on"]]
    merged = [*kept, *replanned]
    await emit("observation", f"已重新规划剩余 {len(replanned)} 步")
    await _trace_reflect(
        "ok", {"failed_tool": failed["tool"], "replanned_steps": len(replanned)}
    )
    return {
        "plan": merged,
        "replans": replans,
        "errors": [f"第 {replans} 次重规划"],
    }


# ------------------------------------------------------------------ 条件边


def after_observe(state: GraphState) -> str:
    plan = state["plan"]
    if not plan:
        return END
    if plan_mod.settle(plan) == plan_mod.SUCCEEDED:
        return END
    if any(step["status"] == plan_mod.FAILED for step in plan):
        if state.get("replans", 0) >= MAX_REPLANS:
            return END  # 优雅降级：FAILED + 人工接手，绝不死循环（DoD ③）
        return "reflect"
    if plan_mod.settle(plan) == plan_mod.CANCELED:
        return END
    return "execute"


def after_plan(state: GraphState) -> str:
    if not state.get("plan"):
        return END  # 规划失败 / 空计划
    return "confirm_gate"


def after_gate(state: GraphState) -> str:
    plan = state["plan"]
    if plan and all(step["status"] == plan_mod.CANCELED for step in plan):
        return END  # 用户在中断恢复时选择了取消
    if plan and plan_mod.ready(plan):
        return "execute"
    return "observe"


# ------------------------------------------------------------------ 组装


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("plan", plan_node)
    builder.add_node("confirm_gate", confirm_gate)
    builder.add_node("execute", execute_node)
    builder.add_node("observe", observe_node)
    builder.add_node("reflect", reflect_node)

    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", after_plan, {"confirm_gate": "confirm_gate", END: END})
    builder.add_conditional_edges(
        "confirm_gate", after_gate, {"execute": "execute", "observe": "observe", END: END}
    )
    builder.add_edge("execute", "observe")
    builder.add_conditional_edges(
        "observe",
        after_observe,
        {"execute": "execute", "reflect": "reflect", END: END},
    )
    builder.add_edge("reflect", "execute")
    return builder


def _emitter(run_id: str):
    """绑定 run 的 CoT 发射器（同步工厂 + async 闭包，别把工厂本身写成协程）。"""
    run_uuid = uuid.UUID(run_id)

    async def emit(kind: str, delta: str) -> None:
        await cot_service.emit(run_uuid, kind, delta)

    return emit


async def _session_of(state: GraphState):
    from app.services import sessions as sessions_service

    async with runs_service.session_scope() as session:
        return await sessions_service.get_edit_session(
            session, uuid.UUID(state["user_id"]), uuid.UUID(state["session_id"])
        )


def _function_schemas() -> list[dict[str, Any]]:
    from app.tools.registry import function_schemas

    return function_schemas()
