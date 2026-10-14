"""服务端画布拍平：LayerDocument → 一张 PNG。

为什么必须有它：本项目「存结构不存像素」，像素由前端 Konva 合成 ——
但 inpaint 要把**当前画面**交给模型改，选区遮罩也要和当前画面逐像素对齐，
这两件事都绕不开服务端自己合成一份。

对齐纪律：这里的合成规则必须与前端 CanvasStage 逐条对齐（crop 在源图
像素空间取、transform.width/height 缺省回退画布尺寸、flip 用符号、
旋转绕图层中心、opacity 乘 alpha）。两边各写各的迟早漂移，漂移的表现是
「重绘的位置和画布上看到的不一样」。

调色数学**逐字复刻** `frontend/src/domain/pixels.ts` 的 adjustPixels：
同一张图前端看到的和服务端拍平的必须是一个颜色。numpy 可用时走逐像素
精确路径；没有 numpy 时用 PIL 的查找表近似（前厅环境够用）。
"""

from __future__ import annotations

import io
import uuid

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.schemas.layer_doc import Layer, LayerDocument

WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

_FONT_PATHS = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)
_font_file: str | None = None


def flatten(
    doc: LayerDocument,
    images: dict[uuid.UUID, bytes],
    *,
    include_text: bool = True,
) -> bytes:
    """按文档合成一张 PNG（层序从下到上）。"""
    background = doc.canvas.background or "#ffffff"
    canvas = Image.new("RGBA", (doc.canvas.width, doc.canvas.height), _rgba(background))
    for layer in doc.layers:
        if not layer.visible:
            continue
        if layer.type == "text":
            if include_text:
                _composite_text(canvas, layer)
            continue
        if layer.type != "image" or layer.source is None:
            continue
        raw = images.get(layer.source.asset_id)
        if raw is None:
            continue
        source = Image.open(io.BytesIO(raw)).convert("RGBA")

        crop = layer.crop
        if crop is not None:
            # 与前端 Konva crop 同语义：在**源图像素空间**取窗
            left = max(0, min(crop.x, source.width - 1))
            top = max(0, min(crop.y, source.height - 1))
            right = min(source.width, left + crop.width)
            bottom = min(source.height, top + crop.height)
            if right > left and bottom > top:
                source = source.crop((left, top, right, bottom))

        source = _apply_adjustments(source, layer)

        display_w = int(layer.transform.width or doc.canvas.width)
        display_h = int(layer.transform.height or doc.canvas.height)
        if source.size != (display_w, display_h):
            source = source.resize((max(1, display_w), max(1, display_h)),
                                   Image.Resampling.LANCZOS)

        _place(canvas, layer, source)

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def _apply_adjustments(source: Image.Image, layer: Layer) -> Image.Image:
    adj = layer.adjustments
    if (adj.brightness, adj.contrast, adj.saturation, adj.temperature) == (0, 0, 0, 0):
        return source

    try:
        import numpy as np

        return _adjust_numpy(np.asarray(source.convert("RGBA")).copy(), adj)
    except ImportError:
        return _adjust_pil(source, adj)


def _adjust_numpy(pixels, adj) -> Image.Image:
    """逐字复刻前端 adjustPixels 的数学（顺序：对比 → 明度 → 饱和 → 色温）。"""
    import numpy as np

    step = 2.55
    contrast = adj.contrast * step
    factor = (259 * (contrast + 255)) / max(255 * (259 - contrast), 1)
    brightness = adj.brightness * step
    saturation = adj.saturation / 100
    warm = (adj.temperature / 100) * 24

    rgb = pixels[:, :, :3].astype(np.float32)
    if contrast != 0:
        rgb = factor * (rgb - 128) + 128
    if brightness != 0:
        rgb = rgb + brightness
    if saturation != 0:
        gray = (
            0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
        )[:, :, None]
        rgb = gray + (rgb - gray) * (1 + saturation)
    if warm != 0:
        # 暖 = 红多蓝少。刻意只对 R/B 施力：动 G 会把肤色推向品红
        rgb[:, :, 0] += warm
        rgb[:, :, 2] -= warm

    pixels[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="RGBA")


def _adjust_pil(source: Image.Image, adj) -> Image.Image:
    """没有 numpy 时的近似路径：逐通道 LUT + 601 灰度混饱和。"""
    step = 2.55
    contrast = adj.contrast * step
    factor = (259 * (contrast + 255)) / max(255 * (259 - contrast), 1)
    brightness = adj.brightness * step

    lut = []
    for value in range(256):
        v = value
        if contrast != 0:
            v = factor * (v - 128) + 128
        if brightness != 0:
            v = v + brightness
        lut.append(max(0, min(255, int(v))))
    rgb = source.convert("RGB").point(lut * 3)
    if adj.saturation != 0:
        gray = rgb.convert("L")
        mixed = Image.blend(gray.convert("RGB"), rgb, 1 + adj.saturation / 100)
        rgb = mixed
    if adj.temperature != 0:
        warm = int((adj.temperature / 100) * 24)
        r, g, b = rgb.split()
        r = r.point(lambda v: max(0, min(255, v + warm)))
        b = b.point(lambda v: max(0, min(255, v - warm)))
        rgb = Image.merge("RGB", (r, g, b))
    out = Image.new("RGBA", source.size)
    out.paste(rgb, (0, 0))
    out.putalpha(source.getchannel("A"))
    return out


def _composite_text(canvas: Image.Image, layer: Layer) -> None:
    """文字层的近似渲染：M7 会重构文字层，这里只求「拍平结果大致像」。

    定位用图层中心 + 水平垂直居中，与前端的对齐方式一致到「看得过去」的程度。
    """
    content = (layer.text.text if layer.text else layer.name).strip()
    if not content:
        return
    width = max(1, int(layer.transform.width or canvas.width))
    font_size = layer.text.font_size if layer.text else 48
    height = max(1, int(layer.transform.height or max(48, font_size)))
    source = Image.new("RGBA", (width, height), TRANSPARENT)
    draw = ImageDraw.Draw(source)
    font = _font(layer.text.font_size if layer.text else 48)
    color = _rgba(layer.text.fill if layer.text else "#171917")
    box = draw.textbbox((0, 0), content, font=font)
    text_w, text_h = box[2] - box[0], box[3] - box[1]
    x = (width - text_w) / 2 - box[0]
    y = (height - text_h) / 2 - box[1]
    draw.text((x, y), content, font=font, fill=color)
    _place(canvas, layer, source)


def _place(canvas: Image.Image, layer: Layer, source: Image.Image) -> None:
    """变换落位：flip → 缩放 → 透明度 → 旋转（绕中心）→ 贴到画布。"""
    transform = layer.transform
    if transform.flip_x:
        source = ImageOps.mirror(source)
    if transform.flip_y:
        source = ImageOps.flip(source)

    if layer.opacity < 1:
        alpha = source.getchannel("A").point(lambda value: int(value * layer.opacity))
        source.putalpha(alpha)

    if transform.rotation:
        # Pillow 逆时针为正，画布旋转顺时针为正（与前端 Konva 一致）
        source = source.rotate(
            -transform.rotation, expand=True, resample=Image.Resampling.BICUBIC
        )

    center_x = transform.x + (layer.transform.width or canvas.width) / 2
    center_y = transform.y + (layer.transform.height or canvas.height) / 2
    left = int(round(center_x - source.width / 2))
    top = int(round(center_y - source.height / 2))
    _paste(canvas, source, left, top)


def _paste(canvas: Image.Image, source: Image.Image, left: int, top: int) -> None:
    """越界安全贴图：只贴画布内的部分。"""
    src_x, src_y = max(0, -left), max(0, -top)
    dst_x, dst_y = max(0, left), max(0, top)
    width = min(source.width - src_x, canvas.width - dst_x)
    height = min(source.height - src_y, canvas.height - dst_y)
    if width <= 0 or height <= 0:
        return
    piece = source.crop((src_x, src_y, src_x + width, src_y + height))
    canvas.alpha_composite(piece, (dst_x, dst_y))


def _font(size: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    global _font_file
    if _font_file is None:
        for path in _FONT_PATHS:
            try:
                ImageFont.truetype(path, 12)
                _font_file = path
                break
            except OSError:
                continue
        else:
            _font_file = ""
    px = max(8, int(round(size)))
    if _font_file:
        try:
            return ImageFont.truetype(_font_file, px)
        except OSError:
            pass
    return ImageFont.load_default()


def _rgba(color: str) -> tuple[int, int, int, int]:
    value = color.lstrip("#")
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
        255,
    )
