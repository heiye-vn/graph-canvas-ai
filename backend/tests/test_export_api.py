"""导出物料接口：投放尺寸（letterbox）+ ZIP 打包。

两条不变量：
    1. letterbox 只补边、不裁切 —— 电商投放最怕导出的图被切掉一角
    2. 打包只允许本会话素材 —— 同一个用户也不该能跨会话把文件拖进 ZIP
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:12]}@example.com"


def make_png(width: int = 64, height: int = 48) -> bytes:
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


def export_sizes(client: TestClient, user: dict, session: dict, ratios=None) -> dict:
    r = client.post(
        f"/api/edit-sessions/{session['id']}/export-sizes",
        json={"ratios": ratios or ["1:1", "4:5", "9:16"]},
        headers=auth(user),
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_export_sizes_returns_delivery_assets(client: TestClient, user: dict):
    session = make_session(client, user)
    items = export_sizes(client, user, session)["items"]

    assert [(item["width"], item["height"]) for item in items] == [
        (1080, 1080),
        (1080, 1350),
        (1080, 1920),
    ]
    assert all(item["url"] for item in items)
    # 标成 export 才能在素材库里和作品分开（默认 Tab 不显示）
    assert all(item["kind"] == "export" for item in items)


def test_export_sizes_dedupes_ratios(client: TestClient, user: dict):
    session = make_session(client, user)
    items = export_sizes(client, user, session, ["1:1", "1:1", "4:5"])["items"]
    assert [(item["width"], item["height"]) for item in items] == [
        (1080, 1080),
        (1080, 1350),
    ]


def test_export_zip_contains_manifest_and_png(client: TestClient, user: dict):
    session = make_session(client, user)
    items = export_sizes(client, user, session)["items"]
    ids = ",".join(item["id"] for item in items)

    r = client.get(
        f"/api/edit-sessions/{session['id']}/export?asset_ids={ids}",
        headers=auth(user),
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"

    bundle = zipfile.ZipFile(io.BytesIO(r.content))
    names = bundle.namelist()
    assert "manifest.json" in names

    manifest = json.loads(bundle.read("manifest.json"))
    assert manifest["session_id"] == session["id"]
    assert len(manifest["items"]) == 3

    first = manifest["items"][0]
    assert first["file"] in names
    assert bundle.read(first["file"]).startswith(b"\x89PNG")


def test_export_zip_rejects_assets_from_another_session(
    client: TestClient, user: dict
):
    """同用户的另一个会话的素材也不能打包进来。"""
    session = make_session(client, user)
    other = make_session(client, user)
    foreign_id = other["assets"][0]["id"]

    r = client.get(
        f"/api/edit-sessions/{session['id']}/export?asset_ids={foreign_id}",
        headers=auth(user),
    )
    assert r.status_code == 400
