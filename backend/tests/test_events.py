"""事件协议与 Pub/Sub 通道的测试。"""

from __future__ import annotations

import asyncio
import uuid

from conftest import run_async  # noqa: I001  pytest 会把 tests/ 加入 sys.path

from app.schemas.events import (
    CotEvent,
    DoneEvent,
    PingEvent,
    ProgressEvent,
    SnapshotEvent,
    StreamEvent,
    frame,
)
from app.services import events


def test_frame_format():
    """SSE 帧必须是 `data:{json}\n\n`，少一个换行客户端就解析不了。"""
    raw = frame(PingEvent(run_id=uuid.uuid4()))
    assert raw.startswith("data:{")
    assert raw.endswith("\n\n")


def test_cot_event_is_defined_upfront():
    """协议在 M2 定死：思维链事件本阶段不发，但结构必须存在。"""
    ev = CotEvent(run_id=uuid.uuid4(), seq=1, kind="thought", delta="先分析构图…")
    assert ev.type == "cot"
    assert ev.delta == "先分析构图…"


def test_discriminated_union_parses_by_type():
    from pydantic import TypeAdapter

    adapter = TypeAdapter(StreamEvent)
    run_id = uuid.uuid4()
    parsed = adapter.validate_python(
        {"type": "progress", "run_id": str(run_id), "progress": 30, "stage": "生成中"}
    )
    assert isinstance(parsed, ProgressEvent)
    assert parsed.progress == 30


async def _publish_and_collect():
    run_id = uuid.uuid4()
    collected = []

    async with events.subscription(run_id) as stream:
        # 订阅已建立后再发，确保不会漏
        await asyncio.sleep(0)
        await events.publish(ProgressEvent(run_id=run_id, progress=10, stage="排队"))
        await events.publish(ProgressEvent(run_id=run_id, progress=50, stage="生成"))
        await events.publish(DoneEvent(run_id=run_id, status="succeeded"))

        async for ev in stream:
            collected.append(ev)
            if ev.type == "done":
                break

    return collected


def test_pubsub_roundtrip():
    collected = run_async(_publish_and_collect())
    kinds = [e.type for e in collected]
    assert kinds == ["progress", "progress", "done"]
    assert collected[0].progress == 10
    assert collected[1].stage == "生成"


async def _bad_frame_is_skipped():
    run_id = uuid.uuid4()
    collected = []
    async with events.subscription(run_id) as stream:
        await events.publish_raw(run_id, {"type": "not-a-type", "run_id": str(run_id)})
        await events.publish(DoneEvent(run_id=run_id, status="succeeded"))
        async for ev in stream:
            collected.append(ev)
            if ev.type == "done":
                break
    return collected


def test_malformed_frame_does_not_kill_stream():
    """一条坏帧不该让整个流断开——否则生产环境一次序列化 bug 就全站掉线。"""
    collected = run_async(_bad_frame_is_skipped())
    assert [e.type for e in collected] == ["done"]


def test_snapshot_carries_current_state():
    from app.models.run import QUEUED
    from app.services import runs as runs_service

    class Fake:
        id = uuid.uuid4()
        status = QUEUED
        progress = 0
        stage = None
        result = None
        error = None

    snap = runs_service.snapshot_of(Fake())  # type: ignore[arg-type]
    assert isinstance(snap, SnapshotEvent)
    assert snap.status == "queued"
