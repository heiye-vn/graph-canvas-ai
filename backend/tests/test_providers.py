"""图像 Provider 契约测试。

Provider 是全链路唯一的外部依赖点。这里把三件事钉死：
    1. 返回**图片字节**而不是 URL（URL 有有效期，落库即烂数据）
    2. 同一 prompt 出同一张图（回归比对的前提）
    3. 未接入的实现**显式报错**，绝不静默回退到 mock

换真实模型时只要这组用例还绿，上层一行都不用改。
DashScope 的用例用 httpx.MockTransport 把 2026-10 核对过的接口契约
（异步头 / 星号 size / Base64 参考图 / choices 结果路径）钉进测试，
防止后人凭记忆把协议改漂。
"""

from __future__ import annotations

import base64
import io
import json

import httpx
import pytest
from PIL import Image

from app.config import get_settings
from app.providers import clear_provider_cache, get_image_provider
from app.providers.base import ImageProvider
from app.providers.dashscope import (
    CREATE_PATH,
    TASK_PATH,
    DashscopeProvider,
    ProviderError,
)
from app.providers.mock import MockProvider
from app.providers.openai import OpenAIImageProvider


@pytest.fixture(autouse=True)
def _isolated_provider_cache():
    """lru_cache 是进程级的，不清理就会把上一个用例的 provider 带进下一个。"""
    clear_provider_cache()
    yield
    clear_provider_cache()


# ------------------------------------------------------------------ mock


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


# ------------------------------------------------------------------ 工厂


def test_factory_returns_process_level_singleton():
    assert get_image_provider().name == "mock"
    assert get_image_provider() is get_image_provider()


def test_factory_returns_dashscope_provider(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test")
    clear_provider_cache()
    provider = get_image_provider()
    assert provider.name == "dashscope"
    assert isinstance(provider, DashscopeProvider)


def test_factory_requires_api_key_for_dashscope(monkeypatch):
    """选了真 provider 却没配 Key：建实例时立刻失败，不拖到第一个任务。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "image_provider", "dashscope")
    monkeypatch.setattr(settings, "dashscope_api_key", None)
    clear_provider_cache()
    with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
        get_image_provider()


def test_factory_returns_openai_provider(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "image_provider", "openai")
    monkeypatch.setattr(settings, "image_api_key", "sk-test-relay")
    clear_provider_cache()
    provider = get_image_provider()
    assert provider.name == "openai"
    assert isinstance(provider, OpenAIImageProvider)


def test_factory_requires_api_key_for_openai(monkeypatch):
    """选了 openai provider 却没配 Key：建实例时立刻失败。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "image_provider", "openai")
    monkeypatch.setattr(settings, "image_api_key", None)
    monkeypatch.setattr(settings, "dashscope_api_key", None)
    clear_provider_cache()
    with pytest.raises(RuntimeError, match="IMAGE_API_KEY"):
        get_image_provider()


def test_factory_fails_fast_for_unimplemented_provider(monkeypatch):
    """未接入的实现必须显式报错。

    静默回退 mock 是最危险的一种兜底：线上会「以为在调真模型」，
    实际一直在出占位图，且没有任何报错能把这件事暴露出来。
    """
    monkeypatch.setattr(get_settings(), "image_provider", "stability")
    clear_provider_cache()
    with pytest.raises(RuntimeError, match="尚未接入"):
        get_image_provider()


# ------------------------------------------------------------------ DashScope


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def _succeeded(image_url: str) -> httpx.Response:
    """messages 式成功响应：结果在 output.choices[].message.content[].image。"""
    return httpx.Response(
        200,
        json={
            "output": {
                "task_status": "SUCCEEDED",
                "choices": [{"message": {"content": [{"image": image_url}]}}],
            }
        },
    )


def _make_provider(calls: list[httpx.Request], routes: dict, **overrides) -> DashscopeProvider:
    """routes: {(method, path): Response | (Request) -> Response}，未命中一律 404。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        for (method, path), responder in routes.items():
            if request.method == method and request.url.path == path:
                if callable(responder):
                    return responder(request)
                return responder
        return httpx.Response(404, json={"message": "test handler 没有这条路由"})

    defaults: dict = {
        "api_key": "sk-test",
        "text_model": "qwen-image-3.0",
        "edit_model": "qwen-image-3.0",
        "poll_interval": 0.0,
        "transport": httpx.MockTransport(handler),
    }
    return DashscopeProvider(**{**defaults, **overrides})


def test_dashscope_provider_satisfies_protocol():
    assert isinstance(
        DashscopeProvider(api_key="sk-test", text_model="m", edit_model="m"),
        ImageProvider,
    )


async def test_dashscope_text_to_image_happy_path():
    calls: list[httpx.Request] = []
    png = _png_bytes()
    task_id = "task-abc"
    provider = _make_provider(
        calls,
        {
            ("POST", CREATE_PATH): httpx.Response(
                200, json={"output": {"task_id": task_id}, "request_id": "req-1"}
            ),
            ("GET", TASK_PATH.format(task_id=task_id)): _succeeded("https://oss.example.com/a.png"),
            ("GET", "/a.png"): httpx.Response(200, content=png),
        },
    )

    images = await provider.text_to_image("一只柴犬", size="1024x1024")

    assert images == [png]
    create = calls[0]
    # 契约 1：该端点只收异步，缺头会报 "does not support synchronous calls"
    assert create.headers["X-DashScope-Async"] == "enable"
    assert create.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(create.content)
    assert body["model"] == "qwen-image-3.0"
    assert body["input"]["messages"] == [{"role": "user", "content": [{"text": "一只柴犬"}]}]
    # 契约 2：size 用星号分隔；prompt_extend 关掉（编辑场景要听话不要扩写）
    assert body["parameters"] == {"prompt_extend": False, "size": "1024*1024"}
    # 契约 3：结果图是签名 OSS 直链，下载绝不能带 Authorization
    download = calls[-1]
    assert download.url.host == "oss.example.com"
    assert "Authorization" not in download.headers


async def test_dashscope_task_failure_surfaces_reason():
    calls: list[httpx.Request] = []
    task_id = "task-err"
    provider = _make_provider(
        calls,
        {
            ("POST", CREATE_PATH): httpx.Response(200, json={"output": {"task_id": task_id}}),
            ("GET", TASK_PATH.format(task_id=task_id)): httpx.Response(
                200,
                json={
                    "output": {"task_status": "FAILED"},
                    "code": "InvalidParameter",
                    "message": "prompt 含有敏感词",
                },
            ),
        },
    )

    with pytest.raises(ProviderError) as exc_info:
        await provider.text_to_image("x")

    assert exc_info.value.code == "task_failed"
    assert "敏感词" in str(exc_info.value)


async def test_dashscope_http_error_is_translated():
    calls: list[httpx.Request] = []
    provider = _make_provider(
        calls,
        {
            ("POST", CREATE_PATH): httpx.Response(
                429, json={"code": "Throttling", "message": "请求过快"}
            )
        },
    )

    with pytest.raises(ProviderError) as exc_info:
        await provider.text_to_image("x")

    assert exc_info.value.code == "http_error"
    assert "429" in str(exc_info.value)


async def test_dashscope_edit_image_sends_base64_data_url():
    calls: list[httpx.Request] = []
    raw = _png_bytes()
    task_id = "task-edit"
    provider = _make_provider(
        calls,
        {
            ("POST", CREATE_PATH): httpx.Response(200, json={"output": {"task_id": task_id}}),
            ("GET", TASK_PATH.format(task_id=task_id)): _succeeded("https://oss.example.com/b.png"),
            ("GET", "/b.png"): httpx.Response(200, content=raw),
        },
    )

    images = await provider.edit_image(raw, "把背景换成海滩", mime="image/png")

    assert images == [raw]
    body = json.loads(calls[0].content)
    content = body["input"]["messages"][0]["content"]
    # 契约 4：参考图走 Base64 data URL（image 在前 text 在后）
    assert content[0]["image"].startswith("data:image/png;base64,")
    assert base64.b64decode(content[0]["image"].split(",", 1)[1]) == raw
    assert content[1] == {"text": "把背景换成海滩"}
    # 编辑不传 size：保持原图比例，由模型决定输出尺寸
    assert "size" not in body["parameters"]


async def test_dashscope_edit_image_rejects_oversize_without_http_call():
    """10MB 是 data URL 的硬上限，超了要报人话而不是等服务端含糊的 400。"""
    calls: list[httpx.Request] = []
    provider = _make_provider(calls, {})

    with pytest.raises(ProviderError) as exc_info:
        await provider.edit_image(b"\x00" * (10 * 1024 * 1024 + 1), "改")

    assert exc_info.value.code == "image_too_large"
    assert calls == []


async def test_dashscope_n_greater_than_one_creates_parallel_tasks():
    """qwen-image 单次任务只出一张，n>1 靠并发建多个任务。"""
    calls: list[httpx.Request] = []
    png = _png_bytes()
    counter = {"created": 0}

    def create_response(request: httpx.Request) -> httpx.Response:
        counter["created"] += 1
        return httpx.Response(200, json={"output": {"task_id": f"task-{counter['created']}"}})

    provider = _make_provider(
        calls,
        {
            ("POST", CREATE_PATH): create_response,
            ("GET", TASK_PATH.format(task_id="task-1")): _succeeded(
                "https://oss.example.com/a.png"
            ),
            ("GET", TASK_PATH.format(task_id="task-2")): _succeeded(
                "https://oss.example.com/b.png"
            ),
            ("GET", "/a.png"): httpx.Response(200, content=png),
            ("GET", "/b.png"): httpx.Response(200, content=png),
        },
    )

    images = await provider.text_to_image("x", n=2)

    assert len(images) == 2
    assert sum(1 for r in calls if r.method == "POST") == 2


# ------------------------------------------------------------------ OpenAI 中转站


def _make_openai_provider(
    calls: list[httpx.Request],
    routes: dict[tuple[str, str], httpx.Response | Any],
) -> OpenAIImageProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        key = (request.method, request.url.path)
        responder = routes.get(key)
        if responder is None:
            raise AssertionError(f"未 mock 的请求：{key}（url={request.url}）")
        if callable(responder):
            return responder(request)
        return responder

    return OpenAIImageProvider(
        api_key="sk-test",
        text_model="gpt-image-2",
        edit_model="gpt-image-2",
        base_url="https://api.monkeycoding.club/v1",
        transport=httpx.MockTransport(handler),
    )


def test_openai_provider_satisfies_protocol():
    provider = OpenAIImageProvider(
        api_key="sk-test",
        text_model="gpt-image-2",
        edit_model="gpt-image-2",
    )
    assert isinstance(provider, ImageProvider)


async def test_openai_text_to_image_returns_png_from_b64_json():
    calls: list[httpx.Request] = []
    png = _png_bytes()
    b64 = base64.b64encode(png).decode()

    provider = _make_openai_provider(
        calls,
        {
            ("POST", "/v1/images/generations"): httpx.Response(
                200,
                json={"data": [{"b64_json": b64}]},
            )
        },
    )

    images = await provider.text_to_image("夕阳下的山间湖泊", size="1024x1024")
    assert images == [png]
    assert len(calls) == 1
    req = calls[0]
    assert req.headers["Authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "gpt-image-2"
    assert body["prompt"] == "夕阳下的山间湖泊"
    assert body["size"] == "1024x1024"


async def test_openai_text_to_image_downloads_url_fallback():
    calls: list[httpx.Request] = []
    png = _png_bytes()

    provider = _make_openai_provider(
        calls,
        {
            ("POST", "/v1/images/generations"): httpx.Response(
                200,
                json={"data": [{"url": "https://api.monkeycoding.club/v1/files/img1.png"}]},
            ),
            ("GET", "/v1/files/img1.png"): httpx.Response(200, content=png),
        },
    )

    images = await provider.text_to_image("测试 URL 下载")
    assert images == [png]


async def test_openai_text_to_image_n_parallel():
    calls: list[httpx.Request] = []
    png = _png_bytes()
    b64 = base64.b64encode(png).decode()

    provider = _make_openai_provider(
        calls,
        {
            ("POST", "/v1/images/generations"): lambda r: httpx.Response(
                200, json={"data": [{"b64_json": b64}]}
            )
        },
    )

    images = await provider.text_to_image("多图", n=3)
    assert len(images) == 3
    assert len(calls) == 3


async def test_openai_text_to_image_translates_http_error():
    calls: list[httpx.Request] = []
    provider = _make_openai_provider(
        calls,
        {
            ("POST", "/v1/images/generations"): httpx.Response(
                401,
                json={"error": {"message": "Invalid API Key"}},
            )
        },
    )

    with pytest.raises(ProviderError) as exc_info:
        await provider.text_to_image("x")

    assert exc_info.value.code == "http_error"
    assert "Invalid API Key" in str(exc_info.value)
