"""M9.3 trace + 指标测试。

    ① 一次对话能回溯完整 trace（planner/validate/tool/turn 全落库）
    ② 拒绝率口径正确：被六道关卡拦下的计划计入分子与分母
    ③ metrics 按 prompt_version 分组
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent import llm as llm_module
from app.main import app


def unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client: TestClient):
    r = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    )
    assert r.status_code == 201
    token = r.json()["token"]["access_token"]
    return {"Authorization": f"Bearer {token}", "_token": token}


def make_session(client: TestClient, headers: dict) -> dict:
    data = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 50)).save(data, format="PNG")
    ticket = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "s.png", "mime": "image/png", "size": data.getbuffer().nbytes},
        headers=headers,
    ).json()
    client.post(
        ticket["upload_url"],
        data={"key": ticket["key"]},
        files={"file": ("s.png", data.getvalue(), "image/png")},
        headers=headers,
    )
    asset = client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": data.getbuffer().nbytes},
        headers=headers,
    ).json()
    r = client.post("/api/edit-sessions", json={"asset_ids": [asset["id"]]}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def stub_planner(monkeypatch, calls):
    async def fake(instruction, summary, functions, emit=None):
        if emit is not None:
            await emit("thought", "桩")
        return calls

    monkeypatch.setattr(llm_module, "plan_tool_calls_stream", fake)


def wait_plan(client: TestClient, headers: dict, run_id: str, timeout: float = 8.0) -> dict:
    import time

    terminal = {"succeeded", "failed", "cancelled", "awaiting_confirm"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/agent/runs/{run_id}", headers=headers).json()
        if run["status"] in terminal:
            return run
        time.sleep(0.05)
    raise AssertionError("图执行超时仍未收敛")


def test_trace_captures_full_round(client, auth, monkeypatch):
    """DoD ①：一轮对话的 planner / tool / turn span 全部可回溯。"""
    session = make_session(client, auth)
    stub_planner(
        monkeypatch,
        [
            {"name": "adjust_color", "args": {"brightness": 20}},
            {"name": "flip_layer", "args": {"direction": "horizontal"}},
        ],
    )

    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "两步"},
        headers=auth,
    ).json()
    run = wait_plan(client, auth, created["id"])
    assert run["status"] == "awaiting_confirm"
    client.post(f"/api/agent/runs/{created['id']}/confirm", headers=auth)
    wait_plan(client, auth, created["id"])

    r = client.get(f"/api/agent/runs/{created['id']}/trace", headers=auth)
    assert r.status_code == 200
    spans = r.json()

    kinds = {span["kind"] for span in spans}
    assert {"planner", "tool", "turn"} <= kinds

    planner = next(span for span in spans if span["kind"] == "planner")
    assert planner["prompt_version"]  # 版本号必须带上（DoD ③ 的根基）
    assert planner["duration_ms"] is not None

    tool_spans = [span for span in spans if span["kind"] == "tool"]
    assert len(tool_spans) == 2
    assert all(span["status"] == "ok" for span in tool_spans)

    turn_span = next(span for span in spans if span["kind"] == "turn")
    assert turn_span["detail"]["steps"] == 2


def test_validate_rejection_counted_in_metrics(client, auth, monkeypatch):
    """DoD ②：被拦下的计划计入拒绝率 —— 分子分母口径都对。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "不存在的工具", "args": {}}])

    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "必然被拒"},
        headers=auth,
    ).json()
    run = wait_plan(client, auth, created["id"])
    assert run["status"] == "failed"

    metrics = client.get("/api/agent/metrics?days=7", headers=auth).json()
    assert metrics["rejected_total"] >= 1
    assert 0 < metrics["reject_rate"] <= 1

    # validate span 带 failed 状态与失败原因
    spans = client.get(f"/api/agent/runs/{created['id']}/trace", headers=auth).json()
    validate = [span for span in spans if span["kind"] == "validate"]
    assert len(validate) == 1
    assert validate[0]["status"] == "failed"
    assert "不存在的工具" in str(validate[0]["detail"])


def test_metrics_groups_by_prompt_version(client, auth, monkeypatch):
    """DoD ③：planner span 带版本号，metrics 按版本分组。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "flip_layer", "args": {}}])

    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "单步"},
        headers=auth,
    ).json()
    wait_plan(client, auth, created["id"])

    metrics = client.get("/api/agent/metrics?days=7", headers=auth).json()
    versions = {item["prompt_version"] for item in metrics["by_prompt_version"]}
    assert versions and all(v for v in versions)  # 不允许落在 unknown
    for item in metrics["by_prompt_version"]:
        assert 0 <= item["reject_rate"] <= 1
        assert "avg_duration_ms" in item


def test_trace_requires_ownership(client, auth):
    """归属校验：别人的 trace 拿不到。"""
    other = client.post(
        "/api/auth/register",
        json={"email": f"trace_{uuid.uuid4().hex[:10]}@example.com", "password": "Strong-Pass-123"},
    ).json()["token"]["access_token"]
    session = make_session(client, auth)
    stub = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "x"},
        headers=auth,
    ).json()["id"]
    wait_plan(client, auth, stub)  # 等后台图收敛，避免 module teardown 撞上在途任务
    r = client.get(f"/api/agent/runs/{stub}/trace", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 200
    assert r.json() == []  # 看不到别人的 span，也不报错


def test_metrics_are_scoped_to_the_current_user(client, auth, monkeypatch):
    """指标是个人观测，不是全局看板：别人的失败不能污染我的口径。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "不存在的工具", "args": {}}])
    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "必然被拒"},
        headers=auth,
    ).json()
    wait_plan(client, auth, created["id"])

    own = client.get("/api/agent/metrics?days=7", headers=auth).json()
    assert own["rounds_total"] == 1
    assert own["rejected_total"] >= 1

    other_token = client.post(
        "/api/auth/register",
        json={
            "email": f"metrics_{uuid.uuid4().hex[:10]}@example.com",
            "password": "Strong-Pass-123",
        },
    ).json()["token"]["access_token"]
    other = client.get(
        "/api/agent/metrics?days=7", headers={"Authorization": f"Bearer {other_token}"}
    ).json()
    assert other["rounds_total"] == 0
    assert other["rejected_total"] == 0
    assert other["by_prompt_version"] == []


def test_metrics_counts_replanned_rounds(client, auth, monkeypatch):
    """重规划次数来自 reflect span，而不是去 error 文案里找关键词。"""
    session = make_session(client, auth)
    calls = {"n": 0}

    async def fake(instruction, summary, functions, emit=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"name": "remove_layer", "args": {"layer": "不存在的图层"}}]
        return [{"name": "flip_layer", "args": {"direction": "horizontal"}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls_stream", fake)
    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "先失败再重来"},
        headers=auth,
    ).json()
    run = wait_plan(client, auth, created["id"], timeout=12.0)
    assert run["status"] == "succeeded", run

    metrics = client.get("/api/agent/metrics?days=7", headers=auth).json()
    assert metrics["replan_rounds"] == 1
