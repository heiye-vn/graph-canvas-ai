from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services.security import (
    create_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user_id) -> TokenResponse:
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user_id),
        expires_in=settings.jwt_ttl_hours * 3600,
    )


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    email = payload.email.lower()

    exists = await session.scalar(select(User).where(User.email == email))
    if exists is not None:
        # 刻意不区分「邮箱已注册」与「邮箱密码错」以外的细节，避免账号枚举
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已被注册")

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return AuthResponse(token=_token_response(user.id), user=UserOut.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    email = payload.email.lower()
    user = await session.scalar(select(User).where(User.email == email))

    # 用户不存在时也走一次密码校验（用占位哈希），避免通过响应时间枚举账号。
    # 不能写成 `user is None or verify(...)`：短路会让缺失用户跳过 bcrypt。
    password_hash = user.password_hash if user is not None else dummy_password_hash()
    valid = verify_password(payload.password, password_hash)
    if user is None or not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")

    return AuthResponse(token=_token_response(user.id), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)
