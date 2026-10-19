"""DashScope（阿里云百炼）图像 Provider —— qwen-image 系列的真实实现。

接口契约（2026-10 按官方文档核对，写死在这里防止凭记忆漂移）：

    1. qwen-image-3.0 / 2.1 系列走 **messages 式**新接口：
       POST /api/v1/services/aigc/image-generation/generation
       必须带 `X-DashScope-Async: enable`（该端点只收异步，缺头会报
       "current user api does not support synchronous calls"）
    2. 任务体：input.messages 有且只有一个 user 消息；
       content 数组里 {"text": ...} 与 {"image": ...} 并列 ——
       文生图只有 text；图生图是 1~3 张 image + 1 个 text
    3. 参考图支持 Base64 data URL（data:{mime};base64,...），单张 ≤10MB
    4. size 用 **星号**分隔（"1024*1024"），面积 512²~2048²，宽高比 1:8~8:1
    5. 轮询 GET /api/v1/tasks/{task_id}，task_status ∈
       PENDING/RUNNING/SUCCEEDED/FAILED/CANCELED/UNKNOWN；
       失败时顶层 code / message 带原因
    6. 结果图 URL 在 output.choices[].message.content[].image，**有效期只有 24h**
       —— 所以本 Provider 下载成 bytes 再返回，URL 永不外泄（Provider 约定）

与 mock 的本质差异：这里没有任何确定性可言，同样的 prompt 出不同的图，
每次都是真实的钱 —— 所以重试/预算这类问题留给调用方，Provider 只负责「一次调用」。
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import Any

import httpx

from app.providers.base import ProviderError

# Provider 层的失败对外要能被任务层翻译成 run.error，用最普通的异常即可；
# 刻意不继承 ToolError —— 那是「工具参数错」的语义，混用会让错误码失真。


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com"
CREATE_PATH = "/api/v1/services/aigc/image-generation/generation"
TASK_PATH = "/api/v1/tasks/{task_id}"

# 任务图 URL 24h 过期，下载自己的超时不必跟创建任务共用一个值
_DOWNLOAD_TIMEOUT = 120.0

_PENDING_STATES = {"PENDING", "RUNNING"}
_TERMINAL_FAILED = {"FAILED", "CANCELED", "UNKNOWN"}


class DashscopeProvider:
    name = "dashscope"

    def __init__(
        self,
        api_key: str,
        *,
        text_model: str,
        edit_model: str,
        base_url: str = DEFAULT_BASE_URL,
        poll_interval: float = 3.0,
        poll_timeout: float = 240.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        `transport` 只给测试注入 MockTransport 用，生产永远走默认。

        poll_timeout 默认 240s：ARQ 的 job_timeout 是 300s，轮询上限必须给
        下载与落库留时间——顶满 300 会被 ARQ 硬杀，CancelledError 不走
        任务层的 except Exception，run 就永远停在 running 了。
        """
        self._text_model = text_model
        self._edit_model = edit_model
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            timeout=httpx.Timeout(60.0),
            transport=transport,
        )
        # 结果图是带签名的 OSS 直链：带 Authorization 头反而会被拒，
        # 所以下载用独立的匿名客户端（与任务客户端共享 transport，便于测试注入）
        self._download_client = httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT, transport=transport)

    # ------------------------------------------------------------------ 协议实现

    async def text_to_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]:
        """文生图：qwen-image 系列单次任务只出一张，n>1 时并发建 n 个任务。"""
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        tasks = [self._run_task(self._text_model, messages, size=size) for _ in range(max(1, n))]
        return [item for batch in await asyncio.gather(*tasks) for item in batch]

    async def edit_image(
        self,
        image: bytes,
        prompt: str,
        *,
        mime: str = "image/png",
        mask: bytes | None = None,
        **kwargs: Any,
    ) -> list[bytes]:
        """图生图 / 编辑：参考图走 Base64 data URL（服务端不要求公网可访问）。

        `mask` 这里用不上：qwen-image-edit 只吃「图 + 一句话」，
        没有遮罩入参。局部性由调用方的 apply_masked 保证，不靠模型自觉。
        """
        encoded = base64.b64encode(image).decode()
        # data URL 上限 10MB：超了报人话，而不是等服务端回一个含糊的 400
        if len(encoded) * 3 // 4 > 10 * 1024 * 1024:
            raise ProviderError("参考图超过 10MB，请先压缩后再编辑", code="image_too_large")

        messages = [
            {
                "role": "user",
                "content": [{"image": f"data:{mime};base64,{encoded}"}, {"text": prompt}],
            }
        ]
        return await self._run_task(self._edit_model, messages, size=None)

    # ------------------------------------------------------------------ 任务编排

    async def _run_task(
        self, model: str, messages: list[dict[str, Any]], *, size: str | None
    ) -> list[bytes]:
        task_id = await self._create_task(model, messages, size)
        urls = await self._wait_for_task(task_id)
        return await self._download_all(urls)

    async def _create_task(
        self, model: str, messages: list[dict[str, Any]], size: str | None
    ) -> str:
        parameters: dict[str, Any] = {"prompt_extend": False}
        if size:
            # DashScope 协议用星号分隔（OpenAI 兼容模式才是 x），这里做一次翻译
            parameters["size"] = size.replace("x", "*")

        response = await self._client.post(
            CREATE_PATH,
            json={"model": model, "input": {"messages": messages}, "parameters": parameters},
        )
        payload = _json_of(response, "创建任务")
        task_id = (payload.get("output") or {}).get("task_id")
        if not task_id:
            raise ProviderError(f"创建任务成功但没有 task_id：{payload}", code="no_task_id")
        return str(task_id)

    async def _wait_for_task(self, task_id: str) -> list[str]:
        """轮询到终态。任务一般十几秒到几分钟（官方建议 3~5 秒一查）。"""
        deadline = time.monotonic() + self._poll_timeout
        path = TASK_PATH.format(task_id=task_id)

        while True:
            response = await self._client.get(path)
            payload = _json_of(response, "查询任务")
            output = payload.get("output") or {}
            status = str(output.get("task_status") or "").upper()

            if status == "SUCCEEDED":
                urls = _extract_urls(output)
                if not urls:
                    raise ProviderError(
                        f"任务 {task_id} 成功但响应里没有图片 URL：{payload}",
                        code="no_result_url",
                    )
                return urls
            if status in _TERMINAL_FAILED:
                raise ProviderError(
                    f"任务失败（{status}）：{payload.get('code')} {payload.get('message')}",
                    code="task_failed",
                )

            if time.monotonic() > deadline:
                raise ProviderError(
                    f"任务 {task_id} 轮询超时（{int(self._poll_timeout)}s 仍是 {status}）",
                    code="poll_timeout",
                )
            await asyncio.sleep(self._poll_interval)

    async def _download_all(self, urls: list[str]) -> list[bytes]:
        images = await asyncio.gather(*(self._download(url) for url in urls))
        return list(images)

    async def _download(self, url: str) -> bytes:
        response = await self._download_client.get(url)
        if response.status_code >= 400:
            raise ProviderError(
                f"下载结果图失败：HTTP {response.status_code}", code="download_failed"
            )
        return response.content


# ------------------------------------------------------------------ 纯函数助手（可单测）


def _json_of(response: httpx.Response, action: str) -> dict[str, Any]:
    """把 HTTP 错误翻成能看懂的人话 —— 直接把 status+body 抛给用户等于没诊断。"""
    if response.status_code >= 400:
        detail = response.text[:300]
        raise ProviderError(
            f"{action}失败：HTTP {response.status_code} {detail}",
            code="http_error" if response.status_code < 500 else "provider_unavailable",
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{action}失败：响应不是 JSON：{response.text[:200]}") from exc


def _extract_urls(output: dict[str, Any]) -> list[str]:
    """兼容两种响应形态：messages 式（choices）与旧式（results）。"""
    urls: list[str] = []
    for choice in output.get("choices") or []:
        for item in (choice.get("message") or {}).get("content") or []:
            if isinstance(item, dict) and item.get("image"):
                urls.append(str(item["image"]))
    if not urls:
        for item in output.get("results") or []:
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
    return urls
