"""测试夹具安全回归；可用 --noconftest 独立执行，绝不连接基础设施。"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "isolated_test_conftest", Path(__file__).with_name("conftest.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_environment_is_overridden_before_app_import(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://unused/real_data")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("S3_BUCKET", "real-assets")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "not-a-real-test-key")
    monkeypatch.setenv("IMAGE_API_KEY", "not-a-real-test-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "not-a-real-test-key")
    module = _load_conftest()
    try:
        assert os.environ["DATABASE_URL"] == module._TEST_ENV["DATABASE_URL"]
        assert os.environ["REDIS_URL"] == module._TEST_ENV["REDIS_URL"]
        assert os.environ["IMAGE_PROVIDER"] == "mock"
        assert os.environ["S3_BUCKET"] == "retouch-test"
        from app.config import Settings

        assert Settings.model_config["env_file"] is None
        settings = Settings()
        assert not settings.dashscope_api_key
        assert not settings.image_api_key
        assert not settings.langfuse_secret_key
    finally:
        if hasattr(module, "pytest_unconfigure"):
            module.pytest_unconfigure(None)


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://unused/real_data",
    "postgresql+asyncpg://unused/postgres",
    "postgresql+asyncpg://unused/retouch_test?host=remote",
    "not-a-database-url",
])
def test_database_reset_rejects_unsafe_target(monkeypatch, url):
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    monkeypatch.setenv("TEST_ALLOW_DATABASE_RESET", "1")
    module = _load_conftest()
    engine = AsyncMock()
    monkeypatch.setattr(module, "create_async_engine", engine)
    try:
        with pytest.raises(pytest.UsageError):
            module._validate_test_services()
        engine.assert_not_called()
    finally:
        if hasattr(module, "pytest_unconfigure"):
            module.pytest_unconfigure(None)


@pytest.mark.parametrize("redis_url", [
    "redis://127.0.0.1:6379/0", "redis://127.0.0.1:6379/1?db=0",
])
def test_database_reset_rejects_unsafe_redis(monkeypatch, redis_url):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://unused/retouch_test")
    monkeypatch.setenv("TEST_ALLOW_DATABASE_RESET", "1")
    monkeypatch.setenv("TEST_REDIS_URL", redis_url)
    module = _load_conftest()
    try:
        with pytest.raises(pytest.UsageError):
            module._validate_test_services()
    finally:
        module.pytest_unconfigure(None)


def test_explicit_dedicated_services_are_accepted_without_connecting(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+asyncpg://unused/retouch_test")
    monkeypatch.setenv("TEST_ALLOW_DATABASE_RESET", "1")
    monkeypatch.setenv("TEST_REDIS_URL", "redis://127.0.0.1:6379/1")
    module = _load_conftest()
    engine = AsyncMock()
    monkeypatch.setattr(module, "create_async_engine", engine)
    try:
        module._validate_test_services()
        engine.assert_not_called()
    finally:
        module.pytest_unconfigure(None)


def test_database_reset_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("TEST_ALLOW_DATABASE_RESET", raising=False)
    module = _load_conftest()
    try:
        with pytest.raises(pytest.UsageError):
            module._validate_test_services()
    finally:
        if hasattr(module, "pytest_unconfigure"):
            module.pytest_unconfigure(None)
