"""像素增强任务（M11，ARQ worker 内执行）：去背景 / 换背景 / 扩图 / 超分。

与局部编辑（只上墙）的分工：
    这四个工具的结果就是用户要的画布，所以执行完**整份替换文档 + 落撤销栈**
    （record_external）。让用户再去候选条点一次「采用」只会多一步，
    而且中间态（画布没变、候选里多一张）本身就是一种困惑。

尺寸纪律：
    - 去背景：源图尺寸不变，crop / transform 原样保留
    - 换背景：结果 resize 回画布尺寸，避免模型返回别的档位导致整层被拉伸
    - 扩图：按目标比例算新画布，原始画面居中补边后交给模型，结果再贴回目标尺寸
    - 超分：只放大 canvas 与各图层几何，素材像素不动（可逆且不糊两次）
"""

from __future__ import annotations

import asyncio
import io
import logging
from uuid import UUID

from PIL import Image

from app.models import SessionAsset, ToolRun
from app.providers import get_image_provider
from app.providers.base import ProviderError
from app.schemas.events import DoneEvent, ResultEvent
from app.schemas.layer_doc import Canvas, LayerDocument
from app.services import assets as asset_service
from app.services import events, storage
from app.services import flatten as flatten_service
from app.services import history as history_service
from app.services import layer_doc as L
from app.services import runs as runs_service
from app.services import sessions as sessions_service

logger = logging.getLogger("graph-canvas-ai.tasks")

_MAX_CANVAS_EDGE = 8192


# ------------------------------------------------------------------ 公共


async def _open_run(session, run_id: str) -> ToolRun | None:
    run = await session.get(ToolRun, UUID(run_id))
    if run is None:
        logger.warning("任务 %s 不存在，跳过", run_id)
        return None
    if run.is_terminal:
        logger.info("任务 %s 已处于终态 %s，跳过", run_id, run.status)
        return None
    return run


async def _bind(session, run: ToolRun):
    params = run.params or {}
    session_id = params.get("session_id") or (
        str(run.session_id) if run.session_id else None
    )
    if not session_id:
        return None, None
    record = await sessions_service.get_edit_session(
        session, run.user_id, UUID(session_id)
    )
    return record, params


async def _fail(session, run: ToolRun, code: str, message: str) -> None:
    await runs_service.fail(run, code=code, message=message, recoverable=True)
    await session.commit()
    await events.publish(DoneEvent(run_id=run.id, status=run.status))


async def _store(session, run: ToolRun, record, data: bytes):
    """落素材 + 建立会话关联 + 推一张结果事件。"""
    asset = await asset_service.create_from_bytes(
        session, user_id=run.user_id, data=data, kind="image"
    )
    session.add(SessionAsset(session_id=record.id, asset_id=asset.id))
    await events.publish(
        ResultEvent(
            run_id=run.id,
            asset_id=asset.id,
            url=storage.presign_get(asset.s3_key),
            wall_only=True,
        )
    )
    return asset


async def _finish(
    session,
    run: ToolRun,
    record,
    *,
    doc: LayerDocument,
    tool: str,
    label: str,
    params: dict,
    asset_ids: list[str],
) -> None:
    """文档与历史同一事务 —— 与 apply_tool_calls 同一条不变量。"""
    await history_service.record_external(
        session, record, tool=tool, label=label, after=doc, params=params
    )
    await runs_service.succeed(
        run,
        {
            "asset_ids": asset_ids,
            "document": doc.model_dump(mode="json"),
        },
    )


# ------------------------------------------------------------------ 去背景


def _matte(source: bytes) -> bytes:
    try:
        from rembg import remove
    except ImportError as exc:  # pragma: no cover - 依赖缺失时才走到
        raise RuntimeError(
            "去背景需要 rembg：请安装后端 cv 依赖（uv sync --extra cv）"
        ) from exc
    return bytes(remove(source))


async def remove_background(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await _open_run(session, run_id)
        if run is None:
            return
        record, params = await _bind(session, run)
        if record is None:
            await _fail(session, run, "no_session", "任务没有绑定编辑会话")
            return

        try:
            await runs_service.report(run, progress=15, stage="读取图层", to_running=True)
            await session.commit()

            doc = LayerDocument.model_validate(record.doc)
            layer = L.resolve_layer(doc, params.get("layer_id"))
            if layer.type != "image" or layer.source is None:
                raise ValueError(f"「{layer.name}」不是图像层，无法去背景")

            asset = await asset_service.get_asset(
                session, run.user_id, layer.source.asset_id
            )
            # get_object 是同步的（boto3），绝不能 await
            raw = storage.get_object(asset.s3_key)

            await runs_service.report(run, progress=45, stage="分离主体")
            cut = await asyncio.to_thread(_matte, raw)

            new_asset = await _store(session, run, record, cut)
            # 只换图源：尺寸与 crop 都不变，视觉位置因此不会跳
            updated = L.update_layer(
                doc, layer.id, {"source": {"asset_id": new_asset.id}}
            )
            await _finish(
                session,
                run,
                record,
                doc=updated,
                tool="remove_background",
                label=f"已去除「{layer.name}」的背景",
                params={"layer_id": str(layer.id)},
                asset_ids=[str(new_asset.id)],
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await _fail(session, run, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - 任务里的任何异常都要落到 run.error
            logger.exception("任务 %s 失败", run_id)
            await _fail(session, run, "task_failed", str(exc) or "去背景失败")
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


# ------------------------------------------------------------------ 超分


def _upscale(source: bytes, scale: int) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    target = (image.width * scale, image.height * scale)
    resized = image.resize(target, Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


async def upscale_image(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await _open_run(session, run_id)
        if run is None:
            return
        record, params = await _bind(session, run)
        if record is None:
            await _fail(session, run, "no_session", "任务没有绑定编辑会话")
            return

        try:
            await runs_service.report(run, progress=15, stage="读取画布", to_running=True)
            await session.commit()

            doc = LayerDocument.model_validate(record.doc)
            longest = max(doc.canvas.width, doc.canvas.height)
            scale = min(int(params.get("scale") or 2), _MAX_CANVAS_EDGE // longest)
            if scale < 2:
                raise ValueError(
                    f"画布已经很大（{doc.canvas.width}×{doc.canvas.height}），"
                    f"再放大就超过 {_MAX_CANVAS_EDGE}px 上限"
                )

            source = await flatten_service.flatten_session(session, record)
            await runs_service.report(run, progress=45, stage="提升分辨率")
            output = await asyncio.to_thread(_upscale, source, scale)

            new_asset = await _store(session, run, record, output)

            # 几何整体放大：canvas、每个图层的位置/尺寸、文字字号
            updated = doc.model_copy(deep=True)
            updated.canvas = Canvas(
                width=doc.canvas.width * scale,
                height=doc.canvas.height * scale,
                background=doc.canvas.background,
            )
            for layer in updated.layers:
                transform = layer.transform
                width = (
                    transform.width
                    if transform.width is not None
                    else doc.canvas.width
                )
                height = (
                    transform.height
                    if transform.height is not None
                    else doc.canvas.height
                )
                transform.x *= scale
                transform.y *= scale
                transform.width = width * scale
                transform.height = height * scale
                if layer.text is not None:
                    layer.text.font_size *= scale
            # layer_doc 是可变模型；重新校验一次确保宽高没越过 Canvas 上限
            updated = LayerDocument.model_validate(updated.model_dump(mode="json"))

            await _finish(
                session,
                run,
                record,
                doc=updated,
                tool="upscale_image",
                label=f"超分：画布放大到 {scale} 倍",
                params={"scale": scale},
                asset_ids=[str(new_asset.id)],
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await _fail(session, run, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务 %s 失败", run_id)
            await _fail(session, run, "task_failed", str(exc) or "超分失败")
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


# ------------------------------------------------------------------ 换背景


def _to_size(source: bytes, width: int, height: int) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    if image.size != (width, height):
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def replace_background(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await _open_run(session, run_id)
        if run is None:
            return
        record, params = await _bind(session, run)
        if record is None:
            await _fail(session, run, "no_session", "任务没有绑定编辑会话")
            return

        try:
            await runs_service.report(run, progress=15, stage="读取画布", to_running=True)
            await session.commit()

            doc = LayerDocument.model_validate(record.doc)
            source = await flatten_service.flatten_session(session, record)
            prompt = params.get("prompt") or ""

            await runs_service.report(run, progress=35, stage="生成新背景")
            images = await get_image_provider().edit_image(
                source,
                f"只替换背景，保持主体、光线和边缘不变。新背景：{prompt}",
            )
            output = await asyncio.to_thread(
                _to_size, images[0], doc.canvas.width, doc.canvas.height
            )

            new_asset = await _store(session, run, record, output)
            layer = L.new_image_layer(
                new_asset.id,
                width=doc.canvas.width,
                height=doc.canvas.height,
                name="换背景结果",
            )
            updated = L.add_layer(doc, layer)
            # 新结果成为唯一可见的图像层 —— 叠在旧图上只会看到原图
            updated = L.switch_current_image(updated, layer.id)

            await _finish(
                session,
                run,
                record,
                doc=updated,
                tool="replace_background",
                label="已替换背景",
                params={"prompt": prompt},
                asset_ids=[str(new_asset.id)],
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await _fail(session, run, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务 %s 失败", run_id)
            await _fail(session, run, "task_failed", str(exc) or "换背景失败")
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


# ------------------------------------------------------------------ 指令编辑


async def edit_image(ctx, run_id: str) -> None:
    """整图按一句话编辑（改颜色 / 材质 / 样式），**不需要选区**。

    与换背景同构：拍平 → Provider 编辑 → 缩回画布尺寸 → 结果成为新的
    当前图（旧层保留但隐藏，可切换回来）。

    局部性靠提示词约束，不如 replace_region 的遮罩硬，所以提示词里
    明确要求「只改涉及的对象」；改坏了用户还能撤销。
    """
    async with runs_service.session_scope() as session:
        run = await _open_run(session, run_id)
        if run is None:
            return
        record, params = await _bind(session, run)
        if record is None:
            await _fail(session, run, "no_session", "任务没有绑定编辑会话")
            return

        try:
            await runs_service.report(run, progress=15, stage="读取画布", to_running=True)
            await session.commit()

            doc = LayerDocument.model_validate(record.doc)
            source = await flatten_service.flatten_session(session, record)
            prompt = params.get("prompt") or ""

            await runs_service.report(run, progress=35, stage="编辑画面")
            images = await get_image_provider().edit_image(
                source,
                f"按用户要求编辑画面：{prompt}。"
                "只改涉及的对象或区域，其余主体、构图、光线与背景保持原样。",
            )
            output = await asyncio.to_thread(
                _to_size, images[0], doc.canvas.width, doc.canvas.height
            )

            new_asset = await _store(session, run, record, output)
            layer = L.new_image_layer(
                new_asset.id,
                width=doc.canvas.width,
                height=doc.canvas.height,
                name="编辑结果",
            )
            updated = L.switch_current_image(L.add_layer(doc, layer), layer.id)

            await _finish(
                session,
                run,
                record,
                doc=updated,
                tool="edit_image",
                label=f"已编辑：{prompt[:24]}",
                params={"prompt": prompt},
                asset_ids=[str(new_asset.id)],
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await _fail(session, run, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务 %s 失败", run_id)
            await _fail(session, run, "task_failed", str(exc) or "编辑失败")
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))


# ------------------------------------------------------------------ 扩图


def _cover_size(width: int, height: int, ratio: str) -> tuple[int, int]:
    """按目标比例算出「能装下原图」的最小画布（cover 语义：只扩不裁）。"""
    try:
        rw, rh = (int(part) for part in ratio.split(":"))
        target = rw / rh
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"不支持的画幅比例：{ratio}") from exc

    if width / height < target:
        return int(round(height * target)), height
    return width, int(round(width / target))


def _pad_center(source: bytes, width: int, height: int, background: str) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    canvas = Image.new("RGBA", (width, height), background)
    canvas.paste(
        image,
        ((width - image.width) // 2, (height - image.height) // 2),
        image,
    )
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


async def expand_canvas(ctx, run_id: str) -> None:
    async with runs_service.session_scope() as session:
        run = await _open_run(session, run_id)
        if run is None:
            return
        record, params = await _bind(session, run)
        if record is None:
            await _fail(session, run, "no_session", "任务没有绑定编辑会话")
            return

        try:
            await runs_service.report(run, progress=15, stage="读取画布", to_running=True)
            await session.commit()

            doc = LayerDocument.model_validate(record.doc)
            width, height = _cover_size(
                doc.canvas.width, doc.canvas.height, params.get("ratio") or "1:1"
            )
            if max(width, height) > _MAX_CANVAS_EDGE:
                raise ValueError(
                    f"扩图后的尺寸 {width}×{height} 超过 {_MAX_CANVAS_EDGE}px 上限"
                )

            source = await flatten_service.flatten_session(session, record)
            base = await asyncio.to_thread(
                _pad_center, source, width, height, doc.canvas.background or "#ffffff"
            )

            await runs_service.report(run, progress=35, stage="延伸画幅")
            images = await get_image_provider().edit_image(
                base,
                params.get("prompt")
                or "自然延伸画面边缘，保持主体完整与光线一致",
            )
            output = await asyncio.to_thread(_to_size, images[0], width, height)

            new_asset = await _store(session, run, record, output)
            layer = L.new_image_layer(
                new_asset.id, width=width, height=height, name="扩图结果"
            )
            # 扩图换的是整块画布：新文档只留结果层，避免旧图层按旧坐标错位
            updated = LayerDocument(
                canvas=Canvas(
                    width=width, height=height, background=doc.canvas.background
                ),
                layers=[layer],
                active_layer_id=layer.id,
            )

            await _finish(
                session,
                run,
                record,
                doc=updated,
                tool="expand_canvas",
                label=f"已扩图到 {params.get('ratio') or '1:1'}",
                params={"ratio": params.get("ratio"), "prompt": params.get("prompt")},
                asset_ids=[str(new_asset.id)],
            )
        except ProviderError as exc:
            logger.warning("任务 %s Provider 失败：%s", run_id, exc)
            await _fail(session, run, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("任务 %s 失败", run_id)
            await _fail(session, run, "task_failed", str(exc) or "扩图失败")
        finally:
            await session.commit()
            await events.publish(DoneEvent(run_id=run.id, status=run.status))
