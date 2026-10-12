/**
 * SSE 事件协议 —— 与后端 app/schemas/events.py 一一对应。
 *
 * 协议在 M2 一次性定死，后续只增不改：
 *   step / plan / cot 三类事件当前后端**不会发送**，但结构先在这里定义好，
 *   等 M8（多步计划）与 M9.1（思维链）直接启用，前端解析层不用返工。
 *
 * 传输约定（改任何一条都会让流卡住，别动）：
 *   1. 令牌走 query 参数 —— 浏览器原生 EventSource 发不了自定义请求头
 *   2. 收到 done / error 后**主动 close** —— 否则 EventSource 会自动重连，
 *      把已经结束的任务又拉一遍
 *   3. 单帧解析失败只跳该帧，不断开连接 —— 一次序列化 bug 不该让整条流死掉
 */

import { tokenStore } from '@/api/client'

export type RunStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

interface BaseEvent {
  run_id: string
  ts: number
}

export interface SnapshotEvent extends BaseEvent {
  type: 'snapshot'
  status: RunStatus
  progress: number
  stage: string | null
  result: RunResult | null
  error: string | null
}

export interface ProgressEvent extends BaseEvent {
  type: 'progress'
  progress: number
  stage: string
  message?: string | null
}

export interface StepEvent extends BaseEvent {
  type: 'step'
  step_id: string
  status: string
  progress: number
  stage: string | null
}

export interface PlanEvent extends BaseEvent {
  type: 'plan'
  steps: Array<Record<string, unknown>>
  needs_confirm: boolean
}

/** 思维链增量（M9.1 启用）：delta 是增量，前端负责拼接。 */
export interface CotEvent extends BaseEvent {
  type: 'cot'
  seq: number
  node: string | null
  kind: 'thought' | 'tool_call' | 'observation' | 'reflection'
  delta: string
}

export interface ResultEvent extends BaseEvent {
  type: 'result'
  asset_id: string | null
  url: string | null
  wall_only: boolean
}

export interface ErrorEvent extends BaseEvent {
  type: 'error'
  step_id: string | null
  code: string
  message: string
  recoverable: boolean
}

export interface DoneEvent extends BaseEvent {
  type: 'done'
  status: RunStatus
}

export interface PingEvent extends BaseEvent {
  type: 'ping'
}

export type StreamEvent =
  | SnapshotEvent
  | ProgressEvent
  | StepEvent
  | PlanEvent
  | CotEvent
  | ResultEvent
  | ErrorEvent
  | DoneEvent
  | PingEvent

export interface RunResult {
  asset_ids?: string[]
  count?: number
  [key: string]: unknown
}

/** 收到这些类型即视为本轮结束，连接可以关掉了。 */
const TERMINAL_TYPES = new Set(['done', 'error'])

export interface SubscribeOptions {
  onEvent: (event: StreamEvent) => void
  /** 连接被服务端关闭或令牌失效；EventSource 对 401 会直接进入 CLOSED 不再重连。 */
  onClosed?: (reason: string) => void
}

/**
 * 订阅一条任务流，返回取消函数。
 *
 * 刻意用原生 EventSource 而不是 fetch 流：自动重连是它的核心能力，
 * 后端 600s 主动断开后正是靠它把连接接回去。
 */
export function subscribeRun(runId: string, options: SubscribeOptions): () => void {
  const token = tokenStore.get() ?? ''
  const url = `/events/runs/${encodeURIComponent(runId)}?token=${encodeURIComponent(token)}`
  const source = new EventSource(url)

  source.onmessage = (message) => {
    let event: StreamEvent
    try {
      event = JSON.parse(message.data) as StreamEvent
    } catch {
      return // 坏帧跳过，不断开
    }

    options.onEvent(event)

    if (TERMINAL_TYPES.has(event.type)) {
      source.close()
    }
  }

  source.onerror = () => {
    // CLOSED 说明服务端拒绝（401/404）或未再重连；CONNECTING 是正常断线重试
    if (source.readyState === EventSource.CLOSED) {
      source.close()
      options.onClosed?.('事件流已关闭（可能是令牌失效或任务不可见）')
    }
  }

  return () => source.close()
}

export function isTerminalStatus(status: RunStatus): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

/** 状态 → 中文；新增状态必须同步这里，否则界面会露出英文原值。 */
export const STATUS_LABEL: Record<RunStatus, string> = {
  queued: '排队中',
  running: '生成中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
