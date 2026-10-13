"""编辑会话 API 集成测试（需要 Postgres + 对象存储）。

这组用例回答四个问题：
    1. 用素材建会话时，初始文档是不是**符合预期**（层级顺序、可见性、画布尺寸）
    2. 别人的会话 / 别人的素材是不是 404
    3. 文档进 JSONB 再取出来是不是**等价**（这是「刷新后能恢复」的前提）
    4. 坏文档能不能被写进库
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


def upload_asset(client: TestClient, user: dict, width: int = 8, height: int = 6) -> dict:
    data = make_png(width, height)
    ticket = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "sample.png", "mime": "image/png", "size": len(data)},
        headers=auth(user),
    ).json()

    r = client.post(
        ticket["upload_url"],
        data={"key": ticket["key"]},
        files={"file": ("sample.png", data, "image/png")},
        headers=auth(user),
    )
    assert r.status_code == 204, r.text

    return client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
        headers=auth(user),
    ).json()


def create_session(client: TestClient, user: dict, asset_ids: list[str], **extra) -> dict:
    payload = {"asset_ids": asset_ids}
    payload.update(extra)
    r = client.post("/api/edit-sessions", json=payload, headers=auth(user))
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- 建会话


def test_create_builds_doc_from_first_asset(client: TestClient, user: dict):
    asset = upload_asset(client, user, width=32, height=24)

    data = create_session(client, user, [asset["id"]])

    assert data["doc"]["canvas"] == {"width": 32, "height": 24, "background": "#ffffff"}
    assert len(data["doc"]["layers"]) == 1
    layer = data["doc"]["layers"][0]
    assert layer["type"] == "image"
    assert layer["source"]["asset_id"] == asset["id"]
    assert layer["visible"] is True
    assert layer["name"] == "图像层"
    # 第一个图层即当前选中项 —— 前端不用再自己猜
    assert data["doc"]["active_layer_id"] == layer["id"]


def test_create_with_multiple_assets_only_shows_the_first(client: TestClient, user: dict):
    """候选图不能全叠上去：那样画布上只看得见最上面那张。"""
    assets = [upload_asset(client, user), upload_asset(client, user, width=16, height=16)]

    data = create_session(client, user, [a["id"] for a in assets])

    layers = data["doc"]["layers"]
    assert [layer["name"] for layer in layers] == ["候选图 1", "候选图 2"]
    assert [layer["visible"] for layer in layers] == [True, False]
    assert data["doc"]["active_layer_id"] == layers[0]["id"]
    assert len(data["assets"]) == 2


def test_create_keeps_asset_order(client: TestClient, user: dict):
    first = upload_asset(client, user, width=8, height=6)
    second = upload_asset(client, user, width=10, height=10)

    data = create_session(client, user, [second["id"], first["id"]])

    assert [a["id"] for a in data["assets"]] == [second["id"], first["id"]]


def test_create_without_assets_is_422(client: TestClient, user: dict):
    r = client.post("/api/edit-sessions", json={"asset_ids": []}, headers=auth(user))
    assert r.status_code == 422


def test_create_with_unknown_asset_is_404(client: TestClient, user: dict):
    r = client.post(
        "/api/edit-sessions",
        json={"asset_ids": [str(uuid.uuid4())]},
        headers=auth(user),
    )
    assert r.status_code == 404


def test_create_with_other_users_asset_is_404(client: TestClient, user: dict):
    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    other_auth = {"Authorization": f"Bearer {other['token']['access_token']}"}
    asset = upload_asset(client, {"token": other["token"]["access_token"]})

    r = client.post("/api/edit-sessions", json={"asset_ids": [asset["id"]]}, headers=other_auth)
    assert r.status_code == 201

    mine = client.post(
        "/api/edit-sessions", json={"asset_ids": [asset["id"]]}, headers=auth(user)
    )
    assert mine.status_code == 404


def test_create_requires_auth(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    r = client.post("/api/edit-sessions", json={"asset_ids": [asset["id"]]})
    assert r.status_code == 401


# ---------------------------------------------------------------- 读取与归属


def test_get_returns_full_state_for_refresh_recovery(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]], title="主图改稿")

    r = client.get(f"/api/edit-sessions/{created['id']}", headers=auth(user))
    assert r.status_code == 200
    data = r.json()

    assert data["title"] == "主图改稿"
    assert data["doc"] == created["doc"]
    assert len(data["assets"]) == 1
    assert data["assets"][0]["url"]  # 预签名 URL 必须存在，否则前端取不到图


def test_list_only_returns_own_sessions(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    create_session(client, user, [asset["id"]], title="我的会话")

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    other_auth = {"Authorization": f"Bearer {other['token']['access_token']}"}

    own = client.get("/api/edit-sessions", headers=auth(user)).json()
    theirs = client.get("/api/edit-sessions", headers=other_auth).json()

    assert [item["title"] for item in own] == ["我的会话"]
    assert theirs == []


def test_summary_counts_layers_and_assets(client: TestClient, user: dict):
    assets = [upload_asset(client, user), upload_asset(client, user)]
    create_session(client, user, [a["id"] for a in assets])

    summary = client.get("/api/edit-sessions", headers=auth(user)).json()[0]
    assert summary["layer_count"] == 2
    assert summary["asset_count"] == 2


def test_get_other_users_session_is_404(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()

    r = client.get(
        f"/api/edit-sessions/{created['id']}",
        headers={"Authorization": f"Bearer {other['token']['access_token']}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- 追加素材


def test_add_assets_appends_layer(client: TestClient, user: dict):
    asset_a = upload_asset(client, user)
    asset_b = upload_asset(client, user, width=20, height=20)
    created = create_session(client, user, [asset_a["id"]])

    r = client.post(
        f"/api/edit-sessions/{created['id']}/assets",
        json={"asset_ids": [asset_b["id"]]},
        headers=auth(user),
    )
    assert r.status_code == 200
    data = r.json()

    assert len(data["doc"]["layers"]) == 2
    assert data["doc"]["layers"][1]["source"]["asset_id"] == asset_b["id"]
    assert len(data["assets"]) == 2


def test_add_same_asset_twice_is_idempotent(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    for _ in range(2):
        r = client.post(
            f"/api/edit-sessions/{created['id']}/assets",
            json={"asset_ids": [asset["id"]]},
            headers=auth(user),
        )
        assert r.status_code == 200

    data = r.json()
    assert len(data["doc"]["layers"]) == 1  # 同一张图叠两遍毫无意义
    assert len(data["assets"]) == 1


def test_add_assets_to_other_users_session_is_404(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    other_asset = upload_asset(client, {"token": other["token"]["access_token"]})

    r = client.post(
        f"/api/edit-sessions/{created['id']}/assets",
        json={"asset_ids": [other_asset["id"]]},
        headers={"Authorization": f"Bearer {other['token']['access_token']}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- 文档写入


def test_replace_doc_persists_changes(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    doc = created["doc"]
    doc["active_layer_id"] = None

    r = client.put(
        f"/api/edit-sessions/{created['id']}/doc", json={"doc": doc}, headers=auth(user)
    )
    assert r.status_code == 200
    assert r.json()["doc"]["active_layer_id"] is None

    again = client.get(f"/api/edit-sessions/{created['id']}", headers=auth(user)).json()
    assert again["doc"]["active_layer_id"] is None


def test_replace_doc_rejects_broken_document(client: TestClient, user: dict):
    """坏文档必须在 HTTP 边界被挡住 —— 进库之后没有任何地方再校验它。"""
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    doc = created["doc"]
    doc["layers"].append(doc["layers"][0])  # 重复 id

    r = client.put(
        f"/api/edit-sessions/{created['id']}/doc", json={"doc": doc}, headers=auth(user)
    )
    assert r.status_code == 422

    unchanged = client.get(f"/api/edit-sessions/{created['id']}", headers=auth(user)).json()
    assert len(unchanged["doc"]["layers"]) == 1


def test_replace_doc_rejects_image_layer_without_source(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    doc = created["doc"]
    doc["layers"][0]["source"] = None

    r = client.put(
        f"/api/edit-sessions/{created['id']}/doc", json={"doc": doc}, headers=auth(user)
    )
    assert r.status_code == 422


def test_replace_doc_on_missing_session_is_404(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    r = client.put(
        f"/api/edit-sessions/{uuid.uuid4()}/doc",
        json={"doc": created["doc"]},
        headers=auth(user),
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- 改标题与删除


def test_rename_and_delete(client: TestClient, user: dict):
    asset = upload_asset(client, user)
    created = create_session(client, user, [asset["id"]])

    renamed = client.patch(
        f"/api/edit-sessions/{created['id']}",
        json={"title": "618 主图"},
        headers=auth(user),
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "618 主图"

    deleted = client.delete(f"/api/edit-sessions/{created['id']}", headers=auth(user))
    assert deleted.status_code == 204

    assert client.get(f"/api/edit-sessions/{created['id']}", headers=auth(user)).status_code == 404
