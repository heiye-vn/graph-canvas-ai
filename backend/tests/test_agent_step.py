"""Agent 单步集成测试。

模型这一段**必须打桩**：跑一次真实调用要钱、要 Key、还不确定。
桩的位置固定在 `app.agent.llm.plan_tool_calls` —— 打在这一层意味着
「文档摘要 → 工具调用 → 执行 → 落库」全链路都是真代码，只有「模型怎么想」
被替换掉了，这恰恰是我们不需要在集成测试里验证的部分。

额外钉住两条：
    · 传给模型的上下文里没有 UUID（模型看不见 id 才不会编 id）
    · 模型输出里再出现 id 也不会被当成素材引用（add_image_layer 仍要求界面传）
"""

from __future__ import annotations

import io
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent import llm as llm_module
from app.main import app

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:12]}@example.com"


def make_png(width: int = 8, height: int = 6) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def user(client: TestClient):
    r = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    )
    assert r.status_code == 201
    return {"token": r.json()["token"]["access_token"], "id": r.json()["user"]["id"]}


def auth(user: dict) -> dict:
    return {"Authorization": f"Bearer {user['token']}"}


def make_session(client: TestClient, user: dict, count: int = 1) -> dict:
    ids = []
    for _ in range(count):
        data = make_png()
        ticket = client.post(
            "/api/assets/upload-ticket",
            json={"filename": "s.png", "mime": "image/png", "size": len(data)},
            headers=auth(user),
        ).json()
        client.post(
            ticket["upload_url"],
            data={"key": ticket["key"]},
            files={"file": ("s.png", data, "image/png")},
            headers=auth(user),
        )
        ids.append(
            client.post(
                "/api/assets/confirm",
                json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
                headers=auth(user),
            ).json()["id"]
        )

    r = client.post("/api/edit-sessions", json={"asset_ids": ids}, headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


def step(client: TestClient, user: dict, session_id: str, instruction: str):
    return client.post(
        "/api/agent/step",
        json={"session_id": session_id, "instruction": instruction},
        headers=auth(user),
    )


# ------------------------------------------------------------------ 核心 DoD


def test_instruction_runs_a_tool_and_persists(monkeypatch, client: TestClient, user: dict):
    """DoD ①：「把图变亮一点」真的能调用到调色工具并落库。"""
    seen: dict = {}

    async def fake_plan(instruction, doc_summary, functions):
        seen["summary"] = doc_summary
        seen["functions"] = functions
        return [{"name": "adjust_color", "args": {"brightness": 30}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    session = make_session(client, user)
    r = step(client, user, session["id"], "把图变亮一点")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["steps"][0]["tool"] == "adjust_color"
    assert body["steps"][0]["ok"] is True
    assert body["session"]["doc"]["layers"][0]["adjustments"]["brightness"] == 30

    # 落库确认
    again = client.get(f"/api/edit-sessions/{session['id']}", headers=auth(user)).json()
    assert again["doc"]["layers"][0]["adjustments"]["brightness"] == 30


def test_context_sent_to_model_has_no_ids(monkeypatch, client: TestClient, user: dict):
    """DoD ③：给模型的上下文里不能出现 UUID（看见了它就会照着编）。"""
    seen: dict = {}

    async def fake_plan(instruction, doc_summary, functions):
        seen["summary"] = doc_summary
        return [{"name": "adjust_color", "args": {"brightness": 10}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    make_session(client, user, count=2)
    session = client.get("/api/edit-sessions", headers=auth(user)).json()[0]
    step(client, user, session["id"], "把图变亮一点")

    assert not _UUID_RE.search(seen["summary"]), f"摘要里出现了 id：{seen['summary']}"
    assert "候选图 1" in seen["summary"]


def test_hidden_field_is_not_offered_to_the_model(monkeypatch, client: TestClient, user: dict):
    seen: dict = {}

    async def fake_plan(instruction, doc_summary, functions):
        seen["functions"] = functions
        return [{"name": "adjust_color", "args": {"brightness": 10}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    session = make_session(client, user)
    step(client, user, session["id"], "把图变亮一点")

    add = next(
        f for f in seen["functions"] if f["function"]["name"] == "add_image_layer"
    )["function"]
    assert "asset_id" not in add["parameters"]["properties"]


# ------------------------------------------------------------------ 错误处理


def test_failed_tool_step_is_reported_not_500(monkeypatch, client: TestClient, user: dict):
    """工具失败是正常结果：一句话里有一个工具失败，其余的仍然有效。"""

    async def fake_plan(instruction, doc_summary, functions):
        return [{"name": "adjust_color", "args": {"layer": "不存在的图层"}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    session = make_session(client, user)
    r = step(client, user, session["id"], "把不存在的图层调亮")

    assert r.status_code == 200
    body = r.json()
    assert body["steps"][0]["ok"] is False
    assert "找不到图层" in body["steps"][0]["message"]


def test_no_tool_call_returns_a_note(monkeypatch, client: TestClient, user: dict):
    async def fake_plan(instruction, doc_summary, functions):
        return []

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    session = make_session(client, user)
    r = step(client, user, session["id"], "今天天气怎么样")

    assert r.status_code == 200
    body = r.json()
    assert body["steps"] == []
    assert body["note"]


def test_step_on_other_users_session_is_404(monkeypatch, client: TestClient, user: dict):
    async def fake_plan(instruction, doc_summary, functions):
        return [{"name": "adjust_color", "args": {"brightness": 10}}]

    monkeypatch.setattr(llm_module, "plan_tool_calls", fake_plan)

    session = make_session(client, user)
    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()

    r = client.post(
        "/api/agent/step",
        json={"session_id": session["id"], "instruction": "把图变亮一点"},
        headers={"Authorization": f"Bearer {other['token']['access_token']}"},
    )
    assert r.status_code == 404


def test_step_requires_auth(client: TestClient):
    r = client.post(
        "/api/agent/step",
        json={"session_id": str(uuid.uuid4()), "instruction": "把图变亮"},
    )
    assert r.status_code == 401
