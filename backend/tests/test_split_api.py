"""M7 工具 API 集成测试：set_layer_text（同步）+ split_layers（排队提交）。"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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


def invoke(client: TestClient, headers: dict, tool: str, session_id: str, params: dict):
    return client.post(
        f"/api/tools/{tool}/invoke",
        json={"session_id": session_id, "params": params},
        headers=headers,
    )


def test_set_layer_text_edits_and_keeps_position(client, auth):
    """DoD ②：文案可改、位置不变（transform 逐字段不变）。"""
    session = make_session(client, auth)
    r = invoke(client, auth, "add_text_layer", session["id"],
               {"text": "旧文案", "font_size": 32, "fill": "#101010", "x": 12, "y": 8})
    assert r.status_code == 200, r.text

    r = invoke(client, auth, "set_layer_text", session["id"], {"text": "新文案"})
    assert r.status_code == 200, r.text
    layers = [item for item in r.json()["session"]["doc"]["layers"] if item["type"] == "text"]
    assert len(layers) == 1
    assert layers[0]["text"]["text"] == "新文案"
    assert layers[0]["name"] == "新文案"
    # 几何不动
    assert (layers[0]["transform"]["x"], layers[0]["transform"]["y"]) == (12, 8)
    assert layers[0]["text"]["font_size"] == 32


def test_set_layer_text_without_text_layer_fails_clean(client, auth):
    session = make_session(client, auth)
    r = invoke(client, auth, "set_layer_text", session["id"], {"text": "字"})
    assert r.status_code == 422
    assert "文字" in r.json()["detail"]


def test_split_layers_registered_and_queued(client, auth):
    """拆层进注册表且走排队通道：提交返回 run_id，不改文档。"""
    items = client.get("/api/tools").json()["items"]
    split = next(item for item in items if item["name"] == "split_layers")
    visible = [p["name"] for p in split["params"] if not p["agent_hidden"]]
    assert "include_text" in visible

    session = make_session(client, auth)
    revision = session["revision"]
    r = invoke(client, auth, "split_layers", session["id"], {"include_text": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"]
    # 排队提交不动文档：revision 不变，画布还是原样
    assert body["session"]["revision"] == revision
