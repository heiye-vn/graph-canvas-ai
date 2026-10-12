"""文生图任务（在 worker 进程里执行）。

流程：标记开始 → 调 Provider → 产物存对象存储并落成素材 → 逐步上报进度 → 收尾。
所有状态变更都走 services/runs，与 API 进程共用同一套逻辑。
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.models import Asset, ToolRun
from app.providers import get_image_provider
from app.schemas.events import DoneEvent, ResultEvent
from app.services import assets as asset_service
from app.services import events, storage
from app.services import runs as runs_service

logger = logging.getLogger("graph-canvas-ai.tasks")


async def text_to_image(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await session.get(ToolRun, UUID(run_id))
        if run is None:
            logger.warning("任务 %s 不存在，跳过", run_id)
            return
        # 终态一律不再执行：取消是用户主动的，成功/失败则不该被重放覆盖
        if run.is_terminal:
            logger.info("任务 %s 已处于终态 %s，跳过", run_id, run.status)
            return

        params = run.params or {}
        prompt = params.get("prompt") or ""
        size = params.get("size") or "1024x1024"
        n = int(params.get("n") or 1)

        try:
            await runs_service.report(run, progress=5, stage="准备中", to_running=True)
            await session.commit()

            provider = get_image_provider()
            images = await provider.text_to_image(prompt, size=size, n=n)
            await runs_service.report(run, progress=40, stage="生成完成，转存中")

            asset_ids: list[str] = []
            for index, data in enumerate(images, start=1):
                mime, width, height = asset_service.probe_image(data)
                key = asset_service.build_key(run.user_id, mime)
                storage.put_object(key, data, content_type=mime)

                asset = Asset(
                    user_id=run.user_id,
                    kind="image",
                    s3_key=key,
                    mime=mime,
                    width=width,
                    height=height,
                    size=len(data),
                )
                session.add(asset)
                await session.flush()
                asset_ids.append(str(asset.id))

                await events.publish(
                    ResultEvent(
                        run_id=run.id,
                        asset_id=asset.id,
                        url=storage.presign_get(key),
                    )
                )
                await runs_service.report(
                    run,
                    progress=40 + int(index / len(images) * 55),
                    stage=f"已产出 {index}/{len(images)}",
                )
                await session.commit()

            await runs_service.succeed(run, {"asset_ids": asset_ids, "count": len(asset_ids)})
        except Exception as exc:  # noqa: BLE001 - 任务里的任何异常都要落到 run.error
            logger.exception("任务 %s 失败", run_id)
            await runs_service.fail(
                run, code="task_failed", message=str(exc) or "生成失败", recoverable=True
            )
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))
