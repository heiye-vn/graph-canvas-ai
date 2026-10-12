"""任务 API 与 SSE 入口（HTTP 层）。

这组用例回答三个问题：
    1. 创建任务是不是 202（不是 200 —— 结果还没出来）
    2. 别人的任务是不是 404
    3. SSE 连接建立后，客户端是不是**立刻**收到一帧快照
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import queue


def unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:12]}@example.com"


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


def create_run(client: TestClient, user: dict, **overrides) -> dict:
    payload = {"prompt": "一只橘猫坐在窗台", "size": "512x512", "n": 1}
    payload.update(overrides)
    r = client.post("/api/runs/text-to-image", json=payload, headers=auth(user))
    assert r.status_code == 202, r.text
    return r.json()


def test_create_returns_202_with_queued_status(client: TestClient, user: dict):
    run = create_run(client, user)
    assert run["status"] == "queued"
    assert run["tool"] == "text_to_image"
    assert run["params"]["prompt"] == "一只橘猫坐在窗台"
    assert run["progress"] == 0


def test_create_enqueues_job_with_run_id(monkeypatch, client: TestClient, user: dict):
    """job id = run id 是幂等的唯一保障，必须在 HTTP 层也验一次。"""

    class FakePool:
        def __init__(self):
            self.calls = []

        async def enqueue_job(self, task, *args, **kwargs):
            self.calls.append((task, args, kwargs))

    pool = FakePool()

    async def fake_get_pool():
        return pool

    monkeypatch.setattr(queue, "get_pool", fake_get_pool)

    run = create_run(client, user)
    assert pool.calls[0][0] == "text_to_image"
    assert pool.calls[0][1] == (run["id"],)
    assert pool.calls[0][2]["_job_id"] == run["id"]


def test_blank_prompt_is_rejected(client: TestClient, user: dict):
    """min_length=1 挡不住一串空格 —— 必须显式 trim 后再判空。"""
    r = client.post(
        "/api/runs/text-to-image", json={"prompt": "   "}, headers=auth(user)
    )
    assert r.status_code == 422


def test_prompt_is_trimmed(client: TestClient, user: dict):
    """trim 过才能保证「看着一样」的 prompt 真的生成同一张图。"""
    run = create_run(client, user, prompt="  一只橘猫  ")
    assert run["params"]["prompt"] == "一只橘猫"


def test_out_of_range_size_is_rejected(client: TestClient, user: dict):
    r = client.post(
        "/api/runs/text-to-image",
        json={"prompt": "x", "size": "5000x5000"},
        headers=auth(user),
    )
    assert r.status_code == 400
    assert "256~2048" in r.json()["detail"]


def test_malformed_size_is_rejected(client: TestClient, user: dict):
    r = client.post(
        "/api/runs/text-to-image",
        json={"prompt": "x", "size": "big"},
        headers=auth(user),
    )
    assert r.status_code == 422


def test_runs_require_auth(client: TestClient):
    assert client.post("/api/runs/text-to-image", json={"prompt": "x"}).status_code == 401
    assert client.get("/api/runs").status_code == 401


def test_list_and_get_roundtrip(client: TestClient, user: dict):
    run = create_run(client, user, prompt="第二张")
    listed = client.get("/api/runs", headers=auth(user)).json()
    assert any(r["id"] == run["id"] for r in listed)

    got = client.get(f"/api/runs/{run['id']}", headers=auth(user))
    assert got.status_code == 200
    assert got.json()["params"]["prompt"] == "第二张"


def test_cancel_then_cancel_again_conflicts(client: TestClient, user: dict):
    run = create_run(client, user)
    first = client.post(f"/api/runs/{run['id']}/cancel", headers=auth(user))
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"

    second = client.post(f"/api/runs/{run['id']}/cancel", headers=auth(user))
    assert second.status_code == 409


def test_other_users_run_is_invisible(client: TestClient):
    owner = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    owner_headers = {"Authorization": f"Bearer {owner['token']['access_token']}"}
    run = client.post(
        "/api/runs/text-to-image", json={"prompt": "私有任务"}, headers=owner_headers
    ).json()

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['token']['access_token']}"}

    assert client.get(f"/api/runs/{run['id']}", headers=other_headers).status_code == 404
    assert (
        client.post(f"/api/runs/{run['id']}/cancel", headers=other_headers).status_code == 404
    )


def test_sse_sends_snapshot_immediately(client: TestClient, user: dict):
    """建立连接后必须立刻有一帧：否则「任务已结束」时客户端会永远空等。"""
    run = create_run(client, user)
    with client.stream(
        "GET", f"/events/runs/{run['id']}?token={user['token']}", timeout=10
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert resp.headers.get("x-accel-buffering") == "no"
        first = next(resp.iter_lines())

    assert first.startswith("data:{")
    assert '"type":"snapshot"' in first
    assert '"status":"queued"' in first


def test_sse_requires_token(client: TestClient, user: dict):
    run = create_run(client, user)
    r = client.get(f"/events/runs/{run['id']}")
    assert r.status_code == 401
