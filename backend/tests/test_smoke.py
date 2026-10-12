"""冒烟测试：不需要任何外部依赖即可运行。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app


def test_health_endpoint():
    # 刻意不用 context manager：那会触发 lifespan 去连对象存储，冒烟测试不该依赖外部服务
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_settings_require_secret(monkeypatch):
    """缺必填配置必须抛错，绝不能静默使用不安全默认值。"""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
