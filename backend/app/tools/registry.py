"""工具注册表。

工具只在 `install_builtin_tools()` 里注册一次（模块导入时执行）。
没有「动态注册」是为了让工具清单在进程启动时就是确定的 ——
运行时才能知道有哪些工具，会让 `/api/tools` 的返回变得不可预测。
"""

from __future__ import annotations

from app.tools.base import ToolSpec, to_function_schema

_REGISTRY: dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> ToolSpec:
    if spec.name in _REGISTRY:
        raise RuntimeError(f"工具重复注册：{spec.name}")
    _REGISTRY[spec.name] = spec
    return spec


def get_tool(name: str) -> ToolSpec | None:
    return _REGISTRY.get(name)


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def function_schemas() -> list[dict]:
    """给 LLM 的全部 function schema；顺序即注册顺序（稳定的，不会每次调用都变）。"""
    return [to_function_schema(spec) for spec in _REGISTRY.values()]


def metadata() -> list[dict]:
    """/api/tools 的下发内容：前端据此渲染标签与表单。"""
    from app.tools.base import param_meta

    return [
        {
            "name": spec.name,
            "label": spec.label,
            "description": spec.description,
            "group": spec.group,
            "undoable": spec.undoable,
            "params": param_meta(spec.params_model),
        }
        for spec in _REGISTRY.values()
    ]
