"""密码哈希与 JWT。

密码方案：sha256 预哈希 + bcrypt。

为什么不直接 bcrypt.hashpw(password)：
    bcrypt 只取前 72 字节，超长会被**静默截断**（早期实现）或直接报错（bcrypt 4.x）。
    先用 sha256 + base64 归一到固定 44 字节，既绕开上限，又支持任意长度口令。
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import get_settings

_BCRYPT_ROUNDS = 12
_ALGORITHM = "HS256"


def _prehash(password: str) -> bytes:
    """sha256 → base64：固定 44 字节，远低于 bcrypt 的 72 字节上限。"""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        # 哈希值损坏或不是合法 bcrypt 串：按「校验失败」处理，不暴露内部错误
        return False


def create_access_token(user_id: uuid.UUID | str) -> str:
    settings = get_settings()
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """解析成功返回 user_id，任何异常一律返回 None。

    过期/签名错误/结构不对，对调用方没有区别——都不该放行。
    """
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[_ALGORITHM],
        )
        sub = payload.get("sub")
        return uuid.UUID(str(sub)) if sub else None
    except (jwt.PyJWTError, ValueError):
        return None
