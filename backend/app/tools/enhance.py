"""M11 的像素增强工具：去背景 / 换背景 / 扩图 / 超分。

与 builtins 那批「只改文档」的确定性工具不同，这批**改像素**：
    提交路径（这里）：校验参数 → 落 ToolRun → 返回 QueuedOutcome
    执行路径（tasks/enhance.py，ARQ worker）：读图 → 调本地算法或 Provider
        → 存新素材 → **整份替换文档并落撤销栈**

为什么它们必须改文档而不是「只上墙」：
去背景 / 换背景 / 扩图 / 超分的结果就是用户要的那张画布，
让用户再从候选条里点一次「采用」只会多一步。写入走 record_external，
撤销栈里找得到这一步（与拆层同一不变量）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.models import ToolRun
from app.tools.base import QueuedOutcome, ToolContext, ToolError, ToolSpec
from app.tools.builtins import LayerRef
from app.tools.registry import register


async def _submit(
    ctx: ToolContext, tool: str, params: dict, message: str
) -> QueuedOutcome:
    if ctx.db is None:  # pragma: no cover - 提交路径必带 db
        raise ToolError("提交环境异常，请重试", code="no_db")
    payload = {"session_id": str(ctx.session_id), **params}
    run = ToolRun(
        user_id=ctx.user_id,
        tool=tool,
        params=payload,
        session_id=ctx.session_id,
    )
    ctx.db.add(run)
    # id 在提交前就要拿到（事务提交后统一投递 ARQ）
    await ctx.db.flush()
    return QueuedOutcome(run_id=run.id, message=message, task=tool)


# ------------------------------------------------------------------ 去背景


class RemoveBackgroundParams(LayerRef):
    pass


async def remove_background_submit(
    params: RemoveBackgroundParams, ctx: ToolContext
) -> QueuedOutcome:
    from app.services import layer_doc as L

    layer = L.topmost_visible_image_layer(ctx.doc) if not params.layer else None
    if params.layer:
        try:
            layer = L.resolve_layer(ctx.doc, params.layer)
        except L.LayerNotFoundError as exc:
            raise ToolError(f"找不到图层「{params.layer}」", code="no_layer") from exc
    if layer is None:
        raise ToolError("画布上没有可处理的图像层", code="no_layer")
    if layer.type != "image" or layer.source is None:
        raise ToolError(f"「{layer.name}」不是图像层，去背景只能作用于图片", code="not_image")

    return await _submit(
        ctx,
        "remove_background",
        {"layer_id": str(layer.id)},
        "已提交去背景任务，完成后画布自动更新",
    )


# ------------------------------------------------------------------ 换背景


class ReplaceBackgroundParams(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=500,
        description="新背景的描述，例如「浅灰色水泥墙，柔和侧光」",
        json_schema_extra={"label": "新背景"},
    )


async def replace_background_submit(
    params: ReplaceBackgroundParams, ctx: ToolContext
) -> QueuedOutcome:
    return await _submit(
        ctx,
        "replace_background",
        {"prompt": params.prompt},
        "已提交换背景任务，完成后画布自动更新",
    )


# ------------------------------------------------------------------ 扩图


class ExpandCanvasParams(BaseModel):
    ratio: Literal["1:1", "4:5", "9:16", "16:9"] = Field(
        default="1:1",
        description="目标画幅比例",
        json_schema_extra={"label": "目标比例"},
    )
    prompt: str = Field(
        default="自然延伸画面边缘，保持主体完整与光线一致",
        max_length=500,
        description="扩图时的补充描述（默认自然延伸）",
        json_schema_extra={"label": "延伸描述"},
    )


async def expand_canvas_submit(
    params: ExpandCanvasParams, ctx: ToolContext
) -> QueuedOutcome:
    return await _submit(
        ctx,
        "expand_canvas",
        {"ratio": params.ratio, "prompt": params.prompt},
        "已提交扩图任务，完成后画布尺寸会更新",
    )


# ------------------------------------------------------------------ 超分


class UpscaleImageParams(BaseModel):
    scale: int = Field(
        default=2,
        ge=2,
        le=4,
        description="放大倍数（2~4）",
        json_schema_extra={"label": "倍数"},
    )


async def upscale_image_submit(
    params: UpscaleImageParams, ctx: ToolContext
) -> QueuedOutcome:
    return await _submit(
        ctx,
        "upscale_image",
        {"scale": params.scale},
        "已提交超分任务，完成后画布分辨率会更新",
    )


# ------------------------------------------------------------------ 指令编辑


class EditImageParams(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=500,
        description="要改成什么样，例如「把眼镜的镜片改成粉红色」",
        json_schema_extra={"label": "编辑要求"},
    )


async def edit_image_submit(params: EditImageParams, ctx: ToolContext) -> QueuedOutcome:
    return await _submit(
        ctx,
        "edit_image",
        {"prompt": params.prompt},
        "已提交编辑任务，完成后画布自动更新",
    )


# ------------------------------------------------------------------ 注册


register(
    ToolSpec(
        name="edit_image",
        label="指令编辑",
        description=(
            "按一句话描述直接修改画面内容（改颜色、材质、样式等），**不需要选区**。"
            "只改用户点名的对象，其余保持原样。适合「把眼镜改成粉红色」这类需求。"
            "用户已经画了选区且要求只改选区时才用 replace_region。"
        ),
        params_model=EditImageParams,
        handler=edit_image_submit,
        group="生成",
        queued=True,
    )
)

register(
    ToolSpec(
        name="remove_background",
        label="去背景",
        description="抠出当前图层的主体，背景变透明。只用于「去背景」，不要用它换背景或生成新画面。",
        params_model=RemoveBackgroundParams,
        handler=remove_background_submit,
        group="生成",
        queued=True,
    )
)

register(
    ToolSpec(
        name="replace_background",
        label="换背景",
        description="按文字描述替换画布背景，保持主体、光线和边缘不变。用户说「把背景换成…」时用它。",
        params_model=ReplaceBackgroundParams,
        handler=replace_background_submit,
        group="生成",
        queued=True,
    )
)

register(
    ToolSpec(
        name="expand_canvas",
        label="扩图",
        description="把当前画布扩展到指定比例，并自然补全新增区域。主体保持完整，不要裁切。",
        params_model=ExpandCanvasParams,
        handler=expand_canvas_submit,
        group="生成",
        queued=True,
    )
)

register(
    ToolSpec(
        name="upscale_image",
        label="超分",
        description="把当前画布分辨率放大到 2~4 倍。不要用它换内容或改构图。",
        params_model=UpscaleImageParams,
        handler=upscale_image_submit,
        group="生成",
        queued=True,
    )
)
