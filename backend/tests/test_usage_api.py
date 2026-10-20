"""使用概览接口（用户视角）。

只钉两件事：
    1. 空数据时结构完整、daily 按天补齐（图表要靠它画出「那天是 0」）
    2. days 参数越界要 422，不能让空区间一路查到全表
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


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


def test_usage_summary_empty(client: TestClient, user: dict):
    r = client.get("/api/usage/summary?days=7", headers=auth(user))
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["days"] == 7
    assert body["tasks"] == {"total": 0, "succeeded": 0, "failed": 0, "cancelled": 0}
    assert body["chats"]["total"] == 0
    assert body["avg_seconds"] == 0.0
    assert body["images"] == 0

    # 7 天必须一天不少，否则图表上会缺柱
    assert len(body["daily"]) == 7
    assert all(item["succeeded"] == 0 and item["failed"] == 0 for item in body["daily"])
    assert body["failures"] == []

    # token 只统计真实返回的 usage：空态必须是 0，且 by_day 同样按天补齐
    assert body["tokens"]["total"] == 0
    assert body["tokens"]["calls"] == 0
    assert body["tokens"]["missing_calls"] == 0
    assert len(body["tokens"]["by_day"]) == 7


def test_usage_summary_rejects_bad_days(client: TestClient, user: dict):
    assert client.get("/api/usage/summary?days=0", headers=auth(user)).status_code == 422
    assert client.get("/api/usage/summary?days=999", headers=auth(user)).status_code == 422


def test_usage_summary_requires_login(client: TestClient):
    assert client.get("/api/usage/summary").status_code == 401
