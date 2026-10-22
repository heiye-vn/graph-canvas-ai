"""对象存储（S3 兼容）。

镜像是 pgsty/silo（MinIO 分支），S3 API 完全兼容，用 boto3 即可。
注意：silo 不会自动建桶，**应用启动时必须 ensure_bucket**（见 app.main.lifespan）。
"""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_settings

_PRESIGN_GET_TTL = 3600
_PRESIGN_PUT_TTL = 900


def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def bucket_name() -> str:
    return get_settings().s3_bucket


def ensure_bucket() -> None:
    """启动期建桶（幂等）。失败直接抛错——存储不可用则应用不可用，不要静默降级。"""
    name = bucket_name()
    client = _client()
    try:
        client.head_bucket(Bucket=name)
        return
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"404", "NoSuchBucket"}:
            raise RuntimeError(f"对象存储不可达或凭据错误（{code}）：{exc}") from exc
    try:
        client.create_bucket(Bucket=name)
    except ClientError as exc:  # pragma: no cover - 仅在并发启动或权限异常时触发
        raise RuntimeError(f"创建桶 {name} 失败：{exc}") from exc


def check_storage() -> bool:
    """/ready 探针用。"""
    try:
        _client().head_bucket(Bucket=bucket_name())
        return True
    except Exception:  # noqa: BLE001
        return False


def put_object(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    _client().put_object(
        Bucket=bucket_name(),
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


def get_object(key: str) -> bytes:
    resp = _client().get_object(Bucket=bucket_name(), Key=key)
    return resp["Body"].read()


def delete_object(key: str) -> None:
    _client().delete_object(Bucket=bucket_name(), Key=key)


def presign_get(key: str, ttl: int = _PRESIGN_GET_TTL) -> str:
    """返回可直接访问的临时 URL（桶是私有的，前端一律走预签名）。"""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket_name(), "Key": key},
        ExpiresIn=ttl,
    )


def presign_put(
    key: str,
    content_type: str = "application/octet-stream",
    ttl: int = _PRESIGN_PUT_TTL,
) -> str:
    return _client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket_name(), "Key": key, "ContentType": content_type},
        ExpiresIn=ttl,
    )


def object_exists(key: str) -> bool:
    try:
        _client().head_object(Bucket=bucket_name(), Key=key)
    except Exception:  # noqa: BLE001
        return False
    return True


def _health_detail() -> dict[str, Any]:
    return {"bucket": bucket_name(), "endpoint": get_settings().s3_endpoint}
