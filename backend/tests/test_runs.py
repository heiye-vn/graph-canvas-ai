"""ToolRun 生命周期与进度上报。

状态机只有三个不变量值得测：
    1. 新建即 queued，进度从 0 开始
    2. report 是**幂等的推进**，进度必须被夹在 0~100（前端进度条不能有 137%）
    3. 终态不可逆 —— succeeded 之后再 cancel 不能把状态改回去
"""

from __future__ import annotations

import uuid

import pytest
from conftest import run_async
from fastapi import HTTPException

from app.models import User
from app.models.run import CANCELLED, QUEUED, RUNNING, SUCCEEDED
from app.services import events
from app.services import runs as runs_service
from app.services.security import hash_password


async def _seed_run(params: dict | None = None):
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


def test_create_run_starts_queued():
    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run({"prompt": "一只橘猫"})
        async with runs_service.session_scope() as session:
            return await session.get(ToolRun, run_id)

    run = run_async(scenario())
    assert run.status == QUEUED
    assert run.progress == 0
    assert run.params == {"prompt": "一只橘猫"}
    assert run.started_at is None


def test_report_advances_status_and_clamps_progress():
    async def scenario():
        run_id, _ = await _seed_run()
        from app.models import ToolRun

        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.report(run, progress=5, stage="准备中", to_running=True)
            await runs_service.report(run, progress=150, stage="越界")
            await runs_service.report(run, progress=-20, stage="负越界")
            return run.status, run.progress, run.started_at

    status, progress, started_at = run_async(scenario())
    assert status == RUNNING
    assert progress == 0  # -20 被夹到 0；150 那次先被夹成 100
    assert started_at is not None


def test_succeed_then_cancel_is_noop():
    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run()
        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.succeed(run, {"asset_ids": ["x"], "count": 1})
            await session.commit()
            status_after_success = run.status

        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.cancel(run)
            await session.commit()
            return status_after_success, run.status, run.result

    first, second, result = run_async(scenario())
    assert first == SUCCEEDED
    assert second == SUCCEEDED  # 终态不可逆
    assert result == {"asset_ids": ["x"], "count": 1}


def test_cancel_marks_cancelled_before_worker_picks_it_up():
    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run()
        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.cancel(run)
            await session.commit()
            return run.status

    assert run_async(scenario()) == CANCELLED


def test_cancel_closes_the_stream_with_done():
    """取消不推 done 的话，前端那条流会一直挂到超时——用户看到的是「卡住了」。"""

    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run()
        async with events.subscription(run_id) as stream:
            async with runs_service.session_scope() as session:
                run = await session.get(ToolRun, run_id)
                await runs_service.cancel(run)
                await session.commit()

            async for ev in stream:
                return ev

    event = run_async(scenario())
    assert event.type == "done"
    assert event.status == CANCELLED


def test_fail_publishes_error_event():
    """失败必须让正在等着的客户端立刻知道：只写库不推事件，进度条会一直转。"""

    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run()
        collected = []
        async with events.subscription(run_id) as stream:
            async with runs_service.session_scope() as session:
                run = await session.get(ToolRun, run_id)
                await runs_service.fail(
                    run, code="task_failed", message="模型超时", recoverable=True
                )
                await session.commit()

            async for ev in stream:
                collected.append(ev)
                break
        return collected, run_id

    collected, _ = run_async(scenario())
    assert len(collected) == 1
    assert collected[0].type == "error"
    assert collected[0].code == "task_failed"
    assert collected[0].message == "模型超时"
    assert collected[0].recoverable is True


def test_get_run_is_scoped_to_owner():
    """别人的任务对我不存在 —— 404，不泄露「它存在只是你没权限」。"""

    async def scenario():

        run_id, _ = await _seed_run()
        async with runs_service.session_scope() as session:
            other = User(
                email=f"test_{uuid.uuid4().hex[:12]}@example.com",
                password_hash=hash_password("Strong-Pass-123"),
            )
            session.add(other)
            await session.flush()
            with pytest.raises(HTTPException) as exc:
                await runs_service.get_run(session, other.id, run_id)
            return exc.value.status_code

    assert run_async(scenario()) == 404


def test_snapshot_carries_error_message_for_frontend():
    """刷新页面后前端靠快照恢复现场，error 要的是可读文案而不是整个 dict。"""

    async def scenario():
        from app.models import ToolRun

        run_id, _ = await _seed_run()
        async with runs_service.session_scope() as session:
            run = await session.get(ToolRun, run_id)
            await runs_service.fail(run, code="boom", message="炸了")
            await session.commit()
            return runs_service.snapshot_of(run)

    snap = run_async(scenario())
    assert snap.status == "failed"
    assert snap.error == "炸了"
