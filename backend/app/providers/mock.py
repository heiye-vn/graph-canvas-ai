"""本地占位图 Provider：不联网、不花钱，用来跑通全链路。

生成的图刻意带上 MOCK 标记——避免演示时把占位图当成模型真输出。
"""

from __future__ import annotations

import colorsys
import io
import math

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 老版本 Pillow 的 load_default 不接受 size
        return ImageFont.load_default()


def _gradient(width: int, height: int, hue_base: float) -> Image.Image:
    """用确定性色相做渐变：同一个 prompt 每次出同样的图，方便比对。"""
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / max(height - 1, 1)
        r, g, b = colorsys.hsv_to_rgb((hue_base + t * 0.15) % 1.0, 0.45, 0.92 - t * 0.25)
        draw.line([(0, y), (width, y)], fill=(int(r * 255), int(g * 255), int(b * 255)))
    return img


def _decorate(img: Image.Image, prompt: str, seed: int) -> None:
    draw = ImageDraw.Draw(img)
    width, height = img.size
    cx, cy = width / 2, height / 2
    radius = min(width, height) * 0.22

    for i in range(3):
        offset = radius * (0.35 + 0.25 * i)
        angle = seed + i * 2.1
        x = cx + math.cos(angle) * offset
        y = cy + math.sin(angle) * offset
        draw.ellipse(
            [x - radius / 2, y - radius / 2, x + radius / 2, y + radius / 2],
            outline=(255, 255, 255, 180),
            width=max(2, int(min(width, height) * 0.006)),
        )

    label = f"MOCK · {width}x{height}"
    font = _font(max(16, int(min(width, height) * 0.045)))
    draw.text((cx, cy), label, fill=(38, 42, 38), font=font, anchor="mm")

    # prompt 只画 ASCII 部分：默认字体没有中文字形，画出来是豆腐块
    ascii_prompt = "".join(ch if ord(ch) < 128 else " " for ch in prompt).strip()
    if ascii_prompt:
        small = _font(max(12, int(min(width, height) * 0.028)))
        draw.text(
            (cx, cy + min(width, height) * 0.08),
            ascii_prompt[:48],
            fill=(70, 76, 70),
            font=small,
            anchor="mm",
        )


class MockProvider:
    """满足 ImageProvider 协议（无需显式继承）。"""

    name = "mock"

    async def text_to_image(
        self, prompt: str, *, size: str = "1024x1024", n: int = 1
    ) -> list[bytes]:
        width, height = _parse_size(size)
        seed = _seed_of(prompt)

        images: list[bytes] = []
        for i in range(max(1, n)):
            img = _gradient(width, height, (seed + i * 0.11) % 1.0)
            _decorate(img, prompt, seed + i)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images.append(buf.getvalue())
        return images

    async def edit_image(self, image: bytes, prompt: str, **kwargs) -> list[bytes]:
        """占位实现：原样返回，保证调用链不炸。M6 接入真实局部重绘时替换。"""
        return [image]


def _parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1024, 1024


def _seed_of(prompt: str) -> float:
    return (sum(ord(c) for c in prompt) % 1000) / 1000.0
