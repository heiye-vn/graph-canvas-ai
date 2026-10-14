"""编辑会话的服务层。

约定与其它服务一致：**接收 session，不自己开事务**，API 与 worker 复用同一套逻辑。

两个容易被忽视的默认值，写在这里是因为它们决定了用户的第一眼体验：

    1. 用**多张**素材建会话时，只有第一张初始可见 —— 候选图一股脑叠上去，
       画布上只能看到最上面那张，用户根本不知道下面还有。切换由文档里的
       visible 决定，会话一旦建好，服务端不再干预。
    2. 往已有会话里追加素材时，新图层默认可见 —— 这是用户的显式动作，
       和「候选图初始化」不是一回事。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EditSession, SessionAsset
from app.models.session import DEFAULT_TITLE
from app.schemas.layer_doc import LayerDocument
from app.schemas.session import SessionOut
from app.services import assets as asset_service
from app.services import layer_doc as layer_doc_service

_DEFAULT_CANVAS_SIZE = 1024


async def _owned_assets(
    session: AsyncSession,
    user_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
) -> list:
    """取出素材并保持传入顺序；有任何一个取不到就整体 404。

    这里刻意不允许「部分成功」：用一个不存在的 id 建会话，八成是调用方传错了，
    静默忽略只会让人纳闷「我的图呢」。
    """
    found = await asset_service.list_assets_by_ids(session, user_id, asset_ids)
    if len(found) != len(asset_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="素材不存在")
    return found


def build_initial_doc(assets: list) -> LayerDocument:
    """按素材列表拼初始文档。

    画布尺寸取**第一张**的尺寸：它就是用户一开始正对着看的那张，
    其余候选按同样尺寸进去，切换时才不会跳大小。
    """
    first = assets[0]
    doc = layer_doc_service.empty_doc(
        first.width or _DEFAULT_CANVAS_SIZE,
        first.height or _DEFAULT_CANVAS_SIZE,
    )

    for index, asset in enumerate(assets):
        layer = layer_doc_service.new_image_layer(
            asset.id,
            width=asset.width,
            height=asset.height,
            name="图像层" if len(assets) == 1 else f"候选图 {index + 1}",
        )
        if index > 0:
            layer.visible = False  # 见模块注释第 1 条
        doc = layer_doc_service.add_layer(doc, layer)

    doc.active_layer_id = doc.layers[0].id
    return doc


async def to_out(session: AsyncSession, edit_session: EditSession) -> SessionOut:
    """把 ORM 对象组装成响应（文档按 LayerDocument 解析，素材补预签名 URL）。

    放在服务层而不是路由里：编辑会话与工具执行两个入口都要返回同一种结构，
    各写一份必然会在某次改动后分叉。
    """
    from app.schemas.layer_doc import LayerDocument

    doc = LayerDocument.model_validate(edit_session.doc)
    asset_ids = await session_assets(session, edit_session.id)
    found = await asset_service.list_assets_by_ids(session, edit_session.user_id, asset_ids)

    return SessionOut(
        id=edit_session.id,
        title=edit_session.title,
        doc=doc,
        revision=edit_session.revision,
        assets=[asset_service.asset_to_out(asset) for asset in found],
        created_at=edit_session.created_at,
        updated_at=edit_session.updated_at,
    )


async def create_session(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
    title: str | None = None,
) -> EditSession:
    assets = await _owned_assets(session, user_id, asset_ids)
    doc = build_initial_doc(assets)

    edit_session = EditSession(
        user_id=user_id,
        title=title or DEFAULT_TITLE,
        doc=doc.model_dump(mode="json"),
    )
    session.add(edit_session)
    await session.flush()

    for asset in assets:
        session.add(SessionAsset(session_id=edit_session.id, asset_id=asset.id))

    await session.commit()
    await session.refresh(edit_session)
    return edit_session


async def get_edit_session(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID
) -> EditSession:
    edit_session = await session.get(EditSession, session_id)
    if edit_session is None or edit_session.user_id != user_id:
        # 与 assets 服务同一口径：不区分「不存在」和「无权」，避免泄露资源是否存在
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    return edit_session


async def list_sessions(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 50
) -> list[EditSession]:
    result = await session.execute(
        select(EditSession)
        .where(EditSession.user_id == user_id)
        .order_by(EditSession.updated_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def session_assets(session: AsyncSession, session_id: uuid.UUID) -> list[uuid.UUID]:
    """会话引用的素材 id，按加入顺序。"""
    result = await session.execute(
        select(SessionAsset.asset_id)
        .where(SessionAsset.session_id == session_id)
        .order_by(SessionAsset.created_at)
    )
    return list(result.scalars().all())


async def add_assets(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    asset_ids: list[uuid.UUID],
) -> EditSession:
    """把素材加进会话：关联表补一行、文档里追加一个图层。

    重复加入同一个素材不会报错：唯一约束挡掉关联表的重复行，
    图层也不再加第二层（同样的图叠两遍毫无意义，还会让后续工具误判层级）。
    """
    edit_session = await get_edit_session(session, user_id, session_id)
    assets = await _owned_assets(session, user_id, asset_ids)

    existing = await session_assets(session, edit_session.id)
    doc = LayerDocument.model_validate(edit_session.doc)
    already_layered = {str(layer.source.asset_id) for layer in doc.layers if layer.source}

    changed = False
    for asset in assets:
        if asset.id in existing:
            continue
        session.add(SessionAsset(session_id=edit_session.id, asset_id=asset.id))
        existing.append(asset.id)
        if str(asset.id) in already_layered:
            continue
        doc = layer_doc_service.add_layer(
            doc,
            layer_doc_service.new_image_layer(
                asset.id, width=asset.width, height=asset.height
            ),
        )
        changed = True

    if changed:
        edit_session.doc = doc.model_dump(mode="json")

    await session.commit()
    await session.refresh(edit_session)
    return edit_session


async def replace_doc(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    doc: LayerDocument,
) -> EditSession:
    """整份替换图层文档。

    调用方（M4 起的工具 / 前端）给的必须是**完整文档**：层级增删后，
    用 patch 表达这些变化既啰嗦又容易错。
    """
    edit_session = await get_edit_session(session, user_id, session_id)
    edit_session.doc = doc.model_dump(mode="json")
    # 整份替换同样改变像素 → 选区作废（revision 裁判覆盖所有改文档的路径）
    edit_session.revision += 1
    await session.commit()
    await session.refresh(edit_session)
    return edit_session


async def rename_session(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID, title: str
) -> EditSession:
    edit_session = await get_edit_session(session, user_id, session_id)
    edit_session.title = title
    await session.commit()
    await session.refresh(edit_session)
    return edit_session


async def delete_session(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID
) -> None:
    edit_session = await get_edit_session(session, user_id, session_id)
    await session.delete(edit_session)
    await session.commit()


async def count_assets(session: AsyncSession, session_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count(SessionAsset.id)).where(SessionAsset.session_id == session_id)
    )
    return int(result.scalar_one())
