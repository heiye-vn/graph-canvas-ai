"""局部编辑工具（M6）：erase_region / replace_region。

与 builtins 那批确定性工具的本质区别：**重像素、走队列**。
    提交路径（这里）：校验选区在不在 → 落一条 ToolRun → 返回 QueuedOutcome
    执行路径（tasks/region.py，ARQ worker）：拍平画布 → 调 Provider → 合成选区 → 只上墙

为什么不直接在请求里跑：中转站生图 30s~3min 不等，HTTP 请求等不起；
「提交即返回 run_id、进度走 SSE」是 M2 已经定型的协议，这里复用。

agent_hidden 的两个字段（mask_asset_id / revision）与 add_image_layer 的
asset_id 同一个道理：模型会幻觉 UUID。遮罩由选区服务按会话回填，
revision 由服务端比对 —— 模型只给 prompt。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import ToolRun
from app.tools.base import QueuedOutcome, ToolContext, ToolError, ToolSpec
from app.tools.registry import register

TASK = "inpaint_region"


class _RegionParams(BaseModel):
    mask_asset_id: str | None = Field(
        default=None,
        description="选区遮罩素材 id；由界面或服务端回填，模型不要填",
        json_schema_extra={"label": "遮罩素材", "agent_hidden": True},
    )
    revision: int | None = Field(
        default=None,
        description="会话版本号；由服务端回填，模型不要填",
        json_schema_extra={"label": "会话版本", "agent_hidden": True},
    )


class EraseRegionParams(_RegionParams):
    pass


class ReplaceRegionParams(_RegionParams):
    prompt: str = Field(
        min_length=1,
        max_length=500,
        description="选区内要替换成什么",
        json_schema_extra={"label": "替换描述"},
    )


async def _submit(
    params: _RegionParams, ctx: ToolContext, *, tool: str, message: str
) -> QueuedOutcome:
    if ctx.db is None:  # pragma: no cover - 提交路径必带 db
        raise ToolError("提交环境异常，请重试", code="no_db")

    # revision 的唯一权威来源是会话记录本身。
    # 界面/模型都不会传这个隐藏字段 —— 拿请求参数当 revision 比对，
    # 永远对不上，选区就「永远不存在」（这正是第一版踩的坑）。
    from app.models import EditSession
    from app.services import selections

    record = await ctx.db.get(EditSession, ctx.session_id)
    if record is None:
        raise ToolError("编辑会话不存在", code="no_session")

    mask_asset_id = params.mask_asset_id
    if mask_asset_id is None:
        stored = await selections.get(ctx.session_id, record.revision)
        if not stored:
            raise ToolError("请先点选或涂抹要修改的区域", code="no_selection")
        mask_asset_id = stored["mask_asset_id"]

    run = ToolRun(
        user_id=ctx.user_id,
        tool=tool,
        params={
            "prompt": getattr(params, "prompt", "") or "",
            "mask_asset_id": mask_asset_id,
            "revision": record.revision,
            "session_id": str(ctx.session_id),
        },
        session_id=ctx.session_id,
    )
    ctx.db.add(run)
    await ctx.db.flush()  # id 在提交前就要拿到（事务提交后统一投递）
    return QueuedOutcome(run_id=run.id, message=message, task=TASK)


async def erase_region_submit(params: EraseRegionParams, ctx: ToolContext) -> QueuedOutcome:
    return await _submit(
        params,
        ctx,
        tool="erase_region",
        message="已提交局部消除任务，完成后自动加入候选区",
    )


async def replace_region_submit(params: ReplaceRegionParams, ctx: ToolContext) -> QueuedOutcome:
    return await _submit(
        params,
        ctx,
        tool="replace_region",
        message="已提交局部替换任务，完成后自动加入候选区",
    )


register(
    ToolSpec(
        name="erase_region",
        label="局部消除",
        description="消除当前选区内的物体，并用周围内容自然填补。用户还没有选区时，先提示他点选或涂抹要消除的区域，不要直接调用。",
        params_model=EraseRegionParams,
        handler=erase_region_submit,
        group="生成",
        queued=True,
        queue_task=TASK,
    )
)

register(
    ToolSpec(
        name="replace_region",
        label="局部替换",
        description=(
            "按文字描述替换当前选区内的内容。只在用户已经画了选区、"
            "或明确要求「只改选区」时使用；没有选区却要改某个对象（颜色、材质）时"
            "改用 edit_image，不要要求用户先选区。"
        ),
        params_model=ReplaceRegionParams,
        handler=replace_region_submit,
        group="生成",
        queued=True,
        queue_task=TASK,
    )
)
