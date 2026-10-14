"""OpenAI 兼容中转站图像 Provider —— 适配第三方 OpenAI 格式生图接口。

接口契约（标准 OpenAI /v1/images/generations 规范）：
    1. POST {base_url}/images/generations
    2. Headers: Authorization: Bearer {api_key}, Content-Type: application/json
    3. Payload: {"model": model, "prompt": prompt, "size": size, "response_format": "b64_json"}
    4. Response: {"data": [{"b64_json": "..."}]} 或 {"data": [{"url": "..."}]}
    5. 返回图片原始字节（bytes），不返回 URL。
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any

import httpx

from app.providers.base import ProviderError

DEFAULT_BASE_URL = "https://api.monkeycoding.club/v1"
GENERATE_PATH = "/images/generations"
_DEFAULT_TIMEOUT = 300.0
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
        self._client = httpx.AsyncClient(
            base_url=clean_base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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
        **kwargs: Any,
    ) -> list[bytes]:
        """图生图 / 局部重绘。

        M6 局部编辑时启用；当前阶段返回原图以保证链路不崩溃。
        """
        return [image]

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

        items = data.get("data")
        if not items or not isinstance(items, list):
            raise ProviderError(
                f"生图响应格式异常，缺少 data 列表：{data}",
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
                        f"生图结果 Base64 解码失败：{exc}",
                        code="decode_failed",
                    ) from exc
            elif url := item.get("url"):
                images.append(await self._download(url))

        if not images:
            raise ProviderError("生图成功但未返回有效图片数据", code="no_image_data")
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
