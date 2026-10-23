"""文生图任务端到端（worker 侧真实执行，不走 HTTP）。

覆盖三条路径：成功 / 已取消跳过 / Provider 抛错。
成功路径必须验到「事件流完整 + 产物进对象存储 + 素材落库」三件事，
只验其中一件都可能漏掉「图生成了但前端收不到」这类问题。
"""

from __future__ import annotations

import asyncio
import uuid

from conftest import run_async

from app.models import ToolRun, User
from app.services import events, storage
from app.services import runs as runs_service
from app.services.security import hash_password
from app.tasks import image as image_task


async def _seed_run(params: dict):
    async with runs_service.session_scope() as session:
        user = User(
            email=f"test_{uuid.uuid4().hex[:12]}@example.com",
            password_hash=hash_password("Strong-Pass-123"),
        )
        session.add(user)
        await session.flush()
        run = await runs_service.create_run(
            session, user_id=user.id, tool="text_to_image", params=params
        )
        return run.id, user.id


async def _run_and_collect(run_id: uuid.UUID) -> list:
    """先订阅再执行：Pub/Sub 不给迟到者补发，顺序反了就永远收不到事件。"""
    collected: list = []

    async with events.subscription(run_id) as stream:

        async def collect():
            async for ev in stream:
                collected.append(ev)
                if ev.type == "done":
                    break

        collector = asyncio.create_task(collect())
        await image_task.text_to_image(None, str(run_id))  # type: ignore[arg-type]
        await asyncio.wait_for(collector, timeout=30)
    return collected


def test_text_to_image_happy_path():
    async def scenario():
        run_id, user_id = await _seed_run({"prompt": "一只橘猫", "size": "256x128", "n": 2})
        events_ = await _run_and_collect(run_id)

        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            return run_id, user_id, events_, run.status, run.result, run.progress

    run_id, user_id, collected, status, result, progress = run_async(scenario())

    assert status == "succeeded", result
    assert progress == 100
    assert result["count"] == 2

    kinds = [e.type for e in collected]
    assert kinds[0] == "progress"
    assert kinds.count("result") == 2
    assert kinds[-1] == "done"
    assert collected[-1].status == "succeeded"
    assert len(result["asset_ids"]) == 2


def test_generated_asset_is_persisted_and_readable():
    async def scenario():
        from sqlalchemy import select

        from app.models import Asset

        run_id, user_id = await _seed_run({"prompt": "red bottle", "size": "128x128", "n": 1})
        await _run_and_collect(run_id)

        async with runs_service.session_scope() as session:
            rows = (
                await session.execute(select(Asset).where(Asset.user_id == user_id))
            ).scalars().all()
            return run_id, [
                (a.mime, a.width, a.height, a.s3_key, a.size) for a in rows
            ]

    run_id, rows = run_async(scenario())
    assert len(rows) == 1
    mime, width, height, s3_key, size = rows[0]
    assert mime == "image/png"
    assert (width, height) == (128, 128)
    assert s3_key.startswith("assets/")
    assert size > 0
    assert storage.object_exists(s3_key), "产物没进桶，前端拿到的是死链"


def test_cancelled_run_is_skipped():
    async def scenario():
        run_id, _ = await _seed_run({"prompt": "x", "n": 1})
        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.cancel(run)
            await session.commit()

        await image_task.text_to_image(None, str(run_id))  # type: ignore[arg-type]

        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            return run.status, run.result

    status, result = run_async(scenario())
    assert status == "cancelled"
    assert result is None  # 取消之后不能再被 worker 覆盖成成功


def test_run_assets_are_returned_in_generation_order():
    """候选页刷新后靠这个恢复现场：顺序错了，用户会以为图被换掉了。"""

    async def scenario():
        from app.services import assets as asset_service

        run_id, user_id = await _seed_run({"prompt": "red bottle", "size": "96x96", "n": 3})
        await _run_and_collect(run_id)

        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            ids = [uuid.UUID(value) for value in run.result["asset_ids"]]
            in_order = await asset_service.list_assets_by_ids(session, user_id, ids)
            reversed_order = await asset_service.list_assets_by_ids(
                session, user_id, list(reversed(ids))
            )
            foreign = await asset_service.list_assets_by_ids(session, uuid.uuid4(), ids)
            empty = await asset_service.list_assets_by_ids(session, user_id, [])
            return (
                [str(a.id) for a in in_order],
                [str(a.id) for a in reversed_order],
                foreign,
                empty,
            )

    in_order, reversed_order, foreign, empty = run_async(scenario())
    assert in_order == list(reversed(reversed_order))
    assert set(in_order) == set(reversed_order)
    assert foreign == []  # 别人的 id 一律忽略，不是报错
    assert empty == []


def test_provider_failure_is_recorded_and_broadcast(monkeypatch):
    class BoomProvider:
        name = "boom"

        async def text_to_image(self, prompt: str, *, size="1024x1024", n=1):
            raise RuntimeError("上游 502")

    monkeypatch.setattr(image_task, "get_image_provider", lambda: BoomProvider())

    real_publish = events.publish
    committed_at_error: list[str] = []

    async def checked_publish(event):
        # 前端收到 error 会立刻 continue 计划；此刻任务必须已经落成终态，
        # 否则 continue 会读到 running 并返回 409，计划就卡住了。
        if event.type == "error":
            async with runs_service.session_scope() as fresh_session:
                fresh = await fresh_session.get(ToolRun, event.run_id)
                committed_at_error.append(fresh.status)
        await real_publish(event)

    monkeypatch.setattr(events, "publish", checked_publish)

    async def scenario():
        run_id, _ = await _seed_run({"prompt": "x", "n": 1})
        collected = await _run_and_collect(run_id)
        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            return collected, run.status, run.error

    collected, status, error = run_async(scenario())
    assert status == "failed"
    assert error["code"] == "task_failed"
    assert "上游 502" in error["message"]
    assert committed_at_error == ["failed"]
    kinds = [e.type for e in collected]
    assert kinds.count("error") == 1
    assert kinds.count("done") == 1
    assert kinds[-1] == "done"
    assert collected[-1].status == "failed"
