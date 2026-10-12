"""Provider 工厂。

用 lru_cache 做进程级单例（连接池/客户端不该每次请求重建），
同时暴露 clear() 供测试切换实现——缓存不清理是测试污染的经典来源。
"""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.providers.base import ImageProvider
from app.providers.mock import MockProvider


@lru_cache(maxsize=1)
def get_image_provider() -> ImageProvider:
    settings = get_settings()
    if settings.image_provider == "mock":
        return MockProvider()
    raise RuntimeError(
        f"尚未接入 provider={settings.image_provider}。"
        "当前阶段请保持 IMAGE_PROVIDER=mock，后续接入真实模型时在此补实现。"
    )


def clear_provider_cache() -> None:
    get_image_provider.cache_clear()
