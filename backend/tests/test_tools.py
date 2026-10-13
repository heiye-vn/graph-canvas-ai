"""工具契约与注册表（纯逻辑，不碰数据库）。

这组用例守的是那条「一处定义三处消费」的承诺：
同一份 pydantic 模型，既要给服务端校验用，又要派生出给模型的 function schema，
还要下发成前端表单。任何一处派生错了，表现都是「界面上有、模型调不动」这类
极难定位的问题。
"""

from __future__ import annotations

import re
import uuid

import pytest
from pydantic import BaseModel, Field

from app.schemas.layer_doc import Canvas, ImageSource, Layer, LayerDocument
from app.services import tool_exec
from app.tools.base import ToolContext, ToolError, param_meta
from app.tools.builtins import AddImageLayerParams, AdjustColorParams
from app.tools.registry import all_tools, function_schemas, get_tool, metadata

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def image_layer(name: str, visible: bool = True) -> Layer:
    return Layer(
        name=name,
        type="image",
        visible=visible,
        source=ImageSource(asset_id=uuid.uuid4()),
    )


def doc_with(*layers: Layer) -> LayerDocument:
    return LayerDocument(
        canvas=Canvas(width=512, height=512),
        layers=list(layers),
        active_layer_id=layers[-1].id if layers else None,
    )


def ctx_of(doc: LayerDocument, **pinned) -> ToolContext:
    return ToolContext(session_id=uuid.uuid4(), user_id=uuid.uuid4(), doc=doc, pinned=pinned)


# ------------------------------------------------------------------ 注册表


def test_registry_is_populated():
    names = {spec.name for spec in all_tools()}
    assert "adjust_color" in names
    assert len(names) > 5


def test_metadata_has_everything_a_form_needs():
    """DoD ②：前端靠这份元数据渲染表单，缺一样就得硬编码回去。"""
    item = next(i for i in metadata() if i["name"] == "adjust_color")
    assert item["label"] == "调色"
    assert item["description"]

    brightness = next(p for p in item["params"] if p["name"] == "brightness")
    assert brightness["label"] == "明度"
    assert brightness["description"]
    assert brightness["type"] == "integer"
    assert brightness["min"] == -100 and brightness["max"] == 100
    assert brightness["default"] == 0


def test_hidden_params_are_removed_from_model_schema():
    """DoD ③：asset_id 不能出现在给模型的 schema 里，否则模型会编一个 UUID。"""
    schema = next(
        f for f in function_schemas() if f["function"]["name"] == "add_image_layer"
    )["function"]
    assert "asset_id" not in schema["parameters"]["properties"]
    assert "asset_id" not in schema["parameters"]["required"]

    spec = get_tool("add_image_layer")
    assert spec is not None and spec.hidden_params() == ["asset_id"]


def test_metadata_still_shows_hidden_params_for_the_ui():
    """隐藏是对**模型**隐藏，界面还得能传 —— 元数据里要带 agent_hidden 标记。"""
    item = next(i for i in metadata() if i["name"] == "add_image_layer")
    asset = next(p for p in item["params"] if p["name"] == "asset_id")
    assert asset["agent_hidden"] is True


def test_param_meta_marks_optional_vs_required():
    """有默认值 = 选填；没有默认值 = 必填。前端据此决定要不要标红。"""

    class RequiredDemo(BaseModel):
        name: str = Field(description="必填字段", json_schema_extra={"label": "名字"})
        note: str = Field(default="", description="选填字段", json_schema_extra={"label": "备注"})

    meta = {item["name"]: item for item in param_meta(RequiredDemo)}
    assert meta["name"]["required"] is True
    assert meta["name"]["label"] == "名字"
    assert meta["note"]["required"] is False

    layer = next(p for p in param_meta(AdjustColorParams) if p["name"] == "layer")
    assert layer["required"] is False  # 不填 = 作用于当前图层
    assert layer["default"] is None


# ------------------------------------------------------------------ 执行


async def test_adjust_color_updates_the_target_layer():
    doc = doc_with(image_layer("底"), image_layer("顶"))
    result = await tool_exec.invoke(
        "adjust_color", {"layer": "底", "brightness": 30}, ctx_of(doc)
    )
    updated = next(layer for layer in result.doc.layers if layer.name == "底")
    assert updated.adjustments.brightness == 30
    assert result.message


async def test_default_target_is_the_topmost_visible_image_layer():
    doc = doc_with(image_layer("隐藏", visible=False), image_layer("唯一可见"))
    result = await tool_exec.invoke("adjust_color", {"contrast": 20}, ctx_of(doc))
    affected = [layer for layer in result.doc.layers if layer.adjustments.contrast == 20]
    assert len(affected) == 1 and affected[0].name == "唯一可见"


async def test_bad_param_type_is_rejected_by_server_validation():
    """DoD ④：类型错误来自服务端校验，不是让模型自己纠正。"""
    doc = doc_with(image_layer("底"))
    with pytest.raises(ToolError) as exc:
        await tool_exec.invoke("adjust_color", {"brightness": "很亮"}, ctx_of(doc))
    assert exc.value.code == "bad_params"


async def test_unknown_layer_error_lists_available_names():
    doc = doc_with(image_layer("候选图 1"), image_layer("候选图 2"))
    with pytest.raises(ToolError) as exc:
        await tool_exec.invoke("adjust_color", {"layer": "不存在"}, ctx_of(doc))
    assert "候选图 1" in exc.value.message


async def test_unknown_tool():
    with pytest.raises(ToolError) as exc:
        await tool_exec.invoke("不是工具", {}, ctx_of(doc_with()))
    assert exc.value.code == "unknown_tool"


async def test_switch_current_image_only_touches_image_layers():
    text = Layer(
        name="文案", type="text", text={"text": "促销", "font_size": 48, "fill": "#ffffff"}
    )
    doc = doc_with(image_layer("第一张"), image_layer("第二张"), text)

    result = await tool_exec.invoke("switch_current_image", {"layer": "第二张"}, ctx_of(doc))
    visible = {layer.name: layer.visible for layer in result.doc.layers}
    assert visible == {"第一张": False, "第二张": True, "文案": True}


async def test_add_image_layer_requires_an_asset():
    with pytest.raises(ToolError) as exc:
        await tool_exec.invoke("add_image_layer", {}, ctx_of(doc_with()))
    assert "素材" in exc.value.message


async def test_add_image_layer_takes_asset_from_pinned_context():
    asset_id = uuid.uuid4()
    doc = doc_with(image_layer("已有"))
    result = await tool_exec.invoke("add_image_layer", {}, ctx_of(doc, asset_id=str(asset_id)))
    assert len(result.doc.layers) == 2
    assert result.doc.layers[-1].source is not None
    assert result.doc.layers[-1].source.asset_id == asset_id


async def test_reorder_layer_bounds():
    doc = doc_with(image_layer("A"), image_layer("B"))
    with pytest.raises(ToolError):
        await tool_exec.invoke("reorder_layer", {"layer": "A", "index": 9}, ctx_of(doc))


async def test_remove_layer():
    doc = doc_with(image_layer("A"), image_layer("B"))
    result = await tool_exec.invoke("remove_layer", {"layer": "A"}, ctx_of(doc))
    assert [layer.name for layer in result.doc.layers] == ["B"]


# ------------------------------------------------------------------ 给模型的上下文


def test_doc_summary_contains_no_uuid():
    """DoD ③ 的另一半：给模型的上下文里就没有 id，模型才不会照着编。"""
    doc = doc_with(image_layer("候选图 1"), image_layer("候选图 2"))
    summary = tool_exec.summarize_doc(doc)

    assert not _UUID_RE.search(summary), f"摘要里出现了 id：{summary}"
    assert "候选图 1" in summary


def test_doc_summary_marks_the_default_target():
    doc = doc_with(image_layer("底"), image_layer("顶"))
    assert "「顶」" in tool_exec.summarize_doc(doc)


def test_doc_summary_handles_empty_canvas():
    assert "没有图层" in tool_exec.summarize_doc(doc_with())


def test_hidden_param_defaults_to_none_without_pinning():
    params = AddImageLayerParams(name="新图层")
    assert params.asset_id is None
