"""拆层任务（M7，ARQ worker 内执行）。

链路：拍平画布 → rembg 分离主体 → Provider 修补背景 →（可选）OCR 文字框
→ 抠掉原字像素 → 两张新素材落库 → **整份替换图层文档 + 落历史**。

与 inpaint（结果只上墙）不同，拆层的产出就是一份新文档 ——
但文档绝不能悄悄换：必须走 record_external 落进撤销栈，
否则用户拆完层按撤销「没反应」。
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from PIL import Image

from app.edits.mask import apply_masked
from app.edits.ocr import detect_text
from app.edits.split import alpha_mask, remove_text
from app.models import ToolRun
from app.providers.base import ProviderError
from app.schemas.events import DoneEvent, ResultEvent
from app.services import assets as asset_service
from app.services import events, selections, storage
from app.services import flatten as flatten_service
from app.services import history as history_service
from app.services import runs as runs_service
from app.services import sessions as sessions_service
from app.services.split import build_split_document
from app.tasks.region import edit_image_clamped

logger = logging.getLogger("graph-canvas-ai.tasks")

_RECONSTRUCT = "移除选中物体，用周围背景自然填补，不要改变选区以外的画面。"


async def split_layers(ctx, run_id: str) -> None:
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
            await _fail(run, session, "no_session", "任务没有绑定编辑会话")
            return
        record = await sessions_service.get_edit_session(session, run.user_id, UUID(session_id))

        try:
            await runs_service.report(run, progress=15, stage="读取画布", to_running=True)
            await session.commit()

            source = await flatten_service.flatten_session(session, record)

            await runs_service.report(run, progress=35, stage="分离主体")
            subject = await asyncio.to_thread(_remove_background, source)
            mask = alpha_mask(subject)

            await runs_service.report(run, progress=55, stage="修补背景")
            edited = await edit_image_clamped(source, _RECONSTRUCT)
            background = apply_masked(source, edited, mask)

            texts = []
            if params.get("include_text"):
                await runs_service.report(run, progress=80, stage="识别文字")
                texts = await asyncio.to_thread(detect_text, source)
                if texts:
                    size = (record.doc["canvas"]["width"], record.doc["canvas"]["height"])
                    subject, background = await asyncio.to_thread(
                        remove_text, subject, background, texts, size
                    )

            subject_asset = await asset_service.create_from_bytes(
                session, user_id=run.user_id, data=subject, kind="image"
            )
            background_asset = await asset_service.create_from_bytes(
                session, user_id=run.user_id, data=background, kind="image"
            )
            for asset in (background_asset, subject_asset):
                await events.publish(
                    ResultEvent(
                        run_id=run.id,
                        asset_id=asset.id,
                        url=storage.presign_get(asset.s3_key),
                        wall_only=True,
                    )
                )

            next_doc = build_split_document(
                history_service.LayerDocument.model_validate(record.doc),
                background_asset_id=background_asset.id,
                subject_asset_id=subject_asset.id,
                texts=texts,
            )
            label = "已拆层：背景 / 主体" + (f" / 文字 ×{len(texts)}" if texts else "")
            # 文档与历史同一事务（与 apply_tool_calls 同一不变量）——
            # 拆层替换的是整份文档，撤销栈里必须找得到这一步
            await history_service.record_external(
                session,
                record,
                tool="split_layers",
                label=label,
                after=next_doc,
                params={"include_text": bool(params.get("include_text"))},
            )
            await selections.clear(record.id)

            await runs_service.succeed(
                run,
                {
                    "asset_ids": [str(background_asset.id), str(subject_asset.id)],
                    "document": next_doc.model_dump(mode="json"),
                    "text_count": len(texts),
                },
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await runs_service.fail(run, code=exc.code, message=exc.message, recoverable=True)
        except Exception as exc:  # noqa: BLE001 - 任务里的任何异常都要落到 run.error
            logger.exception("任务 %s 失败", run_id)
            await runs_service.fail(
                run, code="task_failed", message=str(exc) or "拆层失败", recoverable=True
            )
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


async def _fail(run: ToolRun, session, code: str, message: str) -> None:
    await runs_service.fail(run, code=code, message=message, recoverable=True)
    await session.commit()
    await events.publish(DoneEvent(run_id=run.id, status=run.status))


def warm_matting() -> None:
    """进程启动预热：把 rembg 的 u2net 会话建好（首次拆层不再承担模型加载）。"""
    from rembg import remove
    from rembg.session_factory import new_session

    remove(Image.new("RGB", (64, 64), (120, 120, 120)), session=new_session("u2net"))


def _remove_background(source: bytes) -> bytes:
    """rembg 默认 u2net 分离主体（透明背景 RGBA）。

    与选区的 SAM 不同：拆层要的是整图主体的完整抠像，u2net 一次到位。
    rembg 未安装时直接抛 —— 拆层没有它没有意义，让错误进 run.error 报人话。
    """
    from rembg import remove

    return bytes(remove(source))
