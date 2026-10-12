/**
 * 把一条 SSE 流折叠成组件可直接渲染的状态。
 *
 * 折叠规则只有一条值得强调：**结果按 asset_id 去重**。
 * 断线重连时后端会先补一帧快照，里面带着已产出的 asset_ids，
 * 不去重就会把同一张图渲染两遍。
 */

import { useEffect, useState } from 'react'

import { subscribeRun } from '@/domain/events'
import type { RunStatus, StreamEvent } from '@/domain/events'

export interface Candidate {
  assetId: string
  url: string
}

export interface RunStreamState {
  status: RunStatus | null
  progress: number
  stage: string | null
  candidates: Candidate[]
  error: string | null
  /** 连接已断开（正常结束或异常关闭） */
  closed: boolean
}

const INITIAL: RunStreamState = {
  status: null,
  progress: 0,
  stage: null,
  candidates: [],
  error: null,
  closed: false,
}

export function useRunStream(runId: string | null): RunStreamState {
  const [state, setState] = useState<RunStreamState>(INITIAL)

  useEffect(() => {
    if (!runId) return
    setState(INITIAL)

    const close = subscribeRun(runId, {
      onEvent: (event) => setState((prev) => reduce(prev, event)),
      onClosed: (reason) =>
        setState((prev) => ({ ...prev, closed: true, error: prev.error ?? reason })),
    })

    return close
  }, [runId])

  return state
}

function reduce(prev: RunStreamState, event: StreamEvent): RunStreamState {
  switch (event.type) {
    case 'snapshot':
      return {
        ...prev,
        status: event.status,
        progress: event.progress,
        stage: event.stage,
        error: event.error,
      }

    case 'progress':
      return {
        ...prev,
        status: prev.status === 'queued' ? 'running' : prev.status,
        progress: event.progress,
        stage: event.stage,
      }

    case 'result': {
      if (!event.asset_id || !event.url) return prev
      if (prev.candidates.some((c) => c.assetId === event.asset_id)) return prev
      return {
        ...prev,
        candidates: [
          ...prev.candidates,
          { assetId: event.asset_id as string, url: event.url as string },
        ],
      }
    }

    case 'error':
      return { ...prev, error: event.message, closed: true }

    case 'done':
      return { ...prev, status: event.status, progress: 100, closed: true }

    case 'ping':
    case 'cot':
    case 'step':
    case 'plan':
      // 本阶段后端不发这些；留着分支是为了 M8 / M9 接入时不用改这里
      return prev
  }
}
