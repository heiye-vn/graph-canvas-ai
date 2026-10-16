"""评测指标（M10）—— 全部是纯函数，不碰 IO。

    tool_f1         工具名多重集合的 F1（预测多调/漏调都扣分）
    exact_match     工具名序列完全一致
    slot_accuracy   参数槽位命中率（宽松：查键存在 + 类型兼容，不查具体值）

为什么槽位不查具体数值：「亮度调多少」是模型的创作判断，不是对错问题；
但「调亮度却没给 brightness」「翻转却写成方向 45 度」是硬错误。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

Number = (int, float)


def tool_f1(pred_tools: list[str], expected_tools: list[str]) -> float:
    """多重集合 F1：precision = 命中/预测数，recall = 命中/期望数。"""
    if not pred_tools and not expected_tools:
        return 1.0
    if not pred_tools or not expected_tools:
        return 0.0
    common = sum((Counter(pred_tools) & Counter(expected_tools)).values())
    precision = common / len(pred_tools)
    recall = common / len(expected_tools)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def exact_match(pred_tools: list[str], expected_tools: list[str]) -> bool:
    return pred_tools == expected_tools


def _slot_ok(pred_value: Any, spec: Any) -> bool:
    """单个槽位判定：spec 是类型名（number/integer/string/boolean）或 literal 枚举列表。"""
    if isinstance(spec, list):
        return pred_value in spec
    if spec == "number":
        return isinstance(pred_value, Number) and not isinstance(pred_value, bool)
    if spec == "integer":
        return isinstance(pred_value, int) and not isinstance(pred_value, bool)
    if spec == "string":
        return isinstance(pred_value, str)
    if spec == "boolean":
        return isinstance(pred_value, bool)
    return False


def slot_accuracy(
    pred_calls: list[dict[str, Any]],
    expected_steps: list[dict[str, Any]],
) -> float:
    """期望步骤按位置对齐预测步骤，逐槽位判命中。

    序列长度不齐时按 min(len) 对齐 —— 对不上的部分已由 F1 惩罚，这里不重复扣。
    """
    pairs = list(zip(pred_calls, expected_steps))
    if not pairs:
        return 1.0
    total, hits = 0, 0
    for pred, expected in pairs:
        slots = expected.get("slots") or {}
        args = pred.get("args") or {}
        for key, spec in slots.items():
            total += 1
            if key in args and _slot_ok(args[key], spec):
                hits += 1
    return hits / total if total else 1.0
