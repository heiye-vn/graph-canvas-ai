/**
 * 思维链面板（M9.1）—— 可折叠的「模型在想什么」。
 *
 * 四类增量四种样式；planning 期间默认展开（此刻它是唯一的进度信号），
 * 规划/执行完成后折叠成一行摘要，点开可回看全程。
 * 与进度条并列存在、互不阻塞（DoD ②）：CoT 走 agent_run 通道，
 * 排队任务的进度走 tool_run 通道，两条 EventSource 各说各的。
 */

import { useEffect, useRef, useState } from 'react'
import { DownOutlined, RightOutlined } from '@ant-design/icons'

import type { CotItem } from '@/domain/cot'
import type { CotEvent } from '@/domain/events'

const KIND_LABEL: Record<CotEvent['kind'], string> = {
  thought: '思考',
  tool_call: '决定调用',
  observation: '观察',
  reflection: '反思',
}

const KIND_CLASS: Record<CotEvent['kind'], string> = {
  thought: 'text-muted',
  tool_call: 'text-brand',
  observation: 'text-ink',
  reflection: 'text-danger',
}

export default function CoTStream({
  items,
  closed,
  defaultOpen,
}: {
  items: CotItem[]
  /** 流已收束：折叠成摘要，点开回放 */
  closed: boolean
  defaultOpen?: boolean
}) {
  // 展开状态跟随流生命周期：收束瞬间自动折叠，用户手动展开后不再抢控制权
  const [open, setOpen] = useState(defaultOpen ?? true)
  const [touched, setTouched] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (closed && !touched) setOpen(false)
  }, [closed, touched])

  // items.length 只在「起新块」时变，token 增长时不变 ——
  // 光靠它会漏掉同一块内的续写，所以再把末块长度算进依赖。
  const tailLength = items.length > 0 ? items[items.length - 1].delta.length : 0

  useEffect(() => {
    if (open) listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [items.length, tailLength, open])

  if (items.length === 0) return null

  return (
    <div className="border-line rounded-control border">
      <button
        type="button"
        className="text-muted flex w-full items-center gap-1 px-2 py-1.5 text-xs"
        onClick={() => {
          setOpen((prev) => !prev)
          setTouched(true)
        }}
      >
        {open ? <DownOutlined /> : <RightOutlined />}
        思考过程
        <span className="text-faint ml-1">（{items.length} 条）</span>
        {!closed && open && <span className="text-brand ml-auto animate-pulse">流式中…</span>}
      </button>

      {open && (
        // role="log"（隐含 aria-live=polite）：屏幕阅读器能跟上流式增量
        <div
          ref={listRef}
          role="log"
          className="max-h-44 space-y-0.5 overflow-y-auto px-2 pb-1.5"
        >
          {items.map((item) => (
            <p
              key={item.seq}
              className={`m-0 text-xs leading-snug whitespace-pre-wrap break-words ${KIND_CLASS[item.kind]}`}
            >
              <span className="text-faint mr-1 select-none">[{KIND_LABEL[item.kind]}]</span>
              {item.delta}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
