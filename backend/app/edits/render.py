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
    if not any(
        (
            adj.brightness,
            adj.contrast,
            adj.highlights,
            adj.shadows,
            adj.temperature,
            adj.tint,
            adj.saturation,
            adj.vibrance,
            adj.sharpness,
            adj.clarity,
            adj.vignette,
        )
    ):
        return source

    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - 依赖缺失才走到
        # 不再退回「只支持四项」的 PIL 近似：那会让高光/阴影/锐化等新参数静默失效，
        # 画布（前端精确算）与拍平结果直接不是一张图。宁可报错。
        raise RuntimeError("拍平调色需要 numpy：backend 依赖里已声明") from exc

    return _adjust_numpy(np.asarray(source.convert("RGBA")).copy(), adj)


def _adjust_numpy(pixels, adj) -> Image.Image:
    """逐字复刻前端 adjustPixels 的数学。

    顺序固定：对比 → 明度 → 高光/阴影 → 色温/色调 → 饱和 → 自然饱和
    → 锐化 → 清晰度 → 晕影。`frontend/src/domain/pixels.ts` 必须同序 ——
    顺序一换，颜色就会差一截，而「画布上看到的」和「拍平喂给模型的」
    必须是同一张图。
    """
    import numpy as np
    from PIL import ImageFilter

    step = 2.55
    contrast = adj.contrast * step
    factor = (259 * (contrast + 255)) / max(255 * (259 - contrast), 1)
    brightness = adj.brightness * step
    highlights = adj.highlights / 100
    shadows = adj.shadows / 100
    warm = (adj.temperature / 100) * 24
    tint = adj.tint / 100
    saturation = adj.saturation / 100
    vibrance = adj.vibrance / 100

    alpha = pixels[:, :, 3].copy()
    rgb = pixels[:, :, :3].astype(np.float32)

    if contrast != 0:
        rgb = factor * (rgb - 128) + 128
    if brightness != 0:
        rgb = rgb + brightness
    if highlights != 0 or shadows != 0:
        # 按亮度线性分配：亮部吃高光、暗部吃阴影，中间调基本不动
        luma = (
            0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
        ) / 255
        lift = shadows * (1 - luma) * 64 + highlights * luma * 64
        rgb = rgb + lift[:, :, None]
    if warm != 0 or tint != 0:
        # 暖 = 红多蓝少；色调正品红、负绿。G 只吃色调，动它会把肤色推向品红
        rgb[:, :, 0] += warm + tint * 12
        rgb[:, :, 1] -= tint * 20
        rgb[:, :, 2] -= warm + tint * 12
    if saturation != 0:
        gray = (
            0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
        )[:, :, None]
        rgb = gray + (rgb - gray) * (1 + saturation)
    if vibrance != 0:
        # 自然饱和度：本来就鲜艳的像素少改，灰扑扑的多改
        average = rgb.mean(axis=2, keepdims=True)
        chroma = np.abs(rgb - average).sum(axis=2, keepdims=True) / 3
        weight = vibrance * np.maximum(0, 1 - chroma / 128)
        rgb = rgb + (rgb - average) * weight

    image = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB")

    # 邻域运算放在颜色之后；负值退化成模糊（与把滑杆拖到负数的直觉一致）
    if adj.sharpness:
        if adj.sharpness > 0:
            image = image.filter(
                ImageFilter.UnsharpMask(
                    radius=1, percent=int(adj.sharpness), threshold=0
                )
            )
        else:
            image = image.filter(
                ImageFilter.GaussianBlur(radius=abs(adj.sharpness) / 200)
            )
    if adj.clarity:
        if adj.clarity > 0:
            image = image.filter(
                ImageFilter.UnsharpMask(
                    radius=2, percent=int(adj.clarity * 0.8), threshold=2
                )
            )
        else:
            image = image.filter(
                ImageFilter.GaussianBlur(radius=abs(adj.clarity) / 150)
            )

    rgb = np.asarray(image).astype(np.float32)

    if adj.vignette:
        height, width = rgb.shape[:2]
        ys, xs = np.mgrid[0:height, 0:width]
        cx, cy = (width - 1) / 2, (height - 1) / 2
        farthest = float(np.hypot(cx, cy)) or 1.0
        distance = np.hypot(xs - cx, ys - cy) / farthest
        shade = 1 - (adj.vignette / 100) * np.power(
            np.minimum(1.0, distance), 1.6
        )
        rgb = rgb * shade[:, :, None]

    out = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.uint8)
    out[:, :, :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    out[:, :, 3] = alpha
    return Image.fromarray(out, mode="RGBA")


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
