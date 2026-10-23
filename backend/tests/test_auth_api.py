"""鉴权接口集成测试（需要 Postgres）。"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # 走完整 lifespan：建测试桶、连测试库
    with TestClient(app) as c:
        yield c


def unique_email(prefix: str = "test_") -> str:  # 统一前缀，便于定向清理
    return f"{prefix}{uuid.uuid4().hex[:12]}@example.com"


def test_register_then_login_then_me(client: TestClient):
    email = unique_email()
    payload = {"email": email, "password": "Strong-Pass-123", "display_name": "测试用户"}

    r = client.post("/api/auth/register", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["token"]["access_token"]
    assert body["user"]["email"] == email

    # 登录拿新 token
    r = client.post("/api/auth/login", json={"email": email, "password": "Strong-Pass-123"})
    assert r.status_code == 200, r.text
    token = r.json()["token"]["access_token"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == email


def test_register_duplicate_email_returns_409(client: TestClient):
    email = unique_email()
    payload = {"email": email, "password": "Strong-Pass-123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_login_wrong_password_returns_401(client: TestClient):
    email = unique_email()
    client.post("/api/auth/register", json={"email": email, "password": "Strong-Pass-123"})
    r = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json()["detail"] == "邮箱或密码错误"


def test_login_unknown_email_returns_same_message(client: TestClient):
    """未知邮箱与错误密码返回同一句提示，避免账号枚举。"""
    r = client.post(
        "/api/auth/login",
        json={"email": unique_email("test_unknown_"), "password": "whatever-123"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "邮箱或密码错误"


def test_login_unknown_email_still_verifies_password(client: TestClient, monkeypatch):
    """未知邮箱也要跑一次 bcrypt，否则响应时间差就能枚举账号。"""
    from app.routers import auth as auth_router

    hashes: list[str] = []
    real = auth_router.verify_password

    def spy(password: str, password_hash: str) -> bool:
        hashes.append(password_hash)
        return real(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", spy)

    r = client.post(
        "/api/auth/login",
        json={"email": unique_email("test_unknown_"), "password": "whatever-123"},
    )
    assert r.status_code == 401
    assert len(hashes) == 1
    assert hashes[0].startswith("$2"), "必须用真实 bcrypt 哈希陪跑，不能短路"


def test_weak_password_rejected_by_schema(client: TestClient):
    r = client.post("/api/auth/register", json={"email": unique_email(), "password": "123"})
    assert r.status_code == 422


def test_invalid_email_rejected_by_schema(client: TestClient):
    r = client.post(
        "/api/auth/register", json={"email": "not-an-email", "password": "Strong-Pass-123"}
    )
    assert r.status_code == 422


def test_me_without_token_returns_401(client: TestClient):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_garbage_token_returns_401(client: TestClient):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401
    assert r.json()["detail"] == "令牌无效或已过期"
