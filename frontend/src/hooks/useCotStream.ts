/**
 * 订阅一轮对话的 CoT 流，折叠成组件可直接渲染的**块**列表 ——
 * 同一段思考的 token 碎片已拼接成一块（见 domain/cot.ts），
 * 所以 items.length 是「几段话」，不是「几帧」。
 *
 * 去重规则（DoD ③）：只接受 seq 单调递增的增量 —— EventSource 自动重连
 * 会带着打开时的 cot_after 重放缓冲，重叠帧在这里被过滤；后端回放 +
 * 前端过滤，双保险。
 */

import { useEffect, useRef, useState } from 'react'

import { appendCotItem } from '@/domain/cot'
import type { CotItem } from '@/domain/cot'
import { subscribeAgent } from '@/domain/events'
import type { StreamEvent } from '@/domain/events'

export interface CotStreamState {
  items: CotItem[]
  /** 建流时快照的状态（planning / running / …） */
  status: string | null
  /** 服务端已收束（done 帧或连接关闭） */
  closed: boolean
}

const INITIAL: CotStreamState = { items: [], status: null, closed: false }

export function useCotStream(runId: string | null, enabled = true, resetKey = 0): CotStreamState {
  const [state, setState] = useState<CotStreamState>(INITIAL)
  // lastSeq 用 ref：闭包内读取不触发重订阅
  const lastSeq = useRef(0)

  useEffect(() => {
    if (!runId || !enabled) return
    lastSeq.current = 0
    setState(INITIAL)

    const close = subscribeAgent(runId, 0, {
      onEvent: (event: StreamEvent) => {
        if (event.type === 'snapshot') {
          setState((prev) => ({ ...prev, status: event.status }))
          return
        }
        if (event.type === 'cot') {
          if (event.seq <= lastSeq.current) return // 重放重叠帧，丢弃
          lastSeq.current = event.seq
          // 分块规则见 domain/cot.ts：thought 是逐 token 的碎片，必须拼进上一块
          setState((prev) => ({ ...prev, items: appendCotItem(prev.items, event) }))
          return
        }
        if (event.type === 'done') {
          setState((prev) => ({ ...prev, status: event.status, closed: true }))
        }
      },
      onClosed: (reason) => {
        setState((prev) => ({
          ...prev,
          status: prev.status,
          closed: true,
        }))
        void reason
      },
    })

    return close
  }, [runId, enabled, resetKey])

  return state
}
