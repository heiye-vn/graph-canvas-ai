"""任务闭环离线回归：不连接数据库、Redis、对象存储或真实模型。"""

from contextlib import asynccontextmanager
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
