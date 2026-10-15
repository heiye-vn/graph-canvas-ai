"""M9.1 CoT 流式测试：缓冲/回放 + 流式规划透传。

规划模型打桩（与 M8 同法），重点验证：
    · cot 缓冲 seq 单调、replay 按 after_seq 过滤（DoD ③ 的服务端半边）
    · plan_tool_calls_stream 把 reasoning_content 与 content 都当思考透传
    · 规划异常照旧翻成 PlannerError 人话
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from langchain_core.messages import AIMessageChunk

from app.agent import llm as llm_module
from app.services import cot as cot_service
from app.services import events as events_service


@pytest.fixture(autouse=True)
def _reset_redis_client():
    """全局 Redis 客户端绑定第一个事件循环 —— 每个用例后丢弃，避免跨 loop 报错。"""
    events_service._redis = None
    yield
    events_service._redis = None


# ------------------------------------------------------------------ 缓冲与回放


@pytest.mark.asyncio
async def test_emit_seq_monotonic_and_replay_filters():
    run_id = uuid.uuid4()
    s1 = await cot_service.emit(run_id, "thought", "先看画布")
    s2 = await cot_service.emit(run_id, "tool_call", "调用 adjust_color")
    assert s2 == s1 + 1

    all_items = await cot_service.replay(run_id)
    assert [item["seq"] for item in all_items] == [s1, s2]

    tail = await cot_service.replay(run_id, after_seq=s1)
    assert [item["seq"] for item in tail] == [s2]
    assert tail[0]["kind"] == "tool_call"


@pytest.mark.asyncio
async def test_emit_empty_delta_skipped():
    run_id = uuid.uuid4()
    assert await cot_service.emit(run_id, "thought", "") == 0
    assert await cot_service.replay(run_id) == []


# ------------------------------------------------------------------ 流式规划


@pytest.mark.asyncio
async def test_stream_planner_pushes_thought_and_tool_call(monkeypatch):
    """reasoning_content 与 content 两个字段都要透传（施工图钉死的坑）。"""
    pushed: list[tuple[str, str]] = []

    async def chunks(_messages):
        yield AIMessageChunk(content="", additional_kwargs={"reasoning_content": "先调亮"})
        yield AIMessageChunk(content="好的，")
        yield AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "name": "adjust_color",
                    "args": '{"brightness":20}',
                    "id": "1",
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        )

    class _Fake:
        def bind_tools(self, _functions, **_kwargs):
            return self

        def astream(self, _messages):
            return chunks(_messages)

    monkeypatch.setattr(llm_module, "get_chat_model", lambda: _Fake())

    async def emit(kind: str, delta: str) -> None:
        pushed.append((kind, delta))

    calls, meta = await llm_module.plan_tool_calls_stream("调亮", "画布摘要", [], emit)
    assert calls == [{"name": "adjust_color", "args": {"brightness": 20}}]
    assert meta["model"]  # M9.3：trace 需要 model 与 token 用量

    kinds = [kind for kind, _delta in pushed]
    assert "thought" in kinds and "tool_call" in kinds
    assert ("thought", "先调亮") in pushed  # reasoning_content 没被丢
    assert ("thought", "好的，") in pushed  # content 也没被丢
    assert pushed[-1][0] == "tool_call"  # 决定调用最后发


def test_stream_wrapper_keeps_planner_error(monkeypatch):
    """astream 抛错也要翻成人话的 PlannerError。"""

    class _Fake:
        def bind_tools(self, _functions, **_kwargs):
            return self

        async def astream(self, _messages):
            raise RuntimeError("connection refused")
            yield  # noqa: unreachable - 使其成为异步生成器

    monkeypatch.setattr(llm_module, "get_chat_model", lambda: _Fake())

    async def main():
        async def emit(kind: str, delta: str) -> None:
            return None

        with pytest.raises(llm_module.PlannerError) as exc:
            await llm_module.plan_tool_calls_stream("x", "y", [], emit)
        assert "connection refused" in str(exc.value)

    asyncio.run(main())
