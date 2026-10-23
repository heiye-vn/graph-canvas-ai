"""拆层像素原语（M7）：抠物体、挖空、背景修补、文字框遮罩。

全部是 bytes in / bytes out 的纯函数，查库与文档组装在 services/tasks 层。

降级链是本模块的灵魂（DoD ③）：
    fill_background 优先 OpenCV 的 TELEA 修补，没装 cv2（或任何异常）
    退到 `_blur_inpaint` —— 边界平均色铺底 + 多轮由粗到细的高斯模糊。
    表现会糙一点，但**绝不报错**：拆层是主流程，不能因为一个可选
    依赖把用户拦在门外。
"""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from app.edits.mask import overlay_png, to_luma
from app.edits.ocr import TextBox


def punch(source: bytes, mask: bytes, *, x: float = 0, y: float = 0) -> bytes:
    """把遮罩覆盖到的像素打成透明。mask 为画布尺寸，x/y 是图层原点。"""
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    luma = to_luma(mask)
    left, top = int(round(x)), int(round(y))
    local = Image.new("L", image.size, 0)
    local.paste(luma, (-left, -top))
    keep = ImageChops.invert(local)
    image.putalpha(ImageChops.multiply(image.getchannel("A"), keep))
    return _png(image)


def alpha_mask(data: bytes) -> bytes:
    """把透明通道做成可视化遮罩，供局部合成复用。"""
    alpha = Image.open(io.BytesIO(data)).convert("RGBA").getchannel("A")
    return overlay_png(alpha)


def grow_mask(mask: bytes, radius: int) -> bytes:
    """把遮罩向外扩 radius 像素（尺寸不变，只动 alpha）。

    为什么非扩不可：rembg 的 alpha 边界压在物体的**抗锯齿边**上，
    紧贴遮罩外还有约 1px 的亮边（实测：遮罩外 0~1px 原图亮度 191，
    1~2px 就掉到 33，也就是干净的绸缎）。不清掉这 1px，
    apply_masked 的羽化带会把它按比例混回来 ——
    拆完层的背景上就留一圈清晰的物体轮廓（1px 灰线）。
    外扩后过渡带整体落到「已经是背景」的外侧，轮廓自然消失。
    """
    if radius <= 0:
        return mask
    image = Image.open(io.BytesIO(mask)).convert("RGBA")
    return _png(image.filter(ImageFilter.MaxFilter(radius * 2 + 1)))


def fill_background(source: bytes, mask: bytes) -> bytes:
    """挖掉遮罩覆盖的像素，用周围颜色填上，保证背景不再含主体。"""
    image = Image.open(io.BytesIO(source)).convert("RGB")
    luma = to_luma(mask, image.size)
    try:
        filled = _cv_inpaint(image, luma)
    except Exception:  # noqa: BLE001 - 没有 cv2 / 任何 CV 异常都走兜底
        filled = _blur_inpaint(image, luma)
    return _png(filled.convert("RGBA"))


def text_mask(size: tuple[int, int], boxes: list[TextBox], *, grow: int | None = None) -> bytes:
    """把文字框画成画布遮罩，略外扩以免边缘残留。"""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for box in boxes:
        draw.rectangle((box.x, box.y, box.x + box.width, box.y + box.height), fill=255)
    radius = 3 if grow is None else grow
    if radius > 0:
        mask = mask.filter(ImageFilter.MaxFilter(radius * 2 + 1))
    return overlay_png(mask)


def remove_text(
    subject: bytes,
    background: bytes,
    boxes: list[TextBox],
    size: tuple[int, int],
) -> tuple[bytes, bytes]:
    """主体挖空文字，背景用周围色填上，避免矢量字叠在原像素上（DoD ② 的前提）。

    只把文字做成新图层、不抠原字，改文案时旧字还在底下 ——
    「文字层可编辑」必须连像素一起抹掉才算数。
    """
    if not boxes:
        return subject, background
    hole = text_mask(size, boxes)
    return punch(subject, hole), fill_background(background, hole)


def _cv_inpaint(image: Image.Image, luma: Image.Image) -> Image.Image:
    import cv2
    import numpy as np

    hole = np.where(np.array(luma) > 12, 255, 0).astype(np.uint8)
    if not hole.any():
        return image
    radius = max(3, min(image.size) // 80)
    repaired = cv2.inpaint(np.array(image), hole, radius, cv2.INPAINT_TELEA)
    return Image.fromarray(repaired)


def _blur_inpaint(image: Image.Image, luma: Image.Image) -> Image.Image:
    """未安装 OpenCV 时的兜底：用边界平均色铺底，再反复模糊抹平空洞。"""
    keep = ImageChops.invert(luma)
    ring = ImageChops.subtract(luma.filter(ImageFilter.MaxFilter(9)), luma)
    seed = Image.new("RGB", image.size, _mean_where(image, ring) or _mean_where(image, keep))
    seed.paste(image, mask=keep)
    patched = seed
    for radius in (24, 12, 5):
        patched = Image.composite(patched.filter(ImageFilter.GaussianBlur(radius)), patched, luma)
    return Image.composite(patched, image, luma)


def _mean_where(image: Image.Image, mask: Image.Image) -> tuple[int, int, int] | None:
    pixels = image.load()
    levels = mask.load()
    total = [0, 0, 0]
    count = 0
    for y in range(image.height):
        for x in range(image.width):
            if levels[x, y] <= 16:
                continue
            red, green, blue = pixels[x, y][:3]
            total[0] += red
            total[1] += green
            total[2] += blue
            count += 1
    if not count:
        return None
    return (total[0] // count, total[1] // count, total[2] // count)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
