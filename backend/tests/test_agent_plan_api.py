"""M8 多步计划 API 集成测试（规划模型打桩）。

桩固定在 `app.agent.llm.plan_tool_calls` —— 「计划校验 → 确认 → 执行 →
推进 → 级联取消」全链路都是真代码。
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
    return {"Authorization": f"Bearer {token}"}


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
    async def fake(instruction, summary, functions):
        return calls

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake)


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
    run = r.json()
    assert run["status"] == "awaiting_confirm"
    assert len(run["plan"]) == 2
    assert run["plan"][0]["status"] == "pending"

    # 确认前画布没动
    before = client.get(f"/api/edit-sessions/{session['id']}", headers=auth).json()
    assert before["revision"] == session["revision"]

    r = client.post(f"/api/agent/runs/{run['id']}/confirm", headers=auth)
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
    r = client.post(f"/api/agent/runs/{run['id']}/confirm", headers=auth)
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
    run = r.json()
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
    run = r.json()
    assert run["status"] == "failed"
    assert run["plan"] == []
    assert "不存在的工具" in run["error"]


def test_planner_error_becomes_plain_words(client, auth, monkeypatch):
    async def boom(instruction, summary, functions):
        raise llm_module.PlannerError("规划模型 404：端点填错了")

    monkeypatch.setattr(llm_module, "plan_tool_calls", boom)
    session = make_session(client, auth)
    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "随便"},
        headers=auth,
    )
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "failed"
    assert "404" in run["error"]


def test_cancel_cascades_queued_runs(client, auth, monkeypatch):
    """DoD ③：取消后续时，已投递的排队任务级联取消。"""
    session = make_session(client, auth)
    # 先造一个选区，erase_region 提交时才走得通
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
    run = r.json()
    assert run["status"] == "awaiting_confirm"

    r = client.post(f"/api/agent/runs/{run['id']}/confirm", headers=auth)
    confirmed = r.json()
    assert confirmed["status"] == "running"
    queued_step = next(step for step in confirmed["plan"] if step["tool"] == "erase_region")
    assert queued_step["status"] == "queued"
    assert queued_step["run_id"]

    # 取消后续：排队中的 ToolRun 一并取消
    r = client.post(f"/api/agent/runs/{run['id']}/cancel", headers=auth)
    assert r.status_code == 200
    cancelled = r.json()
    assert cancelled["status"] == "cancelled"
    by_id = {step["id"]: step for step in cancelled["plan"]}
    assert by_id[queued_step["id"]]["status"] == "canceled"

    # 级联：对应的 ToolRun 也是 canceled
    tool_run = client.get(f"/api/runs/{queued_step['run_id']}", headers=auth).json()
    assert tool_run["status"] == "cancelled"

    # continue 一个已取消的任务：状态如实写回，不崩
    r = client.post(
        f"/api/agent/runs/{run['id']}/continue",
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

    fetched = client.get(f"/api/agent/runs/{created['id']}", headers=auth).json()
    assert fetched["id"] == created["id"]
    assert len(fetched["plan"]) == 2
    assert fetched["status"] == "awaiting_confirm"

    listed = client.get(
        f"/api/agent/sessions/{session['id']}/runs", headers=auth
    ).json()
    assert [item["id"] for item in listed][-1] == created["id"]
