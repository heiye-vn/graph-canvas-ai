"""工具 API 集成测试。

覆盖两条对外承诺：
    1. `GET /api/tools` 下发的东西足以渲染表单（DoD ② 的服务端那一半）
    2. 直接调用工具会真的落到会话文档上，并且**归属校验**与其它端点同口径
"""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


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


def upload_asset(client: TestClient, user: dict) -> dict:
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
    return client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
        headers=auth(user),
    ).json()


def make_session(client: TestClient, user: dict) -> dict:
    asset = upload_asset(client, user)
    r = client.post(
        "/api/edit-sessions", json={"asset_ids": [asset["id"]]}, headers=auth(user)
    )
    assert r.status_code == 201, r.text
    return r.json()


def invoke(client: TestClient, user: dict, tool: str, session_id: str, params: dict):
    return client.post(
        f"/api/tools/{tool}/invoke",
        json={"session_id": session_id, "params": params},
        headers=auth(user),
    )


# ------------------------------------------------------------------ 元数据


def test_list_tools_is_public_and_complete(client: TestClient, user: dict):
    r = client.get("/api/tools")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "工具注册表是空的"

    adjust = next(i for i in items if i["name"] == "adjust_color")
    assert adjust["label"] == "调色"
    assert {p["name"] for p in adjust["params"]} >= {
        "layer",
        "brightness",
        "contrast",
        "saturation",
        "temperature",
    }


def test_list_tools_needs_no_auth(client: TestClient):
    """元数据不含任何用户数据，不该要求登录 —— 前端首屏就能渲染工具面板。"""
    assert client.get("/api/tools").status_code == 200


def test_hidden_param_is_absent_from_model_facing_schema(client: TestClient):
    """DoD ③：asset_id 不进模型视野。"""
    items = client.get("/api/tools").json()["items"]
    add = next(i for i in items if i["name"] == "add_image_layer")
    asset = next(p for p in add["params"] if p["name"] == "asset_id")
    assert asset["agent_hidden"] is True


# ------------------------------------------------------------------ 调用


def test_invoke_persists_document_change(client: TestClient, user: dict):
    session = make_session(client, user)

    r = invoke(client, user, "adjust_color", session["id"], {"brightness": 40})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tool"] == "adjust_color"
    assert body["session"]["doc"]["layers"][0]["adjustments"]["brightness"] == 40

    again = client.get(f"/api/edit-sessions/{session['id']}", headers=auth(user)).json()
    assert again["doc"]["layers"][0]["adjustments"]["brightness"] == 40


def test_invoke_unknown_tool_is_404(client: TestClient, user: dict):
    session = make_session(client, user)
    assert invoke(client, user, "not_a_tool", session["id"], {}).status_code == 404


def test_invoke_bad_params_is_422_with_readable_message(client: TestClient, user: dict):
    """DoD ④：类型不对时报错来自服务端校验。"""
    session = make_session(client, user)
    r = invoke(client, user, "adjust_color", session["id"], {"brightness": "很亮"})
    assert r.status_code == 422
    assert "参数" in r.json()["detail"]


def test_invoke_unknown_layer_is_422(client: TestClient, user: dict):
    session = make_session(client, user)
    r = invoke(client, user, "adjust_color", session["id"], {"layer": "不存在的图层"})
    assert r.status_code == 422
    assert "找不到图层" in r.json()["detail"]
    assert "当前可选" in r.json()["detail"]


def test_invoke_without_visible_image_layer_explains_why(client: TestClient, user: dict):
    """默认目标（最上层可见图像层）不存在时，要说清「为什么没有」和「现有图层」。

    回归：这里曾经把 LayerNotFoundError 的「找不到匹配的图层」再套一层
    「找不到图层」，用户看到的是「找不到图层找不到匹配的图层」，且没说清是
    图层被隐藏了。
    """
    session = make_session(client, user)
    layer_id = session["doc"]["layers"][0]["id"]

    hidden = invoke(
        client, user, "set_layer_visible", session["id"], {"layer": layer_id, "visible": False}
    )
    assert hidden.status_code == 200, hidden.text

    r = invoke(client, user, "adjust_color", session["id"], {"brightness": 10})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "可见图像层" in detail
    assert "找不到图层" not in detail
    assert session["doc"]["layers"][0]["name"] in detail


def test_invoke_on_other_users_session_is_404(client: TestClient, user: dict):
    session = make_session(client, user)
    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    r = client.post(
        "/api/tools/adjust_color/invoke",
        json={"session_id": session["id"], "params": {}},
        headers={"Authorization": f"Bearer {other['token']['access_token']}"},
    )
    assert r.status_code == 404


def test_invoke_requires_auth(client: TestClient, user: dict):
    session = make_session(client, user)
    r = client.post(
        "/api/tools/adjust_color/invoke",
        json={"session_id": session["id"], "params": {}},
    )
    assert r.status_code == 401


def test_add_image_layer_uses_ui_supplied_asset(client: TestClient, user: dict):
    """隐藏字段由界面传：手动调用能成功，模型侧却看不到这个参数。"""
    session = make_session(client, user)
    asset = upload_asset(client, user)

    r = invoke(
        client, user, "add_image_layer", session["id"], {"asset_id": asset["id"], "name": "新品图"}
    )
    assert r.status_code == 200, r.text
    layers = r.json()["session"]["doc"]["layers"]
    assert len(layers) == 2
    assert layers[-1]["name"] == "新品图"


def test_add_image_layer_rejects_foreign_asset(client: TestClient, user: dict):
    """不能把别人的素材 id 写进自己的文档 —— 拍平时会变成一张静默缺失的图层。"""
    other = client.post(
        "/api/auth/register",
        json={"email": f"test_{uuid.uuid4().hex[:12]}@example.com", "password": "Strong-Pass-123"},
    ).json()
    other_user = {"token": other["token"]["access_token"], "id": other["user"]["id"]}
    foreign_asset = upload_asset(client, other_user)

    session = make_session(client, user)
    r = invoke(
        client, user, "add_image_layer", session["id"], {"asset_id": foreign_asset["id"]}
    )
    assert r.status_code == 422
    assert "素材不存在" in r.json()["detail"]
