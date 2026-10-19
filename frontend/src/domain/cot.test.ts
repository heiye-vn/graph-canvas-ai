import { describe, expect, it } from 'vitest'

import { appendCotItem } from './cot'
import type { CotItem } from './cot'

const item = (seq: number, kind: CotItem['kind'], delta: string): CotItem => ({
  seq,
  kind,
  delta,
})

describe('appendCotItem', () => {
  it('把同一段思考的碎片拼成一块（token 间不插空格）', () => {
    const seq = [
      [1, 'thought', '我'],
      [2, 'thought', '先把画面拆'],
      [3, 'thought', '成背景层'],
    ] as const
    let items: CotItem[] = []
    for (const [s, k, d] of seq) items = appendCotItem(items, { seq: s, kind: k, delta: d })

    expect(items).toEqual([{ seq: 1, kind: 'thought', delta: '我先把画面拆成背景层' }])
  })

  it('被别的 kind 打断就另起一块', () => {
    let items: CotItem[] = []
    items = appendCotItem(items, { seq: 1, kind: 'thought', delta: '思考A' })
    items = appendCotItem(items, { seq: 2, kind: 'tool_call', delta: '调用 split_layers' })
    items = appendCotItem(items, { seq: 3, kind: 'thought', delta: '思考B' })

    expect(items).toHaveLength(3)
    expect(items.map((i) => i.kind)).toEqual(['thought', 'tool_call', 'thought'])
  })

  it('observation 是整句话，连续两帧也不合并', () => {
    let items: CotItem[] = []
    items = appendCotItem(items, { seq: 1, kind: 'observation', delta: '开始执行第 1 步' })
    items = appendCotItem(items, { seq: 2, kind: 'observation', delta: '已提交后台任务' })

    expect(items).toHaveLength(2)
  })

  it('不改原数组，返回新引用（React 才能感知变化）', () => {
    const before = [item(1, 'thought', '甲')]
    const after = appendCotItem(before, { seq: 2, kind: 'thought', delta: '乙' })

    expect(after).not.toBe(before)
    expect(before[0].delta).toBe('甲')
    expect(after[0].delta).toBe('甲乙')
  })
})
