"""遮罩的原语运算。

三块职责：
    1. 选区可视化 —— `overlay_png`，选中处半透明着色，前端直接叠在画布上
    2. 笔刷栅格化 —— `rasterize_strokes`，归一化笔迹 → L 模式遮罩
    3. 选区合成 —— `apply_masked`，只把选区内的像素换成编辑结果

⚠️ 尺寸纪律：**遮罩与画布尺寸不符时显式判废，绝不拉伸**（M6 关键设计 ③）。
拉伸过的遮罩会让「选区」悄悄指到别的像素上 —— 用户看到的是重绘跑到了
错误的位置，这种错比直接报错难排查十倍。唯一允许 resize 的是
`apply_masked` 里的编辑结果：那是模型不按请求尺寸出图时的补救，宽高比
不变、事后还要和原图合成，不影响选区语义。
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFilter

OVERLAY_COLOR = (95, 152, 173)


class MaskSizeMismatch(ValueError):
    """遮罩尺寸与画布不符 —— 显式判废，绝不拉伸。"""


def to_luma(data: bytes, size: tuple[int, int] | None = None) -> Image.Image:
    """任意遮罩图 → L 模式。尺寸不符直接抛错，调用方决定怎么提示。"""
    mask = Image.open(io.BytesIO(data))
    if mask.mode in {"RGBA", "LA"}:
        mask = mask.split()[-1]
    else:
        mask = mask.convert("L")
    if size is not None and mask.size != size:
        raise MaskSizeMismatch(f"遮罩尺寸 {mask.size} 与画布尺寸 {size} 不符")
    return mask


def overlay_png(mask: Image.Image, *, color: tuple[int, int, int] = OVERLAY_COLOR) -> bytes:
    """选区可视化：选中处半透明着色，其余全透明。"""
    luma = mask.convert("L")
    overlay = Image.new("RGBA", luma.size, (*color, 0))
    pixels = overlay.load()
    levels = luma.load()
    for y in range(luma.height):
        for x in range(luma.width):
            if levels[x, y]:
                pixels[x, y] = (*color, 255)
    return _png(overlay)


def rasterize_strokes(
    size: tuple[int, int],
    strokes: list[list[tuple[float, float]]],
    *,
    radius: float,
    base: Image.Image | None = None,
) -> Image.Image:
    """归一化笔迹（0~1）→ 遮罩。radius 是相对画布短边的比例。

    base 不为空时在它上面续画（笔刷多次涂抹共用一张遮罩）。
    """
    mask = base.convert("L") if base is not None else Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    width, height = size
    brush = max(2, int(min(width, height) * radius))
    for stroke in strokes:
        if not stroke:
            continue
        points = [(x * width, y * height) for x, y in stroke]
        if len(points) == 1:
            _dot(draw, points[0], brush)
            continue
        draw.line(points, fill=255, width=brush, joint="curve")
        for point in points:
            _dot(draw, point, brush)
    return mask


def apply_masked(source: bytes, edited: bytes, mask: bytes) -> bytes:
    """只把选区内的像素换成编辑结果，选区外保持原图（DoD ② 的落点）。

    遮罩边缘做 1.2px 高斯羽化：重绘边界和原图的色彩很难逐像素对齐，
    一条硬边会把「局部编辑」暴露成「贴图」。
    """
    original = Image.open(io.BytesIO(source)).convert("RGBA")
    result = Image.open(io.BytesIO(edited)).convert("RGBA")
    if result.size != original.size:
        result = result.resize(original.size, Image.Resampling.LANCZOS)
    luma = to_luma(mask, original.size).filter(ImageFilter.GaussianBlur(1.2))
    return _png(Image.composite(result, original, luma))


def _dot(draw: ImageDraw.ImageDraw, point: tuple[float, float], brush: int) -> None:
    x, y = point
    r = brush / 2
    draw.ellipse((x - r, y - r, x + r, y + r), fill=255)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
