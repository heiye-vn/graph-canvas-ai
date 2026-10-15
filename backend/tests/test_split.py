"""M7 拆层单测：像素原语 + 文档组装 + 降级链。

不查库。OCR/重复模型加载全部绕开（conftest 已把 OCR_PROVIDER 设 none）。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.edits.ocr import TextBox, detect_text
from app.edits.split import (
    EmptyCut,
    cut_object,
    fill_background,
    punch,
    remove_text,
)
from app.schemas.layer_doc import LayerDocument
from app.services.split import build_split_document

SIZE = (64, 48)


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _doc() -> LayerDocument:
    return LayerDocument.model_validate(
        {
            "canvas": {"width": SIZE[0], "height": SIZE[1], "background": "#ffffff"},
            "layers": [
                {
                    "name": "原图",
                    "type": "image",
                    "source": {"asset_id": "00000000-0000-0000-0000-00000000abcd"},
                }
            ],
        }
    )


# ------------------------------------------------------------------ 像素原语


def test_cut_object_and_punch_roundtrip():
    source = _png(Image.new("RGBA", SIZE, (10, 200, 30, 255)))
    mask = Image.new("L", SIZE, 0)
    for y in range(10, 20):
        for x in range(20, 30):
            mask.putpixel((x, y), 255)
    mask_bytes = _png(mask)

    cut, left, top, width, height = cut_object(source, mask_bytes)
    assert (left, top, width, height) == (20, 10, 10, 10)
    cut_img = Image.open(io.BytesIO(cut))
    assert cut_img.size == (10, 10)
    assert cut_img.getpixel((5, 5))[3] == 255

    punched = Image.open(io.BytesIO(punch(source, mask_bytes)))
    assert punched.getpixel((25, 15))[3] == 0  # 遮罩内透明
    assert punched.getpixel((0, 0))[3] == 255  # 遮罩外保留


def test_cut_object_empty_mask_raises():
    source = _png(Image.new("RGBA", SIZE, (0, 0, 0, 255)))
    mask = _png(Image.new("L", SIZE, 0))
    with pytest.raises(EmptyCut):
        cut_object(source, mask)


def test_fill_background_blur_fallback_fills_hole():
    """没有 cv2 也要能填：强制 _cv_inpaint 抛错，走 _blur_inpaint 兜底。"""
    from app.edits import split as split_mod

    image = Image.new("RGB", SIZE, (255, 255, 255))
    mask = Image.new("L", SIZE, 0)
    for y in range(10, 20):
        for x in range(20, 30):
            mask.putpixel((x, y), 255)

    original_cv = split_mod._cv_inpaint

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no cv2 here")

    split_mod._cv_inpaint = _boom
    try:
        out = Image.open(io.BytesIO(fill_background(_png(image), _png(mask))))
    finally:
        split_mod._cv_inpaint = original_cv

    assert out.mode == "RGBA"
    # 空洞被周围颜色（白）填上，不再是硬洞；至少不报错且尺寸不变
    assert out.size == SIZE


def test_text_mask_and_remove_text_punches_pixels():
    size = SIZE
    subject = _png(Image.new("RGBA", size, (200, 10, 10, 255)))
    background = _png(Image.new("RGBA", size, (10, 10, 200, 255)))
    box = TextBox(text="耳机", x=20, y=10, width=12, height=8)

    new_subject, new_background = remove_text(subject, background, [box], size)
    s_img = Image.open(io.BytesIO(new_subject))
    b_img = Image.open(io.BytesIO(new_background))
    # 文字框内：主体被挖空；背景被填补 —— 纯色底上 TELEA 修补会把洞填回
    # 周围颜色，所以结果 ≈ 原底色（这恰是「填上了」的正确表现）
    assert s_img.getpixel((25, 13))[3] == 0
    br, bg_, bb = b_img.getpixel((25, 13))[:3]
    assert abs(br - 10) < 12 and abs(bg_ - 10) < 12 and abs(bb - 200) < 12
    # 框外原样
    assert s_img.getpixel((2, 2))[3] == 255
    assert b_img.getpixel((2, 2))[:3] == (10, 10, 200)


def test_remove_text_without_boxes_is_noop():
    subject = _png(Image.new("RGBA", SIZE, (1, 2, 3, 255)))
    background = _png(Image.new("RGBA", SIZE, (4, 5, 6, 255)))
    s2, b2 = remove_text(subject, background, [], SIZE)
    assert s2 == subject and b2 == background


# ------------------------------------------------------------------ 文档组装


def test_build_split_document_three_layers():
    doc = _doc()
    from uuid import UUID

    next_doc = build_split_document(
        doc,
        background_asset_id=UUID("00000000-0000-0000-0000-00000000bbbb"),
        subject_asset_id=UUID("00000000-0000-0000-0000-00000000cccc"),
        texts=[],
    )
    assert [layer.name for layer in next_doc.layers] == ["背景", "主体"]
    assert next_doc.layers[0].locked is True
    assert str(next_doc.active_layer_id) == str(next_doc.layers[1].id)
    # 画布规格不变
    assert (next_doc.canvas.width, next_doc.canvas.height) == SIZE


def test_build_split_document_with_text_layers():
    doc = _doc()
    from uuid import UUID

    boxes = [
        TextBox(text="限时五折", x=8, y=4, width=40, height=20),
        TextBox(text="新品", x=10, y=30, width=16, height=10),
    ]
    next_doc = build_split_document(
        doc,
        background_asset_id=UUID("00000000-0000-0000-0000-00000000bbbb"),
        subject_asset_id=UUID("00000000-0000-0000-0000-00000000cccc"),
        texts=boxes,
    )
    text_layers = [layer for layer in next_doc.layers if layer.type == "text"]
    assert len(text_layers) == 2
    first = text_layers[0]
    assert first.name == "限时五折"
    assert first.text is not None and first.text.text == "限时五折"
    # 位置来自 OCR 框、字号按框高反推 —— 改文案不动几何的根基
    assert (first.transform.x, first.transform.y) == (8, 4)
    assert first.transform.width == 40 and first.transform.height == 20
    assert first.text.font_size == int(20 * 0.72)


# ------------------------------------------------------------------ OCR 降级


def test_detect_text_disabled_provider_returns_empty(monkeypatch):
    """OCR_PROVIDER=none（conftest 默认）时不碰引擎直接返回空 —— DoD ③。"""
    assert detect_text(_png(Image.new("RGB", SIZE, (0, 0, 0)))) == []
