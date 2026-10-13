"""图层文档的读写工具（纯函数，不碰数据库）。

这个模块的存在感来自一条约定：**「改哪个图层」这件事只能有一个答案**。

UI 里用户选中了某一层，Agent 里模型说「把背景调亮一点」——两者最终要落到同一个
图层对象上。如果 UI 走一套查找规则、Agent 走另一套，同一个操作在两个地方结果就
不一样了，而且极难复现。所以 `resolve_layer()` 是唯一入口，两边共享同一个默认值
（不指定时取「最上层可见图像层」）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.layer_doc import (
    DEFAULT_LAYER_NAME,
    Canvas,
    ImageSource,
    Layer,
    LayerDocument,
    Transform,
)

LayerRef = uuid.UUID | str | dict[str, Any] | None

_NOT_FOUND_MSG = "找不到匹配的图层"


class LayerNotFoundError(LookupError):
    """按 id / 名称找不到图层，或文档里根本没有可作为默认值的图层。"""

    def __init__(self, ref: LayerRef = None) -> None:
        self.ref = ref
        detail = "" if ref is None else f"：{ref}"
        super().__init__(f"{_NOT_FOUND_MSG}{detail}")


def empty_doc(width: int, height: int) -> LayerDocument:
    return LayerDocument(canvas=Canvas(width=width, height=height))


def new_image_layer(
    asset_id: uuid.UUID,
    *,
    width: float | None = None,
    height: float | None = None,
    name: str | None = None,
) -> Layer:
    """按素材建一个图像层。

    transform 里的 width/height 来自素材自身尺寸；拿不到尺寸的素材也能先占位
    （None 表示「用原始尺寸」），不必为了建图层先去对象存储读一遍图。
    """
    return Layer(
        name=name or DEFAULT_LAYER_NAME["image"],
        type="image",
        transform=Transform(width=width, height=height),
        source=ImageSource(asset_id=asset_id),
    )


def top_down(doc: LayerDocument) -> list[Layer]:
    """从最上层到最底层的顺序 —— 图层面板渲染与「按名查找」都用这个顺序。"""
    return list(reversed(doc.layers))


def topmost_visible_image_layer(doc: LayerDocument) -> Layer | None:
    """默认图层：最上层**可见**的 image 层。

    只认 image 类型是有意的：文字层 / 形状层没有像素来源，
    让它们成为「调色」「抠图」这类操作的默认目标，只会得到一团乱。
    """
    for layer in top_down(doc):
        if layer.visible and layer.type == "image":
            return layer
    return None


def add_layer(doc: LayerDocument, layer: Layer) -> LayerDocument:
    """把图层追加为**最上层**并返回新文档（不修改入参）。"""
    updated = doc.model_copy(deep=True)
    updated.layers.append(layer)
    return LayerDocument.model_validate(updated.model_dump(mode="json"))


def remove_layer(doc: LayerDocument, layer_id: uuid.UUID) -> LayerDocument:
    """删除图层；连带的 active_layer_id 一并清空。"""
    updated = doc.model_copy(deep=True)
    remaining = [layer for layer in updated.layers if layer.id != layer_id]
    if len(remaining) == len(updated.layers):
        raise LayerNotFoundError(str(layer_id))
    updated.layers = remaining
    if updated.active_layer_id == layer_id:
        updated.active_layer_id = None
    return LayerDocument.model_validate(updated.model_dump(mode="json"))


def resolve_layer(doc: LayerDocument, ref: LayerRef = None) -> Layer:
    """定位图层 —— UI 选中态与 Agent 工具都必须从这里走。

    ref 支持四种形态，覆盖从「精确」到「什么都不说」：

        uuid.UUID / UUID 字符串   -> 按 id 精确匹配
        {"id": ...}               -> 同上
        普通字符串 / {"name": ..} -> 按名称匹配，**取最上层**（重名时的确定规则）
        None                      -> 最上层可见图像层

    找不到一律抛 LayerNotFoundError。**绝不悄悄回退到「第一个图层」** ——
    那会让用户以为在改 A，实际改了 B。
    """
    if isinstance(ref, dict):
        ref = ref.get("id") or ref.get("name")
        if ref is None:
            raise LayerNotFoundError(ref)

    if ref is None:
        layer = topmost_visible_image_layer(doc)
        if layer is None:
            raise LayerNotFoundError()
        return layer

    raw = str(ref)
    try:
        wanted_id = uuid.UUID(raw)
    except ValueError:
        wanted_id = None

    if wanted_id is not None:
        for layer in doc.layers:
            if layer.id == wanted_id:
                return layer
        raise LayerNotFoundError(raw)

    for layer in top_down(doc):
        if layer.name == raw:
            return layer
    raise LayerNotFoundError(raw)
