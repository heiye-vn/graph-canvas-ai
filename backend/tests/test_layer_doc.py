"""图层文档（纯函数层，不碰数据库）。

这组用例守三件事：
    1. **文档不能被写坏** —— 坏文档一旦进库，前端渲染和第 4 个月起的工具全废
    2. **图层顺序的语义** —— 数组从下到上，别的地方都建立在这个约定上
    3. **resolve_layer 的默认值** —— UI 与 Agent 共用，行为必须锁死
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.layer_doc import Adjustments, Canvas, Layer, LayerDocument, Transform
from app.services import layer_doc as svc


def image_layer(name: str = "图像层", visible: bool = True) -> Layer:
    return Layer(name=name, type="image", visible=visible, source={"asset_id": uuid.uuid4()})


def doc_with(*layers: Layer) -> LayerDocument:
    return LayerDocument(canvas=Canvas(width=512, height=512), layers=list(layers))


def layer_with(**kwargs) -> Layer:
    payload = {"type": "image", "source": {"asset_id": uuid.uuid4()}}
    payload.update(kwargs)
    if "name" not in payload:
        payload["name"] = "图像层"
    return Layer(**payload)


# ---------------------------------------------------------------- 文档结构校验


def test_empty_layer_list_is_allowed():
    doc = doc_with()
    assert doc.layers == []
    assert doc.active_layer_id is None


def test_image_layer_requires_source():
    with pytest.raises(ValidationError) as exc:
        Layer(name="缺素材的图像层", type="image", source=None)
    assert "source.asset_id" in str(exc.value)


def test_text_layer_requires_text_payload():
    with pytest.raises(ValidationError):
        Layer(name="缺文字的文字层", type="text", source=None)


def test_image_layer_rejects_text_payload():
    with pytest.raises(ValidationError) as exc:
        Layer(
            name="混载荷",
            type="image",
            source={"asset_id": uuid.uuid4()},
            text={"text": "hi", "font_size": 32, "fill": "#ffffff"},
        )
    assert "不应带 text" in str(exc.value)


def test_duplicate_layer_ids_are_rejected():
    shared = uuid.uuid4()
    with pytest.raises(ValidationError) as exc:
        doc_with(
            layer_with(id=shared, name="A"),
            layer_with(id=shared, name="B"),
        )
    assert "图层 id 重复" in str(exc.value)


def test_duplicate_names_are_allowed():
    """重名必须允许：同一张素材被插入两次是很正常的操作。"""
    doc = doc_with(layer_with(name="图像层"), layer_with(name="图像层"))
    assert len(doc.layers) == 2


def test_active_layer_id_must_exist():
    with pytest.raises(ValidationError) as exc:
        LayerDocument(
            canvas=Canvas(width=8, height=8),
            layers=[layer_with()],
            active_layer_id=uuid.uuid4(),
        )
    assert "active_layer_id" in str(exc.value)


def test_unknown_doc_version_is_rejected():
    with pytest.raises(ValidationError) as exc:
        LayerDocument(version=99, canvas=Canvas(width=8, height=8))
    assert "版本" in str(exc.value)


def test_opacity_and_adjustments_are_clamped():
    with pytest.raises(ValidationError):
        Adjustments(brightness=120)
    with pytest.raises(ValidationError):
        layer_with(opacity=1.5)
    assert Adjustments(brightness=100).brightness == 100


def test_background_must_be_hex_color():
    with pytest.raises(ValidationError):
        Canvas(width=8, height=8, background="white")


# ---------------------------------------------------------------- 顺序语义


def test_layers_array_is_bottom_up():
    bottom = layer_with(name="底")
    top = layer_with(name="顶")
    doc = doc_with(bottom, top)

    assert doc.layers[0].name == "底"  # 存储顺序：index 0 在最下
    assert svc.top_down(doc)[0].name == "顶"  # 面板渲染：最上层在前
    assert svc.top_down(doc)[-1].name == "底"


def test_add_layer_appends_to_top():
    doc = doc_with(layer_with(name="底"))
    updated = svc.add_layer(doc, layer_with(name="新"))

    assert updated.layers[-1].name == "新"
    assert len(doc.layers) == 1  # 入参未被修改


def test_add_layer_revalidates_result():
    """追加后仍跑一遍完整校验：unique id / version 这些约束不会被绕过。"""
    doc = doc_with(layer_with(name="底"))
    duplicate = Layer.model_validate(doc.layers[0].model_dump())
    with pytest.raises(ValidationError):
        svc.add_layer(doc, duplicate)


# ---------------------------------------------------------------- resolve_layer


def test_resolve_by_id_is_exact():
    wanted = layer_with(name="目标")
    doc = doc_with(layer_with(name="无关"), wanted)

    assert svc.resolve_layer(doc, wanted.id) is wanted
    assert svc.resolve_layer(doc, str(wanted.id)) is wanted
    assert svc.resolve_layer(doc, {"id": str(wanted.id)}) is wanted


def test_resolve_by_name_takes_topmost():
    doc = doc_with(layer_with(name="同名"), layer_with(name="同名"))
    bottom, top = doc.layers

    assert svc.resolve_layer(doc, "同名") is top
    assert svc.resolve_layer(doc, {"name": "同名"}) is top
    assert bottom is not top


def test_resolve_default_is_topmost_visible_image_layer():
    doc = doc_with(
        layer_with(name="隐藏的", visible=False),
        layer_with(name="底下"),
        Layer(name="文字层", type="text", source=None, text={"text": "x"}),
    )
    assert svc.resolve_layer(doc).name == "底下"


def test_hidden_layers_are_not_the_default():
    doc = doc_with(layer_with(name="唯一", visible=False))
    with pytest.raises(svc.LayerNotFoundError):
        svc.resolve_layer(doc)


def test_text_layer_is_never_the_default():
    doc = doc_with(Layer(name="文字层", type="text", source=None, text={"text": "x"}))
    with pytest.raises(svc.LayerNotFoundError):
        svc.resolve_layer(doc)


def test_missing_ref_raises_instead_of_silently_falling_back():
    doc = doc_with(layer_with(name="A"))
    with pytest.raises(svc.LayerNotFoundError):
        svc.resolve_layer(doc, "不存在的图层")
    with pytest.raises(svc.LayerNotFoundError):
        svc.resolve_layer(doc, uuid.uuid4())


def test_empty_ref_dict_raises():
    doc = doc_with(layer_with())
    with pytest.raises(svc.LayerNotFoundError):
        svc.resolve_layer(doc, {})


def test_remove_layer_clears_active_pointer():
    target = layer_with(name="待删")
    doc = doc_with(target)
    doc = LayerDocument.model_validate(
        {**doc.model_dump(mode="json"), "active_layer_id": str(target.id)}
    )

    updated = svc.remove_layer(doc, target.id)
    assert updated.layers == []
    assert updated.active_layer_id is None


def test_remove_unknown_layer_raises():
    doc = doc_with(layer_with())
    with pytest.raises(svc.LayerNotFoundError):
        svc.remove_layer(doc, uuid.uuid4())


# ---------------------------------------------------------------- 工厂函数


def test_new_image_layer_defaults():
    asset_id = uuid.uuid4()
    layer = svc.new_image_layer(asset_id, width=640, height=480)

    assert layer.type == "image"
    assert layer.source is not None and layer.source.asset_id == asset_id
    assert layer.visible is True
    assert layer.opacity == 1.0
    assert isinstance(layer.transform, Transform)
    assert (layer.transform.width, layer.transform.height) == (640, 480)


def test_empty_doc_has_no_layers():
    doc = svc.empty_doc(1024, 768)
    assert (doc.canvas.width, doc.canvas.height) == (1024, 768)
    assert doc.layers == []
