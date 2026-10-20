"""Langfuse 导出（可选旁路）测试。

守三件事：
1. 没有 LANGFUSE_* 时完全 no-op（不联网、不建客户端）；
2. 有 Key 时 payload 符合 OTLP/JSON 契约（trace 归组、generation 用量、错误等级）；
3. 导出失败被吞掉，绝不影响调用方。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.config import get_settings
from app.services import langfuse_export as lf


@pytest.fixture()
def langfuse_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _span(payload: dict) -> dict:
    return payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def _attr(payload: dict, key: str):
    for item in _span(payload)["attributes"]:
        if item["key"] == key:
            return next(iter(item["value"].values()))
    return None


def test_disabled_without_keys(monkeypatch):
    # 注意：本地 .env 可能已有真实 Key，这里显式置空覆盖它
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    get_settings.cache_clear()
    assert lf.enabled() is False


def test_enabled_defaults_to_cloud(langfuse_keys):
    assert lf.enabled() is True
    credentials = lf._credentials()
    assert credentials is not None
    assert credentials[2] == "https://cloud.langfuse.com"


def test_planner_maps_to_generation_with_usage(langfuse_keys):
    run_id = uuid.uuid4()
    payload = lf.build_payload(
        agent_run_id=run_id,
        session_id=uuid.uuid4(),
        kind="planner",
        name="plan",
        duration_ms=1200,
        prompt_version="v1",
        model="qwen-plus",
        tokens_in=100,
        tokens_out=20,
        detail={"steps": 2},
    )
    span = _span(payload)

    assert span["traceId"] == run_id.hex  # 同一轮归到一条 trace
    assert span["name"] == "planner.plan"
    assert span["status"] == {"code": 0}
    assert _attr(payload, "langfuse.observation.type") == "generation"
    assert _attr(payload, "langfuse.observation.model.name") == "qwen-plus"
    assert _attr(payload, "langfuse.observation.usage_details") == '{"input": 100, "output": 20}'
    assert _attr(payload, "langfuse.version") == "v1"
    # OTLP/JSON 的 intValue 是字符串（proto3 JSON 约定）
    assert _attr(payload, "langfuse.observation.metadata.steps") == "2"
    assert _attr(payload, "service.name") is None  # resource 属性不在 span 上


def test_session_and_resource_attributes(langfuse_keys):
    session_id = uuid.uuid4()
    payload = lf.build_payload(
        agent_run_id=uuid.uuid4(), session_id=session_id, kind="tool", name="flip"
    )
    assert _attr(payload, "langfuse.session.id") == str(session_id)
    assert _attr(payload, "langfuse.observation.type") == "tool"
    resource = payload["resourceSpans"][0]["resource"]["attributes"]
    keys = {item["key"] for item in resource}
    assert {"service.name", "deployment.environment"} <= keys


def test_detail_is_redacted(langfuse_keys):
    """用户原文与工具参数不出本机：只发结构化字段与工具名。"""
    payload = lf.build_payload(
        agent_run_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="planner",
        name="plan.stream",
        detail={
            "steps": 2,
            "tool_calls": [
                {"name": "add_text_layer", "args": {"text": "用户的私密文案"}},
                {"name": "flip_layer", "args": {}},
            ],
            "message": "已完成：把文案改成 XXX",
            "error": "x" * 400,
        },
    )
    assert _attr(payload, "langfuse.observation.metadata.steps") == "2"
    tools = _attr(payload, "langfuse.observation.metadata.tools")
    assert tools == '["add_text_layer", "flip_layer"]'
    assert _attr(payload, "langfuse.observation.metadata.message") is None
    assert "用户的私密文案" not in str(payload)
    assert len(_attr(payload, "langfuse.observation.metadata.error")) == 300


def test_failed_span_marked_error(langfuse_keys):
    payload = lf.build_payload(
        agent_run_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="validate",
        name="plan-check",
        status="failed",
    )
    assert _span(payload)["status"] == {"code": 2}
    assert _attr(payload, "langfuse.observation.level") == "ERROR"
    assert _attr(payload, "langfuse.observation.status_message") == "status=failed"


@pytest.mark.asyncio
async def test_export_span_schedules_send(langfuse_keys, monkeypatch):
    sent: dict[str, object] = {}

    async def fake_send(payload, credentials):
        sent["payload"] = payload
        sent["credentials"] = credentials

    monkeypatch.setattr(lf, "_send", fake_send)
    lf.export_span(
        agent_run_id=uuid.uuid4(), session_id=uuid.uuid4(), kind="tool", name="flip"
    )
    await asyncio.sleep(0)  # 让 create_task 排到

    assert sent["credentials"][0] == "pk-test"  # type: ignore[index]
    payload = sent["payload"]
    assert isinstance(payload, dict)
    assert _span(payload)["name"] == "tool.flip"


@pytest.mark.asyncio
async def test_send_swallows_network_failure(monkeypatch):
    """导出失败只吞掉：编辑流程不该因为观测后端挂了而失败。"""

    class BrokenClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("network down")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(lf.httpx, "AsyncClient", BrokenClient)
    await lf._send({"resourceSpans": []}, ("pk", "sk", "https://cloud.langfuse.com"))
