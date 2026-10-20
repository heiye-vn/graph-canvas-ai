"""可选的 Langfuse 导出（双写，默认关闭）。

`agent_traces` 表始终是真相源：指标聚合、TraceModal、评测门禁都读它。
配置了 `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` 时，额外的 span 会通过
**OTLP/HTTP JSON** 推到 Langfuse（Cloud 或自托管），供现成的 trace 树与成本面板消费。

为什么用 OTel 而不是 `/api/public/ingestion`：
后者的 v3 契约将于 2026-11-16 停用（只保留 score 事件），OTel 端点是官方
推荐路径，且带 `x-langfuse-ingestion-version: 4` 头即可实时可见（否则延迟约 10 分钟）。

三条约束：

1. 未配置 = 完全 no-op（不发请求、不建客户端），离线演示零依赖；
2. 导出失败只记 debug 日志，绝不影响主流程 —— 观测设施不连累业务；
3. 不引 SDK：OTLP/JSON 结构简单，httpx 已在依赖里，少一层版本漂移风险；
4. **只发结构化元数据**：用户原文与工具参数不出本机（见 `_safe_detail`）。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("graph-canvas-ai.langfuse")

_CLOUD_HOST = "https://cloud.langfuse.com"
_TIMEOUT = 3.0
_INGESTION_VERSION = "4"
_SERVICE_NAME = "graph-canvas-ai"
# create_task 的结果必须有强引用，否则可能被 GC 掉（事件循环只持弱引用）
_PENDING: set[asyncio.Task[None]] = set()

# 本地 span 类型 → Langfuse observation 类型（合法值：span/generation/tool/...）
_OBSERVATION_TYPE = {
    "planner": "generation",
    "tool": "tool",
}

# 允许出本机的 detail 字段白名单：只发结构化元数据，
# 用户原文（文字层内容、工具参数）一律不离开本机。
_SAFE_DETAIL_KEYS = {"steps", "step_id", "async", "replans"}


def _safe_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    if not detail:
        return {}
    safe: dict[str, Any] = {k: v for k, v in detail.items() if k in _SAFE_DETAIL_KEYS}
    if detail.get("error"):
        safe["error"] = str(detail["error"])[:300]
    calls = detail.get("tool_calls")
    if isinstance(calls, list):
        # 只留工具名，丢掉 args —— 参数里可能有用户输入的内容
        safe["tools"] = [
            call.get("name") for call in calls if isinstance(call, dict) and call.get("name")
        ]
    return safe


def _credentials() -> tuple[str, str, str] | None:
    settings = get_settings()
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    host = (settings.langfuse_host or _CLOUD_HOST).rstrip("/")
    return settings.langfuse_public_key, settings.langfuse_secret_key, host


def enabled() -> bool:
    return _credentials() is not None


def _nanos(value: datetime) -> str:
    return str(int(value.astimezone(UTC).timestamp() * 1_000_000_000))


def _attr_str(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _attr_int(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"intValue": str(value)}}


def _metadata_attrs(prefix: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """把扁平 metadata 映射成 `langfuse.*.metadata.<key>`。

    只有带前缀的 key 才会进 Langfuse 顶层 metadata（可过滤）；
    嵌套对象统一序列化成 JSON 字符串。
    """
    attrs: list[dict[str, Any]] = []
    for key, value in metadata.items():
        if value is None:
            continue
        name = f"{prefix}{key}"
        if isinstance(value, bool):
            attrs.append({"key": name, "value": {"boolValue": value}})
        elif isinstance(value, int):
            attrs.append(_attr_int(name, value))
        elif isinstance(value, float):
            attrs.append({"key": name, "value": {"doubleValue": value}})
        elif isinstance(value, str):
            attrs.append(_attr_str(name, value))
        else:
            attrs.append(_attr_str(name, json.dumps(value, ensure_ascii=False, default=str)))
    return attrs


def build_payload(
    *,
    agent_run_id: uuid.UUID | str,
    session_id: uuid.UUID | str,
    kind: str,
    name: str,
    status: str = "ok",
    duration_ms: int | None = None,
    prompt_version: str | None = None,
    model: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    detail: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """把一条本地 span 映射成 OTLP/JSON 请求体（纯函数，便于单测断言结构）。"""
    stamp = now or datetime.now(UTC)
    start = stamp - timedelta(milliseconds=duration_ms or 0)
    failed = status == "failed"

    # traceId 由 run id 派生（32 hex）：同一轮的所有 span 自动归到一条 trace
    run_hex = (
        agent_run_id.hex
        if isinstance(agent_run_id, uuid.UUID)
        else uuid.UUID(str(agent_run_id)).hex
    )

    attributes: list[dict[str, Any]] = [
        _attr_str("langfuse.observation.type", _OBSERVATION_TYPE.get(kind, "span")),
        _attr_str("langfuse.trace.name", "agent-run"),
        _attr_str("langfuse.session.id", str(session_id)),
        _attr_str("langfuse.observation.level", "ERROR" if failed else "DEFAULT"),
    ]
    if prompt_version:
        attributes.append(_attr_str("langfuse.version", prompt_version))
    if failed:
        attributes.append(_attr_str("langfuse.observation.status_message", f"status={status}"))

    # 观测级 metadata：kind / 耗时 / prompt 版本 / 业务 detail 平铺
    attributes += _metadata_attrs(
        "langfuse.observation.metadata.",
        {
            "kind": kind,
            "duration_ms": duration_ms,
            "prompt_version": prompt_version,
            **_safe_detail(detail),
        },
    )

    if kind == "planner":
        if model:
            attributes.append(_attr_str("langfuse.observation.model.name", model))
        attributes.append(
            _attr_str(
                "langfuse.observation.usage_details",
                json.dumps({"input": tokens_in or 0, "output": tokens_out or 0}),
            )
        )

    span = {
        "traceId": run_hex,
        "spanId": uuid.uuid4().hex[:16],
        "name": f"{kind}.{name}",
        "kind": 1,  # SPAN_KIND_INTERNAL
        "startTimeUnixNano": _nanos(start),
        "endTimeUnixNano": _nanos(stamp),
        "attributes": attributes,
        "status": {"code": 2 if failed else 0},
    }

    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attr_str("service.name", _SERVICE_NAME),
                        _attr_str("deployment.environment", get_settings().app_env),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": f"{_SERVICE_NAME}.agent"},
                        "spans": [span],
                    }
                ],
            }
        ]
    }


def export_span(**kwargs: Any) -> None:
    """记录入口调用的旁路导出：未配置直接返回，绝不抛错。"""
    credentials = _credentials()
    if credentials is None:
        return
    try:
        payload = build_payload(**kwargs)
        loop = asyncio.get_running_loop()
        task = loop.create_task(_send(payload, credentials))
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)
    except Exception:  # noqa: BLE001 - 观测设施绝不连累主流程
        logger.debug("Langfuse 导出准备失败（已忽略）", exc_info=True)


async def _send(payload: dict[str, Any], credentials: tuple[str, str, str]) -> None:
    public_key, secret_key, host = credentials
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{host}/api/public/otel/v1/traces",
                json=payload,
                headers={
                    "Authorization": f"Basic {token}",
                    "x-langfuse-ingestion-version": _INGESTION_VERSION,
                },
            )
        if response.status_code >= 400:
            logger.debug(
                "Langfuse 导出返回 %s：%s", response.status_code, response.text[:200]
            )
    except Exception:  # noqa: BLE001 - 网络不可用/超时都不该影响编辑流程
        logger.debug("Langfuse 导出失败（已忽略）", exc_info=True)
