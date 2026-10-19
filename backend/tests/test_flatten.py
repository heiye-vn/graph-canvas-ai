"""拍平（flatten_session）回归测试。

守的是一个真实踩过的坑（M6 引入、M7 才暴露）：
`storage.get_object` 是**同步**的（boto3，返回 bytes），曾经被写成 `await` →
TypeError 被宽 except 吞掉 → 每个图层都被静默跳过 → 拍平成一张纯白图 →
拆层照常「成功」，产物却是一张白背景 + 一个幻觉出来的白色主体。

所以这里两件事都要钉住：
    1. 图层像素真的进得了合成结果（同步调用不能被 await）
    2. 一个素材都取不到时必须**报错**，不许交白图
"""

from __future__ import annotations

import io
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image

from app.services import flatten as flatten_service
from app.services import storage

SIZE = (8, 8)
ASSET_ID = uuid.uuid4()
RED = (220, 20, 20, 255)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _doc_with_layer() -> dict:
    return {
        "canvas": {"width": SIZE[0], "height": SIZE[1], "background": "#ffffff"},
        "layers": [
            {
                "name": "原图",
                "type": "image",
                "source": {"asset_id": str(ASSET_ID)},
            }
        ],
    }


@pytest.mark.asyncio
async def test_flatten_puts_layer_pixels_on_canvas(monkeypatch):
    red = _png(Image.new("RGBA", SIZE, RED))
    seen: dict[str, object] = {}

    async def fake_get_asset(_session, _user_id, asset_id):
        seen["asset_id"] = asset_id
        return SimpleNamespace(s3_key="assets/u/x.png")

    def fake_get_object(key: str) -> bytes:
        # 故意保持同步签名：被 await 就会抛
        # 「object bytes can't be used in 'await' expression」
        seen["key"] = key
        return red

    monkeypatch.setattr("app.services.assets.get_asset", fake_get_asset)
    monkeypatch.setattr(storage, "get_object", fake_get_object)

    record = SimpleNamespace(doc=_doc_with_layer(), user_id=uuid.uuid4())
    out = await flatten_service.flatten_session(None, record)

    assert seen["asset_id"] == ASSET_ID
    assert seen["key"] == "assets/u/x.png"
    pixels = Image.open(io.BytesIO(out)).convert("RGB")
    assert pixels.getpixel((4, 4)) == RED[:3]


@pytest.mark.asyncio
async def test_flatten_raises_instead_of_returning_blank(monkeypatch):
    async def fake_get_asset(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="素材不存在")

    monkeypatch.setattr("app.services.assets.get_asset", fake_get_asset)

    record = SimpleNamespace(doc=_doc_with_layer(), user_id=uuid.uuid4())
    with pytest.raises(RuntimeError, match="拍平失败"):
        await flatten_service.flatten_session(None, record)


@pytest.mark.asyncio
async def test_flatten_allows_canvas_only_document(monkeypatch):
    """没有引用任何素材的空文档照常拍平 —— 报错只针对「该有素材却没有」."""

    def fake_get_object(_key: str) -> bytes:  # pragma: no cover - 不该被调用
        raise AssertionError("空文档不该去对象存储取东西")

    monkeypatch.setattr(storage, "get_object", fake_get_object)

    doc = {"canvas": {"width": SIZE[0], "height": SIZE[1], "background": "#ffffff"}, "layers": []}
    record = SimpleNamespace(doc=doc, user_id=uuid.uuid4())
    out = await flatten_service.flatten_session(None, record)

    pixels = Image.open(io.BytesIO(out)).convert("RGB")
    assert pixels.getpixel((0, 0)) == (255, 255, 255)
