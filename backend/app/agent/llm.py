"""Agent 用的对话模型。

只有这一个文件依赖 langchain —— 其余部分（工具、文档、路由）都不 import 它，
这样「没装 agent extra」时应用照样能跑，只有真的要规划时才报错。

缺配置一律显式抛错：静默降级到「假装理解了」的假规划最危险，
用户会以为模型听懂了，然后得到一个莫名其妙的画布。
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.config import get_settings

SYSTEM_PROMPT = """你是图像编辑工作台里的执行助手。

规则：
1. 只调用给定的工具，不要自己发明工具或参数。
2. 需要指定图层时，用**图层名**（例如「候选图 1」）。不要使用任何 id、UUID
   —— 你不知道它们，猜出来的 id 一定是错的。
3. 用户没说改哪一层时，不传 layer 参数（服务端会作用于当前选中的图层）。
4. 一次用户指令只做一件事；用户说了多件事就调用多个工具。
5. 参数填整数/浮点数，不要填字符串数字。
"""


class PlannerError(RuntimeError):
    """规划模型调用失败（配置错 / 网络不通 / 服务端拒绝）。

    message 面向用户可直接展示 —— 404 里最常见的坑是 base_url 填成
    原生 API 前缀（/api/v1）而不是兼容模式（/compatible-mode/v1），
    或者模型名不在兼容模式清单里；报错必须把这两层都说破，
    否则前端只剩一个含糊的 500，用户根本无从下手。
    """


def _describe_llm_error(exc: Exception, *, model: str, base_url: str) -> str:
    """把 openai SDK 的异常翻成能指导排错的一句话（langchain 只包了一层皮）。"""
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return "规划模型鉴权失败（401）：DASHSCOPE_API_KEY 无效或已过期。"
    if isinstance(exc, openai.NotFoundError):
        return (
            f"规划模型不存在（404）：model={model} @ {base_url}。"
            "用百炼时端点必须是 OpenAI 兼容模式 /compatible-mode/v1"
            "（/api/v1 是原生 API 前缀，拼 /chat/completions 必然 404），"
            "模型名也要用兼容模式支持的（如 qwen-plus / qwen-max）。"
        )
    if isinstance(exc, openai.RateLimitError):
        return "规划模型触发限流（429）：稍后重试，或降低调用频率。"
    if isinstance(exc, openai.APITimeoutError):
        return f"规划模型请求超时：{exc}"
    if isinstance(exc, openai.APIConnectionError):
        return f"规划模型网络不通：{exc}"
    if isinstance(exc, openai.APIStatusError):
        return f"规划模型调用失败（HTTP {exc.status_code}）：{exc.message}"
    return f"规划模型调用失败：{exc}"


def get_chat_model() -> ChatOpenAI:
    base_url, api_key, model = get_settings().require_llm_config()
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=get_settings().llm_temperature,
    )


async def plan_tool_calls(
    instruction: str,
    doc_summary: str,
    functions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把一句自然语言变成一个（或多个）工具调用。

    返回 `[{name, args}]`。模型没调用任何工具时返回空列表 ——
    这是正常情况（比如用户说的是一句闲聊），由上层决定怎么回应用户。
    """
    calls = await _plan_stream(instruction, doc_summary, functions, emit=None)
    return calls


async def plan_tool_calls_stream(
    instruction: str,
    doc_summary: str,
    functions: list[dict[str, Any]],
    emit,
) -> list[dict[str, Any]]:
    """流式版规划：思考 token 经 `emit(kind, delta)` 实时推出去（M9.1）。

    emit 是 `async (kind: str, delta: str) -> None`，由上层绑定 run 通道。
    """
    return await _plan_stream(instruction, doc_summary, functions, emit=emit)


async def _plan_stream(
    instruction: str,
    doc_summary: str,
    functions: list[dict[str, Any]],
    emit,
) -> list[dict[str, Any]]:
    try:
        base_url, _api_key, model = get_settings().require_llm_config()
    except RuntimeError as exc:
        # 缺 Key 也是「规划不了」的一种：同样给人话，而不是落进 500
        raise PlannerError(str(exc)) from exc

    llm = get_chat_model().bind_tools(functions)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"{doc_summary}\n\n用户要求：{instruction}"),
    ]

    async def _push(kind: str, delta: str) -> None:
        if emit is not None and delta:
            await emit(kind, delta)

    # 两条硬规矩（施工图钉死的坑）：
    #   1. 推理模型的 reasoning_content 与 content 是两个字段，都要透传
    #   2. chunk 是增量（delta），只追加、绝不整段覆盖
    merged = None
    try:
        async for chunk in llm.astream(messages):
            reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
            if reasoning:
                await _push("thought", reasoning)
            content = chunk.content if isinstance(chunk.content, str) else ""
            if content:
                await _push("thought", content)
            merged = chunk if merged is None else merged + chunk
    except Exception as exc:
        raise PlannerError(_describe_llm_error(exc, model=model, base_url=base_url)) from exc

    calls = []
    for call in getattr(merged, "tool_calls", []) or []:
        name = call.get("name")
        if not name:
            continue
        args = call.get("args") or {}
        calls.append({"name": name, "args": dict(args)})

    for call in calls:
        await _push("tool_call", f"调用 {call['name']}")
    return calls
