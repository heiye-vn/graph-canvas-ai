"""局部编辑任务（M6，ARQ worker 内执行）。

链路：读选区 → 拍平画布 → Provider 局部生成（边长 clamp [512, 2048]）→
结果缩回原尺寸 → 只把选区内像素换掉 → 产物只上墙（不改文档）。

 revision 双重校验：
    1. mask_bytes 走选区缓存比对（缓存 payload.revision != 当前 → 视为无选区）
    2. run.params.revision 是提交那一刻的版本，执行时再比对一次 ——
       提交到开跑之间用户可能已经撤销/换图，旧选区绝不能碰新图（DoD ③）
"""

from __future__ import annotations

import io
import logging
from uuid import UUID

from PIL import Image

from app.edits.mask import MaskSizeMismatch, apply_masked
from app.models import ToolRun
from app.providers import get_image_provider
from app.providers.base import ProviderError
from app.schemas.events import DoneEvent, ResultEvent
from app.services import assets as asset_service
from app.services import events, selections, storage, tool_exec
from app.services import flatten as flatten_service
from app.services import runs as runs_service
from app.services import sessions as sessions_service

logger = logging.getLogger("graph-canvas-ai.tasks")

_EDIT_MIN_EDGE = 512
_EDIT_MAX_EDGE = 2048
# 消除类指令的默认提示词：不给 prompt 的 erase 也能跑
_ERASE_PROMPT = "移除选中物体，用周围背景自然填补，不要改变选区以外的画面。"


async def inpaint_region(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await session.get(ToolRun, UUID(run_id))
        if run is None:
            logger.warning("任务 %s 不存在，跳过", run_id)
            return
        if run.is_terminal:
            logger.info("任务 %s 已处于终态 %s，跳过", run_id, run.status)
            return

        params = run.params or {}
        session_id = params.get("session_id") or (str(run.session_id) if run.session_id else None)
        if not session_id:
            await runs_service.fail(run, code="no_session", message="任务没有绑定编辑会话")
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))
            return

        record = await sessions_service.get_edit_session(session, run.user_id, UUID(session_id))

        try:
            await runs_service.report(run, progress=10, stage="读取选区", to_running=True)
            await session.commit()

            # 提交后画布又变过 → 选区已过期，明说，别让旧遮罩改坏新图
            submitted_revision = params.get("revision")
            if submitted_revision is not None and int(submitted_revision) != record.revision:
                raise tool_exec.ToolError("画布已更新，选区已失效，请重新选择后重试")

            canvas_size = (record.doc["canvas"]["width"], record.doc["canvas"]["height"])
            mask = await selections.mask_bytes(session, record, params.get("mask_asset_id"))
            if Image.open(io.BytesIO(mask)).size != canvas_size:
                raise MaskSizeMismatch("选区与画布尺寸不符，请重新选择")

            source = await flatten_service.flatten_session(session, record)
            await runs_service.report(run, progress=30, stage="局部生成中")
            await session.commit()

            edited = await _edit_with_clamp(run, source, params.get("prompt") or "")

            await runs_service.report(run, progress=80, stage="合并选区")
            output = apply_masked(source, edited, mask)

            asset = await asset_service.create_from_bytes(
                session, user_id=run.user_id, data=output, kind="image"
            )
            await events.publish(
                ResultEvent(
                    run_id=run.id,
                    asset_id=asset.id,
                    url=storage.presign_get(asset.s3_key),
                    wall_only=True,
                )
            )
            await runs_service.succeed(
                run,
                {
                    "asset_ids": [str(asset.id)],
                    "adopt_asset_id": str(asset.id),
                    "session_id": session_id,
                },
            )
            # 选区用完即弃：遮罩对应的画布马上要被采用结果替换掉
            await selections.clear(record.id)
        except (MaskSizeMismatch, tool_exec.ToolError) as exc:
            logger.info("任务 %s 被判废：%s", run_id, exc)
            await runs_service.fail(
                run, code="stale_selection", message=str(exc), recoverable=True
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await runs_service.fail(run, code=exc.code, message=exc.message, recoverable=True)
        except Exception as exc:  # noqa: BLE001 - 任务里的任何异常都要落到 run.error
            logger.exception("任务 %s 失败", run_id)
            await runs_service.fail(
                run, code="task_failed", message=str(exc) or "局部编辑失败", recoverable=True
            )
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


async def _edit_with_clamp(run: ToolRun, source: bytes, prompt: str) -> bytes:
    """Provider 编辑；边长 clamp 到 [512, 2048]（M6 关键设计 ⑤）。

    太小的图直接送模型，生成质量崩；太大的图又慢又贵。缩放发生在
    送模型之前，结果送回来先放大回原尺寸再合成 —— 选区遮罩始终
    作用在原始分辨率上，精度不因 clamp 损失。
    """
    image = Image.open(io.BytesIO(source))
    width, height = image.size
    longest = max(width, height)
    scale = 1.0
    if longest > _EDIT_MAX_EDGE:
        scale = _EDIT_MAX_EDGE / longest
    elif longest < _EDIT_MIN_EDGE:
        scale = _EDIT_MIN_EDGE / longest

    payload = source
    if scale != 1.0:
        resized = image.resize(
            (int(width * scale), int(height * scale)), Image.Resampling.LANCZOS
        )
        buffer = io.BytesIO()
        resized.save(buffer, format="PNG")
        payload = buffer.getvalue()

    tool = run.tool
    if tool == "erase_region":
        prompt = prompt or _ERASE_PROMPT
    else:  # replace_region 的 prompt 由参数层保证非空
        prompt = f"只改选中区域：{prompt}。选区外的主体、光线和背景必须保持原样。"

    provider = get_image_provider()
    edited = (await provider.edit_image(payload, prompt))[0]

    if scale != 1.0:
        back = Image.open(io.BytesIO(edited)).convert("RGBA")
        if back.size != (width, height):
            back = back.resize((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        back.save(buffer, format="PNG")
        edited = buffer.getvalue()
    return edited
