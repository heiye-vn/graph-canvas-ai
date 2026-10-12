"""图像 Provider 契约测试。

Provider 是全链路唯一的外部依赖点。这里把三件事钉死：
    1. 返回**图片字节**而不是 URL（URL 有有效期，落库即烂数据）
    2. 同一 prompt 出同一张图（回归比对的前提）
    3. 未接入的实现**显式报错**，绝不静默回退到 mock

换真实模型时只要这组用例还绿，上层一行都不用改。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.config import get_settings
from app.providers import clear_provider_cache, get_image_provider
from app.providers.base import ImageProvider
from app.providers.mock import MockProvider


@pytest.fixture(autouse=True)
def _isolated_provider_cache():
    """lru_cache 是进程级的，不清理就会把上一个用例的 provider 带进下一个。"""
    clear_provider_cache()
    yield
    clear_provider_cache()


def test_mock_provider_satisfies_protocol():
    """Protocol 是结构化子类型：不显式继承也能通过 isinstance。"""
    assert isinstance(MockProvider(), ImageProvider)


async def test_text_to_image_returns_png_bytes():
    images = await MockProvider().text_to_image("一只橘猫坐在窗台", size="256x128", n=2)
    assert len(images) == 2
    for data in images:
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        with Image.open(io.BytesIO(data)) as img:
            assert img.size == (256, 128)


async def test_output_is_deterministic_for_same_prompt():
    a = await MockProvider().text_to_image("red bottle", size="64x64")
    b = await MockProvider().text_to_image("red bottle", size="64x64")
    c = await MockProvider().text_to_image("blue bottle", size="64x64")
    assert a[0] == b[0]
    assert a[0] != c[0]


async def test_illegal_size_falls_back_to_default():
    images = await MockProvider().text_to_image("x", size="not-a-size")
    with Image.open(io.BytesIO(images[0])) as img:
        assert img.size == (1024, 1024)


async def test_edit_image_is_passthrough_for_now():
    """M6 接入真实局部重绘前，先保证调用链不炸。"""
    data = b"\x89PNG\r\n\x1a\nfake"
    assert await MockProvider().edit_image(data, "把背景换成沙滩") == [data]


def test_factory_returns_process_level_singleton():
    assert get_image_provider().name == "mock"
    assert get_image_provider() is get_image_provider()


def test_factory_fails_fast_for_unimplemented_provider(monkeypatch):
    """未接入的实现必须显式报错。

    静默回退 mock 是最危险的一种兜底：线上会「以为在调真模型」，
    实际一直在出占位图，且没有任何报错能把这件事暴露出来。
    """
    monkeypatch.setattr(get_settings(), "image_provider", "dashscope")
    clear_provider_cache()
    with pytest.raises(RuntimeError, match="尚未接入"):
        get_image_provider()
