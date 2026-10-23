"""路由依赖：当前登录用户。

`<img>` 与 EventSource 都带不了 Authorization 头，这类入口（SSE、缩略图）
允许 `?token=` 作为第二条通道；解析逻辑仍然只有 `user_from_token` 一处。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.services.security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


async def user_from_token(token: str | None, session: AsyncSession) -> User:
    """令牌 → 用户。三条取 token 的通道共用这一处解析逻辑。"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: UUID | None = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await session.get(User, user_id)
    if user is None:
        # token 有效但用户已删除（资产级联删除的场景）
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    return await user_from_token(credentials.credentials if credentials else None, session)


async def get_user_from_header_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    token: str | None = Query(default=None, description="媒体/SSE 入口的令牌通道"),
    session: AsyncSession = Depends(get_session),
) -> User:
    """给 `<img>` / EventSource 这类带不了 Header 的请求用：Header 优先，其次 query。"""
    return await user_from_token(
        credentials.credentials if credentials else token, session
    )
