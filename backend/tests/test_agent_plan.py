"""M8 计划校验单测 —— 六道关卡逐条钉死。"""

from __future__ import annotations

import pytest

from app.agent import plan as plan_mod
from app.agent.plan import PlanError


def test_validate_unknown_tool_gives_plain_words():
    with pytest.raises(PlanError) as exc:
        plan_mod.validate([{"tool": "make_money", "args": {}}])
    assert "不存在的工具" in str(exc.value)
    assert "可用工具" in str(exc.value)


def test_validate_bad_params_named_step():
    with pytest.raises(PlanError) as exc:
        plan_mod.validate([{"tool": "adjust_color", "args": {"brightness": "很亮"}}])
    assert "参数不对" in str(exc.value)


def test_validate_fills_serial_dependencies():
    steps = plan_mod.validate(
        [
            {"tool": "adjust_color", "args": {"brightness": 20}},
            {"tool": "flip_layer", "args": {"axis": "horizontal"}},
        ]
    )
    assert steps[0]["depends_on"] == []
    assert steps[1]["depends_on"] == [steps[0]["id"]]
    assert all(step["status"] == plan_mod.PENDING for step in steps)


def test_validate_rejects_over_long_plan():
    raw = [{"tool": "flip_layer", "args": {}} for _ in range(plan_mod.MAX_STEPS + 1)]
    with pytest.raises(PlanError) as exc:
        plan_mod.validate(raw)
    assert "超过" in str(exc.value)


def test_assemble_rejects_missing_dependency():
    with pytest.raises(PlanError) as exc:
        plan_mod.assemble(
            [
                {"tool": "flip_layer", "depends_on": ["ghost"], "params": {}},
            ]
        )
    assert "不存在的步骤" in str(exc.value)


def test_assemble_rejects_cycle():
    raw = [
        {"tool": "flip_layer", "id": "a", "depends_on": ["b"], "params": {}},
        {"tool": "flip_layer", "id": "b", "depends_on": ["a"], "params": {}},
    ]
    with pytest.raises(PlanError) as exc:
        plan_mod.assemble(raw)
    assert "循环依赖" in str(exc.value)


def test_ready_and_settle_flow():
    steps = plan_mod.validate(
        [
            {"tool": "adjust_color", "args": {"brightness": 20}},
            {"tool": "flip_layer", "args": {}},
        ]
    )
    assert [step["id"] for step in plan_mod.ready(steps)] == [steps[0]["id"]]

    steps[0]["status"] = plan_mod.SUCCEEDED
    assert [step["id"] for step in plan_mod.ready(steps)] == [steps[1]["id"]]

    steps[1]["status"] = plan_mod.SUCCEEDED
    assert plan_mod.ready(steps) == []
    assert plan_mod.settle(steps) == plan_mod.SUCCEEDED


def test_settle_failed_blocks_dependents():
    steps = plan_mod.validate(
        [
            {"tool": "adjust_color", "args": {"brightness": 20}},
            {"tool": "flip_layer", "args": {}},
        ]
    )
    steps[0]["status"] = plan_mod.FAILED
    assert plan_mod.ready(steps) == []  # 失败步的依赖者不再就绪
    assert plan_mod.settle(steps) == plan_mod.FAILED


def test_cancel_remaining_keeps_terminal():
    steps = [
        {"id": "s1", "status": plan_mod.SUCCEEDED},
        {"id": "s2", "status": plan_mod.PENDING},
        {"id": "s3", "status": plan_mod.QUEUED, "run_id": "r1"},
    ]
    canceled = plan_mod.cancel_remaining(steps)
    assert canceled[0]["status"] == plan_mod.SUCCEEDED  # 已完成的不动
    assert canceled[1]["status"] == plan_mod.CANCELED
    assert canceled[2]["status"] == plan_mod.CANCELED
