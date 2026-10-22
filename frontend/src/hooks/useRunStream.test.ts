import { describe, expect, it } from 'vitest'

import { reduceRunStream } from '@/hooks/useRunStream'
import type { RunStreamState } from '@/hooks/useRunStream'
import type { StreamEvent } from '@/domain/events'

const base = (): RunStreamState => ({
  status: null,
  progress: 0,
  stage: null,
  candidates: [],
  error: null,
  closed: false,
  restored: [],
})

const at = (event: Record<string, unknown>) =>
  ({ run_id: 'run-1', ts: 1, ...event }) as unknown as StreamEvent

describe('reduceRunStream', () => {
  it('快照带回的 asset_ids 会被记住（重连/重开后补图用）', () => {
    const next = reduceRunStream(
      base(),
      at({
        type: 'snapshot',
        status: 'running',
        progress: 40,
        stage: '生成中',
        result: { asset_ids: ['a', 'b'] },
        error: null,
      }),
    )
    expect(next.restored).toEqual(['a', 'b'])
    expect(next.status).toBe('running')
    expect(next.progress).toBe(40)
  })

  it('快照的 asset_ids 会去重并累加，不会覆盖实时 result 已收到的图', () => {
    const withCandidate = {
      ...base(),
      candidates: [{ assetId: 'a', url: 'https://x/a.png' }],
      restored: ['a'],
    }
    const next = reduceRunStream(
      withCandidate,
      at({
        type: 'snapshot',
        status: 'running',
        progress: 60,
        stage: null,
        result: { asset_ids: ['a', 'b'] },
        error: null,
      }),
    )
    expect(next.restored).toEqual(['a', 'b'])
    expect(next.candidates).toHaveLength(1)
  })

  it('error 帧把状态落成 failed —— 否则进度卡永远停在「生成中」', () => {
    const next = reduceRunStream(
      { ...base(), status: 'running', progress: 70 },
      at({
        type: 'error',
        step_id: null,
        code: 'provider_error',
        message: '模型返回失败',
        recoverable: true,
      }),
    )
    expect(next.status).toBe('failed')
    expect(next.closed).toBe(true)
    expect(next.error).toBe('模型返回失败')
  })

  it('同一张图重复下发只保留一条', () => {
    const first = reduceRunStream(
      base(),
      at({ type: 'result', asset_id: 'a', url: 'https://x/a.png', wall_only: false }),
    )
    const second = reduceRunStream(
      first,
      at({ type: 'result', asset_id: 'a', url: 'https://x/a.png', wall_only: false }),
    )
    expect(second.candidates).toEqual([
      { assetId: 'a', url: 'https://x/a.png' },
    ])
  })
})
