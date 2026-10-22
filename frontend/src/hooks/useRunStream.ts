/**
 * 把一条 SSE 流折叠成组件可直接渲染的状态。
 *
 * 折叠规则只有一条值得强调：**结果按 asset_id 去重**。
 * 断线重连时后端会先补一帧快照，里面带着已产出的 asset_ids，
 * 不去重就会把同一张图渲染两遍。
 */

import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { listRunAssets } from '@/api/runs'
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
  /** 快照带回来的产物 id —— 重连或重新打开时，实时 result 帧已经错过了 */
  restored: string[]
}

const INITIAL: RunStreamState = {
  status: null,
  progress: 0,
  stage: null,
  candidates: [],
  error: null,
  closed: false,
  restored: [],
}

export function useRunStream(runId: string | null): RunStreamState {
  const [state, setState] = useState<RunStreamState>(INITIAL)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!runId) return
    setState(INITIAL)

    const close = subscribeRun(runId, {
      onEvent: (event) => setState((prev) => reduceRunStream(prev, event)),
      onClosed: (reason) =>
        setState((prev) => ({ ...prev, closed: true, error: prev.error ?? reason })),
    })

    return close
  }, [runId])

  /**
   * 快照只给 asset_id（不含预签名 URL）。重连、切任务、重开页面时实时 result
   * 帧已经错过，这里按 id 把 URL 找回来 —— 否则候选图条会空着，用户以为图没了。
   * 命中 `['run-assets', runId]` 缓存时不会产生额外请求。
   */
  const restoredKey = state.restored.join(',')
  useEffect(() => {
    if (!runId || !restoredKey) return
    let cancelled = false
    void queryClient
      .fetchQuery({
        queryKey: ['run-assets', runId],
        queryFn: () => listRunAssets(runId),
        staleTime: 30_000,
      })
      .then((assets) => {
        if (cancelled) return
        setState((prev) => {
          const have = new Set(prev.candidates.map((item) => item.assetId))
          const add = assets
            .filter((asset) => prev.restored.includes(asset.id) && !have.has(asset.id))
            .map((asset) => ({ assetId: asset.id, url: asset.url }))
          return add.length
            ? { ...prev, candidates: [...prev.candidates, ...add] }
            : prev
        })
      })
      // 补图失败不影响主流程：后续实时 result 帧仍会补上
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [runId, restoredKey, queryClient])

  return state
}

/** 折叠单帧事件 —— 纯函数，测试直接断言它，不用起 DOM 或 EventSource。 */
export function reduceRunStream(
  prev: RunStreamState,
  event: StreamEvent,
): RunStreamState {
  switch (event.type) {
    case 'snapshot':
      return {
        ...prev,
        status: event.status,
        progress: event.progress,
        stage: event.stage,
        error: event.error,
        // 快照是重连/重开后唯一能拿到「已经产出了哪些图」的地方
        restored: event.result?.asset_ids?.length
          ? Array.from(new Set([...prev.restored, ...event.result.asset_ids]))
          : prev.restored,
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
      // 后端的 fail() 一定已把任务落成 failed，error 帧就是终态；
      // 不同步 status 的话进度卡片会一直停在「生成中」（done 帧也可能已被关掉）。
      return { ...prev, status: 'failed', error: event.message, closed: true }

    case 'done':
      return { ...prev, status: event.status, progress: 100, closed: true }

    case 'ping':
    case 'cot':
    case 'step':
    case 'plan':
      // 任务流不发这几类；对话轮（cot/step/plan）由 useCotStream 消费
      return prev
  }
}
