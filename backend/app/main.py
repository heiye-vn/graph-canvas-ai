"""应用入口。

启动顺序（lifespan）：
    1. preflight_settings()  —— 缺必填配置立即失败并列出缺失项
    2. ensure_bucket()       —— silo 不会自动建桶，必须启动期建（放线程池，避免阻塞事件循环）
    3. yield
    4. dispose_engine()      —— 优雅关闭连接池
"""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path

if sys.platform == "win32":
    # psycopg3 的 async 模式在 Windows 上必须 Selector 事件循环
    # （默认 Proactor 不兼容 —— 会直接 InterfaceError 拒连）。
    # 必须在任何事件循环创建之前设置，所以放在模块顶层。
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.config import get_settings, preflight_settings
from app.db import dispose_engine
from app.routers import health
from app.services import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
logger = logging.getLogger("graph-canvas-ai")

# 容器内由 Dockerfile COPY 到该路径；本地可用 FRONTEND_DIST 指向 frontend/dist 走同源托管
FRONTEND_DIST = Path(getenv("FRONTEND_DIST", "/app/frontend/dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    preflight_settings()
    settings = get_settings()
    logger.info("启动中：env=%s provider=%s", settings.app_env, settings.image_provider)

    await run_in_threadpool(storage.ensure_bucket)
    logger.info("对象存储就绪：bucket=%s", storage.bucket_name())

    # 预热两条重模型的链路（都在后台跑、失败只告警、不阻塞启动）：
    # SAM —— 点选分割；rembg/u2net —— 拆层的主体分离
    if settings.matting_provider in ("auto", "sam"):
        import asyncio

        from app.edits.segment import warm_session
        from app.tasks.split import warm_matting

        async def _preheat_models() -> None:
            try:
                await run_in_threadpool(warm_session)
                logger.info("SAM 会话预热完成，点选即点即用")
            except Exception as exc:  # noqa: BLE001 - 预热失败不阻塞启动
                logger.warning("SAM 预热失败（首次点选将现场加载）：%s", exc)

            try:
                await run_in_threadpool(warm_matting)
                logger.info("rembg 会话预热完成，拆层即点即用")
            except Exception as exc:  # noqa: BLE001 - 预热失败不阻塞启动
                logger.warning("rembg 预热失败（首次拆层将现场加载）：%s", exc)

        app.state.preheat = asyncio.create_task(_preheat_models())

    try:
        yield
    finally:
        from app.services.events import close_redis
        from app.services.queue import close_pool

        await close_pool()
        await close_redis()
        await dispose_engine()

        from app.agent.checkpointer import close_checkpointer

        await close_checkpointer()
        logger.info("已关闭数据库连接池、消息通道与 LangGraph checkpointer")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GraphCanvasAgent",
        version=__version__,
        description="自然语言驱动的多模态图像编辑工作台",
        lifespan=lifespan,
    )

    # 仅开发环境放开：前端 dev server 在 7401（本项目端口段 74xx，与参考项目 73xx 错开）
    if not settings.is_production:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:7401", "http://127.0.0.1:7401"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # /health 与 /ready 不挂业务前缀；后续 /events（SSE）同样不挂
    app.include_router(health.router)

    # 业务路由统一挂 /api
    from app.routers import agent, assets, auth, runs
    from app.routers.edit_sessions import router as edit_session_router
    from app.routers.tools import router as tools_router

    app.include_router(auth.router, prefix=settings.api_prefix)
    app.include_router(assets.router, prefix=settings.api_prefix)
    app.include_router(runs.router, prefix=settings.api_prefix)
    app.include_router(edit_session_router, prefix=settings.api_prefix)
    app.include_router(tools_router, prefix=settings.api_prefix)
    app.include_router(agent.router, prefix=settings.api_prefix)

    # SSE 不挂业务前缀，便于反向代理单独关掉缓冲
    from app.routers import events

    app.include_router(events.router)

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """前端构建产物由后端同源托管（容器内 dist 一定存在，本地开发交给 Vite）。"""
    if not FRONTEND_DIST.is_dir():
        logger.info("未发现前端产物 %s，跳过静态托管（本地请用 npm run dev）", FRONTEND_DIST)
        return

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    index = FRONTEND_DIST / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # 交给前端路由；API 与 SSE 路径已在上面优先匹配
        return FileResponse(index)


app = create_app()
