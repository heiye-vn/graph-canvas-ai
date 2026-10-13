"""工具执行 + 画布现状摘要。

`invoke()`：工具调用的唯一入口（API 与 Agent 共用同一条路径 —— 同一把工具，
两条执行路径，迟早会出现「手动点一次和让模型做一次结果不一样」）。

`summarize_doc()`：给模型看的画布现状。**这里刻意不出现任何 UUID** ——
模型一旦看见 id，就会在下次调用里凭记忆编造一个（DoD ③）。
图层用「名字 + 类型 + 是否可见 + 层级序号」描述，足够定位，又不给幻觉留素材。
"""

from __future__ import annotations

from app.schemas.layer_doc import LayerDocument
from app.services import layer_doc as L
from app.tools.base import ToolContext, ToolError, ToolResult
from app.tools.registry import get_tool


async def invoke(name: str, raw_params: dict, ctx: ToolContext) -> ToolResult:
    spec = get_tool(name)
    if spec is None:
        raise ToolError(f"未知工具：{name}", code="unknown_tool")

    params = spec.parse(raw_params, ctx)
    return await spec.handler(params, ctx)


def summarize_doc(doc: LayerDocument) -> str:
    """给模型的画布现状（不含任何 id）。"""
    if not doc.layers:
        lines = ["（画布上还没有图层）"]
    else:
        lines: list[str] = []
        for index, layer in enumerate(L.top_down(doc)):
            depth = len(doc.layers) - 1 - index  # 转成「0 = 最底层」的编号
            state = "可见" if layer.visible else "隐藏"
            current = "（当前选中）" if layer.id == doc.active_layer_id else ""
            lines.append(f"- 第{depth}层「{layer.name}」{_type_label(layer.type)} {state}{current}")

    current = L.topmost_visible_image_layer(doc)
    head = f"画布 {doc.canvas.width}×{doc.canvas.height}，共 {len(doc.layers)} 个图层"
    if current is not None:
        head += f"；默认操作目标（不指定图层时）：「{current.name}」"
    return "\n".join([head, "图层（从上到下）：", *lines])


def _type_label(layer_type: str) -> str:
    return {"image": "图像层", "text": "文字层", "shape": "形状层"}.get(layer_type, layer_type)
