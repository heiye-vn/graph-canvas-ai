"""密码哈希与令牌的单元测试（不依赖数据库与外部服务）。"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.config import get_settings
from app.services.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_roundtrip():
    hashed = hash_password("Str0ng-Passw0rd!")
    assert hashed != "Str0ng-Passw0rd!"
    assert verify_password("Str0ng-Passw0rd!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_hash_is_salted():
    """同一口令两次哈希结果必须不同，否则彩虹表一把梭。"""
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b
    assert verify_password("same-password", a)
    assert verify_password("same-password", b)


def test_long_password_is_not_truncated():
    """bcrypt 只吃前 72 字节，sha256 预哈希就是为绕开这个坑。

    两个仅在 200 字符之后才有差异的长口令，绝不能验证成同一个。
    """
    p1 = "x" * 200 + "AAA"
    p2 = "x" * 200 + "BBB"
    h1 = hash_password(p1)
    assert verify_password(p1, h1)
    assert not verify_password(p2, h1)


def test_verify_rejects_garbage_hash():
    assert not verify_password("anything", "not-a-bcrypt-hash")
    assert not verify_password("anything", "")


def test_token_roundtrip():
    uid = uuid.uuid4()
    assert decode_access_token(create_access_token(uid)) == uid


def test_token_rejects_bad_signature():
    uid = uuid.uuid4()
    now = int(time.time())
    forged = jwt.encode({"sub": str(uid), "exp": now + 3600}, "wrong-secret", algorithm="HS256")
    assert decode_access_token(forged) is None


def test_token_rejects_expired():
    settings = get_settings()
    uid = uuid.uuid4()
    now = int(time.time())
    expired = jwt.encode(
        {"sub": str(uid), "exp": now - 10, "iat": now - 3600},
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert decode_access_token(expired) is None


def test_token_rejects_malformed():
    assert decode_access_token("not.a.token") is None
    assert decode_access_token("") is None
    assert decode_access_token(
        jwt.encode({"sub": "not-a-uuid", "exp": int(time.time()) + 3600},
                   get_settings().jwt_secret, algorithm="HS256")
    ) is None


@pytest.mark.parametrize("password", ["", " ", "短"])
def test_empty_password_still_hashes(password):
    """空口令由 schema 层拦截；这里只保证哈希函数本身不炸。"""
    assert verify_password(password, hash_password(password))
