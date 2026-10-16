"""M10 评测框架测试 —— 全部打桩，不打真实模型（真实模型走 `python -m app.eval.run`）。

钉死四件事：
    ① 指标计算正确（F1 的多调/漏调、EM、槽位类型兼容）
    ② runner 端到端：桩 planner → 聚合报告
    ③ 门禁语义：低于基线出违规清单，容差内通过
    ④ cases.json 结构合法且 ≥30 条（DoD ①）、工具名全部真实存在
"""

from __future__ import annotations

import pytest

from app.agent import plan as plan_mod
from app.eval import compare, load_cases, run_eval
from app.eval.metrics import exact_match, slot_accuracy, tool_f1
from app.tools.registry import all_tools

# ------------------------------------------------------------------ 指标纯函数


def test_tool_f1_perfect_and_partial():
    assert tool_f1(["adjust_color"], ["adjust_color"]) == 1.0
    assert tool_f1(["adjust_color", "flip_layer"], ["adjust_color"]) == pytest.approx(2 / 3)
    # 多调
    assert tool_f1(["adjust_color", "flip_layer"], ["adjust_color"]) == pytest.approx(2 / 3)
    # 漏调 + 错调
    assert tool_f1(["move_layer"], ["adjust_color", "flip_layer"]) == 0.0
    # 双方为空
    assert tool_f1([], []) == 1.0
    # 重复调用也要按多重集合算
    assert tool_f1(["adjust_color"] * 2, ["adjust_color"]) == pytest.approx(2 / 3)


def test_exact_match_order_sensitive():
    assert exact_match(["a", "b"], ["a", "b"])
    assert not exact_match(["b", "a"], ["a", "b"])


def test_slot_accuracy_type_compat():
    calls = [{"args": {"brightness": 30, "direction": "horizontal"}}]
    steps = [{"slots": {"brightness": "number", "direction": ["horizontal"]}}]
    assert slot_accuracy(calls, steps) == 1.0

    # boolean 不能冒充 number
    assert not slot_accuracy(
        [{"args": {"brightness": True}}], [{"slots": {"brightness": "number"}}]
    )
    # literal 枚举外
    calls = [{"args": {"direction": "diagonal"}}]
    steps = [{"slots": {"direction": ["horizontal"]}}]
    assert slot_accuracy(calls, steps) == 0.0
    # 缺槽位
    assert slot_accuracy([{"args": {}}], [{"slots": {"brightness": "number"}}]) == 0.0
    # 无槽位期望 → 满分
    assert slot_accuracy([{"args": {}}], [{"slots": {}}]) == 1.0


# ------------------------------------------------------------------ runner


@pytest.mark.asyncio
async def test_run_eval_with_stub_planner():
    """桩 planner 按 instruction 查表返回 —— 走真实校验管线打分。"""
    cases = load_cases()
    first = cases[0]  # 「把图调亮一点」→ adjust_color{brightness:number}
    lookup = {
        first["instruction"]: [{"name": "adjust_color", "args": {"brightness": 25}}],
        "dummy": [],
    }

    async def stub(instruction, summary, functions, emit=None):
        return lookup.get(instruction, [])

    report = await run_eval(stub, [], cases=[first])
    assert report["total"] == 1
    assert report["tool_f1"] == 1.0
    assert report["em"] == 1.0
    assert report["slot_accuracy"] == 1.0
    assert report["validate_pass_rate"] == 1.0


@pytest.mark.asyncio
async def test_run_eval_counts_rejection():
    """桩输出幻觉工具 → 被六道关卡拦下 → 计入校验失败，F1 归零。"""
    case = {"id": "x", "instruction": "调亮", "expected": [{"tool": "adjust_color", "slots": {}}]}

    async def stub(instruction, summary, functions, emit=None):
        return [{"name": "delete_everything", "args": {}}]

    report = await run_eval(stub, [], cases=[case])
    assert report["validate_pass_rate"] == 0.0
    assert report["tool_f1"] == 0.0
    assert report["details"][0]["rejected"]


# ------------------------------------------------------------------ 门禁


def test_compare_passes_within_tolerance():
    baseline = {"tool_f1": 0.9, "em": 0.8, "slot_accuracy": 0.9, "validate_pass_rate": 1.0}
    current = {"tool_f1": 0.87, "em": 0.76, "slot_accuracy": 0.95, "validate_pass_rate": 0.98}
    assert compare(current, baseline) == []  # 全部落在 0.05 容差内


def test_compare_fails_below_baseline():
    """DoD ③ 语义：改坏 prompt（指标掉下去）必须被抓到。"""
    baseline = {"tool_f1": 0.9, "em": 0.8, "slot_accuracy": 0.9, "validate_pass_rate": 1.0}
    current = {"tool_f1": 0.5, "em": 0.8, "slot_accuracy": 0.9, "validate_pass_rate": 1.0}
    violations = compare(current, baseline)
    assert len(violations) == 1
    assert "tool_f1" in violations[0]


# ------------------------------------------------------------------ 数据集结构


def test_cases_dataset_structure():
    """DoD ①：≥30 条、字段齐全、工具名全部真实存在、槽位类型合法。"""
    cases = load_cases()
    assert len(cases) >= 30

    known = {spec.name for spec in all_tools()}
    valid_slot_types = {"number", "integer", "string", "boolean"}
    ids = set()
    for case in cases:
        assert case["id"] and case["id"] not in ids, f"用例 id 重复或缺失：{case.get('id')}"
        ids.add(case["id"])
        assert case["instruction"].strip()
        for step in case["expected"]:
            assert step["tool"] in known, f"期望工具 {step['tool']} 不在注册表"
            for _key, spec in (step.get("slots") or {}).items():
                assert isinstance(spec, list) or spec in valid_slot_types, f"非法槽位类型：{spec}"


def test_expected_tools_are_validatable():
    """期望序列必须能通过六道关卡（用例本身不能是坏的）。"""
    known = {spec.name for spec in all_tools()}
    for case in load_cases():
        calls = [{"tool": step["tool"], "args": _args_of_type(step)} for step in case["expected"]]
        steps = plan_mod.assemble(calls)  # 只走 id/依赖/环三关；参数关由槽位测试覆盖
        assert all(step["tool"] in known for step in steps)


def _args_of_type(step: dict) -> dict:
    """按槽位类型造最小合法参数（literal 取枚举第一个）。"""
    args = {}
    for key, spec in (step.get("slots") or {}).items():
        if isinstance(spec, list):
            args[key] = spec[0]
        elif spec == "number":
            args[key] = 10
        elif spec == "integer":
            args[key] = 100
        elif spec == "string":
            args[key] = "x"
        elif spec == "boolean":
            args[key] = False
    return args
