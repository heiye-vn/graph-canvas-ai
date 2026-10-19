"""OpenAI 兼容中转站图像 Provider —— 适配第三方 OpenAI 格式生图接口。

接口契约（标准 OpenAI 规范）：
    1. 文生图 POST {base_url}/images/generations，JSON
       {"model", "prompt", "size", "response_format": "b64_json"}
    2. 图生图 POST {base_url}/images/edits，**multipart/form-data**
       model / prompt / image / mask(可选) / response_format
    3. Response: {"data": [{"b64_json": "..."}]} 或 {"data": [{"url": "..."}]}
    4. 返回图片原始字节（bytes），不返回 URL。

⚠️ 这里绝不「返回原图保链路不崩」：占位实现会让拆层/局部编辑
产出「看起来成功」的错误结果（背景没被修补、主体还在），比直接报错难查十倍。
中转站不支持 edits 就抛 ProviderError，让任务失败得明明白白。
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Any

import httpx
from PIL import Image, ImageChops

from app.providers.base import ProviderError

DEFAULT_BASE_URL = "https://api.monkeycoding.club/v1"
GENERATE_PATH = "/images/generations"
EDIT_PATH = "/images/edits"
_DEFAULT_TIMEOUT = 300.0
# gpt-image 系列 high 档实测接近 190s，留足余量（超时会前功尽弃）
_EDIT_TIMEOUT = 600.0
_DOWNLOAD_TIMEOUT = 120.0


class OpenAIImageProvider:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        text_model: str,
        edit_model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._text_model = text_model
        self._edit_model = edit_model
        self._timeout = timeout

        clean_base_url = base_url.rstrip("/")
        # 不预设 Content-Type：json= 时 httpx 自己会写 application/json，
        # 而 edits 是 multipart —— 预置死会顶掉 httpx 生成的 boundary
        self._client = httpx.AsyncClient(
            base_url=clean_base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout),
            transport=transport,
        )
        self._download_client = httpx.AsyncClient(
            timeout=_DOWNLOAD_TIMEOUT,
            transport=transport,
        )

    # ------------------------------------------------------------------ 协议实现

    async def text_to_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]:
        """文生图。

        注意：多数生图模型（如 DALL-E 3、Flux、Gemini 等）在中转站上要求单次请求 n=1，
        当用户要求 n > 1 时，并发发起 n 次请求，确保最大兼容性。
        """
        count = max(1, n)
        if count == 1:
            return await self._generate_single(prompt, size=size)

        tasks = [self._generate_single(prompt, size=size) for _ in range(count)]
        batches = await asyncio.gather(*tasks)
        return [data for batch in batches for data in batch]

    async def edit_image(
        self,
        image: bytes,
        prompt: str,
        *,
        mime: str = "image/png",
        mask: bytes | None = None,
        size: str | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        """图生图 / 局部重绘（`/images/edits`，multipart）。

        mask 的语义与 `app.edits.mask` 保持一致：**不透明处 = 需要重绘**。
        OpenAI 的约定正好相反（mask 全透明处才是要改的地方），
        所以送出去之前要把 alpha 取反 —— 搞反的话模型会去改选区外的画面。
        """
        files: dict[str, tuple[str, bytes, str]] = {"image": ("image.png", image, mime)}
        data: dict[str, str] = {
            "model": self._edit_model,
            "prompt": prompt,
            "response_format": "b64_json",
            "n": "1",
        }
        if size:
            data["size"] = size
        if mask is not None:
            files["mask"] = ("mask.png", _to_openai_mask(mask), "image/png")

        try:
            response = await self._client.post(
                EDIT_PATH, data=data, files=files, timeout=_EDIT_TIMEOUT
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"图生图超时（>{_EDIT_TIMEOUT:.0f}s），可稍后重试或换小一点的图：{exc}",
                code="timeout",
            ) from exc

        payload = _json_of(response, "OpenAI 中转站图生图")
        return await self._collect(payload, "图生图")

    # ------------------------------------------------------------------ 内部逻辑

    async def _generate_single(self, prompt: str, *, size: str) -> list[bytes]:
        payload: dict[str, Any] = {
            "model": self._text_model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
        }

        response = await self._client.post(GENERATE_PATH, json=payload)
        data = _json_of(response, "OpenAI 中转站生图")
        return await self._collect(data, "生图")

    async def _collect(self, data: dict[str, Any], action: str) -> list[bytes]:
        """把 data 列表里的 b64_json / url 统一落成 bytes。"""
        items = data.get("data")
        # 空列表不算「格式异常」：那是模型没出图，交给下面的 no_image_data 报
        if not isinstance(items, list):
            raise ProviderError(
                f"{action}响应格式异常，缺少 data 列表：{str(data)[:300]}",
                code="invalid_response",
            )

        images: list[bytes] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if b64_str := item.get("b64_json"):
                try:
                    images.append(base64.b64decode(b64_str))
                except Exception as exc:
                    raise ProviderError(
                        f"{action}结果 Base64 解码失败：{exc}",
                        code="decode_failed",
                    ) from exc
            elif url := item.get("url"):
                images.append(await self._download(url))

        if not images:
            raise ProviderError(f"{action}成功但未返回有效图片数据", code="no_image_data")
        return images

    async def _download(self, url: str) -> bytes:
        response = await self._download_client.get(url)
        if response.status_code >= 400:
            raise ProviderError(
                f"下载结果图失败：HTTP {response.status_code}",
                code="download_failed",
            )
        return response.content


# ------------------------------------------------------------------ 纯函数助手


def _to_openai_mask(mask: bytes) -> bytes:
    """内部遮罩（不透明=重绘）→ OpenAI 遮罩（全透明=重绘）。

    只改 alpha，RGB 原样保留：中转站若只读 alpha 才认，读 RGB 的也不会被带偏。
    尺寸必须与 image 一致，调用方（edit_image_clamped）负责缩放。
    """
    image = Image.open(io.BytesIO(mask)).convert("RGBA")
    image.putalpha(ImageChops.invert(image.getchannel("A")))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _json_of(response: httpx.Response, action: str) -> dict[str, Any]:
    """把 HTTP 错误和 OpenAI 风格的错误报文转成人话。"""
    if response.status_code >= 400:
        error_detail = ""
        try:
            err_json = response.json()
            if isinstance(err_json, dict) and "error" in err_json:
                err_info = err_json["error"]
                if isinstance(err_info, dict):
                    error_detail = err_info.get("message") or str(err_info)
                else:
                    error_detail = str(err_info)
            else:
                error_detail = response.text[:300]
        except Exception:
            error_detail = response.text[:300]

        raise ProviderError(
            f"{action}失败：HTTP {response.status_code} - {error_detail}",
            code="http_error" if response.status_code < 500 else "provider_unavailable",
        )

    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{action}失败：响应不是有效 JSON：{response.text[:200]}") from exc
