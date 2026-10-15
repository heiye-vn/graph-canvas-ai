"""选区 API 集成测试（M6）。

四条 DoD 里能落在集成层的部分：
    · 点选/笔刷能生成遮罩并即时下发（overlay 素材带预签名 URL）
    · revision 不一致 → 409（画布已变，选区请求是旧的）
    · 工具侧引用的选区由服务端按会话回填，模型/界面都不用手传 UUID
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


def make_png(width: int = 64, height: int = 64) -> bytes:
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


def make_session(client: TestClient, user: dict) -> dict:
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
    asset = client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
        headers=auth(user),
    ).json()
    r = client.post("/api/edit-sessions", json={"asset_ids": [asset["id"]]}, headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


def test_brush_selection_roundtrip(client: TestClient, user: dict):
    """笔刷选区：生成 → 查回 → 清除，全程 revision 串起来。"""
    session = make_session(client, user)
    revision = session["revision"]

    r = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={"revision": revision, "strokes": [[{"x": 0.2, "y": 0.2}, {"x": 0.4, "y": 0.4}]]},
        headers=auth(user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == revision
    assert body["mask"]["url"]
    assert body["mask"]["kind"] == "mask"

    # 查回：同一 revision 下能恢复现场
    got = client.get(f"/api/edit-sessions/{session['id']}/selection", headers=auth(user))
    assert got.status_code == 200
    assert got.json() is not None

    # 遮罩图下载回来是合法 PNG，且尺寸与画布一致（绝不拉伸）
    import httpx

    mask_bytes = httpx.get(body["mask"]["url"]).content
    assert Image.open(io.BytesIO(mask_bytes)).size == (64, 64)

    # 清除后查不到
    cleared = client.delete(f"/api/edit-sessions/{session['id']}/selection", headers=auth(user))
    assert cleared.status_code == 204
    after = client.get(f"/api/edit-sessions/{session['id']}/selection", headers=auth(user))
    assert after.json() is None


def test_point_selection_accumulates_markers(client: TestClient, user: dict):
    session = make_session(client, user)
    revision = session["revision"]

    first = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={"revision": revision, "points": [{"x": 0.5, "y": 0.5}]},
        headers=auth(user),
    )
    assert first.status_code == 200
    assert len(first.json()["markers"]) == 1

    second = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={"revision": revision, "points": [{"x": 0.6, "y": 0.6}], "append": True},
        headers=auth(user),
    )
    assert second.status_code == 200
    assert len(second.json()["markers"]) == 2  # 追加点，不重置


def test_selection_rejects_stale_revision(client: TestClient, user: dict):
    session = make_session(client, user)
    stale = session["revision"] + 999

    r = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={"revision": stale, "points": [{"x": 0.5, "y": 0.5}]},
        headers=auth(user),
    )
    assert r.status_code == 409


def test_selection_422_without_points_or_strokes(client: TestClient, user: dict):
    session = make_session(client, user)
    r = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={"revision": session["revision"]},
        headers=auth(user),
    )
    assert r.status_code == 422


def test_region_tools_registered_with_hidden_params(client: TestClient):
    """局部编辑工具进注册表：标签/表单元数据下发，隐藏字段不给模型看。"""
    items = client.get("/api/tools").json()["items"]
    by_name = {item["name"]: item for item in items}
    assert "erase_region" in by_name
    assert "replace_region" in by_name

    for name in ("erase_region", "replace_region"):
        hidden = [p["name"] for p in by_name[name]["params"] if p["agent_hidden"]]
        assert set(hidden) == {"mask_asset_id", "revision"}


def test_erase_region_without_selection_fails_clean(client: TestClient, user: dict):
    """没有选区时调用局部消除：422 + 一句人话，不 500。"""
    session = make_session(client, user)
    r = client.post(
        "/api/tools/erase_region/invoke",
        json={"session_id": session["id"], "params": {}},
        headers=auth(user),
    )
    assert r.status_code == 422
    assert "点选" in r.json()["detail"]


def test_erase_region_submits_with_existing_selection(client: TestClient, user: dict):
    """有选区时调用局部消除：提交成功并返回 run_id（回归：revision 权威在服务端）。

    第一版的 bug：提交路径拿请求参数里的 revision 比对选区 —— 界面根本
    不传这个隐藏字段，导致「明明有选区却提示先选区」。
    """
    session = make_session(client, user)
    made = client.post(
        f"/api/edit-sessions/{session['id']}/selection",
        json={
            "revision": session["revision"],
            "strokes": [[{"x": 0.3, "y": 0.3}, {"x": 0.5, "y": 0.5}]],
        },
        headers=auth(user),
    )
    assert made.status_code == 200

    r = client.post(
        "/api/tools/erase_region/invoke",
        json={"session_id": session["id"], "params": {}},
        headers=auth(user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run_id"], "排队型工具必须返回 run_id"
    assert "已提交" in body["message"]
    # 会话 revision 未被排队型工具改变（文档没动）
    assert body["session"]["revision"] == session["revision"]
