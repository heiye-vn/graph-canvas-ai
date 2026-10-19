/**
 * 思维链增量的「分块」规则（M9.1）—— 纯函数，便于单测。
 *
 * 后端把 LLM 的流式 chunk 原样推下来（一个 chunk 一帧 cot），所以
 * thought 的 delta 是**逐 token 的碎片**（「我」「先把画面拆」「成背景层」…）。
 * 一帧一行会让一条 30 字的思考散成十几行，条数失去意义。
 *
 * 规则只有一条：
 *   thought → thought  原地拼接（token 之间不能插空格，否则断词）
 *   其余 kind          每帧本身就是一句完整的话，独立成块
 *
 * seq 保留**首帧**的序号做 React key：拼接时若跟着改，key 会每 token 变一次。
 * 去重仍由调用方的 lastSeq 负责，与本函数无关。
 */

import type { CotEvent } from './events'

export interface CotItem {
  seq: number
  kind: CotEvent['kind']
  delta: string
}

type CotDelta = Pick<CotEvent, 'seq' | 'kind' | 'delta'>

export function appendCotItem(items: CotItem[], event: CotDelta): CotItem[] {
  const last = items[items.length - 1]
  if (last && last.kind === 'thought' && event.kind === 'thought') {
    const head = items.slice(0, -1)
    head.push({ ...last, delta: last.delta + event.delta })
    return head
  }
  return [...items, { seq: event.seq, kind: event.kind, delta: event.delta }]
}
