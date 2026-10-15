"""M8/M9.1 多步计划 API 集成测试（规划模型打桩）。

桩固定在 `app.agent.llm.plan_tool_calls_stream` —— 「占位 → 流式规划 →
校验 → 确认 → 执行 → 推进 → 级联取消」全链路都是真代码。
规划在 API 进程内后台跑，测试里用轮询等它收敛。
"""

from __future__ import annotations

import io
import json
import time
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
            await emit("thought", "桩：想好了")
            for call in calls:
                await emit("tool_call", f"调用 {call['name']}")
        return calls

    monkeypatch.setattr(llm_module, "plan_tool_calls_stream", fake)


def wait_plan(client: TestClient, headers: dict, run_id: str, timeout: float = 5.0) -> dict:
    """规划在后台跑：轮询到收敛（终态，或停在等确认）为止。"""
    terminal = {"succeeded", "failed", "cancelled", "awaiting_confirm"}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/agent/runs/{run_id}", headers=headers).json()
        if run["status"] in terminal:
            return run
        time.sleep(0.05)
    raise AssertionError("规划超时仍未收敛")


def test_multi_step_plan_requires_confirm_then_executes(client, auth, monkeypatch):
    """DoD ① + ③：多步出计划卡片等确认；确认后逐步执行，撤销栈完整。"""
    session = make_session(client, auth)
    stub_planner(
        monkeypatch,
        [
            {"name": "adjust_color", "args": {"brightness": 30}},
            {"name": "flip_layer", "args": {"direction": "horizontal"}},
        ],
    )

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "调亮再翻转"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]

    run = wait_plan(client, auth, run_id)
    assert run["status"] == "awaiting_confirm"
    assert len(run["plan"]) == 2
    assert run["plan"][0]["status"] == "pending"

    # 确认前画布没动
    before = client.get(f"/api/edit-sessions/{session['id']}", headers=auth).json()
    assert before["revision"] == session["revision"]

    r = client.post(f"/api/agent/runs/{run_id}/confirm", headers=auth)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "succeeded"
    assert all(step["status"] == "succeeded" for step in done["plan"])
    assert all(step["message"] for step in done["plan"])

    # 文档真的变了 + 撤销栈找得到这两步
    after = client.get(f"/api/edit-sessions/{session['id']}", headers=auth).json()
    assert after["revision"] > session["revision"]
    history = client.get(f"/api/edit-sessions/{session['id']}/history", headers=auth).json()
    labels = [item["tool"] for item in history["items"]]
    assert "adjust_color" in labels and "flip_layer" in labels

    # 幂等：结束态再 confirm 是 409，不是 500
    r = client.post(f"/api/agent/runs/{run_id}/confirm", headers=auth)
    assert r.status_code == 409


def test_single_step_plan_runs_directly(client, auth, monkeypatch):
    """单步计划不设确认关卡，直接执行完成。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "flip_layer", "args": {"direction": "vertical"}}])

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "垂直翻转"},
        headers=auth,
    )
    assert r.status_code == 200
    run = wait_plan(client, auth, r.json()["id"])
    assert run["status"] == "succeeded"
    assert run["plan"][0]["status"] == "succeeded"


def test_hallucinated_tool_rejected_with_plain_words(client, auth, monkeypatch):
    """DoD ②：幻觉工具名被拦下，plan 清空 + 人话，绝不到执行层。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "delete_everything", "args": {}}])

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "毁灭一切"},
        headers=auth,
    )
    assert r.status_code == 200
    run = wait_plan(client, auth, r.json()["id"])
    assert run["status"] == "failed"
    assert run["plan"] == []
    assert "不存在的工具" in run["error"]


def test_planner_error_becomes_plain_words(client, auth, monkeypatch):
    async def boom(instruction, summary, functions, emit=None):
        raise llm_module.PlannerError("规划模型 404：端点填错了")

    monkeypatch.setattr(llm_module, "plan_tool_calls_stream", boom)
    session = make_session(client, auth)
    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "随便"},
        headers=auth,
    )
    assert r.status_code == 200
    run = wait_plan(client, auth, r.json()["id"])
    assert run["status"] == "failed"
    assert "404" in run["error"]


def test_cancel_cascades_queued_runs(client, auth, monkeypatch):
    """DoD ③：取消后续时，已投递的排队任务级联取消。"""
    session = make_session(client, auth)
    sel = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={
            "revision": session["revision"],
            "strokes": [[{"x": 0.2, "y": 0.2}, {"x": 0.4, "y": 0.4}]],
        },
        headers=auth,
    )
    assert sel.status_code == 200

    stub_planner(
        monkeypatch,
        [
            {"name": "erase_region", "args": {}},
            {"name": "flip_layer", "args": {"direction": "horizontal"}},
        ],
    )
    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "消除再翻转"},
        headers=auth,
    )
    run_id = r.json()["id"]
    wait_plan(client, auth, run_id)

    r = client.post(f"/api/agent/runs/{run_id}/confirm", headers=auth)
    confirmed = r.json()
    assert confirmed["status"] == "running"
    queued_step = next(step for step in confirmed["plan"] if step["tool"] == "erase_region")
    assert queued_step["status"] == "queued"
    assert queued_step["run_id"]

    r = client.post(f"/api/agent/runs/{run_id}/cancel", headers=auth)
    assert r.status_code == 200
    cancelled = r.json()
    assert cancelled["status"] == "cancelled"
    by_id = {step["id"]: step for step in cancelled["plan"]}
    assert by_id[queued_step["id"]]["status"] == "canceled"

    tool_run = client.get(f"/api/runs/{queued_step['run_id']}", headers=auth).json()
    assert tool_run["status"] == "cancelled"

    r = client.post(
        f"/api/agent/runs/{run_id}/continue",
        json={"run_id": queued_step["run_id"]},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_plan_survives_refresh(client, auth, monkeypatch):
    """DoD ④：计划落库 —— 刷新后 GET 仍能拿回完整现场。"""
    session = make_session(client, auth)
    stub_planner(
        monkeypatch,
        [
            {"name": "adjust_color", "args": {"brightness": 10}},
            {"name": "flip_layer", "args": {}},
        ],
    )
    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "两步"},
        headers=auth,
    ).json()
    wait_plan(client, auth, created["id"])

    fetched = client.get(f"/api/agent/runs/{created['id']}", headers=auth).json()
    assert fetched["id"] == created["id"]
    assert len(fetched["plan"]) == 2

    listed = client.get(f"/api/agent/sessions/{session['id']}/runs", headers=auth).json()
    assert [item["id"] for item in listed][-1] == created["id"]


def test_cot_stream_replays_buffer(client, auth, monkeypatch):
    """DoD ③ 服务端半边：SSE 建流即回放缓冲的 CoT，done 收束。"""
    session = make_session(client, auth)
    stub_planner(monkeypatch, [{"name": "flip_layer", "args": {"direction": "vertical"}}])
    created = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "翻转"},
        headers=auth,
    ).json()
    run_id = created["id"]
    wait_plan(client, auth, run_id)  # 等规划收束（缓冲里已有完整 CoT）

    token = auth["_token"]
    resp = client.get(f"/events/agent/{run_id}?token={token}&cot_after=0")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    kinds, saw_done = [], False
    for line in resp.text.splitlines():
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:])
        if event["type"] == "cot":
            kinds.append(event["kind"])
        if event["type"] == "done":
            saw_done = True
    assert "thought" in kinds and "tool_call" in kinds
    assert saw_done
