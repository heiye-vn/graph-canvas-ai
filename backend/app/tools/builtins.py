"""M4 的内置工具。

这一批刻意全是**只改文档、不动像素**的确定性工具：M6 才引入需要 GPU/CV 的
能力（抠图、局部重绘），在那之前先让「自然语言 → 工具 → 文档 → 画布」这条链路跑通。

每个工具都遵循同一形状：
    params（pydantic） → resolve_layer → 改文档 → ToolResult(新文档, 一句话结果)

返回**新文档**而不是就地修改，是为了让调用方（现在是 API，M5 起还有撤销栈）
统一决定「要不要落库」；工具自己不知道自己处在什么事务里。
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.layer_doc import Adjustments, Crop, TextContent, Transform
from app.services import layer_doc as L
from app.tools.base import ToolContext, ToolError, ToolResult, ToolSpec
from app.tools.registry import register


class LayerRef(BaseModel):
    """所有「作用于某个图层」的工具共用这一段参数。"""

    layer: str | None = Field(
        default=None,
        description="目标图层名或 id；不填则作用于当前选中的图层",
        json_schema_extra={"label": "目标图层"},
    )


def _target(ctx: ToolContext, ref: str | None):
    """解析目标图层；找不到时给出**有用的**错误信息（带上可选图层名）。"""
    try:
        return L.resolve_layer(ctx.doc, ref)
    except L.LayerNotFoundError as exc:
        names = [layer.name for layer in L.top_down(ctx.doc)] or ["（这个会话还没有图层）"]
        raise ToolError(f"找不到图层{exc}。当前可选：{'、'.join(names)}", code="no_layer") from exc


def _layer_id(ctx: ToolContext, ref: str | None) -> uuid.UUID:
    return _target(ctx, ref).id


# ------------------------------------------------------------------ 调色


class AdjustColorParams(LayerRef):
    brightness: int = Field(
        default=0, ge=-100, le=100, description="明度，-100~100",
        json_schema_extra={"label": "明度"},
    )
    contrast: int = Field(
        default=0, ge=-100, le=100, description="对比度，-100~100",
        json_schema_extra={"label": "对比度"},
    )
    saturation: int = Field(
        default=0, ge=-100, le=100, description="饱和度，-100~100",
        json_schema_extra={"label": "饱和度"},
    )
    temperature: int = Field(
        default=0, ge=-100, le=100, description="色温，-100~100（正值为暖）",
        json_schema_extra={"label": "色温"},
    )


async def adjust_color(params: AdjustColorParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(
        ctx.doc,
        layer.id,
        {
            "adjustments": Adjustments(
                brightness=params.brightness,
                contrast=params.contrast,
                saturation=params.saturation,
                temperature=params.temperature,
            )
        },
    )
    return ToolResult(doc, f"已调整「{layer.name}」的明度/对比度/饱和度/色温")


class SetOpacityParams(LayerRef):
    opacity: float = Field(
        default=1.0, ge=0, le=1, description="不透明度，0~1",
        json_schema_extra={"label": "不透明度"},
    )


async def set_opacity(params: SetOpacityParams, ctx: ToolContext) -> ToolResult:
    layer_id = _layer_id(ctx, params.layer)
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer_id, {"opacity": params.opacity})
    return ToolResult(doc, f"「{layer.name}」的不透明度已设为 {round(params.opacity * 100)}%")


class SetVisibleParams(LayerRef):
    visible: bool = Field(
        default=True, description="是否显示",
        json_schema_extra={"label": "显示"},
    )


async def set_layer_visible(params: SetVisibleParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer.id, {"visible": params.visible})
    return ToolResult(doc, f"「{layer.name}」已{'显示' if params.visible else '隐藏'}")


class RenameLayerParams(LayerRef):
    name: str = Field(
        default="", min_length=1, max_length=64, description="新的图层名",
        json_schema_extra={"label": "图层名"},
    )


async def rename_layer(params: RenameLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer.id, {"name": params.name})
    return ToolResult(doc, f"图层已改名为「{params.name}」")


# ------------------------------------------------------------------ 变换


class ReorderLayerParams(LayerRef):
    index: int = Field(
        default=0, ge=0, description="目标层级，0 为最底层",
        json_schema_extra={"label": "层级"},
    )


async def reorder_layer(params: ReorderLayerParams, ctx: ToolContext) -> ToolResult:
    layer_id = _layer_id(ctx, params.layer)
    layer = _target(ctx, params.layer)
    if params.index >= len(ctx.doc.layers):
        raise ToolError(f"层级越界：当前只有 {len(ctx.doc.layers)} 层")
    doc = L.reorder_layer(ctx.doc, layer_id, params.index)
    return ToolResult(doc, f"「{layer.name}」已移到第 {params.index} 层")


class MoveLayerParams(LayerRef):
    x: float = Field(default=0, description="横坐标（画布像素）", json_schema_extra={"label": "X"})
    y: float = Field(default=0, description="纵坐标（画布像素）", json_schema_extra={"label": "Y"})


async def move_layer(params: MoveLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer.id, {"transform": {"x": params.x, "y": params.y}})
    return ToolResult(doc, f"「{layer.name}」已移动到 ({params.x}, {params.y})")


class ResizeLayerParams(LayerRef):
    width: int = Field(
        default=0, ge=1, le=8192, description="宽度（像素）", json_schema_extra={"label": "宽度"}
    )
    height: int = Field(
        default=0, ge=1, le=8192, description="高度（像素）", json_schema_extra={"label": "高度"}
    )


async def resize_layer(params: ResizeLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(
        ctx.doc, layer.id, {"transform": {"width": params.width, "height": params.height}}
    )
    return ToolResult(doc, f"「{layer.name}」尺寸已改为 {params.width}×{params.height}")


class RotateLayerParams(LayerRef):
    degrees: float = Field(
        default=0, ge=-360, le=360, description="旋转角度",
        json_schema_extra={"label": "角度"},
    )


async def rotate_layer(params: RotateLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer.id, {"transform": {"rotation": params.degrees}})
    return ToolResult(doc, f"「{layer.name}」已旋转 {params.degrees}°")


# ------------------------------------------------------------------ 裁剪与翻转


class CropLayerParams(LayerRef):
    x: int = Field(
        default=0, ge=0, description="裁剪区左上角横坐标（素材原始像素）",
        json_schema_extra={"label": "左边缘"},
    )
    y: int = Field(
        default=0, ge=0, description="裁剪区左上角纵坐标（素材原始像素）",
        json_schema_extra={"label": "上边缘"},
    )
    width: int = Field(
        gt=0, le=8192, description="裁剪宽度（像素）", json_schema_extra={"label": "宽度"}
    )
    height: int = Field(
        gt=0, le=8192, description="裁剪高度（像素）", json_schema_extra={"label": "高度"}
    )


async def crop_layer(params: CropLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(
        ctx.doc,
        layer.id,
        {
            "crop": Crop(x=params.x, y=params.y, width=params.width, height=params.height),
            # 显示尺寸同步为裁剪尺寸：裁下来的那一块按原大小放下，
            # 而不是把 100×100 的裁剪区拉满原本 1000×1000 的框（那是缩放，不是裁剪）
            "transform": {"width": params.width, "height": params.height},
        },
    )
    return ToolResult(doc, f"「{layer.name}」已裁剪为 {params.width}×{params.height}")


class ResetCropParams(LayerRef):
    pass


async def reset_crop(params: ResetCropParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.update_layer(ctx.doc, layer.id, {"crop": None})
    return ToolResult(doc, f"「{layer.name}」已还原完整画布")


class FlipLayerParams(LayerRef):
    direction: Literal["horizontal", "vertical"] = Field(
        default="horizontal",
        description="翻转方向：horizontal 左右，vertical 上下",
        json_schema_extra={"label": "方向"},
    )


async def flip_layer(params: FlipLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    horizontal = params.direction == "horizontal"
    key = "flip_x" if horizontal else "flip_y"
    doc = L.update_layer(ctx.doc, layer.id, {"transform": {key: not getattr(layer.transform, key)}})
    return ToolResult(doc, f"「{layer.name}」已{'左右' if horizontal else '上下'}翻转")


# ------------------------------------------------------------------ 增删图层


class AddTextLayerParams(BaseModel):
    text: str = Field(
        default="", min_length=1, max_length=2000, description="文字内容",
        json_schema_extra={"label": "文字"},
    )
    font_size: int = Field(
        default=48, gt=0, le=512, description="字号",
        json_schema_extra={"label": "字号"},
    )
    fill: str = Field(
        default="#171917", pattern=r"^#[0-9a-fA-F]{6}$", description="文字颜色，如 #171917",
        json_schema_extra={"label": "颜色"},
    )
    x: float = Field(default=0, description="横坐标", json_schema_extra={"label": "X"})
    y: float = Field(default=0, description="纵坐标", json_schema_extra={"label": "Y"})


async def add_text_layer(params: AddTextLayerParams, ctx: ToolContext) -> ToolResult:
    from app.schemas.layer_doc import Layer

    layer = Layer(
        name="文字层",
        type="text",
        transform=Transform(x=params.x, y=params.y),
        text=TextContent(text=params.text, font_size=params.font_size, fill=params.fill),
    )
    doc = L.set_active_layer(L.add_layer(ctx.doc, layer), layer.id)
    return ToolResult(doc, f"已添加文字层：「{params.text[:20]}」")


class SetLayerTextParams(LayerRef):
    """改文字层文案。图层缺省时作用于最上层可见的文字层。

    位置与字号刻意**不在参数里**（除非显式要改）：拆层产出的文字层
    位置来自 OCR 检测框，「文案可改且字体位置不变」（M7 DoD ②）
    靠的就是改文案不动几何。
    """

    text: str = Field(
        min_length=1, max_length=500, description="新的文案内容",
        json_schema_extra={"label": "文案"},
    )
    font_size: int | None = Field(
        default=None, gt=0, le=512, description="字号（不填保持不变）",
        json_schema_extra={"label": "字号"},
    )
    fill: str | None = Field(
        default=None, pattern=r"^#[0-9a-fA-F]{6}$", description="文字颜色（不填保持不变）",
        json_schema_extra={"label": "颜色"},
    )


async def set_layer_text(params: SetLayerTextParams, ctx: ToolContext) -> ToolResult:
    from app.schemas.layer_doc import TextContent

    if params.layer:
        layer = _target(ctx, params.layer)
    else:
        layer = L.topmost_visible_text_layer(ctx.doc)
        if layer is None:
            raise ToolError(
                "画布上没有文字图层：先用「拆层（同时拆出文字）」生成，或用「加文字」新建",
                code="no_text_layer",
            )
    if layer.type != "text" or layer.text is None:
        raise ToolError(f"「{layer.name}」不是文字图层，只能改文字层的文案", code="not_text")

    text = TextContent(
        text=params.text,
        font_size=params.font_size if params.font_size is not None else layer.text.font_size,
        fill=params.fill if params.fill is not None else layer.text.fill,
    )
    # 只改文案与名字，几何（transform）一律不动 —— 位置稳定性是 DoD ②
    doc = L.update_layer(
        ctx.doc,
        layer.id,
        {"text": text.model_dump(), "name": params.text[:12] or layer.name},
    )
    return ToolResult(doc, f"文字已改为：「{params.text[:20]}」")


class RemoveLayerParams(LayerRef):
    pass


async def remove_layer(params: RemoveLayerParams, ctx: ToolContext) -> ToolResult:
    layer = _target(ctx, params.layer)
    doc = L.remove_layer(ctx.doc, layer.id)
    return ToolResult(doc, f"已删除图层「{layer.name}」")


class AddImageLayerParams(BaseModel):
    """把素材库里的一张图加进会话。

    `asset_id` 标了 agent_hidden：**模型必须不知道它的存在**。
    它会自己编一个 UUID 出来；这个值只能由 UI 传入或服务端按上下文回填。
    """

    asset_id: str | None = Field(
        default=None,
        description="素材 id（由界面选择，不由模型填写）",
        json_schema_extra={"label": "素材", "agent_hidden": True},
    )
    name: str | None = Field(
        default=None, max_length=64, description="图层名；不填用素材类型默认名",
        json_schema_extra={"label": "图层名"},
    )


async def add_image_layer(params: AddImageLayerParams, ctx: ToolContext) -> ToolResult:
    from app.schemas.layer_doc import Layer

    asset_id = params.asset_id or ctx.pinned.get("asset_id")
    if not asset_id:
        raise ToolError("缺少素材：请先在界面上选一张图", code="no_asset")

    doc = L.add_layer(
        ctx.doc,
        Layer(
            name=params.name or "图像层",
            type="image",
            source={"asset_id": asset_id},
        ),
    )
    return ToolResult(doc, "已把这张素材加为新的图像层")


class SwitchCurrentImageParams(LayerRef):
    pass


async def switch_current_image(params: SwitchCurrentImageParams, ctx: ToolContext) -> ToolResult:
    layer_id = _layer_id(ctx, params.layer)
    layer = _target(ctx, params.layer)
    doc = L.switch_current_image(ctx.doc, layer_id)
    return ToolResult(doc, f"已把「{layer.name}」设为当前图")


class SetCanvasBackgroundParams(BaseModel):
    color: str = Field(
        default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$", description="背景色，如 #ffffff",
        json_schema_extra={"label": "背景色"},
    )


async def set_canvas_background(params: SetCanvasBackgroundParams, ctx: ToolContext) -> ToolResult:
    doc = L.LayerDocument.model_validate(
        {
            **ctx.doc.model_dump(mode="json"),
            "canvas": {**ctx.doc.canvas.model_dump(mode="json"), "background": params.color},
        }
    )
    return ToolResult(doc, f"画布背景已改为 {params.color}")


# ------------------------------------------------------------------ 注册


def _tool(
    name: str,
    label: str,
    description: str,
    params_model: type[BaseModel],
    handler: Any,
    group: str,
) -> None:
    """注册一个内置工具。

    参数按固定顺序传是为了让下面那张清单**一眼能扫完**：
    加工具时照抄一行再改，比对着一堆关键字参数找位置不容易漏。
    """
    register(
        ToolSpec(
            name=name,
            label=label,
            description=description,
            params_model=params_model,
            handler=handler,
            group=group,
        )
    )


def install_builtin_tools() -> None:
    _tool(
        "adjust_color", "调色",
        "调整某个图层的明度、对比度、饱和度、色温",
        AdjustColorParams, adjust_color, "调色",
    )
    _tool(
        "set_opacity", "不透明度",
        "设置图层的不透明度（0 完全透明，1 完全不透明）",
        SetOpacityParams, set_opacity, "图层",
    )
    _tool(
        "set_layer_visible", "显示/隐藏",
        "显示或隐藏某个图层",
        SetVisibleParams, set_layer_visible, "图层",
    )
    _tool(
        "rename_layer", "改名",
        "给图层改名",
        RenameLayerParams, rename_layer, "图层",
    )
    _tool(
        "reorder_layer", "调整层级",
        "把图层移到指定层级（0 为最底层）",
        ReorderLayerParams, reorder_layer, "图层",
    )
    _tool(
        "switch_current_image", "切换当前图",
        "把某张候选图设为当前图（其余候选自动隐藏）",
        SwitchCurrentImageParams, switch_current_image, "图层",
    )
    _tool(
        "remove_layer", "删除图层",
        "删除某个图层",
        RemoveLayerParams, remove_layer, "图层",
    )
    _tool(
        "add_image_layer", "加入素材",
        "把素材库里的一张图加进会话（素材由界面选择）",
        AddImageLayerParams, add_image_layer, "图层",
    )
    _tool(
        "move_layer", "移动",
        "移动图层到指定坐标",
        MoveLayerParams, move_layer, "变换",
    )
    _tool(
        "resize_layer", "尺寸",
        "调整图层的宽高",
        ResizeLayerParams, resize_layer, "变换",
    )
    _tool(
        "rotate_layer", "旋转",
        "旋转图层",
        RotateLayerParams, rotate_layer, "变换",
    )
    _tool(
        "add_text_layer", "加文字",
        "新增一个文字层（文案、字号、颜色、位置）",
        AddTextLayerParams, add_text_layer, "内容",
    )
    _tool(
        "set_canvas_background", "画布背景",
        "设置画布背景色",
        SetCanvasBackgroundParams, set_canvas_background, "画布",
    )
    _tool(
        "crop_layer", "裁剪",
        "裁剪某个图层到指定区域（按素材原始像素）",
        CropLayerParams, crop_layer, "变换",
    )
    _tool(
        "reset_crop", "还原裁剪",
        "取消某个图层的裁剪，露出完整画面",
        ResetCropParams, reset_crop, "变换",
    )
    _tool(
        "flip_layer", "翻转",
        "左右或上下翻转某个图层（再执行一次可翻回来）",
        FlipLayerParams, flip_layer, "变换",
    )
    _tool(
        "set_layer_text", "改文字",
        "修改文字图层的文案，可选字号与颜色。未指定图层时改最上层可见文字。",
        SetLayerTextParams, set_layer_text, "编辑",
    )


install_builtin_tools()
