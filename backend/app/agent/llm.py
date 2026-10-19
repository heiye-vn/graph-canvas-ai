"""Agent 用的对话模型。

只有这一个文件依赖 langchain —— 其余部分（工具、文档、路由）都不 import 它，
这样「没装 agent extra」时应用照样能跑，只有真的要规划时才报错。

缺配置一律显式抛错：静默降级到「假装理解了」的假规划最危险，
用户会以为模型听懂了，然后得到一个莫名其妙的画布。
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

# prompt 正文与版本号住在 prompts.py（M9.3 起版本化，改文案必须升 PROMPT_VERSION）
from app.agent.prompts import SYSTEM_PROMPT
from app.config import get_settings

# ---- CoT 攒批（M9.1 补丁）------------------------------------------------
# astream 是逐 token 的：一个 chunk 就 emit 一次，会让「思考过程（N 条）」
# 退化成 token 计数（实测一句 30 字的话散成 13 行、每行 3 个字）。
# 这里按三种时机攒够再发 —— 协议不变（仍是 delta 增量），只是帧数从几百降到十几：
#   · 攒够 COT_FLUSH_CHARS 个字
#   · 这段 delta 以句末标点/换行收尾（读起来正好断句）
#   · 距上次发送已超过 COT_FLUSH_SECONDS（只兜底慢速流：阈值要明显大于
#     正常 chunk 间隔，否则「一 chunk 一帧」会从时间这条口子漏回来）
COT_FLUSH_CHARS = 16
COT_FLUSH_SECONDS = 0.25
COT_FLUSH_BREAKS = "。！？；…\n"


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
        stream_usage=True,  # 流式响应也回传 token 用量（M9.3 trace）
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
    calls, _meta = await _plan_stream(instruction, doc_summary, functions, emit=None)
    return calls


async def plan_tool_calls_stream(
    instruction: str,
    doc_summary: str,
    functions: list[dict[str, Any]],
    emit,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """流式版规划：思考 token 经 `emit(kind, delta)` 实时推出去（M9.1）。

    emit 是 `async (kind: str, delta: str) -> None`，由上层绑定 run 通道。
    返回 `(calls, meta)`：meta 带 model 与 token 用量（M9.3 trace 用）——
    兼容旧桩（只返回 list 的按 meta={} 处理）。
    """
    return await _plan_stream(instruction, doc_summary, functions, emit=emit)


async def _plan_stream(
    instruction: str,
    doc_summary: str,
    functions: list[dict[str, Any]],
    emit,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        base_url, _api_key, model = get_settings().require_llm_config()
    except RuntimeError as exc:
        # 缺 Key 也是「规划不了」的一种：同样给人话，而不是落进 500
        raise PlannerError(str(exc)) from exc

    # stream_usage：流式也要拿到 token 用量（M9.3 trace 需要）。
    # 它是 ChatOpenAI 的模型字段，不是请求参数 —— 放 bind_tools 会被当成
    # 未知参数发给服务端（中转站直接 400）
    llm = get_chat_model().bind_tools(functions)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"{doc_summary}\n\n用户要求：{instruction}"),
    ]

    async def _push(kind: str, delta: str) -> None:
        if emit is not None and delta:
            await emit(kind, delta)

    # thought 的攒批缓冲（只影响 thought；tool_call 仍即时发，顺序不能乱）
    buf: list[str] = []
    buf_chars = 0
    last_flush = time.monotonic()

    async def _flush_thought() -> None:
        nonlocal buf_chars, last_flush
        if not buf:
            return
        text = "".join(buf)
        buf.clear()
        buf_chars = 0
        last_flush = time.monotonic()
        await _push("thought", text)

    async def _push_thought(delta: str) -> None:
        nonlocal buf_chars
        buf.append(delta)
        buf_chars += len(delta)
        if (
            buf_chars >= COT_FLUSH_CHARS
            or (delta and delta[-1] in COT_FLUSH_BREAKS)
            or time.monotonic() - last_flush >= COT_FLUSH_SECONDS
        ):
            await _flush_thought()

    # 两条硬规矩（施工图钉死的坑）：
    #   1. 推理模型的 reasoning_content 与 content 是两个字段，都要透传
    #   2. chunk 是增量（delta），只追加、绝不整段覆盖
    merged = None
    try:
        async for chunk in llm.astream(messages):
            reasoning = (chunk.additional_kwargs or {}).get("reasoning_content")
            if reasoning:
                await _push_thought(reasoning)
            content = chunk.content if isinstance(chunk.content, str) else ""
            if content:
                await _push_thought(content)
            merged = chunk if merged is None else merged + chunk
    except Exception as exc:
        # 已经想到一半的别丢：先冲掉缓冲，用户才看得到它卡在哪一步。
        # 收尾发送失败不该盖住真正的失败原因，所以这里吞掉自身异常。
        try:
            await _flush_thought()
        except Exception:  # noqa: BLE001
            pass
        raise PlannerError(_describe_llm_error(exc, model=model, base_url=base_url)) from exc
    await _flush_thought()

    calls = []
    for call in getattr(merged, "tool_calls", []) or []:
        name = call.get("name")
        if not name:
            continue
        args = call.get("args") or {}
        calls.append({"name": name, "args": dict(args)})

    # 只发工具名：前端标签已经是「决定调用」，再拼「调用 xxx」会读成
    # 「[决定调用] 调用 split_layers」，重复一遍动词
    for call in calls:
        await _push("tool_call", str(call["name"]))

    usage = getattr(merged, "usage_metadata", None) or {}
    meta = {
        "model": model,
        "tokens": {
            "input": usage.get("input_tokens"),
            "output": usage.get("output_tokens"),
        },
    }
    return calls, meta
