"""M6 像素原语单测：遮罩运算 + 服务端拍平。

不查库、不开 FastAPI —— edits 包的纯函数在几行断言里钉死行为。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.edits.mask import (
    MaskSizeMismatch,
    apply_masked,
    overlay_png,
    rasterize_strokes,
    to_luma,
    union,
)
from app.edits.render import flatten
from app.schemas.layer_doc import Adjustments, LayerDocument

SIZE = (64, 48)


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _solid(size, color, mode="RGBA") -> bytes:
    return _png(Image.new(mode, size, color))


# ------------------------------------------------------------------ mask


def test_to_luma_rejects_wrong_size():
    mask = _png(Image.new("L", (32, 32), 255))
    with pytest.raises(MaskSizeMismatch):
        to_luma(mask, SIZE)


def test_to_luma_takes_alpha_channel():
    rgba = _png(Image.new("RGBA", SIZE, (0, 0, 0, 200)))
    luma = to_luma(rgba)
    assert luma.getextrema() == (200, 200)


def test_rasterize_strokes_single_point_is_dot():
    mask = rasterize_strokes(SIZE, [[(0.5, 0.5)]], radius=0.25)
    assert mask.mode == "L"
    assert mask.getpixel((32, 24)) == 255
    assert mask.getpixel((0, 0)) == 0


def test_rasterize_strokes_accumulates_on_base():
    base = rasterize_strokes(SIZE, [[(0.1, 0.1)]], radius=0.25)
    stroke = rasterize_strokes(SIZE, [[(0.9, 0.9)]], radius=0.25, base=base)
    assert stroke.getpixel((6, 4)) == 255  # base 的部分还在
    assert stroke.getpixel((57, 43)) == 255  # 新笔迹也在


def test_union_takes_lighter():
    a = Image.new("L", SIZE, 0)
    a.putpixel((0, 0), 255)
    b = Image.new("L", SIZE, 0)
    b.putpixel((1, 0), 255)
    merged = union(a, b)
    assert merged.getpixel((0, 0)) == 255
    assert merged.getpixel((1, 0)) == 255
    assert merged.getpixel((2, 0)) == 0


def test_apply_masked_only_changes_selected_region():
    original = _solid(SIZE, (255, 0, 0, 255))  # 全红
    edited = _solid(SIZE, (0, 0, 255, 255))  # 全蓝
    mask = Image.new("L", SIZE, 0)
    # 一小块选区（单像素会被 1.2px 羽化稀释，中心不再是纯蓝）
    for y in range(15, 25):
        for x in range(25, 35):
            mask.putpixel((x, y), 255)
    out = Image.open(io.BytesIO(apply_masked(original, edited, _png(mask))))

    # 选区中心是蓝，选区外保持红
    assert out.getpixel((30, 20))[:3] == (0, 0, 255)
    assert out.getpixel((0, 0))[:3] == (255, 0, 0)


def test_apply_masked_resizes_provider_output():
    """模型不按请求尺寸出图时，结果先缩回原尺寸再合成。"""
    original = _solid(SIZE, (255, 0, 0, 255))
    edited = _solid((128, 96), (0, 255, 0, 255))
    mask = _png(Image.new("L", SIZE, 255))  # 全选
    out = Image.open(io.BytesIO(apply_masked(original, edited, mask)))
    assert out.size == SIZE
    assert out.getpixel((10, 10))[:3] == (0, 255, 0)


def test_overlay_png_colors_selected_only():
    mask = Image.new("L", SIZE, 0)
    mask.putpixel((5, 5), 255)
    overlay = Image.open(io.BytesIO(overlay_png(mask)))
    assert overlay.mode == "RGBA"
    assert overlay.getpixel((5, 5))[3] == 255
    assert overlay.getpixel((0, 0))[3] == 0


# ------------------------------------------------------------------ render


def _doc(layers: list[dict], size=SIZE) -> LayerDocument:
    return LayerDocument.model_validate(
        {
            "canvas": {"width": size[0], "height": size[1], "background": "#ffffff"},
            "layers": layers,
        }
    )


def test_flatten_skips_hidden_and_missing_layers():
    doc = _doc(
        [
            {
                "name": "缺失",
                "type": "image",
                "source": {"asset_id": "00000000-0000-0000-0000-000000000001"},
            },
            {
                "name": "隐藏",
                "type": "image",
                "visible": False,
                "source": {"asset_id": "00000000-0000-0000-0000-000000000002"},
            },
        ]
    )
    out = Image.open(io.BytesIO(flatten(doc, {})))
    assert out.size == SIZE
    assert out.getpixel((0, 0))[:3] == (255, 255, 255)  # 全空 → 白底


def test_flatten_places_image_with_transform():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "transform": {"x": 10, "y": 8, "width": 32, "height": 24},
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _solid((16, 16), (10, 200, 30, 255))}
    out = Image.open(io.BytesIO(flatten(doc, images)))
    assert out.getpixel((10, 8))[:3] == (10, 200, 30)  # 左上角落在 (x, y)
    assert out.getpixel((50, 40))[:3] == (255, 255, 255)  # 图层外是白底


def test_flatten_respects_crop():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    # 左半红右半蓝的源图，只取右半（crop x=8）
    source = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    for y in range(16):
        for x in range(8, 16):
            source.putpixel((x, y), (0, 0, 255, 255))
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "crop": {"x": 8, "y": 0, "width": 8, "height": 16},
                "transform": {"x": 0, "y": 0, "width": 16, "height": 16},
            }
        ]
    )
    out = Image.open(io.BytesIO(flatten(doc, {__import__("uuid").UUID(asset_id): _png(source)})))
    assert out.getpixel((2, 2))[:3] == (0, 0, 255)  # 显示的是 crop 后的右半


def test_flatten_applies_flip():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    source = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
    source.putpixel((0, 0), (0, 0, 255, 255))  # 左上角一个蓝点
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "transform": {"x": 0, "y": 0, "width": 16, "height": 16,
                              "flip_x": True},
            }
        ]
    )
    out = Image.open(io.BytesIO(flatten(doc, {__import__("uuid").UUID(asset_id): _png(source)})))
    assert out.getpixel((0, 0))[:3] == (255, 0, 0)  # 翻转后蓝点去了右上，左上恢复红
    assert out.getpixel((15, 0))[:3] == (0, 0, 255)


def test_flatten_applies_opacity():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "opacity": 0.5,
                "source": {"asset_id": asset_id},
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _solid(SIZE, (255, 0, 0, 255))}
    out = Image.open(io.BytesIO(flatten(doc, images)))
    r, g, b, _a = out.getpixel((0, 0))
    # 半透明红叠在白底上
    assert (r, g, b) == (255, 128, 128)


def test_flatten_adjustments_change_pixels():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "adjustments": {"brightness": 40, "contrast": 0,
                                 "saturation": 0, "temperature": 0},
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _solid(SIZE, (100, 100, 100, 255))}
    out = Image.open(io.BytesIO(flatten(doc, images)))
    assert out.getpixel((0, 0))[:3][0] > 100  # 变亮了


def test_flatten_temperature_moves_red_and_blue():
    asset_id = "00000000-0000-0000-0000-00000000abcd"
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "adjustments": Adjustments(temperature=100).model_dump(),
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _solid(SIZE, (128, 128, 128, 255))}
    out = Image.open(io.BytesIO(flatten(doc, images)))
    r, _g, b, _a = out.getpixel((0, 0))
    assert r == 152  # 128 + 24
    assert b == 104  # 128 - 24


def test_flatten_full_adjustments_with_vignette():
    """11 个参数一起上不报错，且晕影确实把四角压暗。"""
    asset_id = "00000000-0000-0000-0000-00000000abce"
    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "adjustments": Adjustments(
                    brightness=10,
                    contrast=20,
                    highlights=15,
                    shadows=10,
                    temperature=20,
                    tint=10,
                    saturation=15,
                    vibrance=20,
                    sharpness=30,
                    clarity=20,
                    vignette=80,
                ).model_dump(),
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _solid(SIZE, (128, 128, 128, 255))}
    out = Image.open(io.BytesIO(flatten(doc, images)))
    assert out.size == SIZE

    center = sum(out.getpixel((SIZE[0] // 2, SIZE[1] // 2))[:3])
    corner = sum(out.getpixel((0, 0))[:3])
    assert corner < center  # 四角被压暗


def test_flatten_sharpen_keeps_transparency():
    """锐化/清晰度不能把透明区填成黑块（沿用 DoD③ 的通道纪律）。"""
    asset_id = "00000000-0000-0000-0000-00000000abcf"
    image = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    for x in range(SIZE[0] // 2):
        for y in range(SIZE[1]):
            image.putpixel((x, y), (200, 40, 40, 255))

    doc = _doc(
        [
            {
                "name": "图",
                "type": "image",
                "source": {"asset_id": asset_id},
                "adjustments": Adjustments(sharpness=100, clarity=100).model_dump(),
            }
        ]
    )
    images = {__import__("uuid").UUID(asset_id): _png(image)}
    out = Image.open(io.BytesIO(flatten(doc, images)))

    # 右半是透明的，叠在白底上必须还是白色
    assert out.getpixel((SIZE[0] - 2, 2))[:3] == (255, 255, 255)


# ------------------------------------------------------------------ 投放尺寸（letterbox）


def test_letterbox_fits_without_cropping():
    """完整放入目标画幅：短边留白，内容一个像素都不裁。"""
    from app.edits.fit import letterbox

    # 100×50 的图放进 1080×1080：宽度撑满，上下留白
    source = _solid((100, 50), (10, 200, 30, 255))
    out = Image.open(io.BytesIO(letterbox(source, 1080, 1080)))

    assert out.size == (1080, 1080)
    assert out.getpixel((540, 10))[:3] == (255, 255, 255)  # 上方留白
    assert out.getpixel((540, 540))[:3] == (10, 200, 30)  # 中间是原图


def test_letterbox_uses_canvas_background():
    from app.edits.fit import letterbox

    source = _solid((100, 50), (10, 200, 30, 255))
    out = Image.open(
        io.BytesIO(letterbox(source, 1080, 1080, background="#112233"))
    )
    assert out.getpixel((540, 10))[:3] == (0x11, 0x22, 0x33)


def test_letterbox_same_size_is_passthrough():
    from app.edits.fit import letterbox

    source = _solid((64, 48), (1, 2, 3, 255))
    out = Image.open(io.BytesIO(letterbox(source, 64, 48)))
    assert out.size == (64, 48)
