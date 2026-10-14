"""Provider 工厂。

用 lru_cache 做进程级单例（连接池/客户端不该每次请求重建），
同时暴露 clear() 供测试切换实现——缓存不清理是测试污染的经典来源。

红线不变：未接入的实现显式报错，绝不静默回退 mock——
「以为在调真模型、实际一直出占位图」是比崩溃恶劣得多的故障。
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.providers.base import ImageProvider
from app.providers.dashscope import DashscopeProvider
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIImageProvider


@lru_cache(maxsize=1)
def get_image_provider() -> ImageProvider:
    settings = get_settings()
    if settings.image_provider == "mock":
        return MockProvider()
    if settings.image_provider == "dashscope":
        # 缺 Key 在这里立刻失败（worker 启动即预热，等于启动自检），
        # 而不是拖到第一个任务才炸
        return DashscopeProvider(
            api_key=settings.require_dashscope_key(),
            text_model=settings.text_to_image_model,
            edit_model=settings.image_edit_model,
        )
    if settings.image_provider == "openai":
        return OpenAIImageProvider(
            api_key=settings.require_image_api_key(),
            text_model=settings.text_to_image_model,
            edit_model=settings.image_edit_model,
            base_url=settings.image_base_url or "https://api.monkeycoding.club/v1",
        )
    raise RuntimeError(
        f"尚未接入 provider={settings.image_provider}。"
        "可选值见 .env.example（当前支持 mock / dashscope / openai）。"
    )


def clear_provider_cache() -> None:
    get_image_provider.cache_clear()
