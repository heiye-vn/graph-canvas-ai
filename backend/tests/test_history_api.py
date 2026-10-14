"""快照式撤销的集成测试 —— M5 的三条 DoD。

这里刻意**全部走 HTTP**而不是直接调服务层：撤销栈最容易坏的地方是
「文档与历史不在同一个事务里」，而那种错只在一次完整请求里才看得出来
（单独测服务函数时两边都写成功，看不出谁先谁后）。
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


def layers_of(session: dict) -> list[dict]:
    return session["doc"]["layers"]


# ------------------------------------------------------------------ DoD ①：一路撤销回初始态


def test_undo_walks_all_the_way_back_to_the_initial_state(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]
    initial = layers_of(session)[0]["name"]

    for name in ("背景层", "中层", "顶层"):
        r = invoke(client, user, "rename_layer", sid, {"name": name})
        assert r.status_code == 200, r.text

    # 三次改名后停在最后一次
    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "顶层"

    history = client.get(f"/api/edit-sessions/{sid}/history", headers=auth(user)).json()
    assert history["seq"] == 3
    assert history["can_undo"] is True
    assert history["can_redo"] is False

    # 一路撤销，回到会话刚建好时的名字 —— 每一步都要真的生效，中途假成功是最大的坑
    expected = ["中层", "背景层", initial]
    for want in expected:
        r = client.post(f"/api/edit-sessions/{sid}/history/undo", headers=auth(user))
        assert r.status_code == 200, r.text
        after = layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())
        assert after[0]["name"] == want
        # 标签要能认出是哪一步：三条一模一样的「改名」等于没有标签
        assert "改名" in r.json()["label"]

    history = client.get(f"/api/edit-sessions/{sid}/history", headers=auth(user)).json()
    assert history["seq"] == 0
    assert history["can_undo"] is False
    assert history["can_redo"] is True


def test_redo_replays_forward(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    invoke(client, user, "rename_layer", sid, {"name": "A"})
    invoke(client, user, "rename_layer", sid, {"name": "B"})

    for _ in range(2):
        assert client.post(
            f"/api/edit-sessions/{sid}/history/undo", headers=auth(user)
        ).status_code == 200

    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "图像层"

    r = client.post(f"/api/edit-sessions/{sid}/history/redo", headers=auth(user))
    assert r.status_code == 200, r.text
    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "A"

    r = client.post(f"/api/edit-sessions/{sid}/history/redo", headers=auth(user))
    assert r.status_code == 200, r.text
    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "B"

    # 已在最新一步：再 redo 得到 409，而且**文档不能被破坏**
    r = client.post(f"/api/edit-sessions/{sid}/history/redo", headers=auth(user))
    assert r.status_code == 409
    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "B"


def test_undo_on_fresh_session_is_409_not_500(client: TestClient, user: dict):
    session = make_session(client, user)
    r = client.post(
        f"/api/edit-sessions/{session['id']}/history/undo", headers=auth(user)
    )
    assert r.status_code == 409


# ------------------------------------------- DoD ②：undo 后新操作要截断 redo 分支


def test_new_operation_after_undo_truncates_the_redo_branch(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    invoke(client, user, "rename_layer", sid, {"name": "第一版"})
    invoke(client, user, "rename_layer", sid, {"name": "第二版"})
    invoke(client, user, "rename_layer", sid, {"name": "第三版"})

    # 退两步，停在第一版
    for _ in range(2):
        assert client.post(
            f"/api/edit-sessions/{sid}/history/undo", headers=auth(user)
        ).status_code == 200

    history = client.get(f"/api/edit-sessions/{sid}/history", headers=auth(user)).json()
    assert history["seq"] == 1
    assert history["can_redo"] is True

    # 新开一条分支：原来那截 redo 分支必须消失
    invoke(client, user, "rename_layer", sid, {"name": "新分支"})

    history = client.get(f"/api/edit-sessions/{sid}/history", headers=auth(user)).json()
    assert history["seq"] == 2
    assert history["can_redo"] is False
    # 旧分支的记录没了：最后一条是被保留下来的第一次改名
    assert len(history["items"]) == 2
    assert "新分支" in history["items"][0]["label"]
    assert "第一版" in history["items"][1]["label"]

    assert client.post(
        f"/api/edit-sessions/{sid}/history/redo", headers=auth(user)
    ).status_code == 409

    # 分支截断后，撤销依然能回到最初
    for _ in range(2):
        assert client.post(
            f"/api/edit-sessions/{sid}/history/undo", headers=auth(user)
        ).status_code == 200
    assert layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0][
        "name"
    ] == "图像层"


# ------------------------------------------------------------------ 无变化的一步：记录但不挡路


def test_no_op_step_is_recorded_but_skipped_by_undo(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    invoke(client, user, "set_opacity", sid, {"opacity": 0.5})
    # 同一个值再设一次：文档没有任何字节会变
    invoke(client, user, "set_opacity", sid, {"opacity": 0.5})

    history = client.get(f"/api/edit-sessions/{sid}/history", headers=auth(user)).json()
    assert len(history["items"]) == 2, "画布没变也要留一条记录（用户在编辑记录里要找得到）"
    assert history["items"][0]["changed"] is False
    assert history["items"][1]["changed"] is True

    # 按一次撤销就该回到 100%，而不是「按了没反应」
    r = client.post(f"/api/edit-sessions/{sid}/history/undo", headers=auth(user))
    assert r.status_code == 200, r.text
    layer = layers_of(client.get(f"/api/edit-sessions/{sid}", headers=auth(user)).json())[0]
    assert layer["opacity"] == 1.0


def test_history_does_not_leak_document_snapshots(client: TestClient, user: dict):
    """历史列表不下发 before/after —— 十几条就能把响应撑到几百 KB。"""
    session = make_session(client, user)
    invoke(client, user, "rename_layer", session["id"], {"name": "X"})

    history = client.get(
        f"/api/edit-sessions/{session['id']}/history", headers=auth(user)
    ).json()
    for key in ("before", "after", "params"):
        assert key not in history["items"][0], f"{key} 不该出现在历史列表里"


# ------------------------------------------------------------------ 新增工具


def test_crop_layer_writes_crop_and_display_size(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    r = invoke(client, user, "crop_layer", sid, {"x": 1, "y": 2, "width": 4, "height": 3})
    assert r.status_code == 200, r.text

    layer = layers_of(r.json()["session"])[0]
    assert layer["crop"] == {"x": 1, "y": 2, "width": 4, "height": 3}
    # 显示尺寸同步：裁剪区按原大小放下，而不是被拉满原来的框
    assert layer["transform"]["width"] == 4.0
    assert layer["transform"]["height"] == 3.0


def test_reset_crop_restores_full_frame(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    invoke(client, user, "crop_layer", sid, {"width": 4, "height": 3})
    r = invoke(client, user, "reset_crop", sid, {})
    assert r.status_code == 200, r.text
    assert layers_of(r.json()["session"])[0]["crop"] is None


def test_flip_layer_toggles_both_axes(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]

    r = invoke(client, user, "flip_layer", sid, {"direction": "horizontal"})
    assert r.status_code == 200, r.text
    assert layers_of(r.json()["session"])[0]["transform"]["flip_x"] is True

    # 再翻一次应该翻回来 —— 「翻转」是幂等的反操作按钮，不是累加器
    r = invoke(client, user, "flip_layer", sid, {"direction": "horizontal"})
    assert layers_of(r.json()["session"])[0]["transform"]["flip_x"] is False

    r = invoke(client, user, "flip_layer", sid, {"direction": "vertical"})
    assert layers_of(r.json()["session"])[0]["transform"]["flip_y"] is True


def test_flip_layer_rejects_unknown_direction(client: TestClient, user: dict):
    session = make_session(client, user)
    r = invoke(client, user, "flip_layer", session["id"], {"direction": "斜着"})
    assert r.status_code == 422
    assert "参数不对" in r.json()["detail"]


# ------------------------------------------------------------------ 越权


def test_history_endpoints_respect_ownership(client: TestClient, user: dict):
    session = make_session(client, user)
    sid = session["id"]
    invoke(client, user, "rename_layer", sid, {"name": "别人的"})

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()["token"]["access_token"]
    headers = {"Authorization": f"Bearer {other}"}

    assert client.get(f"/api/edit-sessions/{sid}/history", headers=headers).status_code == 404
    assert (
        client.post(f"/api/edit-sessions/{sid}/history/undo", headers=headers).status_code
        == 404
    )
