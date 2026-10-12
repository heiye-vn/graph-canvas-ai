"""配置自检相关的测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings

# 必填项的最小可用组合（禁用 env_file，避免被本地 .env 影响）
_REQUIRED = {
    "database_url": "postgresql+asyncpg://user:pwd@127.0.0.1:5432/db",
    "redis_url": "redis://127.0.0.1:6379/0",
    "s3_endpoint": "http://127.0.0.1:9000",
    "s3_access_key": "key",
    "s3_secret_key": "secret",
    "jwt_secret": "x" * 40,
}


def _build(**overrides):
    return Settings(_env_file=None, **{**_REQUIRED, **overrides})  # type: ignore[call-arg]


def test_required_fields_present_ok():
    # 显式传值，避免被 conftest 注入的环境变量影响（env_file=None 不拦截环境变量）
    s = _build(s3_bucket="bucket-a")
    assert s.s3_bucket == "bucket-a"
    assert not s.is_production


def test_missing_required_field_raises(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    data = dict(_REQUIRED)
    data.pop("jwt_secret")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **data)  # type: ignore[call-arg]


def test_production_rejects_short_jwt_secret():
    """HS256 的强度等于密钥字节数，生产环境必须挡住弱密钥。"""
    with pytest.raises(ValidationError, match="至少"):
        _build(app_env="production", jwt_secret="short-dev-secret")


def test_development_allows_short_jwt_secret():
    """开发环境不拦，否则本地跑通流程会被无谓地卡住。"""
    assert _build(app_env="development", jwt_secret="dev").jwt_secret == "dev"


def test_require_dashscope_key_is_lazy():
    """mock 模式下不该被迫填 API Key；真正调用时才校验。"""
    s = _build(dashscope_api_key=None, image_provider="mock")
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        s.require_dashscope_key()
    assert _build(dashscope_api_key="sk-x").require_dashscope_key() == "sk-x"


def test_preflight_lists_missing_vars(monkeypatch):
    """启动自检失败时必须列出缺哪个变量——一句「缺配置」等于让人盲猜。"""
    from app import config

    # conftest 会注入一套测试环境变量，_env_file=None 挡不住它们，必须显式清掉
    for name in (
        "JWT_SECRET",
        "DATABASE_URL",
        "REDIS_URL",
        "S3_ENDPOINT",
        "S3_ACCESS_KEY",
        "S3_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    try:
        config.Settings(_env_file=None)  # 什么都不传，必填项全缺
    except ValidationError as exc:
        real_error = exc
    else:  # pragma: no cover - 走到这里说明必填约束被改坏了
        pytest.fail("Settings 竟然在缺配置时创建成功")

    monkeypatch.setattr(config, "get_settings", lambda: (_ for _ in ()).throw(real_error))

    # 缺失清单在 SystemExit 的异常消息里（用的是 SystemExit(msg)，不写 stdout）
    with pytest.raises(SystemExit) as excinfo:
        config.preflight_settings()

    message = str(excinfo.value)
    assert "jwt_secret" in message
    assert "缺失" in message


def test_upload_mode_defaults_to_backend():
    assert _build().asset_upload_mode == "backend"
    assert _build(asset_upload_mode="presigned").asset_upload_mode == "presigned"
