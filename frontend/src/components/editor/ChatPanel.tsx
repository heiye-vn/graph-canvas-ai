/**
 * 左侧对话面板 —— Agent 单步入口（M5.5 从顶部输入条升级而来）。
 *
 * 为什么值得单独一栏：参考画布类产品的通行形态是「对话即工作区」——
 * 用户一边看画布一边下指令，指令与结果**留在原地**可见，
 * 而不是每次执行完就滚出视野的一句话输入框。
 *
 * 消息刻意只存**组件状态**：Agent 执行记录的持久化（agent_runs 表）是 M8
 * 多步计划的事，现在落库只会存出一堆没有上下文的单轮记录。
 * 刷新后对话消失是已知取舍 —— 画布状态本身是持久的，损失的只是聊天记录。
 */

import { useEffect, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Input, Tag, Tooltip } from 'antd'
import { SendOutlined } from '@ant-design/icons'

import { agentStep } from '@/api/tools'
import type { StepResult } from '@/api/tools'

interface ChatMessage {
  role: 'user' | 'agent'
  text?: string
  steps?: StepResult[]
  note?: string | null
}

const SUGGESTIONS = ['把图变亮一点', '去掉背景', '加一行标题文字', '水平翻转']

export default function ChatPanel({
  sessionId,
  onMutated,
}: {
  sessionId: string
  /** 执行成功后通知外层（画布文档变了） */
  onMutated?: () => void
}) {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const listRef = useRef<HTMLDivElement>(null)

  // 新消息进来自动滚到底 —— 聊天面板不自动滚底等于没做
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [messages])

  const run = useMutation({
    mutationFn: (instruction: string) => agentStep(sessionId, instruction),
    onSuccess: (outcome) => {
      queryClient.setQueryData(['session', sessionId], outcome.session)
      // 模型这条链路同样写历史 —— 编辑记录要跟着长出来，
      // 否则用户会以为「自动帮我做的那些退不回去」
      void queryClient.invalidateQueries({ queryKey: ['history', sessionId] })
      onMutated?.()
      setMessages((prev) => [
        ...prev,
        {
          role: 'agent',
          steps: outcome.steps,
          note: outcome.note,
          text: outcome.note ?? undefined,
        },
      ])
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        { role: 'agent', text: (error as Error).message },
      ])
    },
  })

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || run.isPending) return
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    run.mutate(trimmed)
  }

  const busy = run.isPending

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && (
          <div className="text-faint px-1 text-xs leading-relaxed">
            用一句话描述要改什么，我会拆成具体的编辑操作。
            <div className="mt-3 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((text) => (
                <button
                  key={text}
                  type="button"
                  onClick={() => send(text)}
                  className="border-line text-muted hover:border-brand hover:text-brand rounded-control border px-2 py-1 text-xs transition-colors"
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) => (
          <div key={index} className={message.role === 'user' ? 'flex justify-end' : ''}>
            {message.role === 'user' ? (
              <p className="bg-brand-soft text-ink rounded-control max-w-[85%] px-3 py-2 text-sm">
                {message.text}
              </p>
            ) : (
              <div className="space-y-1.5">
                {(message.steps ?? []).map((step, stepIndex) => (
                  <div
                    key={stepIndex}
                    className="border-line rounded-control border px-2.5 py-2 text-xs"
                  >
                    <div className="flex items-center gap-1.5">
                      <Tag
                        bordered={false}
                        color={step.ok ? 'success' : 'error'}
                        className="m-0"
                      >
                        {step.tool}
                      </Tag>
                      {!step.changed && step.ok && (
                        <Tag bordered={false} className="m-0">
                          画布未变
                        </Tag>
                      )}
                    </div>
                    <p className="text-muted mt-1 mb-0">{step.message}</p>
                  </div>
                ))}
                {message.text && <p className="text-faint m-0 text-xs">{message.text}</p>}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="border-line border-t p-3">
        <div className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={() => send(input)}
            placeholder="描述要改的内容…"
            disabled={busy}
          />
          <Tooltip title={busy ? '正在执行' : '发送'}>
            <Button
              type="primary"
              icon={<SendOutlined />}
              loading={busy}
              disabled={input.trim().length === 0}
              onClick={() => send(input)}
            />
          </Tooltip>
        </div>
      </div>
    </div>
  )
}
