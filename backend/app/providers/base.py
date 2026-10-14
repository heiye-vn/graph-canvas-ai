"""图像模型 Provider 抽象。

用 `typing.Protocol` 而不是 ABC：结构化子类型，
实现类不需要显式继承，也不用 import 本模块——替换实现时少一处耦合。

约定：所有方法返回**图片字节**，不返回 URL。
外部服务给的 URL 有有效期（通常 24 小时），必须取回转存到自有存储后才算数，
这一步放在 Provider 内部，调用方永远拿到能长期用的 bytes。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class ProviderError(RuntimeError):
    """外部模型调用失败（HTTP 错误 / 鉴权失败 / 余额不足 / 格式异常 / 超时）。"""

    def __init__(self, message: str, *, code: str = "provider_failed") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@runtime_checkable
class ImageProvider(Protocol):
    name: str

    async def text_to_image(
        self,
        prompt: str,
        *,
        size: str = "1024x1024",
        n: int = 1,
    ) -> list[bytes]:
        """文生图。返回 n 张图的字节，尺寸按 size 字符串（宽x高）。"""
        ...

    async def edit_image(
        self,
        image: bytes,
        prompt: str,
        **kwargs,
    ) -> list[bytes]:
        """图生图 / 局部重绘。M6 局部编辑时启用。"""
        ...
