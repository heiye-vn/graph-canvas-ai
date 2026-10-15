"""拆层服务（M7）：把当前画面拆成 背景 / 主体 / 文字 三层。

分工：edits/split.py 是像素原语（纯函数），本模块负责数据准备与
**图层文档组装** —— 拆层的本质是一次「整份替换文档」：
背景 + 主体两个新图像层，加上 OCR 出来的若干文字层。

文字层字号按框高反推（0.72 倍），位置用 OCR 框原样 ——
「文案可改且字体位置不变」（DoD ②）靠的就是位置来自原始检测框，
而不是重排后的猜测。
"""

from __future__ import annotations

import uuid

from app.edits.ocr import TextBox
from app.schemas.layer_doc import Layer, LayerDocument, TextContent, Transform


def build_split_document(
    doc: LayerDocument,
    *,
    background_asset_id: uuid.UUID,
    subject_asset_id: uuid.UUID,
    texts: list[TextBox],
) -> LayerDocument:
    """用拆层产物组装新文档：背景（锁定）→ 主体 → 文字层们。

    走 model_validate 重新校验而不是 model_copy 塞 dict ——
    文档是唯一真相源，绕过校验写进去的坏结构会在渲染层才炸。
    """
    payload = doc.model_dump(mode="json")
    layers = [
        Layer(
            name="背景",
            type="image",
            locked=True,
            source={"asset_id": background_asset_id},
        ),
        Layer(
            name="主体",
            type="image",
            source={"asset_id": subject_asset_id},
        ),
        *[_text_layer(index, box) for index, box in enumerate(texts, start=1)],
    ]
    payload["layers"] = [layer.model_dump(mode="json") for layer in layers]
    payload["active_layer_id"] = str(layers[1].id)
    return LayerDocument.model_validate(payload)


def _text_layer(index: int, box: TextBox) -> Layer:
    width = max(8, box.width)
    height = max(12, box.height)
    return Layer(
        name=box.text[:12] or f"文字{index}",
        type="text",
        transform=Transform(x=box.x, y=box.y, width=width, height=height),
        text=TextContent(text=box.text, font_size=max(10, int(height * 0.72))),
    )
