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
    llm = get_chat_model().bind_tools(functions)
    message = await llm.ainvoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"{doc_summary}\n\n用户要求：{instruction}"),
        ]
    )

    calls = []
    for call in getattr(message, "tool_calls", []) or []:
        name = call.get("name")
        if not name:
            continue
        args = call.get("args") or {}
        calls.append({"name": name, "args": dict(args)})
    return calls
