"""点选分割：归一化点击坐标 → 物体遮罩。

两条路径，按 `MATTING_PROVIDER` 决定：

    sam     rembg 的 SAM 会话（encoder/decoder 两个 onnx 模型）。
            首次点击算 embedding（慢，秒级），后续同图点击只跑 decoder（快）
            —— 这就是 DoD ④「连续点击响应明显变快」的来源。
    circle  纯 Pillow 画圆。不装模型也能用，选中范围是个圆而非物体轮廓。
    auto    先试 SAM，任何异常（未装 rembg / 模型缺失 / 推理失败）都静默
            降级到画圆 —— 演示环境不为一个可选依赖崩掉。

embedding 缓存的纪律（M6 关键设计 ④）：
    上限 4 + OrderedDict LRU + Lock。键是原图 bytes 的 sha256 ——
    同一张图换提示点只重跑 decoder；换图/换会话自然失效。
"""

from __future__ import annotations

import hashlib
import io
from collections import OrderedDict
from threading import Lock

from PIL import Image, ImageDraw

from app.config import get_settings
from app.edits.mask import overlay_png

_CACHE_LIMIT = 4
_lock = Lock()
_embeddings: OrderedDict[str, object] = OrderedDict()
_sam = None


def segment_points(image: bytes, points: list[tuple[float, float]]) -> bytes:
    """按归一化点选生成选区可视化 PNG。同一张图的 embedding 只算一次。"""
    source = Image.open(io.BytesIO(image)).convert("RGB")
    if not points:
        return overlay_png(Image.new("L", source.size, 0))

    provider = get_settings().matting_provider
    if provider == "circle":
        return overlay_png(_circles(source.size, points))
    try:
        return overlay_png(_sam_mask(source, image, points))
    except Exception:
        if provider == "sam":
            raise
        return overlay_png(_circles(source.size, points))


def _circles(size: tuple[int, int], points: list[tuple[float, float]]) -> Image.Image:
    """降级路径：以点击点为圆心画圆。半径取短边的 16%，点小物件偏大但可用。"""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    radius = max(16, int(min(size) * 0.16))
    for nx, ny in points:
        x, y = nx * size[0], ny * size[1]
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)
    return mask


def _sam_mask(
    source: Image.Image, raw: bytes, points: list[tuple[float, float]]
) -> Image.Image:
    session = _sam_session()
    embedding = _embedding_of(session, raw, source)
    prompt = [
        {"type": "point", "label": 1, "data": [int(x * source.width), int(y * source.height)]}
        for x, y in points
    ]
    return _decode(session, embedding, prompt)


def _sam_session():
    global _sam
    with _lock:
        if _sam is None:
            from rembg.session_factory import new_session

            _sam = new_session("sam", sam_quant=True)
        return _sam


def _embedding_of(session, raw: bytes, source: Image.Image):
    key = hashlib.sha256(raw).hexdigest()
    with _lock:
        cached = _embeddings.get(key)
        if cached is not None:
            _embeddings.move_to_end(key)
            return cached

    embedding = _encode(session, source)
    with _lock:
        _embeddings[key] = embedding
        _embeddings.move_to_end(key)
        while len(_embeddings) > _CACHE_LIMIT:
            _embeddings.popitem(last=False)
    return embedding


def _encode(session, source: Image.Image):
    """encoder 只跑一次：把原图编码成 SAM 的 image embedding。"""
    import numpy as np
    from rembg.sessions.sam import warp_affine

    target = (684, 1024)
    cv_image = np.array(source.convert("RGB"))
    original_size = cv_image.shape[:2]
    scale = min(target[1] / cv_image.shape[1], target[0] / cv_image.shape[0])
    transform = np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]])
    warped = warp_affine(cv_image, transform[:2], target)
    name = session.encoder.get_inputs()[0].name
    embedding = session.encoder.run(None, {name: warped.astype(np.float32)})[0]
    return {
        "image_embedding": embedding,
        "original_size": original_size,
        "transform_matrix": transform,
        "input_size": target,
    }


def _decode(session, embedding: dict, prompt: list):
    """decoder 每次点击都跑，但相对 encoder 是毫秒级。"""
    import numpy as np
    from PIL import Image as PILImage
    from rembg.sessions.sam import apply_coords, get_input_points, transform_masks

    input_size = embedding["input_size"]
    transform = embedding["transform_matrix"]
    input_points, input_labels = get_input_points(prompt)
    onnx_coord = np.concatenate([input_points, np.array([[0.0, 0.0]])], axis=0)[None, :, :]
    onnx_label = np.concatenate([input_labels, np.array([-1])], axis=0)[None, :].astype(
        np.float32
    )
    onnx_coord = apply_coords(onnx_coord, input_size, 1024).astype(np.float32)
    onnx_coord = np.concatenate(
        [onnx_coord, np.ones((1, onnx_coord.shape[1], 1), dtype=np.float32)],
        axis=2,
    )
    onnx_coord = np.matmul(onnx_coord, transform.T)[:, :, :2].astype(np.float32)
    masks, _, _ = session.decoder.run(
        None,
        {
            "image_embeddings": embedding["image_embedding"],
            "point_coords": onnx_coord,
            "point_labels": onnx_label,
            "mask_input": np.zeros((1, 1, 256, 256), dtype=np.float32),
            "has_mask_input": np.zeros(1, dtype=np.float32),
            "orig_im_size": np.array(input_size, dtype=np.float32),
        },
    )
    masks = transform_masks(masks, embedding["original_size"], np.linalg.inv(transform))
    packed = np.zeros((masks.shape[2], masks.shape[3]), dtype=np.uint8)
    for item in masks[0]:
        packed[item > 0.0] = 255
    return PILImage.fromarray(packed, mode="L")
