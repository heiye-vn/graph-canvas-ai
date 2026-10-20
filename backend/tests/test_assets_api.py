"""素材上传集成测试（需要 Postgres + 对象存储）。

按 UploadTicket 契约走完整链路：ticket → 上传 → confirm → 读取 → 删除。
这套用例在 backend / presigned 两种模式下都能跑通——切模式只改环境变量。
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


def upload_one(client: TestClient, user: dict, data: bytes, mime: str) -> dict:
    """按前端同款流程：拿 ticket → 按 method 上传 → confirm。"""
    ticket = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "sample.png", "mime": mime, "size": len(data)},
        headers=auth(user),
    ).json()
    assert ticket["method"] == "POST"

    r = client.post(
        ticket["upload_url"],
        data={"key": ticket["key"]},
        files={"file": ("sample.png", data, mime)},
        headers=auth(user),
    )
    assert r.status_code == 204, r.text

    return client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": mime, "size": len(data)},
        headers=auth(user),
    )


def test_upload_full_flow(client: TestClient, user: dict):
    data = make_png(20, 10)

    r = upload_one(client, user, data, "image/png")
    assert r.status_code == 200, r.text
    asset = r.json()
    assert asset["width"] == 20
    assert asset["height"] == 10
    assert asset["mime"] == "image/png"
    assert asset["url"]  # 预签名 URL，桶私有

    listed = client.get("/api/assets", headers=auth(user)).json()
    assert any(a["id"] == asset["id"] for a in listed["items"])

    got = client.get(f"/api/assets/{asset['id']}", headers=auth(user))
    assert got.status_code == 200
    assert got.json()["id"] == asset["id"]

    assert client.delete(f"/api/assets/{asset['id']}", headers=auth(user)).status_code == 204
    assert client.get(f"/api/assets/{asset['id']}", headers=auth(user)).status_code == 404


def test_confirm_is_idempotent(client: TestClient, user: dict):
    """网络重试会重复 confirm，必须幂等——否则同一个 key 会落两条记录。"""
    data = make_png()
    ticket = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "a.png", "mime": "image/png", "size": len(data)},
        headers=auth(user),
    ).json()
    client.post(
        "/api/assets/upload-direct",
        data={"key": ticket["key"]},
        files={"file": ("a.png", data, "image/png")},
        headers=auth(user),
    )

    first = client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
        headers=auth(user),
    )
    second = client.post(
        "/api/assets/confirm",
        json={"key": ticket["key"], "mime": "image/png", "size": len(data)},
        headers=auth(user),
    )
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_non_image_content_is_rejected(client: TestClient, user: dict):
    """伪装成 png 的文本必须被拦——按文件内容判断，不信 mimetype。"""
    data = b"<html><script>alert(1)</script></html>" * 10
    r = upload_one(client, user, data, "image/png")
    assert r.status_code == 400
    assert "不是有效的图片文件" in r.json()["detail"]


def test_ticket_rejects_unsupported_mime(client: TestClient, user: dict):
    r = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "a.gif", "mime": "image/gif", "size": 1024},
        headers=auth(user),
    )
    assert r.status_code == 400


def test_ticket_rejects_oversized(client: TestClient, user: dict):
    r = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "a.png", "mime": "image/png", "size": 999 * 1024 * 1024},
        headers=auth(user),
    )
    assert r.status_code == 400
    assert "上限" in r.json()["detail"]


def test_upload_rejects_body_larger_than_declared(client: TestClient, user: dict):
    """声明 1MB 却真传 21MB —— 不能因为 size 是「声明值」就把整个 body 读进内存。"""
    small = make_png()
    ticket = client.post(
        "/api/assets/upload-ticket",
        json={"filename": "small.png", "mime": "image/png", "size": len(small)},
        headers=auth(user),
    ).json()

    oversized = b"\x00" * (21 * 1024 * 1024)
    r = client.post(
        ticket["upload_url"],
        data={"key": ticket["key"]},
        files={"file": ("big.png", oversized, "image/png")},
        headers=auth(user),
    )
    assert r.status_code == 413
    assert "上限" in r.json()["detail"]


def test_confirm_rejects_foreign_key(client: TestClient, user: dict):
    r = client.post(
        "/api/assets/confirm",
        json={
            "key": f"assets/{uuid.uuid4()}/someone-else.png",
            "mime": "image/png",
            "size": 10,
        },
        headers=auth(user),
    )
    assert r.status_code == 403


def test_cross_user_access_is_404(client: TestClient):
    """别人的素材对我不存在——返回 404 而不是 403，不泄露资源是否存在。"""
    owner = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    owner_headers = {"Authorization": f"Bearer {owner['token']['access_token']}"}

    owner_user = {"token": owner["token"]["access_token"]}
    data = make_png()
    asset = upload_one(client, owner_user, data, "image/png").json()

    other = client.post(
        "/api/auth/register",
        json={"email": unique_email(), "password": "Strong-Pass-123"},
    ).json()
    other_headers = {"Authorization": f"Bearer {other['token']['access_token']}"}

    assert client.get(f"/api/assets/{asset['id']}", headers=other_headers).status_code == 404
    assert client.delete(f"/api/assets/{asset['id']}", headers=other_headers).status_code == 404
    # 删除后原主人仍能取到
    assert client.get(f"/api/assets/{asset['id']}", headers=owner_headers).status_code == 200


def test_assets_require_auth(client: TestClient):
    assert client.get("/api/assets").status_code == 401
    assert client.post("/api/assets/upload-ticket", json={}).status_code == 401


def test_thumb_endpoint_serves_small_image(client: TestClient, user: dict):
    """缩略图链路：AssetOut 带 thumb_url → 首次请求生成 480px 小图落桶 → 307 到预签名地址。"""
    import httpx

    data = make_png(1000, 800)
    asset = upload_one(client, user, data, "image/png").json()
    assert asset["thumb_url"].endswith(f"/assets/{asset['id']}/thumb")

    redirect = client.get(
        f"/api/assets/{asset['id']}/thumb", headers=auth(user), follow_redirects=False
    )
    assert redirect.status_code == 307
    location = redirect.headers["location"]
    assert ".thumb.jpg" in location

    # 重定向目标是对象存储的真实地址，必须用真实 HTTP 客户端取：
    # TestClient 的 follow_redirects 会把跨源 307 打回 ASGI 应用（共享 transport），
    # 应用里没有这条路由 → 404，那是测试假象不是功能缺陷。
    r = httpx.get(location, timeout=10, trust_env=False)
    assert r.status_code == 200, r.text
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "JPEG"
    assert max(img.size) <= 480  # 长边压到 480 以内

    # 写穿缓存：之后的请求直接命中已有小图，仍然 307
    again = client.get(f"/api/assets/{asset['id']}/thumb", headers=auth(user), follow_redirects=False)
    assert again.status_code == 307
