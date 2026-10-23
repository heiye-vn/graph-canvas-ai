"""任务闭环离线回归：不连接数据库、Redis、对象存储或真实模型。"""

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import graph, plan
from app.models import AgentRun, ToolRun
from app.routers import events as event_router
from app.schemas.layer_doc import Canvas, LayerDocument
from app.services import agent_runs, runs
from app.tasks import region

pytestmark = pytest.mark.unit


def tool_run(status="running"):
    return ToolRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), tool="erase_region",
        status=status, progress=30, params={},
    )


@pytest.mark.parametrize("operation", ["succeed", "fail", "report"])
async def test_terminal_tool_run_is_immutable(monkeypatch, operation):
    run = tool_run("cancelled")
    publish = AsyncMock()
    monkeypatch.setattr(runs.events, "publish", publish)
    if operation == "succeed":
        await runs.succeed(run, {"asset_ids": ["late"]})
    elif operation == "fail":
        await runs.fail(run, code="late", message="迟到的失败")
    else:
        await runs.report(run, progress=100, stage="迟到的进度", to_running=True)
    assert run.status == "cancelled"
    assert run.progress == 30
    assert run.result is None
    publish.assert_not_awaited()


async def test_replan_ids_and_dependencies_are_unique(monkeypatch):
    steps = plan.assemble([
        {"tool": "flip_layer", "status": "succeeded"},
        {"tool": "flip_layer", "status": "failed"},
    ])
    monkeypatch.setattr(graph.llm_module, "plan_tool_calls_stream", AsyncMock(return_value=[
        {"name": "flip_layer", "args": {"direction": "horizontal"}},
        {"name": "flip_layer", "args": {"direction": "vertical"}},
    ]))
    monkeypatch.setattr(graph.cot_service, "emit", AsyncMock())
    monkeypatch.setattr(graph.traces_service, "record_detached", AsyncMock())
    result = await graph.reflect_node({
        "run_id": str(uuid4()), "session_id": str(uuid4()), "plan": steps,
        "instruction": "翻转", "replans": 0,
    })
    merged = result["plan"]
    assert len({step["id"] for step in merged}) == len(merged)
    assert merged[1]["id"] not in {s["id"] for s in steps}
    assert merged[2]["depends_on"] == [merged[1]["id"]]
    assert plan.ready(merged) == [merged[1]]


@asynccontextmanager
async def empty_subscription(_run_id):
    async def empty():
        if False:
            yield
    yield empty()


async def test_tool_sse_reads_snapshot_after_subscription(monkeypatch):
    run = tool_run()
    latest = tool_run("succeeded")
    latest.id, latest.user_id = run.id, run.user_id
    latest.result = {"document": {"applied": True}}
    session = SimpleNamespace(get=AsyncMock(return_value=latest))
    subscribed = False

    @asynccontextmanager
    async def subscription(_):
        nonlocal subscribed
        subscribed = True
        async with empty_subscription(_) as stream:
            yield stream

    @asynccontextmanager
    async def scope():
        assert subscribed, "必须先订阅，再用独立会话重读终态"
        yield session

    monkeypatch.setattr(event_router.events, "subscription", subscription)
    monkeypatch.setattr(runs, "session_scope", scope)
    frames = [item async for item in event_router._event_stream(run.id, run)]
    assert '"status":"succeeded"' in frames[0]
    assert '"applied":true' in frames[0]
    assert '"type":"done"' in frames[-1]


async def test_agent_sse_reads_snapshot_after_subscription(monkeypatch):
    run_id = uuid4()
    turn = AgentRun(id=run_id, status="cancelled", plan=[])
    session = SimpleNamespace(get=AsyncMock(return_value=turn))

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(event_router.events, "subscription", empty_subscription)
    monkeypatch.setattr(event_router.cot_service, "replay", AsyncMock(return_value=[]))
    monkeypatch.setattr(runs, "session_scope", scope)
    frames = [item async for item in event_router._agent_event_stream(
        run_id, "planning", False, 0,
    )]
    assert '"status":"cancelled"' in frames[0]
    assert '"type":"done"' in frames[-1]


class RegionSession:
    def __init__(self, run):
        self.run = run
        self.commit = AsyncMock()
        self.added = []

    async def get(self, model, key, **kwargs):
        return self.run

    def add(self, value):
        self.added.append(value)


@pytest.fixture
def region_case(monkeypatch):
    import io

    from PIL import Image

    def png(color):
        buffer = io.BytesIO()
        Image.new("RGBA", (4, 4), color).save(buffer, format="PNG")
        return buffer.getvalue()

    run = tool_run("queued")
    run.params = {"session_id": str(run.session_id), "revision": 7}
    record = SimpleNamespace(
        id=run.session_id, user_id=run.user_id, revision=7,
        doc=LayerDocument(canvas=Canvas(width=4, height=4)).model_dump(mode="json"),
    )
    session = RegionSession(run)

    @asynccontextmanager
    async def scope():
        yield session

    async def record_external(db, target, *, expected_revision, after, **kwargs):
        if target.revision != expected_revision:
            from app.services.history import RevisionConflict
            raise RevisionConflict("画布已更新")
        target.doc = after.model_dump(mode="json")
        target.revision += 1

    from app.services import history
    asset = SimpleNamespace(id=uuid4(), s3_key="unit-result", width=4, height=4)
    external = AsyncMock(side_effect=record_external)
    publish = AsyncMock()
    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(region.sessions_service, "get_edit_session", AsyncMock(return_value=record))
    monkeypatch.setattr(region.selections, "mask_bytes", AsyncMock(return_value=png("white")))
    monkeypatch.setattr(region.selections, "clear", AsyncMock())
    monkeypatch.setattr(
        region.flatten_service, "flatten_session", AsyncMock(return_value=png("red")),
    )
    monkeypatch.setattr(region, "_edit_with_clamp", AsyncMock(return_value=png("blue")))
    monkeypatch.setattr(region.asset_service, "create_from_bytes", AsyncMock(return_value=asset))
    monkeypatch.setattr(region.storage, "presign_get", lambda _: "unit-result")
    monkeypatch.setattr(history, "record_external", external)
    monkeypatch.setattr(region.events, "publish", publish)
    return SimpleNamespace(
        run=run, record=record, session=session, external=external, asset=asset, publish=publish,
    )


async def test_region_adopts_once_without_frontend(region_case):
    case = region_case
    await region.inpaint_region({}, str(case.run.id))
    assert case.run.status == "succeeded"
    assert case.record.revision == 8
    assert case.run.result["document"] == case.record.doc
    assert "adopt_asset_id" not in case.run.result
    doc = LayerDocument.model_validate(case.record.doc)
    assert doc.layers[-1].source.asset_id == case.asset.id
    assert doc.active_layer_id == doc.layers[-1].id
    assert len(case.session.added) == 1
    await region.inpaint_region({}, str(case.run.id))
    case.external.assert_awaited_once()
    assert case.record.revision == 8


async def test_region_rejects_revision_changed_during_provider(region_case, monkeypatch):
    case = region_case
    edit = region._edit_with_clamp

    async def change_revision(*args, **kwargs):
        case.record.revision += 1
        return await edit(*args, **kwargs)

    monkeypatch.setattr(region, "_edit_with_clamp", change_revision)
    await region.inpaint_region({}, str(case.run.id))
    assert case.run.status == "failed"
    assert case.run.error["code"] == "revision_conflict"
    assert case.record.doc["layers"] == []
    assert not any(call.args[0].type == "result" for call in case.publish.await_args_list)


async def test_region_cancel_during_provider_does_not_adopt(region_case, monkeypatch):
    case = region_case
    edit = region._edit_with_clamp

    async def cancel(*args, **kwargs):
        case.run.status = "cancelled"
        return await edit(*args, **kwargs)

    monkeypatch.setattr(region, "_edit_with_clamp", cancel)
    await region.inpaint_region({}, str(case.run.id))
    assert case.run.status == "cancelled"
    case.external.assert_not_awaited()
    region.asset_service.create_from_bytes.assert_not_awaited()


async def test_upscale_applies_the_upscaled_asset(monkeypatch):
    """超分产物必须成为画布图源；只放大 canvas 几何会让用户看到旧图被拉伸。"""
    from app.services import layer_doc as L
    from app.tasks import enhance

    old_asset_id = uuid4()
    new_asset_id = uuid4()
    doc = LayerDocument(
        canvas=Canvas(width=4, height=4),
        layers=[L.new_image_layer(old_asset_id, width=4, height=4, name="原图")],
    )
    run = ToolRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(),
        tool="upscale_image", status="running", params={"scale": 2},
    )
    record = SimpleNamespace(
        id=run.session_id, user_id=run.user_id, revision=1,
        doc=doc.model_dump(mode="json"),
    )
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def scope():
        yield session

    async def open_run(_session, _run_id):
        return run

    async def bind(_session, _run):
        return record, {"scale": 2}

    async def store(_session, _run, _record, _data):
        return SimpleNamespace(id=new_asset_id, s3_key="upscaled.png")

    record_external = AsyncMock()

    monkeypatch.setattr(enhance.runs_service, "session_scope", scope)
    monkeypatch.setattr(enhance, "_open_run", open_run)
    monkeypatch.setattr(enhance, "_bind", bind)
    monkeypatch.setattr(enhance, "_store", store)
    monkeypatch.setattr(enhance, "_upscale", lambda source, scale: source)
    monkeypatch.setattr(
        enhance.flatten_service, "flatten_session", AsyncMock(return_value=b"png")
    )
    monkeypatch.setattr(enhance.runs_service, "report", AsyncMock())
    monkeypatch.setattr(enhance.runs_service, "lock_active", AsyncMock(return_value=True))
    monkeypatch.setattr(enhance.runs_service, "succeed", AsyncMock(return_value=True))
    monkeypatch.setattr(enhance.history_service, "record_external", record_external)
    monkeypatch.setattr(enhance.storage, "presign_get", lambda _: "/upscaled.png")
    monkeypatch.setattr(enhance.events, "publish", AsyncMock())

    await enhance.upscale_image(None, str(run.id))

    after = record_external.await_args.kwargs["after"]
    assert after.canvas.width == 8
    assert after.canvas.height == 8
    assert len(after.layers) == 1
    assert after.layers[0].source.asset_id == new_asset_id


async def test_enhance_failure_publishes_single_terminal_frame(monkeypatch):
    """_fail 已提交时外层的 finally 不能再补一帧 done：重复终态会让订阅端重复收尾。"""
    from app.tasks import enhance

    run = ToolRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(),
        tool="remove_background", status="running", params={},
    )
    record = SimpleNamespace(
        id=run.session_id,
        user_id=run.user_id,
        revision=0,
        doc=LayerDocument(canvas=Canvas(width=4, height=4)).model_dump(mode="json"),
    )
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def scope():
        yield session

    async def open_run(_session, _run_id):
        return run

    async def bind(_session, _run):
        return record, {}

    published = []

    async def publish(event):
        published.append(event)

    monkeypatch.setattr(enhance.runs_service, "session_scope", scope)
    monkeypatch.setattr(enhance, "_open_run", open_run)
    monkeypatch.setattr(enhance, "_bind", bind)
    monkeypatch.setattr(enhance.runs_service, "report", AsyncMock())
    monkeypatch.setattr(enhance.events, "publish", publish)

    await enhance.remove_background(None, str(run.id))

    assert run.status == "failed"
    assert [event.type for event in published] == ["error", "done"]


async def test_queued_step_is_not_traced_as_failed(monkeypatch):
    """排队只是提交成功，不是工具失败 —— 否则 tool_fail_rate 会把异步工具全算成错误。"""
    from app.services.history import StepResult

    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running",
        plan=plan.assemble([{"tool": "split_layers"}]),
    )
    session = SimpleNamespace(get=AsyncMock(return_value=turn), info={})

    @asynccontextmanager
    async def scope():
        yield session

    child_id = uuid4()
    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(
        graph.history_service,
        "apply_tool_calls",
        AsyncMock(return_value=(None, [
            StepResult(
                tool="split_layers", args={}, ok=True, message="已排队",
                changed=False, run_id=child_id,
            )
        ])),
    )
    monkeypatch.setattr(graph.cot_service, "emit", AsyncMock())
    recorded = []

    async def record(*args, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(graph.traces_service, "record_detached", record)

    result = await graph.execute_node({
        "run_id": str(turn.id), "user_id": str(uuid4()), "session_id": str(uuid4()),
        "plan": turn.plan,
    })

    assert result["plan"][0]["status"] == "queued"
    tool_span = next(item for item in recorded if item["kind"] == "tool")
    assert tool_span["status"] == "ok"
    assert tool_span["detail"]["async"] is True


async def test_execute_does_not_apply_tools_after_turn_cancel(monkeypatch):
    turn = AgentRun(id=uuid4(), status="cancelled", plan=[])
    session = SimpleNamespace(get=AsyncMock(return_value=turn))

    @asynccontextmanager
    async def scope():
        yield session

    apply = AsyncMock(return_value=(None, []))
    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(graph.history_service, "apply_tool_calls", apply)
    monkeypatch.setattr(graph.cot_service, "emit", AsyncMock())
    monkeypatch.setattr(graph.traces_service, "record_detached", AsyncMock())
    result = await graph.execute_node({
        "run_id": str(turn.id), "user_id": str(uuid4()), "session_id": str(uuid4()),
        "plan": plan.assemble([{"tool": "flip_layer"}]),
    })
    apply.assert_not_awaited()
    assert result["plan"][0]["status"] == "canceled"


async def test_execute_does_not_replay_step_committed_before_checkpoint(monkeypatch):
    """崩溃重放：副作用已随父计划状态提交，checkpoint 仍是 pending 也不能再跑一遍。"""
    checkpoint_plan = plan.assemble([{"tool": "flip_layer"}])
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running",
        plan=[{**checkpoint_plan[0], "status": "succeeded", "message": "已水平翻转"}],
    )
    session = SimpleNamespace(get=AsyncMock(return_value=turn), info={}, commit=AsyncMock())

    @asynccontextmanager
    async def scope():
        yield session

    apply = AsyncMock()
    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(graph.history_service, "apply_tool_calls", apply)
    monkeypatch.setattr(graph.cot_service, "emit", AsyncMock())
    monkeypatch.setattr(graph.traces_service, "record_detached", AsyncMock())

    result = await graph.execute_node({
        "run_id": str(turn.id), "user_id": str(turn.user_id),
        "session_id": str(turn.session_id), "plan": checkpoint_plan,
    })

    apply.assert_not_awaited()
    assert result["plan"][0]["status"] == "succeeded"


async def test_sync_tool_result_commits_with_parent_plan(monkeypatch):
    """同步工具结果必须和文档/历史同一事务写进父计划，重放时才有据可依。"""
    from app.services import history, sessions, tool_exec
    from app.tools.base import ToolResult

    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running",
        plan=plan.assemble([{"tool": "flip_layer"}]),
    )
    doc = LayerDocument(canvas=Canvas(width=4, height=4))
    record = SimpleNamespace(id=turn.session_id, revision=1, doc=doc.model_dump(mode="json"))
    committed_plan = None

    class Session:
        info = {"agent_step": (turn.id, "s1")}

        async def get(self, model, key, **kwargs):
            return turn

        async def commit(self):
            nonlocal committed_plan
            committed_plan = [dict(step) for step in turn.plan]

        async def refresh(self, _):
            pass

    spec = SimpleNamespace(
        parse=lambda raw, ctx: None,
        handler=AsyncMock(
            return_value=ToolResult(
                doc=LayerDocument(canvas=Canvas(width=5, height=4)),
                message="已水平翻转",
            )
        ),
    )
    monkeypatch.setattr(tool_exec, "get_tool", lambda _: spec)
    monkeypatch.setattr(sessions, "lock_edit_session", AsyncMock(return_value=record))
    monkeypatch.setattr(history, "_record", AsyncMock())
    await history.apply_tool_calls(
        Session(), user_id=turn.user_id, session_id=turn.session_id,
        calls=[history.ToolCall(name="flip_layer")],
    )

    assert committed_plan[0]["status"] == "succeeded"
    assert committed_plan[0]["message"] == "已水平翻转"


async def test_queue_submission_links_parent_before_commit_and_enqueue(monkeypatch):
    from app.services import history, queue, sessions, tool_exec
    from app.tools.base import QueuedOutcome

    turn = AgentRun(id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running",
                    plan=plan.assemble([{"tool": "split_layers"}]))
    child = tool_run("queued")
    child.user_id, child.session_id = turn.user_id, turn.session_id
    record = SimpleNamespace(id=turn.session_id, revision=1, doc=LayerDocument(
        canvas=Canvas(width=4, height=4),
    ).model_dump(mode="json"))
    committed_plan = None

    class Session:
        info = {"agent_step": (turn.id, "s1")}

        async def get(self, model, key, **kwargs):
            return turn if model is AgentRun else child

        async def commit(self):
            nonlocal committed_plan
            committed_plan = [dict(s) for s in turn.plan]

        async def refresh(self, _):
            pass

    async def enqueue(*args):
        assert committed_plan[0]["run_id"] == str(child.id), "投递前父子关联必须已提交"
        assert committed_plan[0]["status"] == "queued"
        # 此处尚未返回 graph，也没有图增量写回；取消必须已经能发现子任务。
        steps = plan.cancel_remaining(committed_plan)
        assert steps[0]["run_id"] == str(child.id)
        child.status = "cancelled"
        assert not await runs.lock_active(Session(), child)

    spec = SimpleNamespace(parse=lambda raw, ctx: None, handler=AsyncMock(return_value=
        QueuedOutcome(run_id=child.id, message="已排队", task="split_layers")))
    monkeypatch.setattr(tool_exec, "get_tool", lambda _: spec)
    monkeypatch.setattr(sessions, "lock_edit_session", AsyncMock(return_value=record))
    monkeypatch.setattr(history, "_record", AsyncMock())
    monkeypatch.setattr(queue, "enqueue", enqueue)
    await history.apply_tool_calls(
        Session(), user_id=turn.user_id, session_id=turn.session_id,
        calls=[history.ToolCall(name="split_layers")],
    )


async def test_drive_does_not_execute_when_database_lock_is_busy(monkeypatch):
    from contextlib import nullcontext

    connection = SimpleNamespace(
        begin=lambda: nullcontext(), scalar=AsyncMock(return_value=False),
    )
    engine = SimpleNamespace(connect=lambda: nullcontext(connection))
    monkeypatch.setattr(agent_runs, "get_engine", lambda: engine, raising=False)
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive_once", drive)
    await agent_runs._drive(uuid4())
    drive.assert_not_awaited()
    assert connection.scalar.await_count == 1


async def test_drive_keeps_database_lock_until_graph_exit(monkeypatch):
    from contextlib import nullcontext

    held = False

    @asynccontextmanager
    async def transaction():
        nonlocal held
        held = True
        try:
            yield
        finally:
            held = False

    connection = SimpleNamespace(begin=transaction, scalar=AsyncMock(return_value=True))
    engine = SimpleNamespace(connect=lambda: nullcontext(connection))
    monkeypatch.setattr(agent_runs, "get_engine", lambda: engine, raising=False)

    async def drive(*args, **kwargs):
        assert held, "读取checkpoint和整个图执行必须处于跨进程锁内"
        raise RuntimeError("模拟执行异常")

    monkeypatch.setattr(agent_runs, "_drive_once", drive)
    with pytest.raises(RuntimeError, match="模拟执行异常"):
        await agent_runs._drive(uuid4())
    assert held is False


async def test_drive_serializes_duplicate_callbacks(monkeypatch):
    import asyncio
    from contextlib import nullcontext

    # 这个用例只验锁串行；不 stub engine 会把真实连接池绑到本用例的 loop 上，
    # 污染后续用 asyncio.run 的集成用例（跨 loop 复用 asyncpg 连接）
    @asynccontextmanager
    async def transaction():
        yield

    connection = SimpleNamespace(begin=transaction, scalar=AsyncMock(return_value=True))
    engine = SimpleNamespace(connect=lambda: nullcontext(connection))
    monkeypatch.setattr(agent_runs, "get_engine", lambda: engine, raising=False)

    run_id = uuid4()
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0
    active = 0
    peak = 0

    async def drive_once(*args, **kwargs):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        entered.set()
        await release.wait()
        active -= 1

    monkeypatch.setattr(agent_runs, "_drive_once", drive_once)
    first = asyncio.create_task(agent_runs._drive(run_id))
    await entered.wait()
    assert agent_runs._drive_lock(run_id).locked()
    second = asyncio.create_task(agent_runs._drive(run_id))
    release.set()
    await asyncio.gather(first, second)
    assert calls == 2
    assert peak == 1


async def test_recover_waiting_resumes_completed_tool(monkeypatch):
    tool = tool_run("succeeded")
    turn = AgentRun(id=uuid4(), user_id=tool.user_id, status="running", plan=[
        {"id": "s1", "status": "queued", "run_id": str(tool.id)},
    ])
    session = SimpleNamespace(refresh=AsyncMock())
    monkeypatch.setattr(runs, "get_run", AsyncMock(return_value=tool))
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)
    await agent_runs._recover_waiting(session, turn)
    drive.assert_awaited_once_with(
        turn.id, resume={"action": "tool_done", "run_id": str(tool.id)},
    )


async def test_recover_pending_scans_only_nonterminal_turns(monkeypatch):
    ids = [uuid4(), uuid4()]

    class Result:
        def all(self):
            return ids

    session = SimpleNamespace(scalars=AsyncMock(return_value=Result()))

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(runs, "session_scope", scope)
    recover_one = AsyncMock()
    monkeypatch.setattr(agent_runs, "_recover_one", recover_one)

    await agent_runs.recover_pending()

    assert [call.args[0] for call in recover_one.await_args_list] == ids


async def test_recover_pending_restarts_planning_turn(monkeypatch):
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="planning", plan=[],
    )
    session = SimpleNamespace(get=AsyncMock(return_value=turn))

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(runs, "session_scope", scope)
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)

    await agent_runs._recover_one(turn.id)

    drive.assert_awaited_once_with(turn.id, resume=None, continue_existing=True)


async def test_recover_pending_redelivers_inflight_tool(monkeypatch):
    """worker 崩溃时 job key 可能已丢；运行中的任务也补投一次，由 ARQ 去重兜底。"""
    tool = tool_run("running")
    turn = AgentRun(id=uuid4(), user_id=tool.user_id, status="running", plan=[
        {"id": "s1", "status": "queued", "run_id": str(tool.id)},
    ])
    session = SimpleNamespace(get=AsyncMock(return_value=turn))

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(runs, "get_run", AsyncMock(return_value=tool))
    drive = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)
    monkeypatch.setattr(agent_runs.queue_service, "enqueue", enqueue)

    await agent_runs._recover_one(turn.id)

    drive.assert_not_awaited()
    enqueue.assert_awaited_once_with("inpaint_region", tool.id)


async def test_recover_pending_redelivers_queued_tool(monkeypatch):
    """崩溃可能卡在「run 已提交、ARQ 还没投递」之间：启动恢复必须补投。"""
    tool = tool_run("queued")
    turn = AgentRun(id=uuid4(), user_id=tool.user_id, status="running", plan=[
        {"id": "s1", "tool": "erase_region", "status": "queued", "run_id": str(tool.id)},
    ])
    session = SimpleNamespace(get=AsyncMock(return_value=turn))

    @asynccontextmanager
    async def scope():
        yield session

    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(runs, "get_run", AsyncMock(return_value=tool))
    drive = AsyncMock()
    enqueue = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)
    monkeypatch.setattr(agent_runs.queue_service, "enqueue", enqueue)

    await agent_runs._recover_one(turn.id)

    drive.assert_not_awaited()
    enqueue.assert_awaited_once_with("inpaint_region", tool.id)


async def test_recover_waiting_drives_running_turn_without_children(monkeypatch):
    """confirm/retry 的驱动请求可能丢在 advisory lock 竞争里：轮询时必须重驱。"""
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), status="running",
        plan=plan.assemble([{"tool": "flip_layer"}]),
    )
    session = SimpleNamespace(refresh=AsyncMock())
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)

    await agent_runs._recover_waiting(session, turn)

    drive.assert_awaited_once_with(turn.id, continue_existing=True)


@pytest.mark.parametrize("age", [0, agent_runs.STALE_TASK_SECONDS + 1])
async def test_recover_waiting_fails_only_lost_tools(monkeypatch, age):
    tool = tool_run("running")
    tool.started_at = datetime.now(UTC) - timedelta(seconds=age)
    turn = AgentRun(id=uuid4(), user_id=tool.user_id, status="running", plan=[
        {"id": "s1", "status": "queued", "run_id": str(tool.id)},
    ])
    session = SimpleNamespace(refresh=AsyncMock(), commit=AsyncMock())
    fail = AsyncMock(return_value=True)
    publish = AsyncMock()
    drive = AsyncMock()
    monkeypatch.setattr(runs, "get_run", AsyncMock(return_value=tool))
    monkeypatch.setattr(runs, "fail", fail)
    monkeypatch.setattr(runs, "publish_terminal", publish)
    monkeypatch.setattr(agent_runs, "_drive", drive)

    await agent_runs._recover_waiting(session, turn)

    if age == 0:
        fail.assert_not_awaited()
        drive.assert_not_awaited()
        return
    fail.assert_awaited_once()
    assert fail.await_args.kwargs["code"] == "task_lost"
    session.commit.assert_awaited_once()
    publish.assert_awaited_once_with(tool)
    drive.assert_awaited_once_with(
        turn.id, resume={"action": "tool_done", "run_id": str(tool.id)},
    )


def _fake_drive_env(monkeypatch, turn, *, next_nodes=(), values=None, updates=()):
    """让 _drive_once 在无数据库/无真实图的情况下跑一次，记录输入与写回。"""
    calls = {"inputs": [], "persisted": {}}

    class Graph:
        state = SimpleNamespace(
            values=values or {}, next=tuple(next_nodes), tasks=(), interrupts=(),
        )

        async def aget_state(self, _config):
            return self.state

        def astream(self, input_, config, stream_mode):
            calls["inputs"].append(input_)

            async def events():
                for item in updates:
                    yield item

            return events()

    graph = Graph()
    builder = SimpleNamespace(compile=lambda checkpointer=None: graph)
    checkpointer = SimpleNamespace(aget_tuple=AsyncMock(return_value=SimpleNamespace()))

    class Session:
        info = {}

        async def get(self, model, key, **kwargs):
            return turn

    @asynccontextmanager
    async def scope():
        yield Session()

    async def persist(_session, target, **changes):
        calls["persisted"].update(changes)
        for key, value in changes.items():
            setattr(target, key, value)
        return True

    monkeypatch.setattr(runs, "session_scope", scope)
    monkeypatch.setattr(agent_runs, "get_checkpointer", AsyncMock(return_value=checkpointer))
    monkeypatch.setattr(agent_runs, "build_graph", lambda: builder)
    monkeypatch.setattr(agent_runs, "_persist_active", persist)
    monkeypatch.setattr(agent_runs.traces_service, "record_detached", AsyncMock())
    monkeypatch.setattr(agent_runs.events, "publish", AsyncMock())
    return calls


async def test_recovery_restarts_finished_graph_with_pending_plan(monkeypatch):
    """retry_step 已提交 pending 计划却死在驱动前：checkpoint 停在 END 也必须重新开局。"""
    steps = plan.assemble([{"tool": "flip_layer"}])
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running", plan=steps,
    )
    succeeded = [{**steps[0], "status": "succeeded"}]
    calls = _fake_drive_env(
        monkeypatch, turn, next_nodes=(), values={"plan": steps, "errors": []},
        updates=({"execute": {"plan": succeeded}},),
    )

    await agent_runs._drive_once(turn.id, continue_existing=True)

    assert len(calls["inputs"]) == 1
    seed = calls["inputs"][0]
    assert seed["plan"][0]["status"] == plan.PENDING
    assert seed["approved"] is True
    assert seed["replans"] == 0
    assert calls["persisted"]["status"] == "succeeded"


@pytest.mark.parametrize(
    ("errors", "expected"),
    [([], ("succeeded", None)), (["模型输出无法解析"], ("failed", "模型输出无法解析"))],
)
async def test_recovery_settles_finished_graph_without_pending_work(
    monkeypatch, errors, expected,
):
    """图已收尾但最终写回丢失：直接结算；空计划 + 无错误是正常的无操作轮次。"""
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="planning", plan=[],
    )
    calls = _fake_drive_env(
        monkeypatch, turn, next_nodes=(), values={"plan": [], "errors": errors},
    )

    await agent_runs._drive_once(turn.id, continue_existing=True)

    assert calls["inputs"] == [], "不能对已经 END 的图 astream(None)"
    assert (
        calls["persisted"].get("status"), calls["persisted"].get("error"),
    ) == expected


async def test_recovery_prefers_checkpoint_plan_over_stale_db(monkeypatch):
    """checkpoint 先于 DB 落盘：崩溃恢复时以它为准，不能把已成功的轮次写成失败。"""
    finished = plan.assemble([{"tool": "flip_layer"}])
    stale = [{**finished[0], "status": "failed", "message": "旧失败"}]
    fresh = [{**finished[0], "status": "succeeded", "message": "已水平翻转"}]
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running", plan=stale,
    )
    calls = _fake_drive_env(
        monkeypatch, turn, next_nodes=(), values={"plan": fresh, "errors": []},
    )

    await agent_runs._drive_once(turn.id, continue_existing=True)

    assert calls["inputs"] == []
    assert calls["persisted"]["status"] == "succeeded"


async def test_recovery_keeps_checkpoint_plan_when_reinterrupting(monkeypatch):
    """plan 已进 checkpoint、DB 还没写回：重新挂起确认时不能把计划覆盖成空。"""
    steps = plan.assemble([{"tool": "flip_layer"}, {"tool": "flip_layer"}])
    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="planning", plan=[],
    )
    calls = _fake_drive_env(
        monkeypatch, turn, next_nodes=("confirm_gate",), values={"plan": steps},
        updates=(
            {"__interrupt__": (SimpleNamespace(value={"kind": "confirm"}),)},
        ),
    )

    await agent_runs._drive_once(turn.id, continue_existing=True)

    assert calls["persisted"]["status"] == "awaiting_confirm"
    assert calls["persisted"]["plan"] == steps


def test_every_queued_tool_maps_to_a_worker_task():
    """补偿投递只能按 ARQ 注册的函数名投；映射缺失会让任务永久停在 queued。"""
    from app.tools.registry import all_tools
    from app.worker import WorkerSettings

    tasks = {function.__name__ for function in WorkerSettings.functions}
    queued = {
        spec.name: spec.queue_task or spec.name for spec in all_tools() if spec.queued
    }
    assert queued, "工具注册表未加载，用例会空转通过"
    assert queued["erase_region"] == "inpaint_region"
    assert not {name: task for name, task in queued.items() if task not in tasks}


async def test_sync_agent_step_ignores_terminal_turn():
    from app.services import history
    from app.services.history import StepResult

    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="cancelled",
        plan=plan.assemble([{"tool": "flip_layer"}]),
    )

    class Session:
        info = {"agent_step": (turn.id, "s1")}

        async def get(self, model, key, **kwargs):
            return turn

    await history._sync_agent_step(
        Session(), StepResult(tool="flip_layer", args={}, ok=True, message="已翻转"),
    )

    assert turn.plan[0]["status"] == plan.PENDING


async def test_sync_agent_step_warns_when_step_is_missing(caplog):
    from app.services import history
    from app.services.history import StepResult

    turn = AgentRun(
        id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running",
        plan=plan.assemble([{"tool": "flip_layer"}]),
    )

    class Session:
        info = {"agent_step": (turn.id, "s9")}

        async def get(self, model, key, **kwargs):
            return turn

    with caplog.at_level(logging.WARNING, logger="graph-canvas-ai.history"):
        await history._sync_agent_step(
            Session(), StepResult(tool="flip_layer", args={}, ok=True, message="已翻转"),
        )

    assert turn.plan[0]["status"] == plan.PENDING
    assert "s9" in caplog.text


async def test_cot_emit_survives_redis_outage(monkeypatch):
    """CoT 是旁路：Redis 挂了不能把已经成功的工具执行变成失败轮次。"""
    from app.services import cot

    class BrokenRedis:
        async def incr(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(cot, "get_redis", lambda: BrokenRedis())
    assert await cot.emit(uuid4(), "thought", "正在思考") == 0


async def test_cot_emit_skips_blank_delta(monkeypatch):
    from app.services import cot

    class ExplodingRedis:
        def __getattr__(self, name):
            raise AssertionError("空增量不应访问 Redis")

    monkeypatch.setattr(cot, "get_redis", lambda: ExplodingRedis())
    assert await cot.emit(uuid4(), "thought", "") == 0


async def test_checkpointer_cancellation_closes_connection(monkeypatch):
    import asyncio

    from langgraph.checkpoint.postgres import aio as pg_aio

    from app.agent import checkpointer

    closed = False

    class Connection:
        async def close(self):
            nonlocal closed
            closed = True

    async def connect(*args, **kwargs):
        return Connection()

    class Saver:
        def __init__(self, conn):
            pass

        async def setup(self):
            raise asyncio.CancelledError

    monkeypatch.setattr(checkpointer, "_saver", None)
    monkeypatch.setattr(checkpointer, "_conn", None)
    monkeypatch.setattr(checkpointer.AsyncConnection, "connect", connect)
    monkeypatch.setattr(pg_aio, "AsyncPostgresSaver", Saver)

    with pytest.raises(asyncio.CancelledError):
        await checkpointer.get_checkpointer()
    assert closed


async def test_checkpointer_init_timeout_falls_back_in_dev(monkeypatch):
    import asyncio

    from langgraph.checkpoint.memory import MemorySaver

    from app.agent import checkpointer

    async def slow_connect(*args, **kwargs):
        await asyncio.sleep(60)

    monkeypatch.setattr(checkpointer, "_saver", None)
    monkeypatch.setattr(checkpointer, "_conn", None)
    monkeypatch.setattr(checkpointer, "_INIT_TIMEOUT", 0.01)
    monkeypatch.setattr(checkpointer.AsyncConnection, "connect", slow_connect)
    monkeypatch.setattr(
        checkpointer,
        "get_settings",
        lambda: SimpleNamespace(is_production=False, database_url="postgresql+asyncpg://x/y"),
    )
    try:
        assert isinstance(await checkpointer.get_checkpointer(), MemorySaver)
    finally:
        checkpointer._saver = None
        checkpointer._conn = None


def test_final_status_treats_empty_plan_without_errors_as_noop_success():
    """模型判断无需工具（闲聊）是正常结果；只有带错误的空计划才是规划失败。"""
    assert agent_runs._final_status([], None) == ("succeeded", None)
    assert agent_runs._final_status([], []) == ("succeeded", None)
    assert agent_runs._final_status([], ["模型输出无法解析"]) == (
        "failed", "模型输出无法解析",
    )


async def test_event_publish_survives_redis_outage(monkeypatch):
    """事件只是实时补强：Redis 挂了不能让已提交的状态变成 500，也不能判任务失败。"""
    from app.schemas.events import DoneEvent
    from app.services import events

    class BrokenRedis:
        async def publish(self, *args, **kwargs):
            raise ConnectionError("redis down")

    monkeypatch.setattr(events, "get_redis", lambda: BrokenRedis())
    await events.publish(DoneEvent(run_id=uuid4(), status="succeeded"))


async def test_checkpointer_requires_postgres_in_production(monkeypatch):
    from types import SimpleNamespace as NS

    from app.agent import checkpointer

    async def broken_connect(*args, **kwargs):
        raise OSError("postgres unavailable")

    monkeypatch.setattr(checkpointer, "_saver", None)
    monkeypatch.setattr(checkpointer, "_conn", None)
    monkeypatch.setattr(checkpointer.AsyncConnection, "connect", broken_connect)
    monkeypatch.setattr(
        checkpointer,
        "get_settings",
        lambda: NS(is_production=True, database_url="postgresql+asyncpg://x/y"),
    )

    with pytest.raises(RuntimeError, match="生产环境"):
        await checkpointer.get_checkpointer()


@pytest.mark.parametrize("model", [ToolRun, AgentRun])
async def test_stale_worker_cannot_overwrite_committed_cancel(monkeypatch, model):
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import Session

    @compiles(JSONB, "sqlite")
    def jsonb_as_json(_type, _compiler, **_kwargs):
        return "JSON"

    engine = create_engine("sqlite://")
    model.__table__.create(engine)
    values = dict(id=uuid4(), user_id=uuid4(), session_id=uuid4(), status="running")
    if model is ToolRun:
        values.update(tool="erase_region", params={})
    else:
        values.update(instruction="测试", plan=[])
    with Session(engine) as seed:
        seed.add(model(**values))
        seed.commit()
    with Session(engine, expire_on_commit=False) as worker, Session(engine) as api:
        stale = worker.get(model, values["id"])
        cancelled = api.get(model, values["id"])
        cancelled.status = "cancelled"
        api.commit()
        assert stale.status == "running"

        class AsyncFacade:
            no_autoflush = worker.no_autoflush

            async def execute(self, stmt):
                return worker.execute(stmt)

            async def refresh(self, obj):
                worker.refresh(obj)

            async def commit(self):
                worker.commit()

        facade = AsyncFacade()
        if model is ToolRun:
            monkeypatch.setattr(runs, "async_object_session", lambda _: facade)
            await runs.succeed(stale, {"asset_ids": ["late"]})
            worker.commit()
        else:
            changed = await agent_runs._persist_active(facade, stale, status="succeeded", plan=[])
            assert changed is False
        assert stale.status == "cancelled"
        assert api.get(model, values["id"]).status == "cancelled"
    engine.dispose()


async def test_continue_ignores_terminal_turn(monkeypatch):
    turn = AgentRun(id=uuid4(), user_id=uuid4(), status="cancelled", plan=[])
    monkeypatch.setattr(agent_runs, "_get", AsyncMock(return_value=turn))
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)
    await agent_runs.continue_after_tool_run(
        SimpleNamespace(), user_id=turn.user_id, run_id=turn.id, tool_run_id=uuid4(),
    )
    drive.assert_not_awaited()


async def test_continue_rejects_nonterminal_tool(monkeypatch):
    tool = tool_run()
    turn = AgentRun(id=uuid4(), user_id=tool.user_id, status="running", plan=[
        {"id": "s1", "status": "queued", "run_id": str(tool.id)},
    ])
    monkeypatch.setattr(agent_runs, "_get", AsyncMock(return_value=turn))
    monkeypatch.setattr(runs, "get_run", AsyncMock(return_value=tool))
    drive = AsyncMock()
    monkeypatch.setattr(agent_runs, "_drive", drive)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await agent_runs.continue_after_tool_run(
            SimpleNamespace(refresh=AsyncMock()), user_id=turn.user_id,
            run_id=turn.id, tool_run_id=tool.id,
        )
    assert exc.value.status_code == 409
    drive.assert_not_awaited()
