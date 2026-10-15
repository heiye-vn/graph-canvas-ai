"""画面文字检测（M7）：返回文字框列表。

OCR 是**可选依赖**（rapidocr-onnxruntime，装在 cv extra 里）：
    none      直接返回空 —— 拆层仍可用，只是没有文字层
    auto      装了就用，任何异常（未装/模型缺失/识别失败）静默返回空
    rapidocr  强制模式，失败向上抛（给测试与排障用）

引擎进程级单例：RapidOCR 初始化要加载检测+识别两个模型，不能每次点拆层都来一遍。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from app.config import get_settings


@dataclass(frozen=True)
class TextBox:
    text: str
    x: int
    y: int
    width: int
    height: int


_engine = None


def detect_text(data: bytes) -> list[TextBox]:
    """识别画面中的文字框。未安装 OCR 或识别失败时返回空列表（DoD ③）。"""
    if get_settings().ocr_provider == "none":
        return []
    try:
        boxes = _rapidocr(data)
    except Exception:
        if get_settings().ocr_provider == "rapidocr":
            raise
        return []
    return [box for box in boxes if box.text.strip() and box.width > 2 and box.height > 2]


def _rapidocr(data: bytes) -> list[TextBox]:
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR

    global _engine
    if _engine is None:
        _engine = RapidOCR()

    image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    result, _ = _engine(image)
    if not result:
        return []

    boxes: list[TextBox] = []
    for item in result:
        quad, text, _score = item[0], item[1], item[2]
        xs = [point[0] for point in quad]
        ys = [point[1] for point in quad]
        left, top = int(min(xs)), int(min(ys))
        boxes.append(
            TextBox(
                text=str(text).strip(),
                x=left,
                y=top,
                width=max(1, int(max(xs) - left)),
                height=max(1, int(max(ys) - top)),
            )
        )
    return boxes
