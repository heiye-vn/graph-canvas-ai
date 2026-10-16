"""评测 CLI（M10）—— Prompt Regression 的本地门禁。

用法：
    python -m app.eval.run                    # 跑评测，与基线比对，低于基线 exit 1
    python -m app.eval.run --update-baseline  # 把本次结果写成新基线
    python -m app.eval.run --limit 5          # 冒烟：只跑前 5 条

真实模型模式：需要 .env 里的 LLM 配置（DASHSCOPE_API_KEY 等）。
跑一次约消耗 30 条 × 数百 token —— 门禁只在改 prompt / 改校验规则后手动触发。

不接 CI（用户决策 2026-10-15）：门禁形态不变 —— 评测低于基线就非零退出，
只是触发方式从 GitHub Actions 换成本地手动/脚本。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from app.eval.runner import compare, load_cases, run_eval

BASELINE_PATH = Path(__file__).parent / "baseline.json"
REPORT_PATH = Path(__file__).parent / "report.json"


async def _real_plan_fn(instruction: str, summary: str, functions: list[dict]) -> tuple:
    from app.agent import llm as llm_module

    return await llm_module.plan_tool_calls_stream(instruction, summary, functions, emit=None)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agent 规划评测 + prompt 回归门禁")
    parser.add_argument("--update-baseline", action="store_true", help="把本次结果写成新基线")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条（冒烟）")
    parser.add_argument("--keep-report", action="store_true", help="保留逐条明细 report.json")
    args = parser.parse_args()

    cases = load_cases()
    if args.limit > 0:
        cases = cases[: args.limit]

    try:
        from app.tools.registry import function_schemas

        functions = function_schemas()
    except Exception as exc:  # noqa: BLE001
        print(f"[eval] 工具注册表加载失败：{exc}")
        return 2

    started = time.monotonic()
    try:
        report = asyncio.run(run_eval(_real_plan_fn, functions, cases))
    except Exception as exc:  # noqa: BLE001 - 典型：缺 LLM 配置
        print(f"[eval] 无法启动评测：{exc}")
        return 2

    report["elapsed_s"] = round(time.monotonic() - started, 1)
    gated = {key: report[key] for key in ("tool_f1", "em", "slot_accuracy", "validate_pass_rate")}

    print(
        f"\n[eval] {report['total']} 条 | tool-F1 {gated['tool_f1']} | EM {gated['em']} "
        f"| 槽位 {gated['slot_accuracy']} | 校验通过率 {gated['validate_pass_rate']} "
        f"| 平均 {report['avg_duration_ms']}ms | 总耗时 {report['elapsed_s']}s"
    )

    if args.keep_report or args.update_baseline:
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if args.update_baseline:
        baseline = {
            **gated,
            "prompt_version": _prompt_version(),
            "updated_at": time.strftime("%Y-%m-%d %H:%M"),
        }
        BASELINE_PATH.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[eval] 已更新基线 → {BASELINE_PATH}")
        return 0

    if not BASELINE_PATH.exists():
        print(f"[eval] 尚无基线（{BASELINE_PATH}）。首跑请加 --update-baseline 生成。")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    violations = compare(gated, baseline)
    if violations:
        print("[eval] ✗ 回归门禁未通过（prompt 改坏了吗？）：")
        for item in violations:
            print(f"    - {item}")
        return 1

    print(f"[eval] ✓ 门禁通过（基线 prompt_version={baseline.get('prompt_version')}）")
    return 0


def _prompt_version() -> str:
    from app.agent.prompts import PROMPT_VERSION

    return PROMPT_VERSION


if __name__ == "__main__":
    sys.exit(main())
