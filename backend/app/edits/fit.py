"""交付尺寸：把画布完整放进投放比例，不裁切。

与「扩图」的区别：这里**不调用任何模型**，纯补边 —— 电商投放要的是
「原图一个像素都不裁」，多出来的地方用画布背景色填。

与「裁剪画布」的区别：裁剪是去掉内容、画布变小；这里是保留全部内容、
画布变大。两个操作在素材交付语境里是相反的。
"""

from __future__ import annotations

import io

from PIL import Image, ImageColor

# 与常见投放位对齐：宽度统一 1080，高度按比例（1080×1350 / 1080×1920）
DELIVERY_SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "9:16": (1080, 1920),
}

DEFAULT_RATIOS: tuple[str, ...] = ("1:1", "4:5", "9:16")

_WHITE = (255, 255, 255, 255)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _fill_of(background: str | None) -> tuple[int, int, int, int]:
    """背景色解析失败就退回白色 —— 一个填色不该让整次导出失败。"""
    if not background:
        return _WHITE
    try:
        red, green, blue = ImageColor.getrgb(background)
    except ValueError:
        return _WHITE
    return (red, green, blue, 255)


def letterbox(
    data: bytes,
    width: int,
    height: int,
    *,
    background: str | None = "#ffffff",
) -> bytes:
    """完整放入目标画幅，不裁切，空白居中留白。"""
    source = Image.open(io.BytesIO(data)).convert("RGBA")
    if source.size == (width, height):
        return _png(source)

    scale = min(width / source.width, height / source.height)
    placed_size = (
        max(1, int(round(source.width * scale))),
        max(1, int(round(source.height * scale))),
    )
    placed = source.resize(placed_size, Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (width, height), _fill_of(background))
    canvas.paste(
        placed,
        ((width - placed_size[0]) // 2, (height - placed_size[1]) // 2),
        placed,
    )
    return _png(canvas)
