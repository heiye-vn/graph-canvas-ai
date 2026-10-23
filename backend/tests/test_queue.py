"""任务投递契约：同一个 run 只能入队一次。

重复投递的来源比想象的多——前端超时重试、网关重放、用户狂点按钮。
不去重的结果就是同一张图生成两遍，账单翻倍。
"""

from __future__ import annotations

import uuid

import pytest

from app.services import queue


class FakePool:
    """只记录调用参数，不真的连 Redis：这里要验的是参数，不是网络。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, task: str, *args, **kwargs) -> None:
        self.calls.append((task, args, kwargs))


def _patch_pool(monkeypatch, pool: FakePool) -> None:
    async def fake_get_pool():
        return pool

    monkeypatch.setattr(queue, "get_pool", fake_get_pool)


async def test_enqueue_uses_run_id_as_job_id(monkeypatch):
    pool = FakePool()
    _patch_pool(monkeypatch, pool)

    run_id = uuid.uuid4()
    await queue.enqueue("text_to_image", run_id)

    task, args, kwargs = pool.calls[0]
    assert task == "text_to_image"
    assert args == (str(run_id),)
    assert kwargs["_job_id"] == str(run_id)


async def test_repeated_enqueue_collapses_to_one_job(monkeypatch):
    """投递三次，ARQ 看到的仍是同一个 job id —— 只会执行一次。"""
    pool = FakePool()
    _patch_pool(monkeypatch, pool)

    run_id = uuid.uuid4()
    for _ in range(3):
        await queue.enqueue("text_to_image", run_id)

    assert len(pool.calls) == 3
    assert {call[2]["_job_id"] for call in pool.calls} == {str(run_id)}


async def test_enqueue_wraps_transport_failure(monkeypatch):
    """投递失败必须显式暴露：调用方要能把已提交的任务补偿成 failed。"""

    class BrokenPool:
        async def enqueue_job(self, *args, **kwargs):
            raise ConnectionError("redis down")

    _patch_pool(monkeypatch, BrokenPool())

    with pytest.raises(queue.EnqueueFailed):
        await queue.enqueue("text_to_image", uuid.uuid4())
