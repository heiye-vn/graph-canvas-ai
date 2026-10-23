"""离线数据完整性回归：内存 SQLite，不访问 Postgres / Redis / S3。"""

from __future__ import annotations

import io
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models import Asset, Base, EditHistory, EditSession, SessionAsset, User
from app.schemas.layer_doc import Canvas, LayerDocument
from app.services import assets, history, sessions

pytestmark = pytest.mark.unit


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(element, compiler, **kw):
    return "JSON"


@pytest.fixture
def database():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        user = User(id=uuid.uuid4(), email="test_integrity@example.com", password_hash="unused")
        db.add(user)
        db.commit()
        yield db, engine, user.id
    engine.dispose()


def _async(db):
    @asynccontextmanager
    async def begin_nested():
        with db.begin_nested():
            yield

    return SimpleNamespace(
        execute=AsyncMock(side_effect=db.execute),
        scalar=AsyncMock(side_effect=db.scalar),
        get=AsyncMock(side_effect=db.get),
        flush=AsyncMock(side_effect=db.flush),
        commit=AsyncMock(side_effect=db.commit),
        refresh=AsyncMock(side_effect=db.refresh),
        delete=AsyncMock(side_effect=db.delete),
        add=db.add,
        begin_nested=begin_nested,
        no_autoflush=db.no_autoflush,
        rollback=AsyncMock(side_effect=db.rollback),
    )


def _record(db, user_id):
    record = EditSession(
        id=uuid.uuid4(), user_id=user_id, revision=2, history_seq=0,
        doc=LayerDocument(canvas=Canvas(width=32, height=24)).model_dump(mode="json"),
    )
    db.add(record)
    db.commit()
    return record


async def test_external_write_rejects_stale_identity_map_without_touching_history(database):
    db, engine, user_id = database
    record = _record(db, user_id)
    before = record.doc
    with Session(engine) as editor:
        latest = editor.get(EditSession, record.id)
        latest.revision = 3
        latest.doc = {**before, "canvas": {"width": 40, "height": 30}}
        editor.commit()
    assert record.revision == 2
    api = _async(db)
    with pytest.raises(history.RevisionConflict):
        await history.record_external(
            api, record, tool="split_layers", label="拆层",
            after=LayerDocument(canvas=Canvas(width=64, height=48)), expected_revision=2,
        )
    assert db.scalars(select(EditHistory)).all() == []
    db.expire(record)
    assert record.revision == 3
    assert record.doc["canvas"]["width"] == 40


async def test_external_write_updates_document_revision_and_history_together(database):
    db, _, user_id = database
    record = _record(db, user_id)
    before = record.doc
    after = LayerDocument(canvas=Canvas(width=64, height=48))
    api = _async(db)
    calls = Mock()
    calls.attach_mock(api.execute, "execute")
    calls.attach_mock(api.refresh, "refresh")
    await history.record_external(
        api, record, tool="upscale_image", label="超分", after=after, expected_revision=2,
    )
    entry = db.scalar(select(EditHistory))
    assert (record.revision, record.history_seq) == (3, 1)
    assert record.doc == after.model_dump(mode="json")
    assert entry.before == before
    assert entry.after == record.doc
    api.commit.assert_not_called()
    sql = str(api.execute.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    assert "UPDATE edit_sessions" in sql
    assert "edit_sessions.revision =" in sql
    assert [call[0] for call in calls.mock_calls[:3]] == ["execute", "refresh", "execute"]
    history_sql = str(api.execute.call_args_list[1].args[0].compile(
        dialect=postgresql.dialect(),
    ))
    assert "DELETE FROM edit_history" in history_sql


async def test_external_write_refreshes_history_pointer_before_recording(database):
    db, engine, user_id = database
    record = _record(db, user_id)
    with Session(engine) as editor:
        latest = editor.get(EditSession, record.id)
        latest.history_seq = 1
        editor.add(EditHistory(
            session_id=record.id, seq=1, tool="queued", label="排队记录", changed=False,
            before=record.doc, after=record.doc, params={},
        ))
        editor.commit()
    assert record.history_seq == 0
    await history.record_external(
        _async(db), record, tool="split_layers", label="拆层",
        after=LayerDocument(canvas=Canvas(width=64, height=48)), expected_revision=2,
    )
    assert record.history_seq == 2
    assert list(db.scalars(select(EditHistory.seq).order_by(EditHistory.seq))) == [1, 2]


async def test_external_write_rolls_back_revision_and_history_on_record_failure(
    database, monkeypatch,
):
    db, _, user_id = database
    record = _record(db, user_id)
    before = record.doc
    original_record = history._record

    async def broken_record(*args, **kwargs):
        await original_record(*args, **kwargs)
        raise RuntimeError("模拟历史写入失败")

    monkeypatch.setattr(history, "_record", broken_record)
    with pytest.raises(RuntimeError, match="模拟历史写入失败"):
        await history.record_external(
            _async(db), record, tool="split_layers", label="拆层",
            after=LayerDocument(canvas=Canvas(width=64, height=48)), expected_revision=2,
        )
    # worker 捕获异常后仍会 commit 任务失败状态，不能顺带提交半份文档 / 历史。
    db.commit()
    db.refresh(record)
    assert record.revision == 2
    assert record.doc == before
    assert record.history_seq == 0
    assert db.scalars(select(EditHistory)).all() == []


@pytest.mark.parametrize("reference", ["association", "document", "before", "after"])
async def test_referenced_asset_cannot_be_deleted(database, monkeypatch, reference):
    db, _, user_id = database
    record = _record(db, user_id)
    asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key="unused.png", mime="image/png")
    db.add(asset)
    doc = {**record.doc, "layers": [{
        "name": "隐藏层", "type": "image", "visible": False,
        "source": {"asset_id": str(asset.id)},
    }]}
    if reference == "association":
        db.add(SessionAsset(session_id=record.id, asset_id=asset.id))
    elif reference == "document":
        record.doc = doc
    else:
        db.add(EditHistory(
            session_id=record.id, seq=5, tool="test", label="可重做历史", changed=True,
            before=doc if reference == "before" else record.doc,
            after=doc if reference == "after" else record.doc, params={},
        ))
    db.commit()
    delete_object = Mock()
    monkeypatch.setattr(assets.storage, "delete_object", delete_object)
    api = _async(db)
    with pytest.raises(HTTPException) as error:
        await assets.delete_asset(api, user_id, asset.id)
    assert error.value.status_code == 409
    api.delete.assert_not_called()
    api.commit.assert_not_called()
    delete_object.assert_not_called()


async def test_unreferenced_asset_can_be_deleted(database, monkeypatch):
    db, _, user_id = database
    asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key="unused.png", mime="image/png")
    db.add(asset)
    db.commit()
    delete_object = Mock()
    monkeypatch.setattr(assets.storage, "delete_object", delete_object)
    await assets.delete_asset(_async(db), user_id, asset.id)
    assert db.get(Asset, asset.id) is None
    assert delete_object.call_count == 2


async def test_adding_asset_increments_revision(database, monkeypatch):
    db, _, user_id = database
    record = _record(db, user_id)
    asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key="unused.png", mime="image/png",
                  width=32, height=24)
    db.add(asset)
    db.commit()
    await sessions.add_assets(
        _async(db), user_id=user_id, session_id=record.id, asset_ids=[asset.id],
    )
    assert record.revision == 3
    await sessions.add_assets(
        _async(db), user_id=user_id, session_id=record.id, asset_ids=[asset.id],
    )
    assert record.revision == 3


@pytest.mark.parametrize("operation", [
    "apply", "noop", "queued", "undo", "redo", "add_assets", "replace_doc", "delete_session",
])
async def test_writers_lock_and_refresh_session_before_history_or_document(
    database, monkeypatch, operation,
):
    from app.services import queue
    from app.tools.base import QueuedOutcome, ToolResult

    db, engine, user_id = database
    record = _record(db, user_id)
    initial = record.doc
    latest_doc = LayerDocument(canvas=Canvas(width=80, height=60)).model_dump(mode="json")
    with Session(engine) as editor:
        latest = editor.get(EditSession, record.id)
        latest.doc = initial if operation == "redo" else latest_doc
        latest.revision = 5
        latest.history_seq = 0 if operation == "redo" else 1
        editor.add(EditHistory(
            session_id=record.id, seq=1, tool="prior", label="前一步", changed=True,
            before=initial, after=latest_doc, params={},
        ))
        # 当前指针之后的 redo 分支必须只在拿到会话锁后截断。
        editor.add(EditHistory(
            session_id=record.id, seq=2, tool="redo", label="重做分支", changed=True,
            before=latest_doc, after=latest_doc, params={},
        ))
        editor.commit()
    assert record.revision == 2
    api = _async(db)
    locked = False
    order = []

    async def get(model, key, **kwargs):
        nonlocal locked
        if model is EditSession and kwargs.get("with_for_update"):
            assert not db.autoflush, "拿会话锁之前不能自动 flush 待写历史"
            assert kwargs.get("populate_existing") is True
            locked = True
            order.append("session_lock")
        return db.get(model, key, **kwargs)

    async def execute(statement, *args, **kwargs):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "edit_history" in sql:
            order.append("history")
            assert locked, "访问历史之前必须锁定并刷新会话"
        return db.execute(statement, *args, **kwargs)

    api.get.side_effect = get
    api.execute.side_effect = execute

    async def invoke(name, params, ctx):
        assert locked, "工具必须基于锁定后的最新文档执行"
        assert ctx.doc.canvas.width == 80
        if operation == "queued":
            return QueuedOutcome(run_id=uuid.uuid4(), message="排队", task="unit-task")
        after = ctx.doc.model_copy(deep=True)
        if operation == "apply":
            after.canvas.height += 1
        return ToolResult(doc=after, message="修改完成")

    monkeypatch.setattr(history.tool_exec, "invoke", invoke)
    enqueue = AsyncMock()
    monkeypatch.setattr(queue, "enqueue", enqueue)
    if operation in {"apply", "noop", "queued"}:
        await history.apply_tool_calls(
            api, user_id=user_id, session_id=record.id, calls=[history.ToolCall("unit-tool")],
        )
        assert record.revision == (6 if operation == "apply" else 5)
        assert record.doc["canvas"]["width"] == 80
        assert record.doc["canvas"]["height"] == (61 if operation == "apply" else 60)
        assert record.history_seq == 2
        entry = db.scalar(select(EditHistory).where(EditHistory.seq == 2))
        assert entry.before == latest_doc
        assert entry.tool == "unit-tool"
        assert entry.changed == (operation == "apply")
        assert enqueue.await_count == (1 if operation == "queued" else 0)
    elif operation in {"undo", "redo"}:
        await getattr(history, operation)(api, user_id=user_id, session_id=record.id)
        assert record.revision == 6
        assert record.history_seq == (0 if operation == "undo" else 1)
        assert record.doc == (initial if operation == "undo" else latest_doc)
    elif operation == "add_assets":
        asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key="added.png", mime="image/png")
        db.add(asset)
        db.commit()
        await sessions.add_assets(
            api, user_id=user_id, session_id=record.id, asset_ids=[asset.id],
        )
        assert record.revision == 6
        assert record.doc["canvas"]["width"] == 80
    elif operation == "replace_doc":
        await sessions.replace_doc(
            api, user_id=user_id, session_id=record.id,
            doc=LayerDocument(canvas=Canvas(width=100, height=90)),
        )
        assert record.revision == 6
    else:
        await sessions.delete_session(api, user_id=user_id, session_id=record.id)
        assert db.get(EditSession, record.id) is None
    assert locked
    assert order[0] == "session_lock"


async def test_two_cached_editors_preserve_changes_and_increment_revision(database, monkeypatch):
    from app.tools.base import ToolResult

    db, engine, user_id = database
    record = _record(db, user_id)

    async def invoke(name, params, ctx):
        after = ctx.doc.model_copy(deep=True)
        setattr(after.canvas, params["field"], params["value"])
        return ToolResult(doc=after, message="更新画布")

    monkeypatch.setattr(history.tool_exec, "invoke", invoke)
    with Session(engine, expire_on_commit=False) as second:
        cached = second.get(EditSession, record.id)
        assert cached.revision == 2
        await history.apply_tool_calls(
            _async(db), user_id=user_id, session_id=record.id,
            calls=[history.ToolCall("resize", {"field": "width", "value": 80})],
        )
        assert cached.revision == 2
        await history.apply_tool_calls(
            _async(second), user_id=user_id, session_id=record.id,
            calls=[history.ToolCall("resize", {"field": "height", "value": 60})],
        )
        assert cached.revision == 4
        assert cached.doc["canvas"]["width"] == 80
        assert cached.doc["canvas"]["height"] == 60
        entries = list(second.scalars(select(EditHistory).order_by(EditHistory.seq)))
        assert [entry.seq for entry in entries] == [1, 2]
        assert entries[1].before == entries[0].after
        assert entries[1].after == cached.doc


@pytest.mark.parametrize("missing", [False, True])
async def test_session_write_lock_rejects_foreign_or_missing_session(database, missing):
    db, _, user_id = database
    record = _record(db, user_id)
    api = _async(db)
    with pytest.raises(HTTPException) as error:
        await sessions.lock_edit_session(
            api, uuid.uuid4(), uuid.uuid4() if missing else record.id,
        )
    assert error.value.status_code == 404
    api.commit.assert_not_awaited()
    api.execute.assert_not_awaited()


@pytest.mark.parametrize("task_name", [
    "remove_background", "upscale_image", "replace_background", "edit_image",
    "expand_canvas", "split_layers",
])
@pytest.mark.parametrize("conflict", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_worker_checks_original_revision_and_preserves_later_edit(
    database, monkeypatch, task_name, conflict, cancelled,
):
    from app.models import ToolRun
    from app.tasks import enhance, split

    db, engine, user_id = database
    record = _record(db, user_id)
    input_asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key="input.png", mime="image/png")
    db.add(input_asset)
    doc = LayerDocument.model_validate(record.doc)
    from app.services import layer_doc as L

    doc = L.add_layer(doc, L.new_image_layer(input_asset.id, width=32, height=24))
    record.doc = doc.model_dump(mode="json")
    run = ToolRun(
        id=uuid.uuid4(), user_id=user_id, tool=task_name, session_id=record.id,
        status="queued", progress=0, params={"session_id": str(record.id)},
    )
    db.add(run)
    db.commit()
    api = _async(db)
    saved_doc = doc.model_dump(mode="json")

    @asynccontextmanager
    async def scope():
        yield api

    async def report(*args, **kwargs):
        pass

    async def succeed(run, result):
        run.status, run.result = "succeeded", result
        return True

    async def fail(run, *, code, message, recoverable):
        run.status = "failed"
        run.error = {"code": code, "message": message, "recoverable": recoverable}
        return True

    buffer = io.BytesIO()
    Image.new("RGBA", (32, 24), (20, 40, 60, 255)).save(buffer, format="PNG")
    png = buffer.getvalue()
    injected = False

    async def create_asset(session, **kwargs):
        nonlocal injected, saved_doc
        if (conflict or cancelled) and not injected:
            injected = True
            with Session(engine) as editor:
                if conflict:
                    latest = editor.get(EditSession, record.id)
                    saved_doc = {**latest.doc, "canvas": {"width": 40, "height": 30}}
                    latest.doc, latest.revision = saved_doc, 3
                if cancelled:
                    editor.get(ToolRun, run.id).status = "cancelled"
                editor.commit()
            if cancelled:
                assert run.status == "queued", "取消应来自另一个事务，而非直接改 worker 缓存"
        asset = Asset(id=uuid.uuid4(), user_id=user_id, s3_key=f"{uuid.uuid4()}.png",
                      mime="image/png")
        db.add(asset)
        db.flush()
        return asset

    lock_active = AsyncMock(wraps=enhance.runs_service.lock_active)
    record_external = AsyncMock(wraps=history.record_external)
    calls = Mock()
    calls.attach_mock(lock_active, "lock_active")
    calls.attach_mock(record_external, "record_external")
    monkeypatch.setattr(enhance.runs_service, "lock_active", lock_active)
    monkeypatch.setattr(history, "record_external", record_external)
    monkeypatch.setattr(enhance.runs_service, "session_scope", scope)
    monkeypatch.setattr(enhance.runs_service, "report", report)
    monkeypatch.setattr(enhance.runs_service, "succeed", succeed)
    monkeypatch.setattr(enhance.runs_service, "fail", fail)
    monkeypatch.setattr(enhance.events, "publish", AsyncMock())
    monkeypatch.setattr(enhance.asset_service, "create_from_bytes", create_asset)
    monkeypatch.setattr(enhance.flatten_service, "flatten_session", AsyncMock(return_value=png))
    monkeypatch.setattr(enhance.storage, "get_object", Mock(return_value=png))
    monkeypatch.setattr(enhance.storage, "presign_get", Mock(return_value="/test-image"))
    monkeypatch.setattr(enhance, "_matte", lambda raw: png)
    monkeypatch.setattr(split, "_remove_background", lambda raw: png)
    monkeypatch.setattr(split, "edit_image_clamped", AsyncMock(return_value=png))
    clear = AsyncMock()
    monkeypatch.setattr(split.selections, "clear", clear)
    monkeypatch.setattr(enhance, "get_image_provider", lambda: SimpleNamespace(
        edit_image=AsyncMock(return_value=[png]),
    ))
    task = getattr(split if task_name == "split_layers" else enhance, task_name)
    await task(None, str(run.id))
    db.expire(record)
    if cancelled:
        assert run.status == "cancelled"
        assert run.result is None
        assert run.error is None
        assert record.doc == saved_doc
        assert record.revision == (3 if conflict else 2)
        assert record.history_seq == 0
        assert db.scalars(select(EditHistory)).all() == []
        record_external.assert_not_awaited()
        clear.assert_not_called()
        # 取消方拥有终态：worker 未成功切换状态就不许再发终态事件（否则重复 done）
        enhance.events.publish.assert_not_awaited()
    elif conflict:
        assert run.status == "failed"
        assert run.error["code"] == "revision_conflict"
        assert record.doc == saved_doc
        assert record.revision == 3
        assert db.scalars(select(EditHistory)).all() == []
        clear.assert_not_called()
    else:
        assert run.status == "succeeded", run.error
        assert record.revision == 3
        assert len(db.scalars(select(EditHistory)).all()) == 1
        assert run.result["document"] == record.doc
    lock_active.assert_awaited_once_with(api, run)
    assert [call[0] for call in calls.mock_calls] == (
        ["lock_active"] if cancelled else ["lock_active", "record_external"]
    )
    api.get.assert_any_await(ToolRun, run.id, populate_existing=True, with_for_update=True)
