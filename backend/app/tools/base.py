"""工具契约 —— 一处定义，三处消费。

每个工具只有一个真身：

    params_model（pydantic）
        ├─ 服务端校验          model_validate(params)
        ├─ LLM function schema  to_function_schema()（隐藏 agent_hidden 字段）
        └─ 前端参数表单        GET /api/tools 下发元数据

好处很直接：**新增一个工具，前端一行代码都不用改** —— 标签、字段说明、
取值范围、默认值都从这份模型里派生。手写第二份（前端硬编码一份工具清单）
早晚会对不上，而且这种不一致只在用户点了按钮之后才暴露。

为什么要能把字段从给模型的 schema 里摘掉（`agent_hidden`）：
模型会幻觉 UUID。像 asset_id 这种「只有服务端才知道」的内部标识，
一旦进了 function schema，模型就会自己编一个出来，然后报一堆
「素材不存在」。正确做法是让 UI 传、或服务端按上下文回填，
**永远不让模型填**。
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.schemas.layer_doc import LayerDocument

AGENT_HIDDEN = "agent_hidden"


class ToolError(Exception):
    """工具执行失败，且这个失败**值得告诉用户**（参数不对、图层找不到…）。"""

    def __init__(self, message: str, code: str = "tool_failed") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolContext:
    """工具执行时的现场。

    `pinned` 是服务端回填的内部参数（asset_id、revision…）。
    工具自己不查库、不猜，只从这里拿 —— 也顺便保证了「模型给的值」不会被当真。

    `db` 只有排队型工具（重像素，走 ARQ）用得着：它们要在提交路径里
    创建 ToolRun 记录。确定性工具保持「只改文档」的纯粹，不碰库。
    """

    session_id: uuid.UUID
    user_id: uuid.UUID
    doc: LayerDocument
    pinned: dict[str, Any] = field(default_factory=dict)
    db: Any | None = None


@dataclass
class ToolResult:
    doc: LayerDocument
    message: str


@dataclass
class QueuedOutcome:
    """排队型工具的提交结果：run 已落库（由调用方在事务提交后投递 ARQ）。

    排队型工具**不改文档** —— 生成结果走「只上墙」通道（ResultEvent →
    前端采用为图层），画布的变更留在采用那一刻，撤销栈因此天然干净。
    """

    run_id: uuid.UUID
    message: str
    task: str = "inpaint_region"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str
    description: str
    params_model: type[BaseModel]
    handler: Callable[[Any, ToolContext], Awaitable[Any]]
    group: str = "编辑"
    undoable: bool = True
    """True = 重像素工具：提交时创建 ToolRun 走 ARQ，handler 返回 QueuedOutcome。"""
    queued: bool = False
    queue_task: str | None = None
    """排队型工具对应的 ARQ 任务名；None 表示与工具名相同（选区工具共用 inpaint_region）。"""

    def parse(self, raw: dict[str, Any], ctx: ToolContext) -> BaseModel:
        """校验参数。

        刻意把 pydantic 的 ValidationError 翻成 ToolError：模型传错类型时，
        用户看到的应当是「明度需要是整数」而不是一串 Python 回溯
        （DoD ④：类型错误要来自服务端校验，不是让模型自己纠正）。
        """
        payload = {**raw}
        for key in self.hidden_params():
            payload.setdefault(key, ctx.pinned.get(key))

        try:
            return self.params_model.model_validate(payload)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            raise ToolError(
                f"参数不对：{where or '参数'} {first.get('msg', 'invalid')}",
                code="bad_params",
            ) from exc

    def hidden_params(self) -> list[str]:
        """被标记为 agent_hidden 的字段 —— 不给模型看。"""
        names: list[str] = []
        for key, model_field in self.params_model.model_fields.items():
            extra = model_field.json_schema_extra or {}
            if isinstance(extra, dict) and extra.get(AGENT_HIDDEN):
                names.append(key)
        return names


def param_meta(model: type[BaseModel]) -> list[dict[str, Any]]:
    """把 pydantic 模型翻成前端能直接渲染的表单元数据。"""
    schema = model.model_json_schema()
    props: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))

    items: list[dict[str, Any]] = []
    for key, raw in props.items():
        # pydantic 会把 json_schema_extra 里的内容**摊平**到属性上（label 直接是兄弟节点），
        # 两种位置都兼容一下，免得升级 pydantic 后表单标签一夜之间全变英文
        nested = raw.get("json_schema_extra")
        nested = nested if isinstance(nested, dict) else {}
        meta = {**nested, **raw}

        items.append(
            {
                "name": key,
                "label": meta.get("label") or key,
                "description": raw.get("description") or "",
                "type": _json_type(raw),
                "required": key in required,
                "default": raw.get("default"),
                "min": raw.get("minimum"),
                "max": raw.get("maximum"),
                "enum": raw.get("enum"),
                "agent_hidden": bool(meta.get(AGENT_HIDDEN)),
            }
        )
    return items


def to_function_schema(spec: ToolSpec) -> dict[str, Any]:
    """给 LLM 的 function schema（隐藏字段已摘除）。"""
    schema = spec.params_model.model_json_schema()
    props: dict[str, Any] = dict(schema.get("properties", {}))
    for hidden in spec.hidden_params():
        props.pop(hidden, None)

    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": [
                    key for key in schema.get("required", []) if key not in spec.hidden_params()
                ],
            },
        },
    }


def _json_type(raw: dict[str, Any]) -> str:
    if "enum" in raw:
        return "enum"
    for key in ("anyOf", "oneOf"):
        options = raw.get(key)
        if options:
            for option in options:
                if option.get("type") != "null":
                    return option.get("type", "string")
    return raw.get("type", "string")
