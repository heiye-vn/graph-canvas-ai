"""M9.2 LangGraph 状态机 DoD 测试。

    ① 工具失败后模型能看见错误并重新规划（reflect → replan 剩余）
    ② 中断状态由 checkpointer 落库，新编译的图实例凭同一 thread 续跑
       （服务重启后 confirm/continue 走的就是这条路径 —— 只差进程退出）
    ③ 重规划达到上限后优雅降级为 failed，绝不死循环
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.agent import llm as llm_module
from app.agent.graph import MAX_REPLANS
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


def wait_plan(client: TestClient, headers: dict, run_id: str, timeout: float = 8.0) -> dict:
    terminal = {"succeeded", "failed", "cancelled", "awaiting_confirm"}
    deadline = __import__("time").monotonic() + timeout
    while __import__("time").monotonic() < deadline:
        run = client.get(f"/api/agent/runs/{run_id}", headers=headers).json()
        if run["status"] in terminal:
            return run
        __import__("time").sleep(0.05)
    raise AssertionError("图执行超时仍未收敛")


def stub_sequence(monkeypatch, plans: list[list[dict]]):
    """第 N 次规划调用返回第 N 份调用清单（超出后重复最后一份）。"""
    counter = {"n": 0}

    async def fake(instruction, summary, functions, emit=None):
        index = min(counter["n"], len(plans) - 1)
        counter["n"] += 1
        return plans[index]

    monkeypatch.setattr(llm_module, "plan_tool_calls_stream", fake)


def cot_items(run_id: str) -> list[dict]:
    """读 CoT 缓冲：全局 Redis 客户端绑在 portal 的事件循环上，
    用例里换成新循环时必须丢弃重连，用完即在循环内关闭。"""
    import asyncio as aio

    from app.services import cot as cot_service
    from app.services import events as events_service

    async def _inner() -> list[dict]:
        items = await cot_service.replay(uuid.UUID(run_id))
        await events_service.close_redis()
        return items

    events_service._redis = None
    return aio.run(_inner())


def test_failure_triggers_reflection_and_replan(client, auth, monkeypatch):
    """DoD ①：第一步失败 → reflect 错误回灌 → replan 的剩余步骤执行成功。"""
    session = make_session(client, auth)
    # 第一次规划给了两步：第一步在没有选区时必然失败
    stub_sequence(
        monkeypatch,
        [
            [{"name": "erase_region", "args": {}}],
            [{"name": "flip_layer", "args": {"direction": "vertical"}}],
        ],
    )

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "消除物体再翻转"},
        headers=auth,
    )
    run_id = r.json()["id"]
    run = wait_plan(client, auth, run_id)

    assert run["status"] == "succeeded", run
    tools = [step["tool"] for step in run["plan"]]
    assert tools == ["flip_layer"]  # 失败步被丢弃，换成了重规划的步
    assert run["plan"][0]["status"] == "succeeded"

    # cot 里能看到反思
    items = cot_items(run_id)
    assert any(item["kind"] == "reflection" for item in items)


def test_replan_limit_degrades_gracefully(client, auth, monkeypatch):
    """DoD ③：重规划到上限后停在 failed，收敛而不是死循环。"""
    session = make_session(client, auth)
    stub_sequence(monkeypatch, [[{"name": "erase_region", "args": {}}]])  # 永远失败

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "一直失败"},
        headers=auth,
    )
    run_id = r.json()["id"]
    run = wait_plan(client, auth, run_id)  # 收敛即通过（超时会直接超时失败）

    assert run["status"] == "failed"
    assert run["error"]  # 有人话
    # 反思次数 = 初始失败 + MAX_REPLANS 次重规划
    items = cot_items(run_id)
    reflections = [item for item in items if item["kind"] == "reflection"]
    assert len(reflections) >= MAX_REPLANS


def test_interrupt_state_resumes_via_checkpointer(client, auth, monkeypatch):
    """DoD ②：确认中断由 checkpointer 落库；confirm 用**新编译的图实例**
    凭同一 thread 续跑到完成 —— 服务重启后走的就是这条路径。"""
    session = make_session(client, auth)
    stub_sequence(
        monkeypatch,
        [
            [
                {"name": "adjust_color", "args": {"brightness": 15}},
                {"name": "flip_layer", "args": {"direction": "horizontal"}},
            ]
        ],
    )

    r = client.post(
        "/api/agent/plan",
        json={"session_id": session["id"], "instruction": "两步计划"},
        headers=auth,
    )
    run_id = r.json()["id"]
    run = wait_plan(client, auth, run_id)
    assert run["status"] == "awaiting_confirm"  # 图停在 interrupt 上

    # confirm = 新编译图 + Command(resume)：checkpointer 里读回中断现场
    r = client.post(f"/api/agent/runs/{run_id}/confirm", headers=auth)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "succeeded"
    assert all(step["status"] == "succeeded" for step in done["plan"])
