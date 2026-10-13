"""图层文档（LayerDocument）—— 编辑会话的唯一真相源。

为什么存的是「文档」而不是「一张合成好的图」：

    工具只改这份 JSONB，像素合成由渲染层（前端 Konva）按文档实时完成。
    声明式带来两个直接好处 ——
      1. 任意一步都可逆：把字段改回去即可，不用为每一步存一张位图
      2. Agent 与 UI 消费同一份文档，两边看到的状态必然一致；
         一旦改成「服务端合成 + 返回图」，UI 和对话里说的就不是同一件事了

读代码前必看的三条约定：

    1. **layers 的数组顺序 = 从下到上**（index 0 是最底层）。
       图层面板渲染时要倒过来显示，别在存的时候就倒序 —— 那样「索引」和
       「视觉层级」是反的，后面每个按索引写的工具都要脑内翻转一次。
    2. **id 必须唯一，name 允许重复**（同一张图插两次很常见）。
       按名查找返回**最上层**的那个；按 id 查找是精确的。
    3. 文档里只放**引用**（asset_id），绝不入 URL —— 桶是私有的，
       预签名地址有有效期，落进去就是注定过期的烂数据。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

LayerType = Literal["image", "text", "shape"]

DOC_VERSION = 1

DEFAULT_LAYER_NAME: dict[str, str] = {
    "image": "图像层",
    "text": "文字层",
    "shape": "形状层",
}


class Transform(BaseModel):
    """图层在画布上的位置与尺寸（单位：画布像素）。

    width / height 为空表示「用素材原始尺寸」—— 素材还没量过宽高时也能先占位，
    不必为了建图层先去对象存储读一次图。
    """

    x: float = 0.0
    y: float = 0.0
    width: float | None = None
    height: float | None = None
    rotation: float = 0.0


class ImageSource(BaseModel):
    asset_id: uuid.UUID


class TextContent(BaseModel):
    text: str = Field(max_length=2000)
    font_size: int = Field(default=48, gt=0, le=512)
    fill: str = Field(default="#171917", pattern=r"^#[0-9a-fA-F]{6}$")


class Adjustments(BaseModel):
    """非破坏性调色，范围 -100~100，0 表示不动。

    刻意不做成「调整图层」：MVP 阶段每个图层自带一组参数，
    工具改哪个图层的结果是确定的，不需要用户理解「作用于下方所有图层」这件事。
    """

    brightness: float = Field(default=0, ge=-100, le=100)
    contrast: float = Field(default=0, ge=-100, le=100)
    saturation: float = Field(default=0, ge=-100, le=100)
    temperature: float = Field(default=0, ge=-100, le=100)


class Layer(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str = Field(min_length=1, max_length=64)
    type: LayerType
    visible: bool = True
    locked: bool = False
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    transform: Transform = Field(default_factory=Transform)
    source: ImageSource | None = None
    text: TextContent | None = None
    adjustments: Adjustments = Field(default_factory=Adjustments)

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Layer:
        """类型与载荷必须对得上。

        这条校验是给「将来写工具的自己」准备的护栏：模型幻觉出一个
        `type=image` 却没有 asset_id 的图层时，要在写库之前就被挡住，
        而不是等前端渲染出一个打不开的空图。
        """
        if self.type == "image" and self.source is None:
            raise ValueError("image 图层必须带 source.asset_id")
        if self.type == "text" and self.text is None:
            raise ValueError("text 图层必须带 text")
        if self.type == "image" and self.text is not None:
            raise ValueError("image 图层不应带 text 载荷")
        if self.type != "image" and self.source is not None:
            raise ValueError(f"{self.type} 图层不应带 source 载荷")
        return self


class Canvas(BaseModel):
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    background: str | None = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")


class LayerDocument(BaseModel):
    version: int = DOC_VERSION
    canvas: Canvas
    layers: list[Layer] = Field(default_factory=list)
    """当前选中的图层；为空时工具默认作用于「最上层可见图像层」。"""
    active_layer_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_integrity(self) -> LayerDocument:
        if self.version != DOC_VERSION:
            raise ValueError(f"不支持的图层文档版本：{self.version}（当前支持 {DOC_VERSION}）")

        seen: set[uuid.UUID] = set()
        for layer in self.layers:
            if layer.id in seen:
                raise ValueError(f"图层 id 重复：{layer.id}")
            seen.add(layer.id)

        if self.active_layer_id is not None and self.active_layer_id not in seen:
            raise ValueError(f"active_layer_id 不存在于图层列表：{self.active_layer_id}")
        return self
