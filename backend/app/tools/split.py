"""拆层工具（M7）：整份画面拆成 背景 / 主体 / 文字 三层。

排队型工具（同 erase_region / replace_region）：提交即返回 run_id，
worker 里跑 rembg + Provider 修补 + OCR，完成后**整份替换图层文档**
并落撤销栈。include_text 勾选后会把检测到的文字单独成层，
且从主体/背景里抠掉原字像素 —— 不然改文案时旧字还在底下。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import ToolRun
from app.tools.base import QueuedOutcome, ToolContext, ToolError, ToolSpec
from app.tools.registry import register

TASK = "split_layers"


class SplitLayersParams(BaseModel):
    include_text: bool = Field(
        default=False,
        description="同时拆出文字层（识别画面中的文字并抠掉原字）",
        json_schema_extra={"label": "同时拆出文字"},
    )


async def split_layers_submit(params: SplitLayersParams, ctx: ToolContext) -> QueuedOutcome:
    if ctx.db is None:  # pragma: no cover - 提交路径必带 db
        raise ToolError("提交环境异常，请重试", code="no_db")

    run = ToolRun(
        user_id=ctx.user_id,
        tool="split_layers",
        params={
            "include_text": params.include_text,
            "session_id": str(ctx.session_id),
        },
        session_id=ctx.session_id,
    )
    ctx.db.add(run)
    await ctx.db.flush()
    return QueuedOutcome(
        run_id=run.id,
        message="已提交拆层任务，完成后画布将重建为 背景/主体/文字 三层",
        task=TASK,
    )


register(
    ToolSpec(
        name="split_layers",
        label="拆层",
        description="把当前画面拆成背景、主体、文字三层，之后可以单独隐藏、替换或改文字。适合「背景换个颜色但主体不动」这类需求。",
        params_model=SplitLayersParams,
        handler=split_layers_submit,
        group="生成",
        queued=True,
    )
)
