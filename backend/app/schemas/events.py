"""SSE 事件协议 —— 全项目只有这一处定义。

⚠️ 协议在 M2 一次性定死，后续只增不改：
    cot / plan / reflection 三类事件本阶段**只定义结构、暂不发送**，
    等 M9（思维链与反思循环）再填充。若届时再改协议，前端解析层要整层返工。

线上帧格式：`data:{json}\n\n`
"""

from __future__ import annotations

import time
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EventType = Literal[
    "snapshot",  # 建立连接后立即补发的状态快照
    "progress",  # 整体进度
    "step",      # 单个步骤状态（M8 多步计划启用）
    "plan",      # 计划内容与人机确认标记（M8）
    "cot",       # 思维链增量（M9.1）——本阶段不发
    "result",    # 产物就绪
    "error",     # 失败
    "done",      # 流结束
    "ping",      # 心跳
]


class Event(BaseModel):
    type: EventType
    run_id: UUID
    ts: float = Field(default_factory=time.time)


class SnapshotEvent(Event):
    """先订阅、后发快照：避免任务在两步之间结束导致连接一直空等。"""

    type: Literal["snapshot"] = "snapshot"
    status: str
    progress: int = 0
    stage: str | None = None
    result: dict | None = None
    error: str | None = None


class ProgressEvent(Event):
    type: Literal["progress"] = "progress"
    progress: int
    stage: str
    message: str | None = None


class StepEvent(Event):
    type: Literal["step"] = "step"
    step_id: str
    status: str
    progress: int = 0
    stage: str | None = None


class PlanEvent(Event):
    type: Literal["plan"] = "plan"
    steps: list[dict] = Field(default_factory=list)
    needs_confirm: bool = False


class CotEvent(Event):
    """思维链增量（M9.1 启用）。

    kind 分四类：thought / tool_call / observation / reflection。
    delta 是**增量**而非全量——前端拼接，不做整段覆盖。
    """

    type: Literal["cot"] = "cot"
    seq: int
    node: str | None = None
    kind: Literal["thought", "tool_call", "observation", "reflection"]
    delta: str


class ResultEvent(Event):
    type: Literal["result"] = "result"
    asset_id: UUID | None = None
    url: str | None = None
    wall_only: bool = False


class ErrorEvent(Event):
    type: Literal["error"] = "error"
    step_id: str | None = None
    code: str
    message: str
    recoverable: bool = True


class DoneEvent(Event):
    type: Literal["done"] = "done"
    status: str


class PingEvent(Event):
    type: Literal["ping"] = "ping"


EventUnion = (
    SnapshotEvent
    | ProgressEvent
    | StepEvent
    | PlanEvent
    | CotEvent
    | ResultEvent
    | ErrorEvent
    | DoneEvent
    | PingEvent
)

# 判别联合：前端按 type 分支，后端按 type 校验，两边共用同一份定义
StreamEvent = Annotated[EventUnion, Field(discriminator="type")]


def frame(event: Event) -> str:
    """序列化为一条 SSE 帧。"""
    return f"data:{event.model_dump_json()}\n\n"


def ping_frame(run_id: UUID) -> str:
    return frame(PingEvent(run_id=run_id))
